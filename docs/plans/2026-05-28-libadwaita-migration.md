# libadwaita UI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the Mount Manager GUI from plain GTK 4 widgets to libadwaita ≥ 1.5, splitting the UI code out of `mount_manager.py` into a new `mount_manager_ui.py` module.

**Architecture:** In-place migration. `mount_manager.py` keeps data models, systemd/credentials plumbing, polkit handoff, and the `--helper` subprocess entry point. A new `mount_manager_ui.py` defines `Adw.Application`, `Adw.ApplicationWindow` (with `Adw.ToolbarView` + `Adw.ToastOverlay`), an `AddShareDialog(Adw.Dialog)`, an `Adw.AlertDialog`-based delete confirmation, and an `Adw.AboutDialog`. The custom `APP_CSS` and manual color-scheme detection are deleted in favor of `Adw.StyleManager`.

**Tech Stack:** Python 3, PyGObject (`gi`), GTK 4, libadwaita ≥ 1.5, stdlib `unittest` for tests.

**Spec reference:** `docs/specs/2026-05-28-libadwaita-migration-design.md`

## Testing strategy

This project has no existing test suite. We add stdlib `unittest` tests for the **pure-Python helpers** introduced or touched by this plan (`_libadwaita_supports`, `mount_status_line`). For the GTK/Adw widget construction we use **manual verification on a Bazzite host** because headless widget-tree assertions add little value and would require introducing Xvfb/`gi` to CI for no gain. Each task that builds widgets includes a concrete manual-verification checklist; tasks that introduce a pure helper include a real unittest.

**Test command** (used throughout): `python3 -m unittest discover -s tests -v`
**App run command** (used throughout): `python3 mount_manager.py`

---

## File Structure

After this plan is complete:

- `mount_manager.py` — data models, systemd/creds plumbing, `--helper` subprocess, `_libadwaita_supports()`, `main()`. **No GUI code.**
- `mount_manager_ui.py` *(new)* — `gi.require_version("Adw","1")` at module level. Defines `ensure_libadwaita_supported`, `apply_style_manager`, `mount_status_line`, `MainWindow(Adw.ApplicationWindow)`, `AddShareDialog(Adw.Dialog)`, `DeleteAlertDialog` (factory returning `Adw.AlertDialog`), `MountManagerApplication(Adw.Application)`, and `run_gui()`.
- `tests/` *(new)* — `__init__.py` (empty), `test_libadwaita_support.py`, `test_mount_status_line.py`.
- `packaging/build-appimage.sh` — installs `mount_manager_ui.py` alongside `mount_manager.py`.
- `README.md` — adds libadwaita requirement and updates manual-install commands.

---

## Task 1: Test scaffolding

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

This task establishes the test harness so later tasks can add real tests. It includes a single trivial smoke test that imports `mount_manager` to confirm the harness works.

- [ ] **Step 1: Create empty `tests/__init__.py`**

```bash
mkdir -p tests
: > tests/__init__.py
```

- [ ] **Step 2: Create `tests/test_smoke.py`**

```python
"""Smoke test ensuring the test harness can import the main module."""

import unittest


class ImportSmokeTest(unittest.TestCase):
    def test_import_mount_manager(self) -> None:
        import mount_manager  # noqa: F401

        self.assertTrue(hasattr(mount_manager, "main"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test**

Run: `python3 -m unittest discover -s tests -v`
Expected output ends with `OK` and shows `test_import_mount_manager ... ok`.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add unittest scaffolding with import smoke test"
```

---

## Task 2: `_libadwaita_supports()` version check helper

**Files:**
- Modify: `mount_manager.py` (add helper near `MIN_SYSTEMD_VERSION`)
- Create: `tests/test_libadwaita_support.py`

Adds a pure comparator usable without `gi` so it can be unit-tested directly. The actual `ensure_libadwaita_supported()` (which reads `Adw.MAJOR_VERSION`/`Adw.MINOR_VERSION`) lives in the UI module and calls this.

- [ ] **Step 1: Write the failing test**

Create `tests/test_libadwaita_support.py`:

```python
"""Unit tests for the libadwaita version comparator."""

import unittest

from mount_manager import _libadwaita_supports


class LibadwaitaSupportsTest(unittest.TestCase):
    def test_minimum_supported_version(self) -> None:
        self.assertTrue(_libadwaita_supports(1, 5))

    def test_newer_minor_supported(self) -> None:
        self.assertTrue(_libadwaita_supports(1, 7))

    def test_newer_major_supported(self) -> None:
        self.assertTrue(_libadwaita_supports(2, 0))

    def test_older_minor_unsupported(self) -> None:
        self.assertFalse(_libadwaita_supports(1, 4))

    def test_older_major_unsupported(self) -> None:
        self.assertFalse(_libadwaita_supports(0, 99))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `python3 -m unittest tests.test_libadwaita_support -v`
Expected: `ImportError: cannot import name '_libadwaita_supports' from 'mount_manager'`

- [ ] **Step 3: Add the helper and a `MIN_LIBADWAITA_VERSION` constant**

In `mount_manager.py`, locate the line `MIN_SYSTEMD_VERSION = 258` and insert immediately after it:

```python
# Adw.Dialog and Adw.AlertDialog require libadwaita 1.5 or newer.
MIN_LIBADWAITA_VERSION: tuple[int, int] = (1, 5)


