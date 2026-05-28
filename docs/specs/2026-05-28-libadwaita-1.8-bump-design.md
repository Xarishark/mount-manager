# Libadwaita 1.8 Baseline Bump — Design

**Date:** 2026-05-28
**Branch:** `feat/libadwaita-01` (pre-merge)
**Status:** Approved by user; ready for implementation plan.

## Goal

Raise the minimum libadwaita to 1.8 and opportunistically adopt newer APIs
made possible by the bump (`Adw.Spinner`, `Adw.ShortcutsDialog`). Also
modernize the "open folder" path off `xdg-open` onto `Gtk.FileLauncher`
(GTK 4.10) while we're touching the stack. This keeps the floor in line
with current GNOME, clears the accepted `Gtk.ShortcutsWindow` deprecation
noted at the end of the HIG-fixes plan, and removes a subprocess wart.

## Scope

Five coupled changes:

1. **Bump the floor.** `MIN_LIBADWAITA_VERSION: tuple[int, int] = (1, 5)` →
   `(1, 8)` in `mount_manager.py`. Update the comment above it (currently
   "Adw.Dialog and Adw.AlertDialog require libadwaita 1.5 or newer") to
   reflect what 1.8 buys us.

2. **`Gtk.Spinner` → `Adw.Spinner`** (libadwaita 1.6) inside
   `AddShareDialog`. `Adw.Spinner` spins whenever it is visible, so the
   `start()` / `stop()` calls in `_set_host_status` and `_run_host_check` can
   be deleted entirely — `set_visible(True/False)` is sufficient.

3. **`Gtk.ShortcutsWindow` family → `Adw.ShortcutsDialog` family**
   (libadwaita 1.8) inside `build_shortcuts_window()`. The replacement uses
   `Adw.ShortcutsDialog.add(section)` with `Adw.ShortcutsSection(title=...)`
   containing `Adw.ShortcutsItem` children. The new API lets each item refer
   to an action by name (`action_name="app.quit"`) and libadwaita
   auto-discovers the accelerator from `set_accels_for_action`, so we no
   longer have to repeat each accelerator literal. Resolves the deprecation
   note from Task 6 of the HIG-fixes plan.

4. **`xdg-open` subprocess → `Gtk.FileLauncher`** (GTK 4.10) inside
   `MainWindow.open_mount_folder()`. The current implementation shells out
   to `xdg-open` via `run_command`, which collapses every failure mode
   into a generic `MountManagerError`. `Gtk.FileLauncher.launch()` is
   async, integrates with the desktop's URI launcher (and portals where
   applicable), and reports failure via a proper `GError` we can show as a
   toast.

5. **`AdwPreferencesGroup.set_separate_rows(True)`** (libadwaita 1.6) on
   the mount list group in `MainWindow`. Renders each mount as its own
   boxed card row instead of a single grouped container. Visually
   confirmed to read better than the grouped style for this list. One
   line in `MainWindow.__init__`. No change needed for the empty state
   (the `AdwStatusPage` is shown instead of the group when there are no
   mounts).

## Out of scope

- Adoption of any other 1.6–1.8 API (`AdwBottomSheet`, `AdwMultiLayoutView`,
  `AdwInlineViewSwitcher`, `AdwButtonRow`, `AdwToggleGroup`). These have no
  current pull from the codebase and will be considered as needs arise.
- Refactoring the hybrid `AdwActionRow` mount-row pattern to use
  `AdwSwitchRow`. The hybrid pattern was a deliberate design choice from
  the libadwaita migration; switching now would unwind that. Out of scope.

## Files touched

| File | Change |
|------|--------|
| `mount_manager.py` | Version constant + the comment above it. ~2 lines. |
| `mount_manager_ui.py` | `Adw.Spinner` swap (~3 lines, net simpler). `build_shortcuts_window()` rewrite (~30 lines net). `open_mount_folder()` swap to `Gtk.FileLauncher` (~10 lines). `mount_group.set_separate_rows(True)` (1 line). |
| `README.md` | "libadwaita 1.5 or newer" → "libadwaita 1.8 or newer" (line 27). |
| `tests/test_libadwaita_support.py` | Rebase fixture values on `(1, 8)` — e.g. `older_minor=(1, 7)`, `newer_minor=(1, 9)`, `newer_major=(2, 0)`, etc. |
| `AGENTS.md` | No change. It already says `MIN_LIBADWAITA_VERSION` is the single source of truth and never hardcodes a number. |

