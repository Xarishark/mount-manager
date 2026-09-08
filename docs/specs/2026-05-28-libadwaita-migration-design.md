# libadwaita UI migration — design

**Status:** approved (draft, pre-implementation)
**Date:** 2026-05-28

## Goal

Migrate the Mount Manager GUI from plain GTK 4 widgets to libadwaita so the app
matches the look and behavior of native GNOME / Bazzite applications, and
remove the custom CSS and dark-mode detection currently used to approximate
that look.

The privileged helper-mode subprocess, polkit invocation, systemd-creds
handling, mount-unit generation, and credential storage paths are out of scope
and must not change.

## Approach

In-place migration of the existing code, with a single targeted refactor: the
GUI is moved out of `mount_manager.py` into a new sibling module so that
`mount_manager.py` retains only the data models, systemd / credential plumbing,
and helper-mode subprocess entry point.

The migration targets **libadwaita ≥ 1.5** so that `Adw.Dialog` and
`Adw.AlertDialog` are available. The app gains an explicit version check at
startup, parallel to today's systemd 258 check, that refuses to start with a
clear error if the host's libadwaita is too old.

## File layout

- `mount_manager.py`
  - Keeps everything it has today **except** the body of `run_gui()` and the
    UI classes nested inside it.
  - `run_gui()` becomes a thin shim:
    `from mount_manager_ui import run_gui as _run_gui; return _run_gui()`.
  - Helper mode (`run_helper_mode`, `--helper` arg), data models
    (`ManagedMount`, `DisplayedMount`, `SharePath`), systemd / credential
    helpers, polkit handoff (`request_helper_*`), and `main()` stay put.
  - `import_gtk()`, `apply_theme()`, and the `APP_CSS` constant are removed.
- `mount_manager_ui.py` *(new)*
  - Module-level `gi.require_version("Gtk", "4.0")` and
    `gi.require_version("Adw", "1")`, followed by `from gi.repository import …`.
  - Defines: `ensure_libadwaita_supported()`, `apply_style_manager()`,
    `MainWindow`, `AddShareDialog`, `DeleteAlertDialog` (thin wrapper around
    `Adw.AlertDialog`), `MountManagerApplication`, and a `run_gui()` entry
    point.
  - Imports data models, constants, and helper-invocation functions from
    `mount_manager`.
- `packaging/build-appimage.sh` — install the new file alongside
  `mount_manager.py` (one additional copy/install line).
- `README.md` — add `mount_manager_ui.py` to the "Test as an installed app on
  Bazzite" install commands, and add `libadwaita ≥ 1.5` to the requirements
  section.

## Window & theming

- `MountManagerApplication` becomes `Adw.Application`. Application ID and
  flags unchanged.
- `MainWindow` becomes `Adw.ApplicationWindow` containing an
  `Adw.ToolbarView`. The top bar is an `Adw.HeaderBar`; the content area is an
  `Adw.ToastOverlay` wrapping the list / status-page widget.
- The window title is `APP_NAME`; the icon name is unchanged. No manual title
  widget is set — libadwaita derives the header title from the window title.
- Theming: `APP_CSS` and `apply_theme()` are deleted.
  `Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)` is
  called once at startup so the app follows the system / portal preference
  automatically.

### Header bar

- Start side: a suggested-action **Add Share** button (text label, no icon).
- End side: a refresh icon button (`view-refresh-symbolic`), then a menu
  button (`open-menu-symbolic`) whose menu contains a single `About` entry.

## Mount list

- The content is an `Adw.Clamp` wrapping an `Adw.PreferencesPage` with one
  `Adw.PreferencesGroup` titled "SMB Shares".