def _libadwaita_supports(major: int, minor: int) -> bool:
    """Return True if the given libadwaita (major, minor) meets the app's minimum."""
    return (major, minor) >= MIN_LIBADWAITA_VERSION
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python3 -m unittest tests.test_libadwaita_support -v`
Expected: all five tests pass, output ends with `OK`.

- [ ] **Step 5: Commit**

```bash
git add mount_manager.py tests/test_libadwaita_support.py
git commit -m "feat: add libadwaita version comparator"
```

---

## Task 3: Extract UI to `mount_manager_ui.py` (pure refactor)

**Files:**
- Create: `mount_manager_ui.py`
- Modify: `mount_manager.py` (lines ~1148–1682: remove `import_gtk`, `apply_theme`, `run_gui` body, all nested UI classes)

This is a **pure refactor with no UI behavior change**. We move the existing GTK widgets verbatim into a new module so subsequent tasks operate on a smaller file. `APP_CSS` and `apply_theme` move with the GUI code (they will be deleted in Task 4). Constants needed by the UI (`APP_NAME`, `APP_ID`, `APP_DEVELOPERS`, `APP_WEBSITE`, `APP_ICON_NAME`, `COLOR_SCHEME_ENV`) are imported from `mount_manager`.

- [ ] **Step 1: Create `mount_manager_ui.py` with the extracted code**

Create `mount_manager_ui.py` with:

```python
"""GTK 4 GUI for SMB Mount Manager.

This module is imported lazily from ``mount_manager.run_gui``. Keeping it
separate from ``mount_manager.py`` lets the helper subprocess avoid importing
GTK when invoked with ``--helper``.
"""

from __future__ import annotations

import sys
from typing import Any

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, Gtk, Pango  # noqa: E402

from mount_manager import (
    APP_DEVELOPERS,
    APP_ICON_NAME,
    APP_ID,
    APP_NAME,
    APP_WEBSITE,
    DisplayedMount,
    ManagedMount,
    MountManagerError,
    SharePath,
    check_smb_host_reachable,
    detect_color_scheme,
    load_displayed_mounts,
    request_helper_create,
    request_helper_delete,
    request_helper_set_enabled,
    request_helper_upgrade,
    run_command,
    validate_credentials,
)


APP_CSS = """
# ... PASTE THE EXISTING APP_CSS STRING VERBATIM FROM mount_manager.py ...
"""