## Detailed API notes

### Adw.Spinner (1.6)

`Adw.Spinner` is a `Gtk.Widget` subclass with no methods of its own
(inherited GObject only). It spins continuously when realized and visible.
No `start()` / `stop()`. Sizing follows allocation, never smaller than
16×16, never larger than 64×64. As an `EntryRow` suffix the row's natural
height will allocate appropriately; no `width-request`/`height-request`
needed.

Current usage in `AddShareDialog`:

```python
self.host_spinner = Gtk.Spinner()
self.host_spinner.set_valign(Gtk.Align.CENTER)
self.host_spinner.set_visible(False)
self.path_row.add_suffix(self.host_spinner)
# …
self.host_spinner.set_visible(False)
self.host_spinner.stop()
# …
self.host_spinner.set_visible(True)
self.host_spinner.start()
```

After:

```python
self.host_spinner = Adw.Spinner()
self.host_spinner.set_valign(Gtk.Align.CENTER)
self.host_spinner.set_visible(False)
self.path_row.add_suffix(self.host_spinner)
# …
self.host_spinner.set_visible(False)
# …
self.host_spinner.set_visible(True)
```

### Adw.ShortcutsDialog (1.8)

`Adw.ShortcutsDialog` extends `Adw.Dialog` (so it presents via `.present(parent)`,
not `transient_for=`). Sections are added with `dialog.add(section)`. Items
within a section can specify either `accelerator=` (literal) or
`action_name=` (auto-resolves the accelerator from
`set_accels_for_action`).

Current usage in `build_shortcuts_window()`:

```python
window = Gtk.ShortcutsWindow(transient_for=parent, modal=True)
section = Gtk.ShortcutsSection(section_name="main", visible=True)
general = Gtk.ShortcutsGroup(title="General")
general.add_shortcut(Gtk.ShortcutsShortcut(title="Add Share", accelerator="<Primary>n"))
# … five more shortcuts with literal accelerators …
section.add_group(general)
window.add_section(section)
return window
```

After (new function name reflects the new return type):

```python
def build_shortcuts_dialog() -> Adw.ShortcutsDialog:
    """Construct the keyboard shortcuts dialog for the app."""
    dialog = Adw.ShortcutsDialog()

    general = Adw.ShortcutsSection(title="General")
    general.add(Adw.ShortcutsItem(title="Add Share", action_name="win.add-share"))
    general.add(Adw.ShortcutsItem(title="Refresh", action_name="win.refresh"))
    general.add(Adw.ShortcutsItem(title="Primary Menu", action_name="win.show-menu"))
    general.add(Adw.ShortcutsItem(title="Keyboard Shortcuts", action_name="app.shortcuts"))
    general.add(Adw.ShortcutsItem(title="Close Window", action_name="win.close"))
    general.add(Adw.ShortcutsItem(title="Quit", action_name="app.quit"))

    dialog.add(general)
    return dialog
```

The `_show_shortcuts()` method in `MountManagerApplication` changes from
`shortcuts_window.present()` (no parent) to
`shortcuts_dialog.present(window)` (AdwDialog requires a parent):

```python
def _show_shortcuts(self) -> None:
    window = self.props.active_window
    if window is None:
        return
    dialog = build_shortcuts_dialog()
    dialog.present(window)
```

**Action-name auto-discovery prerequisites:** The actions
(`win.add-share`, `win.refresh`, `win.show-menu`, `win.close`,
`app.shortcuts`, `app.quit`) and their accelerators must already be
registered via `set_accels_for_action()` before the dialog is built.
They are — both `MountManagerApplication.__init__` (`app.*`) and
`MainWindow.__init__` (`win.*`) run before any `Ctrl+?` press.

### Gtk.FileLauncher (GTK 4.10)

`Gtk.FileLauncher` opens a file or folder with the desktop's default
handler. Constructed from a `Gio.File`, launched async with a parent
window for modality, completed via a `GAsyncReadyCallback`. Errors come
back as `GError` from `launch_finish()`, so we get distinct failure
reasons (cancelled, no handler, permission denied) instead of a single
`MountManagerError` from a subprocess exit code.

