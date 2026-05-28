# Libadwaita 1.8 Baseline Bump — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the minimum libadwaita to 1.8 and adopt the newer APIs it (and modern GTK) enable: `Adw.Spinner`, `Adw.ShortcutsDialog`, `Gtk.FileLauncher`, and `AdwPreferencesGroup.set_separate_rows()`.

**Architecture:** Five small surgical changes on the `feat/libadwaita-01` branch. The version bump comes first (with its test-fixture rebase) so subsequent tasks legitimately depend on the new floor. Each subsequent task swaps a single API call site and gets its own commit. No new modules; no architectural change.

**Tech Stack:** Python 3, GTK 4 (≥ 4.18 transitively), libadwaita ≥ 1.8, PyGObject. Tests: stock `unittest` (no pytest).

**Source spec:** `docs/superpowers/specs/2026-05-28-libadwaita-1.8-bump-design.md`

**Pre-flight (executor):**
- Confirm working tree is clean for tracked files (`git status` should show no `M` lines for `mount_manager.py`, `mount_manager_ui.py`, `README.md`, or `tests/`).
- Confirm the runtime libadwaita is at least 1.8: `python3 -c "import gi; gi.require_version('Adw','1'); from gi.repository import Adw; print(Adw.MAJOR_VERSION, Adw.MINOR_VERSION)"` should print `1 8` or higher.
- Baseline test run: `python3 -m unittest discover -s tests -v` should report 9 tests, all passing.

---

## Task 1: Bump `MIN_LIBADWAITA_VERSION` to (1, 8)

**Files:**
- Modify: `mount_manager.py:52-53`
- Modify: `tests/test_libadwaita_support.py` (full file)
- Modify: `README.md:27`

This task is genuinely TDD-shaped: the version-support test file is the contract we're changing. Rebase the test fixtures first, watch them fail, then update the constant.

- [ ] **Step 1: Rebase the test fixtures on the new (1, 8) floor**

Replace the entire body of `tests/test_libadwaita_support.py` with:

```python
"""Unit tests for the libadwaita version comparator."""

import unittest

from mount_manager import _libadwaita_supports


class LibadwaitaSupportsTest(unittest.TestCase):
    def test_minimum_supported_version(self) -> None:
        self.assertTrue(_libadwaita_supports(1, 8))

    def test_newer_minor_supported(self) -> None:
        self.assertTrue(_libadwaita_supports(1, 9))

    def test_newer_major_supported(self) -> None:
        self.assertTrue(_libadwaita_supports(2, 0))

    def test_older_minor_unsupported(self) -> None:
        self.assertFalse(_libadwaita_supports(1, 7))

    def test_older_major_unsupported(self) -> None:
        self.assertFalse(_libadwaita_supports(0, 99))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests, confirm the floor checks fail**

Run: `python3 -m unittest discover -s tests -v`

Expected: `test_minimum_supported_version` and `test_older_minor_unsupported` FAIL.
Specifically: `_libadwaita_supports(1, 8)` returns True under the new test but currently True anyway (since 1.8 >= 1.5), so that one will not fail. The real failure is `test_older_minor_unsupported` — `_libadwaita_supports(1, 7)` returns True under the old (1, 5) floor but the test now asserts False.

(The minimum-version test continues to pass coincidentally; the older-minor test is the one that proves the change.)

- [ ] **Step 3: Bump the version constant and comment**

In `mount_manager.py`, replace lines 52–53:

```python
# Adw.Dialog and Adw.AlertDialog require libadwaita 1.5 or newer.
MIN_LIBADWAITA_VERSION: tuple[int, int] = (1, 5)
```

with:

```python
# Adw.ShortcutsDialog and Adw.Spinner require libadwaita 1.8 or newer.
MIN_LIBADWAITA_VERSION: tuple[int, int] = (1, 8)
```

- [ ] **Step 4: Run the tests, confirm all pass**

Run: `python3 -m unittest discover -s tests -v`

Expected: 9 tests, all pass.

- [ ] **Step 5: Update the README**

In `README.md` line 27, replace:

```
libadwaita 1.5 or newer. The app refuses to start on older versions.
```

with:

```
libadwaita 1.8 or newer. The app refuses to start on older versions.
```

- [ ] **Step 6: Smoke-launch the app**

Run: `timeout 4 python3 mount_manager.py` (in a desktop session). The app should launch and show its main window. Close it (or let the timeout kill it).

Expected: No "libadwaita too old" message. App reaches the main window.

- [ ] **Step 7: Commit**

```bash
git add mount_manager.py tests/test_libadwaita_support.py README.md
git commit -m "feat: raise minimum libadwaita to 1.8"
```

---

## Task 2: Swap `Gtk.Spinner` → `Adw.Spinner`

**Files:**
- Modify: `mount_manager_ui.py` — `AddShareDialog.__init__` host_spinner construction; `AddShareDialog._set_host_status`; `AddShareDialog._run_host_check`.

`Adw.Spinner` (libadwaita 1.6) spins whenever it is realized and visible. It has no `start()` / `stop()` methods — those calls become no-ops on `Adw.Spinner` and would raise `AttributeError`. Replace the construction call and delete the explicit `start()` / `stop()` calls.

- [ ] **Step 1: Swap the construction call**

In `mount_manager_ui.py`, locate (inside `AddShareDialog.__init__`):

```python
            self.host_spinner = Gtk.Spinner()