def apply_theme(Gtk: Any, Gdk: Any) -> None:
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property(
            "gtk-application-prefer-dark-theme",
            detect_color_scheme() == "dark",
        )

    display = Gdk.Display.get_default()
    if display is None:
        return

    Gtk.Window.set_default_icon_name(APP_ICON_NAME)

    provider = Gtk.CssProvider()
    provider.load_from_data(APP_CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def run_gui() -> int:
    if not Gtk.init_check():
        print(
            "GTK could not connect to your graphical session. Run this from your "
            "desktop session, not a plain TTY.",
            file=sys.stderr,
        )
        return 1
    if Gdk.Display.get_default() is None:
        print(
            "GTK did not provide a usable display. Run this from your desktop "
            "session, not a plain TTY.",
            file=sys.stderr,
        )
        return 1
    apply_theme(Gtk, Gdk)

    # PASTE THE EXISTING NESTED CLASSES (AddShareWindow, MessageWindow,
    # DeleteMountWindow, MainWindow, MountManagerApplication) VERBATIM HERE,
    # AS NESTED CLASSES INSIDE run_gui — DO NOT REINDENT OR EDIT THEM.

    app = MountManagerApplication()
    return app.run(sys.argv)
```

Copy the exact text of `APP_CSS` (currently `mount_manager.py` lines 53–122) into the placeholder. Copy the exact nested class definitions from `mount_manager.py` (currently lines 1200–1679) into the `run_gui` body in place of the placeholder comment — preserve indentation.

- [ ] **Step 2: Trim `mount_manager.py`**

In `mount_manager.py`:

1. Delete the `APP_CSS = """..."""` block (currently lines 53–122).
2. Delete `import_gtk()` (currently lines 1148–1156).
3. Delete `apply_theme(Gtk, Gdk)` (currently lines 1159–1179).
4. Replace the entire body of `run_gui()` with:

```python
def run_gui() -> int:
    from mount_manager_ui import run_gui as _run_gui

    return _run_gui()
```

5. Leave the existing imports in `mount_manager.py` alone — leftover imports from removed code don't affect correctness and chasing them down here is risky. They can be cleaned up after the migration is verified.

- [ ] **Step 3: Run the import smoke test**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests pass (smoke + libadwaita comparator). `OK`.

- [ ] **Step 4: Manual verification — app still works**

Run: `python3 mount_manager.py`
Expected:
- Main window opens with the same look as before this task (custom CSS still active, GTK header bar, "ADD SHARE" button visible).
- Existing mounts are listed.
- Add Share → Cancel works.
- About menu entry opens the existing `Gtk.AboutDialog`.

If anything is broken, fix the extraction (most likely cause: a missing import or a missed class reference between the nested classes).

- [ ] **Step 5: Commit**

```bash
git add mount_manager.py mount_manager_ui.py
git commit -m "refactor: split GUI code into mount_manager_ui module"
```

---

## Task 4: Adw application bootstrap, version check, StyleManager

**Files:**
- Modify: `mount_manager_ui.py`

We require libadwaita 1.5+, switch to `Adw.StyleManager`, and delete the custom CSS / theme code introduced by Task 3.

- [ ] **Step 1: Add Adw imports and version-check function**

At the top of `mount_manager_ui.py`, after `gi.require_version("Pango", "1.0")`, add:

```python
gi.require_version("Adw", "1")
```

Update the `from gi.repository` line to include `Adw`:

```python
from gi.repository import Adw, Gdk, Gio, Gtk, Pango  # noqa: E402
```

Add to the imports from `mount_manager`:

```python
    MIN_LIBADWAITA_VERSION,
    _libadwaita_supports,
```

Below the imports add:

```python
def ensure_libadwaita_supported() -> None:
    """Print an error and raise SystemExit if libadwaita is too old."""
    if not _libadwaita_supports(Adw.MAJOR_VERSION, Adw.MINOR_VERSION):
        required = ".".join(str(v) for v in MIN_LIBADWAITA_VERSION)
        found = f"{Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}"
        print(
            f"libadwaita {found} found, but this app requires {required} or newer.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def apply_style_manager() -> None:
    """Hand color-scheme selection to libadwaita's system preference tracker."""
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
    Gtk.Window.set_default_icon_name(APP_ICON_NAME)
```

- [ ] **Step 2: Delete `APP_CSS` and `apply_theme`**

In `mount_manager_ui.py`, delete the whole `APP_CSS = """..."""` block and the `apply_theme(Gtk, Gdk)` function added during Task 3.

- [ ] **Step 3: Replace the prelude of `run_gui`**

Replace the existing `apply_theme(Gtk, Gdk)` call (and the `Gdk.Display.get_default()` check that came after `Gtk.init_check`) so the prelude reads:

```python
def run_gui() -> int:
    ensure_libadwaita_supported()
    if not Gtk.init_check():
        print(
            "GTK could not connect to your graphical session. Run this from your "
            "desktop session, not a plain TTY.",
            file=sys.stderr,
        )
        return 1
    if Gdk.Display.get_default() is None:
        print(
            "GTK did not provide a usable display. Run this from your desktop "
            "session, not a plain TTY.",
            file=sys.stderr,
        )
        return 1
    apply_style_manager()

    # ... existing nested classes unchanged for now ...
```

- [ ] **Step 4: Convert the Application class**

Inside `run_gui()`, change the `MountManagerApplication` definition (currently `class MountManagerApplication(Gtk.Application):`) to:

```python
    class MountManagerApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        def do_activate(self) -> None:
            window = self.props.active_window
            if window is None:
                window = MainWindow(self)
            window.present()
```

The base class change is the only behavioral edit; `do_activate` is unchanged.

- [ ] **Step 5: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- App still launches.
- Window still shows the same content as before (we have not yet changed `MainWindow`).
- Color scheme follows the system: switch GNOME's "Style" preference (Settings → Appearance) between Light and Dark; the window should follow without restart.
- No custom CSS — the window background and header bar may look slightly different from the pre-Adw look; that is expected.

- [ ] **Step 6: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add mount_manager.py mount_manager_ui.py
git commit -m "feat(ui): switch to Adw.Application and Adw.StyleManager"
```

---

## Task 5: Adw.ApplicationWindow + ToolbarView + HeaderBar + ToastOverlay

**Files:**
- Modify: `mount_manager_ui.py` (the nested `MainWindow` class)

Convert `MainWindow` to libadwaita's shell. The header bar gets an "Add Share" suggested-action button on the left and refresh + menu buttons on the right. A `Adw.ToastOverlay` is added around the content so later tasks can call `self.show_toast("…")`. The mount list rendering inside the window body is unchanged in this task (still `Gtk.ListBox` with `boxed-list`); Tasks 6–8 replace it.

- [ ] **Step 1: Replace the `MainWindow` class header and constructor**

Inside `run_gui()`, replace the existing `class MainWindow(Gtk.ApplicationWindow):` definition (constructor only — keep `refresh`, `row_for`, `show_add_dialog`, etc. unchanged for now) with:

```python
    class MainWindow(Adw.ApplicationWindow):
        def __init__(self, app: Adw.Application) -> None:
            super().__init__(application=app, title=APP_NAME)
            self.set_default_size(760, 480)
            self.set_icon_name(APP_ICON_NAME)

            about_action = Gio.SimpleAction.new("about", None)
            about_action.connect("activate", lambda _a, _p: self.show_about_dialog())
            self.add_action(about_action)

            menu = Gio.Menu()
            menu.append(f"About {APP_NAME}", "win.about")

            menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
            menu_button.set_menu_model(menu)
            menu_button.set_tooltip_text("Main menu")

            refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            refresh_button.set_tooltip_text("Refresh")
            refresh_button.connect("clicked", lambda _b: self.refresh())

            add_button = Gtk.Button(label="Add Share")
            add_button.set_tooltip_text("Add share")
            add_button.add_css_class("suggested-action")
            add_button.connect("clicked", lambda _b: self.show_add_dialog())

            header = Adw.HeaderBar()
            header.pack_start(add_button)
            header.pack_end(menu_button)
            header.pack_end(refresh_button)

            self.toast_overlay = Adw.ToastOverlay()

            # Content area; Tasks 6-8 replace the list/empty children inside it.
            self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.toast_overlay.set_child(self.content_box)

            self.empty_label = Gtk.Label(label="No SMB mounts found.")
            self.empty_label.add_css_class("dim-label")
            self.empty_label.set_margin_top(32)

            self.list_box = Gtk.ListBox()
            self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
            self.list_box.add_css_class("boxed-list")

            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_child(self.list_box)
            scroller.set_vexpand(True)
            scroller.set_margin_top(16)
            scroller.set_margin_bottom(16)
            scroller.set_margin_start(16)
            scroller.set_margin_end(16)

            self.content_box.append(scroller)
            self.content_box.append(self.empty_label)

            toolbar_view = Adw.ToolbarView()
            toolbar_view.add_top_bar(header)
            toolbar_view.set_content(self.toast_overlay)
            self.set_content(toolbar_view)

            self.refresh()

        def show_toast(self, message: str) -> None:
            self.toast_overlay.add_toast(Adw.Toast(title=message))
```

Leave the remaining `MainWindow` methods (`refresh`, `row_for`, `show_add_dialog`, `show_about_dialog`, `mount_created`, `open_mount_folder`, `upgrade_mount`, `toggle_mount`, `confirm_delete`) unchanged. They still operate on `self.list_box` and `self.empty_label`.

- [ ] **Step 2: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- Header bar shows "Add Share" (suggested-action, blue) on the left; refresh and menu buttons on the right.
- Window title reads "SMB Mount Manager".
- The mount list shows the same rows as before (we have not yet converted them).
- Add Share dialog still opens (uses the unmodified `AddShareWindow` for now).
- About menu still works (uses the unmodified `Gtk.AboutDialog`).
- Refreshing works.

- [ ] **Step 3: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): adopt Adw.ApplicationWindow with ToolbarView and ToastOverlay"
```

---

## Task 6: `mount_status_line()` helper

**Files:**
- Modify: `mount_manager_ui.py` (add helper at module scope)
- Create: `tests/test_mount_status_line.py`

A pure helper that builds the subtitle string used by each `AdwActionRow`. Task 7 uses it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mount_status_line.py`:

```python
"""Unit tests for the AdwActionRow subtitle builder."""

import unittest
from pathlib import Path

from mount_manager import DisplayedMount


def _mount(**overrides: object) -> DisplayedMount:
    defaults = dict(
        source="//host/share",
        mount_point=Path("/mnt/mount-manager/share"),
        status="Mounted",
        active=True,
        openable=True,
        needs_upgrade=False,
        managed=True,
        managed_record=None,
    )
    defaults.update(overrides)
    return DisplayedMount(**defaults)  # type: ignore[arg-type]


class MountStatusLineTest(unittest.TestCase):
    def test_combines_mount_point_and_status(self) -> None:
        from mount_manager_ui import mount_status_line

        line = mount_status_line(_mount(status="Mounted"))
        self.assertEqual(line, "/mnt/mount-manager/share · Mounted")

    def test_idle_status(self) -> None:
        from mount_manager_ui import mount_status_line

        line = mount_status_line(_mount(status="Idle", active=False))
        self.assertEqual(line, "/mnt/mount-manager/share · Idle")

    def test_unmanaged_uses_unmanaged_status(self) -> None:
        from mount_manager_ui import mount_status_line

        line = mount_status_line(
            _mount(
                mount_point=Path("/mnt/elsewhere"),
                status="Mounted (not managed)",
                managed=False,
            )
        )
        self.assertEqual(line, "/mnt/elsewhere · Mounted (not managed)")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `python3 -m unittest tests.test_mount_status_line -v`
Expected: `ImportError: cannot import name 'mount_status_line' from 'mount_manager_ui'`.

- [ ] **Step 3: Add the helper at module scope in `mount_manager_ui.py`**

After the `apply_style_manager` function (and **outside** `run_gui`), add:

```python
def mount_status_line(mount: DisplayedMount) -> str:
    """Build the AdwActionRow subtitle for a mount: ``<mount_point> · <status>``."""
    return f"{mount.mount_point} \u00b7 {mount.status}"
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python3 -m unittest tests.test_mount_status_line -v`
Expected: three tests pass, `OK`.

- [ ] **Step 5: Commit**

```bash
git add mount_manager_ui.py tests/test_mount_status_line.py
git commit -m "feat(ui): add mount_status_line helper"
```

---

## Task 7: Replace `row_for()` with `AdwPreferencesGroup` + `AdwActionRow`

**Files:**
- Modify: `mount_manager_ui.py` (`MainWindow` class)

Replace the `boxed-list` `Gtk.ListBox` set up in Task 5 with an `Adw.PreferencesPage` containing one `Adw.PreferencesGroup`. Replace `row_for()` to return an `Adw.ActionRow` with the controls in the order: **switch, open-folder (or upgrade), kebab**. Unmanaged rows show a "Not managed" label and no controls.

- [ ] **Step 1: Replace the list scaffolding inside `MainWindow.__init__`**

In the body of `MainWindow.__init__` (the part added in Task 5), replace the `self.list_box`, `scroller`, and the calls that append them to `self.content_box` with:

```python
            self.preferences_page = Adw.PreferencesPage()
            self.preferences_page.set_vexpand(True)

            self.mount_group = Adw.PreferencesGroup()
            self.mount_group.set_title("SMB Shares")
            self.preferences_page.add(self.mount_group)

            self.content_box.append(self.preferences_page)
            self.content_box.append(self.empty_label)
```

The variables `self.list_box` and `scroller` no longer exist. Update `MainWindow.refresh` (next step) accordingly.

- [ ] **Step 2: Rewrite `MainWindow.refresh`**

Replace the existing `refresh` method body with:

```python
        def refresh(self) -> None:
            child = self.mount_group.get_first_child()
            # Remove any previously added rows. Adw.PreferencesGroup exposes them
            # via .remove(); iterating with get_first_child() is the safe pattern.
            rows_to_remove = []
            row = child
            while row is not None:
                rows_to_remove.append(row)
                row = row.get_next_sibling()
            for row in rows_to_remove:
                # Only ActionRow children we added belong here; leave internal
                # widgets of the group untouched by filtering on the type we add.
                if isinstance(row, Adw.ActionRow):
                    self.mount_group.remove(row)

            mounts = load_displayed_mounts()
            self.empty_label.set_visible(not mounts)
            self.preferences_page.set_visible(bool(mounts))

            for mount in mounts:
                self.mount_group.add(self.row_for(mount))
```

> **Note:** `Adw.PreferencesGroup` keeps its title/description widgets internally; the `isinstance(row, Adw.ActionRow)` filter avoids accidentally removing them. If a future Adw release exposes `remove_all()`, that becomes a one-liner.

- [ ] **Step 3: Rewrite `MainWindow.row_for`**

Replace the existing `row_for` method with:

```python
        def row_for(self, mount: DisplayedMount) -> Adw.ActionRow:
            row = Adw.ActionRow()
            row.set_title(GLib_markup_escape(mount.source))
            row.set_subtitle(GLib_markup_escape(mount_status_line(mount)))

            if not mount.managed or mount.managed_record is None:
                not_managed_label = Gtk.Label(label="Not managed")
                not_managed_label.add_css_class("dim-label")
                not_managed_label.set_valign(Gtk.Align.CENTER)
                row.add_suffix(not_managed_label)
                return row

            record = mount.managed_record

            mount_switch = Gtk.Switch()
            mount_switch.set_valign(Gtk.Align.CENTER)
            mount_switch.set_active(mount.active)
            mount_switch.set_sensitive(not mount.needs_upgrade)
            if mount.needs_upgrade:
                mount_switch.set_tooltip_text("Upgrade this older mount before enabling it")
            else:
                mount_switch.set_tooltip_text(
                    "Enable or disable on-demand access for this managed mount"
                )
                mount_switch.connect(
                    "notify::active",
                    lambda switch, _param: self.toggle_mount(record, switch),
                )
            row.add_suffix(mount_switch)

            if mount.needs_upgrade:
                upgrade_button = Gtk.Button(label="Upgrade")
                upgrade_button.set_valign(Gtk.Align.CENTER)
                upgrade_button.set_tooltip_text(
                    "Upgrade mount units using the existing encrypted credentials"
                )
                upgrade_button.add_css_class("suggested-action")
                upgrade_button.connect("clicked", lambda _b: self.upgrade_mount(record))
                row.add_suffix(upgrade_button)
            else:
                open_button = Gtk.Button.new_from_icon_name("folder-open-symbolic")
                open_button.set_valign(Gtk.Align.CENTER)
                open_button.add_css_class("flat")
                open_button.set_sensitive(mount.openable)
                open_button.set_tooltip_text(
                    "Open mount folder"
                    if mount.openable
                    else "Enable on-demand access to open its folder"
                )
                open_button.connect("clicked", lambda _b: self.open_mount_folder(record))
                row.add_suffix(open_button)

            menu = Gio.Menu()
            menu.append("Delete\u2026", f"row.delete::{record.manager_id}")

            row_action_group = Gio.SimpleActionGroup()
            delete_action = Gio.SimpleAction.new("delete", GLib_VariantType("s"))
            delete_action.connect(
                "activate", lambda _a, _p, r=record: self.confirm_delete(r)
            )
            row_action_group.add_action(delete_action)
            row.insert_action_group("row", row_action_group)

            menu_button = Gtk.MenuButton()
            menu_button.set_valign(Gtk.Align.CENTER)
            menu_button.set_icon_name("view-more-symbolic")
            menu_button.add_css_class("flat")
            menu_button.set_menu_model(menu)
            menu_button.set_tooltip_text("More actions")
            row.add_suffix(menu_button)

            return row
```

- [ ] **Step 4: Add the small GLib helpers used above**

At the **top** of `mount_manager_ui.py`, just under the existing `from gi.repository import …` line, add:

```python
from gi.repository import GLib  # noqa: E402


def GLib_markup_escape(text: str) -> str:
    """Escape Pango markup characters in row titles/subtitles."""
    return GLib.markup_escape_text(text, -1)


def GLib_VariantType(spec: str) -> GLib.VariantType:
    return GLib.VariantType.new(spec)
```

(These exist as tiny wrappers so the code reads cleanly.)

- [ ] **Step 5: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- The mount list is rendered as a single boxed group titled "SMB Shares" with one row per mount.
- Each managed row shows: source as title, "`<mount_point> · <status>`" as subtitle, then on the right edge: switch, open-folder button (or "Upgrade" button if `needs_upgrade`), then a kebab (⋯) button.
- Toggling the switch enables/disables on-demand access (verify with `systemctl status <unit>` for one of your mounts).
- Open folder still opens the mount target in the file manager.
- Kebab → Delete… still opens the existing `DeleteMountWindow` (replaced in Task 10).
- Unmanaged mounts (e.g. an SMB mount you created outside this app) show a "Not managed" label and no controls.
- Switching system color scheme still toggles light/dark instantly.

- [ ] **Step 6: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): render mounts as AdwPreferencesGroup with AdwActionRow"
```

---

## Task 8: `Adw.StatusPage` empty state

**Files:**
- Modify: `mount_manager_ui.py` (`MainWindow`)

Replace the dim "No SMB mounts found." label with an `Adw.StatusPage` that includes an action button.

- [ ] **Step 1: Replace `self.empty_label` setup**

In `MainWindow.__init__`, remove the `self.empty_label = Gtk.Label(...)`, `add_css_class("dim-label")`, and `set_margin_top(32)` lines added earlier. Replace with:

```python
            self.empty_page = Adw.StatusPage()
            self.empty_page.set_icon_name("folder-remote-symbolic")
            self.empty_page.set_title("No SMB shares")
            self.empty_page.set_description("Click <i>Add Share</i> to mount one.")
            self.empty_page.set_vexpand(True)

            empty_action = Gtk.Button(label="Add Share")
            empty_action.set_halign(Gtk.Align.CENTER)
            empty_action.add_css_class("suggested-action")
            empty_action.add_css_class("pill")
            empty_action.connect("clicked", lambda _b: self.show_add_dialog())
            self.empty_page.set_child(empty_action)
```

Update the `content_box.append(self.empty_label)` line added in Task 7 to:

```python
            self.content_box.append(self.empty_page)
```

- [ ] **Step 2: Update `refresh()`**

Replace `self.empty_label.set_visible(not mounts)` with:

```python
            self.empty_page.set_visible(not mounts)
```

- [ ] **Step 3: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- If you have any mounts, behavior is unchanged.
- If you remove all mounts (delete them through the app), the empty status page appears centered with the folder-remote icon, the heading "No SMB shares", and a pill suggested-action "Add Share" button. Clicking it opens the Add Share flow.

- [ ] **Step 4: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): replace empty label with Adw.StatusPage"
```

---

## Task 9: `AddShareDialog(Adw.Dialog)` — single page, progressive reveal

**Files:**
- Modify: `mount_manager_ui.py` (`run_gui` body and `MainWindow.show_add_dialog`)

Replace the existing `AddShareWindow(Gtk.Window)` class with `AddShareDialog(Adw.Dialog)`. The dialog uses a single `Adw.PreferencesPage` whose Credentials group is insensitive until the host check succeeds. The "Check host" button is replaced by an automatic debounced check (300 ms after the user stops typing). On success the dialog closes and the main window shows a toast. On failure inside the create flow, an `Adw.Banner` is shown in the dialog and the dialog stays open.

- [ ] **Step 1: Replace the `AddShareWindow` definition**

Inside `run_gui`, **delete** the entire `class AddShareWindow(Gtk.Window):` block. In its place add:

```python
    class AddShareDialog(Adw.Dialog):
        def __init__(self, main_window: "MainWindow") -> None:
            super().__init__()
            self.set_title("Add SMB Share")
            self.set_content_width(420)
            self.main_window = main_window
            self.share_path: SharePath | None = None
            self._debounce_id: int = 0

            self.cancel_button = Gtk.Button(label="Cancel")
            self.cancel_button.connect("clicked", lambda _b: self.close())

            self.add_button = Gtk.Button(label="Add")
            self.add_button.add_css_class("suggested-action")
            self.add_button.set_sensitive(False)
            self.add_button.connect("clicked", lambda _b: self._on_add_clicked())

            header = Adw.HeaderBar()
            header.set_show_start_title_buttons(False)
            header.set_show_end_title_buttons(False)
            header.pack_start(self.cancel_button)
            header.pack_end(self.add_button)

            self.banner = Adw.Banner()
            self.banner.set_revealed(False)

            page = Adw.PreferencesPage()

            share_group = Adw.PreferencesGroup()
            share_group.set_title("Share")
            page.add(share_group)

            self.path_row = Adw.EntryRow()
            self.path_row.set_title("Share path")
            self.path_row.set_tooltip_text(
                "Example: //192.168.1.2/sharename or //hostname/sharename"
            )
            self.path_row.connect("changed", lambda _r: self._on_path_changed())
            share_group.add(self.path_row)

            self.host_spinner = Gtk.Spinner()
            self.host_spinner.set_valign(Gtk.Align.CENTER)
            self.host_spinner.set_visible(False)
            self.path_row.add_suffix(self.host_spinner)

            self.host_status_icon = Gtk.Image()
            self.host_status_icon.set_valign(Gtk.Align.CENTER)
            self.host_status_icon.set_visible(False)
            self.path_row.add_suffix(self.host_status_icon)

            self.credentials_group = Adw.PreferencesGroup()
            self.credentials_group.set_title("Credentials")
            self.credentials_group.set_sensitive(False)
            page.add(self.credentials_group)

            self.user_row = Adw.EntryRow()
            self.user_row.set_title("Username")
            self.user_row.connect("changed", lambda _r: self._update_add_sensitive())
            self.credentials_group.add(self.user_row)

            self.password_row = Adw.PasswordEntryRow()
            self.password_row.set_title("Password")
            self.password_row.connect("changed", lambda _r: self._update_add_sensitive())
            self.credentials_group.add(self.password_row)

            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            body.append(self.banner)
            body.append(page)

            toolbar = Adw.ToolbarView()
            toolbar.add_top_bar(header)
            toolbar.set_content(body)
            self.set_child(toolbar)

        def _show_banner(self, message: str) -> None:
            self.banner.set_title(message)
            self.banner.set_revealed(True)

        def _hide_banner(self) -> None:
            self.banner.set_revealed(False)

        def _set_host_status(self, *, ok: bool | None, message: str) -> None:
            self.host_spinner.set_visible(False)
            self.host_spinner.stop()
            if ok is None:
                self.host_status_icon.set_visible(False)
                self.path_row.set_title("Share path")
                return
            if ok:
                self.host_status_icon.set_from_icon_name("emblem-ok-symbolic")
            else:
                self.host_status_icon.set_from_icon_name("dialog-error-symbolic")
            self.host_status_icon.set_visible(True)
            self.host_status_icon.set_tooltip_text(message)

        def _on_path_changed(self) -> None:
            self.share_path = None
            self.credentials_group.set_sensitive(False)
            self._update_add_sensitive()
            self._hide_banner()
            self._set_host_status(ok=None, message="")
            if self._debounce_id:
                GLib.source_remove(self._debounce_id)
                self._debounce_id = 0
            text = self.path_row.get_text().strip()
            if not text:
                return
            self._debounce_id = GLib.timeout_add(300, self._run_host_check)

        def _run_host_check(self) -> bool:
            self._debounce_id = 0
            self.host_spinner.set_visible(True)
            self.host_spinner.start()
            try:
                share_path = check_smb_host_reachable(self.path_row.get_text())
            except MountManagerError as exc:
                self._set_host_status(ok=False, message=str(exc))
                return False
            except Exception as exc:
                self._set_host_status(ok=False, message=f"Unexpected error: {exc}")
                return False

            self.share_path = share_path
            self._set_host_status(ok=True, message="Host is reachable")
            self.credentials_group.set_sensitive(True)
            self._update_add_sensitive()
            return False  # don't repeat the timeout

        def _update_add_sensitive(self) -> None:
            ready = (
                self.share_path is not None
                and bool(self.user_row.get_text().strip())
                and bool(self.password_row.get_text())
            )
            self.add_button.set_sensitive(ready)

        def _on_add_clicked(self) -> None:
            if self.share_path is None:
                return
            share = self.share_path.source
            username = self.user_row.get_text()
            password = self.password_row.get_text()
            try:
                validate_credentials(username, password)
                request_helper_create(share, username, password)
            except MountManagerError as exc:
                self._show_banner(str(exc))
                return
            except Exception as exc:
                self._show_banner(f"Unexpected error: {exc}")
                return

            self.close()
            self.main_window.refresh()
            self.main_window.show_toast(f"{share} will mount when accessed.")