Current usage in `MainWindow.open_mount_folder`:

```python
def open_mount_folder(self, record: ManagedMount) -> None:
    if not record.mount_point.exists():
        self.show_toast(f"Mount folder does not exist: {record.mount_point}")
        return
    try:
        run_command(["xdg-open", str(record.mount_point)])
    except MountManagerError as exc:
        self.show_toast(f"Could not open {record.mount_point}: {exc}")
```

After:

```python
def open_mount_folder(self, record: ManagedMount) -> None:
    if not record.mount_point.exists():
        self.show_toast(f"Mount folder does not exist: {record.mount_point}")
        return
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(record.mount_point)))
    launcher.launch(self, None, self._on_open_folder_done)

def _on_open_folder_done(
    self, launcher: Gtk.FileLauncher, result: Gio.AsyncResult
) -> None:
    try:
        launcher.launch_finish(result)
    except GLib.Error as exc:
        # Gio.IOErrorEnum.CANCELLED is the user dismissing a portal/handler
        # dialog; not worth a toast.
        if exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
            return
        self.show_toast(f"Could not open folder: {exc.message}")
```

The `run_command` import in `mount_manager_ui.py` may become unused — drop
it if so. `Gtk.FileLauncher` was introduced in GTK 4.10; our minimum
libadwaita 1.8 transitively requires GTK ≥ 4.18 (libadwaita 1.8's hard
floor), so this is always available.

## Distribution impact

Libadwaita 1.8 was released in September 2025. As of May 2026 the floor
covers:

- Fedora 43+ (current release)
- Ubuntu 25.10+
- Rolling distros (Arch, openSUSE Tumbleweed)
- Flatpak runtime 48
- AppImage users: unaffected — `packaging/build-appimage.sh` bundles
  libadwaita into the AppImage at build time

Users on Fedora ≤ 42, Ubuntu LTS 24.04 or 25.04 will see the version-gate
error and must use the AppImage or a newer distro. Acceptable cost per
user direction (the branch has not landed in any production release).

## Testing

- Stock `unittest` only, per `AGENTS.md`. No new test dependencies.
- `tests/test_libadwaita_support.py` fixture values rebased on `(1, 8)`.
  All five existing test cases (`test_minimum_supported_version`,
  `test_newer_major_supported`, `test_newer_minor_supported`,
  `test_older_major_unsupported`, `test_older_minor_unsupported`) keep
  their shape — only the numeric inputs change.
- Widget construction is verified manually per `AGENTS.md`. The smoke
  test (`test_import_mount_manager`) will catch any Python-level breakage
  in the spinner and dialog rewrites.

Manual verification checklist for the user:

1. App launches; no "libadwaita too old" message.
2. Add Share → type a host → spinner spins while resolving, disappears
   when the check completes; check icon appears for reachable host, error
   icon for unreachable.
3. `Ctrl+?` opens a libadwaita-styled shortcuts dialog (note: visually
   distinct from the old `Gtk.ShortcutsWindow` look). Each row shows its
   accelerator badge sourced from `set_accels_for_action`.
4. No deprecation warnings appear in stderr when running the app.
5. With at least one managed mount enabled, click the folder icon → the
   system file manager opens at the mount point. Dismissing any portal
   dialog does not produce a toast; a real failure (e.g. mount point
   removed mid-click) does.
6. Mount list rows render as separate cards (one boxed row per mount)
   rather than a single grouped container.

## Risks / open questions

- **None blocking.** API surface confirmed against current libadwaita
  documentation. Action-name auto-discovery is the only non-obvious
  mechanism and its prerequisites are already satisfied by the existing
  code structure.

## Reference

- Libadwaita ShortcutsDialog docs:
  https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/class.ShortcutsDialog.html
- Libadwaita Spinner docs:
  https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/class.Spinner.html
- HIG-fixes plan (notes the deprecation this spec resolves):
  `docs/plans/2026-05-28-hig-fixes.md` Task 6
- Original migration design (for context on hybrid row pattern, etc.):
  `docs/specs/2026-05-28-libadwaita-migration-design.md`