```

Replace with:

```python
            self.host_spinner = Adw.Spinner()
```

- [ ] **Step 2: Drop the `stop()` call in `_set_host_status`**

In `_set_host_status`, locate:

```python
        def _set_host_status(self, *, ok: bool | None, message: str) -> None:
            self.host_spinner.set_visible(False)
            self.host_spinner.stop()
```

Replace with:

```python
        def _set_host_status(self, *, ok: bool | None, message: str) -> None:
            self.host_spinner.set_visible(False)
```

- [ ] **Step 3: Drop the `start()` call in `_run_host_check`**

In `_run_host_check`, locate:

```python
            self.host_spinner.set_visible(True)
            self.host_spinner.start()
```

Replace with:

```python
            self.host_spinner.set_visible(True)
```

- [ ] **Step 4: Run the smoke test**

Run: `python3 -m unittest discover -s tests -v`

Expected: 9 tests, all pass. (The smoke test `test_import_mount_manager` will catch any import-level break.)

- [ ] **Step 5: Manual verification (executor or user)**

Launch: `python3 mount_manager.py` → click "Add Share" → type a hostname (e.g. `192.0.2.1`, an unroutable address). The spinner appears next to the share-path field while the host check is in flight, then disappears and is replaced by an error icon. No `AttributeError` in stderr.

(If the executor cannot reach a desktop session, document the verification as deferred to the user and proceed.)

- [ ] **Step 6: Commit**

```bash
git add mount_manager_ui.py
git commit -m "refactor(ui): use Adw.Spinner in Add Share dialog"
```

---

## Task 3: Rewrite the shortcuts dialog using `Adw.ShortcutsDialog`

**Files:**
- Modify: `mount_manager_ui.py` — `build_shortcuts_window()` (helper inside `run_gui()`); `MountManagerApplication._show_shortcuts()`.

`Adw.ShortcutsDialog` (libadwaita 1.8) replaces the deprecated `Gtk.ShortcutsWindow`. It extends `Adw.Dialog` (so it presents via `.present(parent)`, not `transient_for=`). Items can specify `action_name=` and the dialog auto-resolves the accelerator from `set_accels_for_action()` registered on the application — so we no longer duplicate accelerator literals here.

- [ ] **Step 1: Replace the helper function**

In `mount_manager_ui.py`, locate the entire `build_shortcuts_window` function inside `run_gui()`:

```python
    def build_shortcuts_window(parent: Gtk.Window) -> Gtk.ShortcutsWindow:
        """Construct the keyboard shortcuts dialog for the app."""
        window = Gtk.ShortcutsWindow(transient_for=parent, modal=True)

        section = Gtk.ShortcutsSection(section_name="main", visible=True)

        general = Gtk.ShortcutsGroup(title="General")
        general.append(
            Gtk.ShortcutsShortcut(title="Add Share", accelerator="<Primary>n")
        )
        general.append(Gtk.ShortcutsShortcut(title="Refresh", accelerator="<Primary>r"))
        general.append(Gtk.ShortcutsShortcut(title="Primary Menu", accelerator="F10"))
        general.append(
            Gtk.ShortcutsShortcut(
                title="Keyboard Shortcuts", accelerator="<Primary>question"
            )
        )
        general.append(
            Gtk.ShortcutsShortcut(title="Close Window", accelerator="<Primary>w")
        )
        general.append(Gtk.ShortcutsShortcut(title="Quit", accelerator="<Primary>q"))
        section.append(general)

        window.add_section(section)
        return window
```

Replace with:

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

(Note: the helper is renamed from `build_shortcuts_window` to `build_shortcuts_dialog` to match the new return type. Step 2 updates the only caller.)

- [ ] **Step 2: Update `MountManagerApplication._show_shortcuts()`**

In `mount_manager_ui.py`, locate (inside `MountManagerApplication`):

```python
        def _show_shortcuts(self) -> None:
            window = self.props.active_window
            if window is None:
                return
            shortcuts_window = build_shortcuts_window(window)
            shortcuts_window.present()
```

Replace with:

```python
        def _show_shortcuts(self) -> None:
            window = self.props.active_window
            if window is None:
                return
            dialog = build_shortcuts_dialog()
            dialog.present(window)