```

- [ ] **Step 2: Replace `MainWindow.show_add_dialog` and remove `MainWindow.mount_created`**

In `MainWindow`, replace:

```python
        def show_add_dialog(self) -> None:
            AddShareWindow(self, self.mount_created).present()
```

with:

```python
        def show_add_dialog(self) -> None:
            AddShareDialog(self).present(self)
```

Delete the entire `mount_created` method — its work is now done inline by `AddShareDialog._on_add_clicked`.

- [ ] **Step 3: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- Clicking "Add Share" presents an adaptive Adw dialog (desktop-style centered dialog on a desktop).
- Typing in the share path triggers an automatic host check after ~300 ms: spinner appears at the end of the row, then a green check or red error icon. The error icon's tooltip explains the failure.
- The Credentials group stays insensitive until the check passes.
- Once credentials are filled, "Add" becomes active.
- On success the dialog closes and the main window shows a toast at the bottom: "//host/share will mount when accessed."
- On failure (e.g. wrong password) a banner appears at the top of the dialog with the error; dialog stays open; you can correct and retry.
- Cancel closes the dialog with no side effects.

- [ ] **Step 4: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): replace AddShareWindow with AdwDialog and progressive reveal"
```

---

## Task 10: `Adw.AlertDialog` for delete confirmation

