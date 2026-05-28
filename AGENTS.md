# AGENTS.md

## Architecture

The application is split across two files:

- `mount_manager.py` — entry point, constants, dataclasses (`SharePath`, `ManagedMount`,
  `DisplayedMount`), exceptions, privileged helper-mode logic (`run_helper_mode`), polkit
  invocations (`request_helper_*`), and pure helpers (`check_smb_host_reachable`,
  `load_displayed_mounts`, `validate_credentials`, `_libadwaita_supports`).
  This module **must remain importable without a display and without libadwaita**: it is
  re-executed as root via `pkexec /usr/bin/mount-manager --helper …` and that path must
  not pull in GTK/Adw. Keep all GUI imports lazy (inside `run_gui()`).
- `mount_manager_ui.py` — all GTK4 / libadwaita UI. Defines a thin module-level
  `run_gui()` that contains the `MainWindow`, `AddShareDialog`, and
  `MountManagerApplication` classes nested inside it. Imports the data + helpers it needs
  from `mount_manager`.

`mount_manager.run_gui()` is a one-line shim that imports `mount_manager_ui` lazily so the
`--helper` path never loads GUI code.

## UI conventions (libadwaita ≥ 1.5)

- Minimum libadwaita version is enforced by `mount_manager._libadwaita_supports` and
  `ensure_libadwaita_supported()` in `mount_manager_ui`. Bumping `MIN_LIBADWAITA_VERSION`
  in `mount_manager.py` is the single source of truth.
- Color scheme is delegated to `Adw.StyleManager` (`ColorScheme.DEFAULT`). Do not
  re-introduce custom CSS for theming or a custom color-scheme detector.
- The mount list uses `Adw.PreferencesPage` → `Adw.PreferencesGroup` → `Adw.ActionRow`
  per mount with the **hybrid row pattern**: switch + one inline primary suffix
  (open-folder or Upgrade) + kebab `MenuButton` containing destructive actions.
  Unmanaged shares show a "Not managed" label and no controls.
- To enumerate or clear rows in an `Adw.PreferencesGroup`, use
  `group.get_row(index)` — not `get_first_child()`, which returns the group's internal
  structure widgets, not the `ActionRow` children.
- Status / error messages are surfaced as `Adw.Toast` via `MainWindow.show_toast()`.
  Do not add new `Gtk.Window` / `Adw.Window` message dialogs.
- Confirmation prompts use `Adw.AlertDialog`; destructive responses get
  `Adw.ResponseAppearance.DESTRUCTIVE`.
- The Add Share flow is a single-page progressive-reveal `Adw.Dialog` with a 300ms
  debounced host check (`GLib.timeout_add` + `GLib.source_remove`). Any pending timer
  **must** be cancelled on the dialog's `"closed"` signal to avoid firing callbacks on
  destroyed widgets.
- Always escape user-controlled strings (mount paths, statuses) with
  `GLib.markup_escape_text` before passing them to widgets that render Pango markup.
- About box uses `Adw.AboutDialog`.

## Tests

- Stock `unittest` only — no pytest, no new dependencies.
- Run: `python3 -m unittest discover -s tests -v`
- Unit-test pure-Python helpers (e.g. `_libadwaita_supports`, `mount_status_line`).
  Widget construction is verified manually — do not add headless GTK widget-tree
  assertions to the test suite.

## Packaging

- `packaging/build-appimage.sh` installs both `mount_manager.py` (as `mount-manager`) and
  `mount_manager_ui.py` (verbatim filename) into `$appdir/usr/bin/`. Python's
  `sys.path[0]` covers the script directory, so the bare `import mount_manager_ui` in the
  GUI shim resolves without `sys.path` manipulation.
- `packaging/appimage-helper.patch` rewrites the helper invocation so the AppImage
  re-execs itself under `pkexec`. Do not change the helper CLI surface
  (`--helper {create|delete|upgrade|set-enabled}`) without updating this patch.
- If you add a new top-level Python module that the GUI imports, you must add a matching
  `install` line in `packaging/build-appimage.sh` AND in the README's manual-install
  section.

## Reference docs

- Design spec: `docs/specs/2026-05-28-libadwaita-migration-design.md`
- Implementation plan (executed, kept for context): `docs/plans/2026-05-28-libadwaita-migration.md`

## Working rules
- Prefer native tools (view/edit/create/grep/glob) over shell for file reading, editing, and
  searching. Use shell only when there is no native equivalent (running tests, builds, git, gh,
  packaging).
- Ad-hoc `python3 -c '...'` snippets for verification are fine. Do not add new throwaway scripts
  to the repo; if a check is worth keeping, make it a unittest under `tests/`.
- Ask before any destructive or irreversible operation: force-push, history rewrites, deleting
  branches that exist on the remote, mass file deletion, or modifying files outside the repo.
- Do not add `Co-authored-by:` trailers to commit messages.