- Each mount is rendered as an `Adw.ActionRow`:
  - Title: the share source (e.g. `//192.168.1.10/media`).
  - Subtitle: the mount point and a short status string
    (`/mnt/mount-manager/media · Mounted`, `… · Idle`, `… · Needs upgrade`,
    `… · Mounted (not managed)`).
  - Trailing widgets, in order:
    1. **Switch** — enables / disables the systemd automount, same semantics as
       today's `mount_switch`. Insensitive when the row is unmanaged or needs
       upgrading.
    2. **Open folder** icon button (`folder-open-symbolic`) — sensitive only
       when on-demand access is active, matching today's `open_button.set_sensitive`
       logic.
    3. **Primary action** (only when applicable): for rows that need an
       upgrade, an inline button labeled "Upgrade" is shown in place of the
       open-folder button (matches today's behavior of swapping these two).
    4. **Kebab** (`Gtk.MenuButton` with `view-more-symbolic`) — menu contains a
       destructive "Delete…" entry.
- Unmanaged mounts: no switch, no open button, no kebab. The trailing area
  shows a dim "Not managed" label as today.
- Tooltips on the switch and open button preserve today's exact strings.

## Empty state

When `load_displayed_mounts()` returns no rows, the preferences page is
hidden and replaced by an `Adw.StatusPage`:

- icon: `folder-remote-symbolic`
- title: "No SMB shares"
- description: "Click *Add Share* to mount one."
- child: a suggested-action button "Add Share" that opens the Add Share dialog
  (same handler as the header button).

## Add Share dialog

`AddShareDialog(Adw.Dialog)` — single page, progressive reveal.

- Header: `Adw.HeaderBar` with `Cancel` (start) and a suggested-action `Add`
  (end). `Add` is insensitive until the host check has succeeded and both
  credential fields are non-empty.
- Body: `Adw.Clamp` wrapping a vertical `Gtk.Box` of two
  `Adw.PreferencesGroup`s (not `Adw.PreferencesPage`, whose internal
  `ScrolledWindow` would pin the dialog at a fixed height and prevent it from
  growing when the credentials group is revealed):
  - **Share** group:
    - `Adw.EntryRow` titled "Share path". The group description carries the
      example: `//192.168.1.2/sharename or //hostname/sharename`.
    - The host check (currently a separate "Check host" button) runs
      automatically after a short typing debounce once the entered path
      parses. A spinner is shown in the row's apply / trailing area while the
      check is in flight, replaced by a green check icon on success or a red
      error icon on failure. The row's subtitle conveys the result text.
  - **Credentials** group:
    - `Adw.EntryRow` titled "Username".
    - `Adw.PasswordEntryRow` titled "Password".
    - The group's `visible` property is bound to "host check succeeded".
- Submitting `Add` runs the existing test-mount → helper-create flow on a
  worker thread (today's logic is preserved). On success the dialog closes,
  the main window's list refreshes, and a toast is shown. On failure an
  `Adw.Banner` is added at the top of the dialog body with the error message;
  the dialog stays open so the user can correct input and retry.

## Delete confirmation

`DeleteAlertDialog` is an `Adw.AlertDialog`:

- Heading: "Delete this SMB mount?"
- Body: "Removes `{record.source}` and its systemd units. The encrypted
  credentials will also be deleted."
- Responses: `cancel` ("Cancel", default) and `delete` ("Delete",
  destructive appearance).

On confirm, the existing helper-delete flow runs. On failure, the alert
closes and a toast is shown with the error; if the error message is long, the
toast has a "Details" button that opens a transient `Adw.AlertDialog` with the
full text.

## About dialog

`Adw.AboutDialog` populated from the existing constants:

- application name: `APP_NAME`
- application icon: `APP_ICON_NAME`
- developer name(s): `APP_DEVELOPERS`
- website: `APP_WEBSITE`
- license type: `Gtk.License.GPL_3_0_ONLY`
- comments: "Create and manage on-demand SMB mounts."

The current `Gtk.AboutDialog` invocation is removed.

## Toasts and banners (replacing MessageWindow)

`MessageWindow` is deleted. Every existing call site is reclassified:

| Existing call | New behavior |
| --- | --- |
| `MessageWindow(self, "SMB Mount Created", …)` | `Adw.Toast` in main window. |
| `MessageWindow(self, "SMB Mount Upgraded", …)` | `Adw.Toast` in main window. |
| `MessageWindow(self, "Open Folder Failed", …)` | `Adw.Toast` (with "Details" button if message is long). |
| `MessageWindow(self, "Upgrade Failed", …)` | `Adw.Toast` (with "Details" button). |
| `MessageWindow(self, "Mount Toggle Failed", …)` | `Adw.Toast` (with "Details" button). |
| Test-mount failure inside Add Share | `Adw.Banner` at top of Add Share dialog, dialog stays open. |
| Delete failure inside Delete confirmation | Alert closes, error shown as toast in main window. |

## Startup checks

A new `ensure_libadwaita_supported()` function runs before window creation. It
checks the linked libadwaita version (via `Adw.MAJOR_VERSION`,
`Adw.MINOR_VERSION`) and refuses to start with a clear stderr message if the
version is below 1.5. This mirrors the existing `require_systemd_support()`
pattern.

## Out of scope

- Helper-mode subprocess (`--helper create|delete|upgrade|set-enabled`).
- polkit / `pkexec` invocation.
- systemd-creds encryption and credential file paths.
- Mount-unit generation and the `/mnt/mount-manager` / `/etc/mount-manager`
  layout.
- `argparse`, `main()`, and the `--helper` entry point in `mount_manager.py`.
- No new third-party Python dependencies. The only new runtime dependency is
  the system libadwaita ≥ 1.5 typing, already present on supported targets.
- RPM spec changes are not in this repo; only README and AppImage notes are
  updated here.

## Risks

- **Host libadwaita version drift.** The AppImage runs against the host's
  libadwaita. Systems with libadwaita < 1.5 will be rejected at startup with a
  clear message. Bazzite and current Fedora ship ≥ 1.5, so impact is limited
  to outliers.
- **Toast vs. window for success messages.** The user no longer dismisses a
  modal window after each successful operation. This is a deliberate UX
  improvement but should be verified by manual testing on a real Bazzite
  install before release.
- **Automatic host check on type.** Removing the explicit "Check host" button
  means hostname / DNS lookups run as the user types (debounced). Network
  errors and slow DNS need to be surfaced clearly in the row's status area to
  avoid the dialog feeling broken. The existing host-check function is reused
  unchanged; only its invocation timing changes.