**Files:**
- Modify: `mount_manager_ui.py`

Replace `DeleteMountWindow(Gtk.Window)` with an `Adw.AlertDialog`-based factory. Errors close the alert and surface as a toast in the main window.

- [ ] **Step 1: Delete the existing `DeleteMountWindow` class**

Inside `run_gui`, delete the entire `class DeleteMountWindow(Gtk.Window):` block.

- [ ] **Step 2: Replace `MainWindow.confirm_delete`**

In `MainWindow`, replace the existing `confirm_delete` method with:

```python
        def confirm_delete(self, record: ManagedMount) -> None:
            alert = Adw.AlertDialog(
                heading="Delete this SMB mount?",
                body=(
                    f"Removes {record.source} and its systemd units. "
                    "The encrypted credentials will also be deleted."
                ),
            )
            alert.add_response("cancel", "Cancel")
            alert.add_response("delete", "Delete")
            alert.set_response_appearance(
                "delete", Adw.ResponseAppearance.DESTRUCTIVE
            )
            alert.set_default_response("cancel")
            alert.set_close_response("cancel")
            alert.connect("response", self._on_delete_response, record)
            alert.present(self)

        def _on_delete_response(
            self, _alert: Adw.AlertDialog, response: str, record: ManagedMount
        ) -> None:
            if response != "delete":
                return
            try:
                request_helper_delete(record)
            except MountManagerError as exc:
                self.show_toast(f"Delete failed: {exc}")
                return
            except Exception as exc:
                self.show_toast(f"Delete failed: {exc}")
                return
            self.refresh()
            self.show_toast(f"{record.source} removed.")
```