```

- [ ] **Step 3: Confirm no other references to the old name**

Run: `grep -n "build_shortcuts_window\|Gtk.ShortcutsWindow\|Gtk.ShortcutsSection\|Gtk.ShortcutsGroup\|Gtk.ShortcutsShortcut" mount_manager_ui.py`

Expected: no output. If anything matches, fix it before continuing.

- [ ] **Step 4: Run the smoke test**

Run: `python3 -m unittest discover -s tests -v`

Expected: 9 tests, all pass.

- [ ] **Step 5: Manual verification (executor or user)**

Launch: `python3 mount_manager.py` → press `Ctrl+?`. A libadwaita-styled shortcuts dialog appears. Each row shows its accelerator (e.g. `Ctrl+N` next to "Add Share"); the accelerators are sourced automatically from `set_accels_for_action()`. No deprecation warnings in stderr.

(If the executor cannot reach a desktop session, document the verification as deferred to the user and proceed.)

- [ ] **Step 6: Commit**

```bash
git add mount_manager_ui.py
git commit -m "refactor(ui): use Adw.ShortcutsDialog for keyboard shortcuts"
```

---

## Task 4: Swap `xdg-open` subprocess → `Gtk.FileLauncher`

**Files:**
- Modify: `mount_manager_ui.py` — `MainWindow.open_mount_folder()`; possibly the `run_command` import at the top of the file.

`Gtk.FileLauncher` (GTK 4.10) opens a file or folder with the desktop's default handler. It's async and reports failures via `GError` so we can distinguish user cancellation from real failures.

- [ ] **Step 1: Rewrite `open_mount_folder` and add `_on_open_folder_done`**

In `mount_manager_ui.py`, locate (inside `MainWindow`):

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

Replace with:

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
                if exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    return
                self.show_toast(f"Could not open folder: {exc.message}")
```

- [ ] **Step 2: Check whether `run_command` is still used in `mount_manager_ui.py`**

Run: `grep -n "run_command" mount_manager_ui.py`

If the only remaining match is the import line at the top of the file, remove `run_command` from the import list.

Locate (near the top of the file):

```python
from mount_manager import (
    ...
    run_command,
    ...
)
```

If `run_command` is no longer referenced anywhere else in the file, delete the `    run_command,` line from the import.

- [ ] **Step 3: Run the smoke test**

Run: `python3 -m unittest discover -s tests -v`

Expected: 9 tests, all pass.

- [ ] **Step 4: Static check — confirm the new symbols are imported**

Run: `grep -nE "^from gi.repository" mount_manager_ui.py`

Expected: the line already imports `Gio`, `GLib`, and `Gtk`, so no import changes are needed for the new code.

- [ ] **Step 5: Manual verification (executor or user)**

Launch: `python3 mount_manager.py`. With at least one managed mount enabled, click its folder icon. The system file manager opens at the mount point. If you have no managed mounts handy, skip the visible part of this check — the `unittest` smoke test will have already caught any Python-level breakage.

(If the executor cannot reach a desktop session, document the verification as deferred to the user and proceed.)

- [ ] **Step 6: Commit**

```bash
git add mount_manager_ui.py
git commit -m "refactor(ui): open mount folders with Gtk.FileLauncher"
```

---

## Task 5: Render mount rows as separate cards

**Files:**
- Modify: `mount_manager_ui.py` — `MainWindow.__init__` mount group construction.

`AdwPreferencesGroup.set_separate_rows(True)` (libadwaita 1.6) renders each row as its own boxed card instead of a single grouped container. The empty state is unaffected (the `AdwStatusPage` is shown in place of the group when no mounts exist).

- [ ] **Step 1: Add the `set_separate_rows` call**

In `mount_manager_ui.py`, locate (inside `MainWindow.__init__`):

```python
            self.mount_group = Adw.PreferencesGroup()
            self.preferences_page.add(self.mount_group)
```

Replace with:

```python
            self.mount_group = Adw.PreferencesGroup()
            self.mount_group.set_separate_rows(True)
            self.preferences_page.add(self.mount_group)
```

- [ ] **Step 2: Run the smoke test**

Run: `python3 -m unittest discover -s tests -v`

Expected: 9 tests, all pass.

- [ ] **Step 3: Manual verification (executor or user)**

Launch: `python3 mount_manager.py`. With at least one managed mount listed, each mount renders as its own card row rather than as a list inside a single bordered container.

(If the executor cannot reach a desktop session, document the verification as deferred to the user and proceed.)

- [ ] **Step 4: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): render mount rows as separate cards"
```

---

## Final verification

After all five tasks are committed:

- [ ] **Run the full test suite:**

```bash
python3 -m unittest discover -s tests -v
```

Expected: 9 tests, all pass.

- [ ] **Verify the helper path is still GUI-free:**

```bash
python3 -X importtime mount_manager.py --helper set-enabled --manager-id never --enabled 0 2>&1 | grep -E "gi\.repository\.(Gtk|Adw)"
```

Expected: no matches. (Per `AGENTS.md`: the helper path must not import GTK/Adw.)

The command will exit non-zero (the helper is unprivileged when not run via pkexec, so it'll bail) — that's expected. We only care that no GTK/Adw import showed up.

- [ ] **Inspect commit history:**

```bash
git log --oneline -n 5
```

Expected: five new commits, one per task, on the `feat/libadwaita-01` branch.

- [ ] **Verify no deprecation warnings when launching:**

```bash
timeout 4 python3 mount_manager.py 2>&1 | grep -iE "deprecat|warning" || echo "OK — no deprecations"
```

Expected: `OK — no deprecations`. (In particular, the `Gtk.ShortcutsWindow.add_section` deprecation noted at the end of the HIG-fixes plan should no longer appear.)