- [ ] **Step 3: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- Kebab → Delete… on a managed row opens an Adw alert dialog with two buttons: "Cancel" (default) and "Delete" (destructive red appearance).
- Pressing Esc dismisses (cancel response).
- Cancel does nothing.
- Delete removes the mount, the list refreshes, and a toast appears: "//host/share removed."
- Simulate a failure (e.g. temporarily revoke polkit auth or rename `/usr/bin/pkexec`): the alert closes and a toast shows "Delete failed: …".

- [ ] **Step 4: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): replace DeleteMountWindow with Adw.AlertDialog"
```

---

## Task 11: Replace `MessageWindow` with toasts + remove the class

**Files:**
- Modify: `mount_manager_ui.py`

`MessageWindow` is no longer used by Add Share or Delete after Tasks 9 and 10. The remaining call sites are in `open_mount_folder`, `upgrade_mount`, and `toggle_mount`. Convert each to a toast. Delete the `MessageWindow` class.

- [ ] **Step 1: Update `MainWindow.open_mount_folder`**

Replace its body with:

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

- [ ] **Step 2: Update `MainWindow.upgrade_mount`**

Replace its body with:

```python
        def upgrade_mount(self, record: ManagedMount) -> None:
            try:
                request_helper_upgrade(record)
            except MountManagerError as exc:
                self.show_toast(f"Upgrade failed: {exc}")
                return
            except Exception as exc:
                self.show_toast(f"Upgrade failed: {exc}")
                return
            self.refresh()
            self.show_toast(f"{record.source} upgraded; will mount when accessed.")
```

- [ ] **Step 3: Update `MainWindow.toggle_mount`**

Replace its body with:

```python
        def toggle_mount(self, record: ManagedMount, switch: Gtk.Switch) -> None:
            enabled = switch.get_active()
            switch.set_sensitive(False)
            try:
                request_helper_set_enabled(record, enabled)
            except MountManagerError as exc:
                self.show_toast(f"Toggle failed: {exc}")
            except Exception as exc:
                self.show_toast(f"Toggle failed: {exc}")
            finally:
                self.refresh()
```

- [ ] **Step 4: Delete the `MessageWindow` class**

Inside `run_gui`, delete the entire `class MessageWindow(Gtk.Window):` block.

- [ ] **Step 5: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- Successful upgrade → toast "//host/share upgraded; will mount when accessed."
- Toggling a switch off then on works without modal interruption; failures surface as toasts.
- Open folder failure (try renaming the mount target) shows a toast, not a window.
- No remaining references to `MessageWindow` (verify with `grep MessageWindow mount_manager_ui.py` — should return nothing).

- [ ] **Step 6: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): replace MessageWindow with AdwToast notifications"
```

---

## Task 12: `Adw.AboutDialog`

**Files:**
- Modify: `mount_manager_ui.py` (`MainWindow.show_about_dialog`)

- [ ] **Step 1: Replace `show_about_dialog`**

Replace the existing `show_about_dialog` method on `MainWindow` with:

```python
        def show_about_dialog(self) -> None:
            about = Adw.AboutDialog(
                application_name=APP_NAME,
                application_icon=APP_ICON_NAME,
                developer_name=APP_DEVELOPERS[0] if APP_DEVELOPERS else "",
                website=APP_WEBSITE,
                issue_url=f"{APP_WEBSITE}/issues",
                license_type=Gtk.License.GPL_3_0_ONLY,
                comments="Create and manage on-demand SMB mounts.",
            )
            about.set_developers(APP_DEVELOPERS)
            about.present(self)
```

- [ ] **Step 2: Manual verification**

Run: `python3 mount_manager.py`
Expected:
- Menu → "About SMB Mount Manager" presents the modern Adw about dialog with the app icon, name, version-less header (Adw shows the application_name), developer credit, website link, and license tab.
- No deprecation warning in stderr about `Gtk.AboutDialog`.

- [ ] **Step 3: Run unit tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add mount_manager_ui.py
git commit -m "feat(ui): use Adw.AboutDialog"
```

---

## Task 13: Packaging and README updates

**Files:**
- Modify: `packaging/build-appimage.sh`
- Modify: `README.md`

- [ ] **Step 1: Update `packaging/build-appimage.sh`**

The AppImage installs `mount_manager.py` to `$appdir/usr/bin/mount-manager` (the executable script). When Python runs that script, `sys.path[0]` is `/usr/bin` (the script's directory), so placing `mount_manager_ui.py` in the same directory makes `import mount_manager_ui` resolve correctly without a shim.

In `packaging/build-appimage.sh`, immediately after the line:

```bash
install -D -m 0755 "$repo_root/mount_manager.py" "$appdir/usr/bin/mount-manager"
```

(currently line 90), add:

```bash
install -D -m 0644 "$repo_root/mount_manager_ui.py" "$appdir/usr/bin/mount_manager_ui.py"
```

No other build-script changes are needed. The patch in `packaging/appimage-helper.patch` only touches `mount-manager` (the renamed `mount_manager.py`) and is unaffected by the new file, because the privileged helper subprocess does not import the UI module.

- [ ] **Step 2: Update `README.md` requirements section**

In `README.md`, find the "Requirements" section. After the line about systemd 258, add:

```markdown
libadwaita 1.5 or newer. The app refuses to start on older versions.
```

- [ ] **Step 3: Update `README.md` install commands**

In the "Test as an installed app on Bazzite" section, find the block of `sudo install -D …` commands. Immediately after the existing line for `mount_manager.py`, add:

```bash
sudo install -D -m 0644 mount_manager_ui.py /usr/bin/mount_manager_ui.py
```

This places the UI module next to the executable so `python3 /usr/bin/mount-manager` can import it (Python adds the script's directory to `sys.path` automatically).

- [ ] **Step 4: Manual verification**

Run the README's documented install commands on a Bazzite test host (or VM). Verify `mount-manager` launches with the new Adw UI from the installed path. Confirm `which mount-manager` still resolves and `mount-manager --helper create < input` still works as a privileged subprocess (the helper code path is unchanged but the import path must resolve when re-execed under pkexec).

- [ ] **Step 5: Commit**

```bash
git add packaging/build-appimage.sh README.md
git commit -m "build: include mount_manager_ui in packaging and document libadwaita requirement"
```

---

## Final verification

- [ ] **Run the full test suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests pass.

- [ ] **End-to-end smoke on Bazzite**

Run `python3 mount_manager.py` from a desktop session and exercise every flow:
1. Empty state appears when there are no mounts; clicking "Add Share" from the empty state opens the dialog.
2. Add a real share end-to-end → toast on success → row appears.
3. Toggle the switch → systemctl reports the automount unit enabled/disabled accordingly.
4. Open folder works.
5. Delete confirmation works and surfaces toast on success.
6. Failure paths surface toasts/banners as documented.
7. Color scheme follows system preference.
8. About dialog shows Adw layout.

- [ ] **Grep for orphaned references**

Run: `grep -nE 'MessageWindow|AddShareWindow|DeleteMountWindow|APP_CSS|apply_theme' mount_manager.py mount_manager_ui.py`
Expected: no matches in either file.

Run: `grep -nE 'Gtk\.AboutDialog' mount_manager.py mount_manager_ui.py`
Expected: no matches.
