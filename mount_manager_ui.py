"""GTK 4 GUI for SMB Mount Manager.

This module is imported lazily from ``mount_manager.run_gui``. Keeping it
separate from ``mount_manager.py`` lets the helper subprocess avoid importing
GTK when invoked with ``--helper``.
"""

from __future__ import annotations

import sys
import threading
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402


def GLib_markup_escape(text: str) -> str:
    """Escape Pango markup characters in row titles/subtitles."""
    return GLib.markup_escape_text(text, -1)


def GLib_VariantType(spec: str) -> GLib.VariantType:
    return GLib.VariantType.new(spec)

from mount_manager import (
    APP_DEVELOPERS,
    APP_ICON_NAME,
    APP_ID,
    APP_NAME,
    APP_WEBSITE,
    MIN_LIBADWAITA_VERSION,
    DisplayedMount,
    ManagedMount,
    MountManagerError,
    SharePath,
    _libadwaita_supports,
    check_smb_host_reachable,
    load_displayed_mounts,
    request_helper_create,
    request_helper_delete,
    request_helper_set_enabled,
    request_helper_upgrade,
    run_command,
    validate_credentials,
)


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


def mount_status_line(mount: DisplayedMount) -> str:
    """Build the AdwActionRow subtitle for a mount: ``<mount_point> · <status>``."""
    return f"{mount.mount_point} · {mount.status}"


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

    def build_shortcuts_dialog() -> Adw.ShortcutsDialog:
        """Construct the keyboard shortcuts dialog for the app."""
        dialog = Adw.ShortcutsDialog()

        general = Adw.ShortcutsSection(title="General")
        general.add(Adw.ShortcutsItem(title="Add Share", action_name="win.add-share"))
        general.add(Adw.ShortcutsItem(title="Refresh", action_name="win.refresh"))
        general.add(Adw.ShortcutsItem(title="Primary Menu", action_name="win.show-menu"))
        general.add(
            Adw.ShortcutsItem(
                title="Keyboard Shortcuts", action_name="app.shortcuts"
            )
        )
        general.add(Adw.ShortcutsItem(title="Close Window", action_name="win.close"))
        general.add(Adw.ShortcutsItem(title="Quit", action_name="app.quit"))

        dialog.add(general)
        return dialog

    class AddShareDialog(Adw.Dialog):
        def __init__(self, main_window: "MainWindow") -> None:
            super().__init__()
            self.set_title("Add SMB Share")
            self.set_content_width(420)
            self.main_window = main_window
            self.share_path: SharePath | None = None
            self._debounce_id: int = 0
            self._cancellable: Gio.Cancellable | None = None

            self.cancel_button = Gtk.Button(label="Cancel")
            self.cancel_button.connect("clicked", lambda _b: self.close())

            self.add_button = Gtk.Button(label="Add")
            self.add_button.add_css_class("suggested-action")
            self.add_button.set_sensitive(False)
            self.add_button.connect("clicked", lambda _b: self._on_add_clicked())

            header = Adw.HeaderBar()
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

            self.host_spinner = Adw.Spinner()
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
            self.set_default_widget(self.add_button)
            
            self.connect("closed", self._cleanup)
            self.connect("map", lambda _d: self.path_row.grab_focus())

        def _cleanup(self, *_args) -> None:
            if self._cancellable is not None:
                self._cancellable.cancel()
                self._cancellable = None
            if self._debounce_id:
                GLib.source_remove(self._debounce_id)
                self._debounce_id = 0

        def _show_banner(self, message: str) -> None:
            self.banner.set_title(message)
            self.banner.set_revealed(True)

        def _hide_banner(self) -> None:
            self.banner.set_revealed(False)

        def _set_host_status(self, *, ok: bool | None, message: str) -> None:
            self.host_spinner.set_visible(False)
            if ok is None:
                self.host_status_icon.set_visible(False)
                self.path_row.set_title("Share path")
                return
            if ok:
                self.host_status_icon.set_from_icon_name("checkmark-symbolic")
            else:
                self.host_status_icon.set_from_icon_name("error-symbolic")
            self.host_status_icon.set_visible(True)
            self.host_status_icon.set_tooltip_text(message)

        def _on_path_changed(self) -> None:
            self.share_path = None
            self.credentials_group.set_sensitive(False)
            self._update_add_sensitive()
            self._hide_banner()
            self._set_host_status(ok=None, message="")
            if self._cancellable is not None:
                self._cancellable.cancel()
                self._cancellable = None
            if self._debounce_id:
                GLib.source_remove(self._debounce_id)
                self._debounce_id = 0
            text = self.path_row.get_text().strip()
            if not text:
                return
            self._debounce_id = GLib.timeout_add(300, self._run_host_check)

        def _run_host_check(self) -> bool:
            self._debounce_id = 0
            text = self.path_row.get_text()
            cancellable = Gio.Cancellable()
            self._cancellable = cancellable
            self.host_spinner.set_visible(True)
            thread = threading.Thread(
                target=self._host_check_worker,
                args=(cancellable, text),
                daemon=True,
            )
            thread.start()
            return False  # don't repeat the timeout

        def _host_check_worker(
            self, cancellable: Gio.Cancellable, text: str
        ) -> None:
            try:
                share_path = check_smb_host_reachable(text)
            except MountManagerError as exc:
                result: tuple[SharePath | None, BaseException | None] = (None, exc)
            except Exception as exc:
                result = (None, exc)
            else:
                result = (share_path, None)
            if cancellable.is_cancelled():
                return
            GLib.idle_add(self._on_host_check_done, cancellable, result[0], result[1])

        def _on_host_check_done(
            self,
            cancellable: Gio.Cancellable,
            share_path: SharePath | None,
            exc: BaseException | None,
        ) -> bool:
            if cancellable.is_cancelled() or cancellable is not self._cancellable:
                return False  # stale or cancelled; ignore
            self._cancellable = None
            if exc is not None:
                if isinstance(exc, MountManagerError):
                    self._set_host_status(ok=False, message=str(exc))
                else:
                    self._set_host_status(ok=False, message=f"Unexpected error: {exc}")
                return False
            self.share_path = share_path
            self._set_host_status(ok=True, message="Host is reachable")
            self.credentials_group.set_sensitive(True)
            self._update_add_sensitive()
            return False

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
            self.main_window.show_toast(f"{share} added")

    class MainWindow(Adw.ApplicationWindow):
        def __init__(self, app: Adw.Application) -> None:
            super().__init__(application=app, title=APP_NAME)
            self.set_default_size(760, 480)
            self.set_icon_name(APP_ICON_NAME)

            about_action = Gio.SimpleAction.new("about", None)
            about_action.connect("activate", lambda _a, _p: self.show_about_dialog())
            self.add_action(about_action)

            close_action = Gio.SimpleAction.new("close", None)
            close_action.connect("activate", lambda _a, _p: self.close())
            self.add_action(close_action)
            app.set_accels_for_action("win.close", ["<Primary>w"])

            add_share_action = Gio.SimpleAction.new("add-share", None)
            add_share_action.connect("activate", lambda _a, _p: self.show_add_dialog())
            self.add_action(add_share_action)
            app.set_accels_for_action("win.add-share", ["<Primary>n"])

            refresh_action = Gio.SimpleAction.new("refresh", None)
            refresh_action.connect("activate", lambda _a, _p: self.refresh())
            self.add_action(refresh_action)
            app.set_accels_for_action("win.refresh", ["<Primary>r"])

            show_menu_action = Gio.SimpleAction.new("show-menu", None)
            show_menu_action.connect("activate", lambda _a, _p: self._open_primary_menu())
            self.add_action(show_menu_action)
            app.set_accels_for_action("win.show-menu", ["F10"])

            menu = Gio.Menu()
            menu.append("Keyboard Shortcuts", "app.shortcuts")
            menu.append(f"About {APP_NAME}", "win.about")

            self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
            self.menu_button.set_menu_model(menu)
            self.menu_button.set_tooltip_text("Primary menu")

            refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
            refresh_button.set_tooltip_text("Refresh")
            refresh_button.set_action_name("win.refresh")

            add_button_content = Adw.ButtonContent(
                icon_name="list-add-symbolic",
                label="Add Share",
            )
            add_button = Gtk.Button()
            add_button.set_child(add_button_content)
            add_button.set_tooltip_text("Mount a new SMB share")
            add_button.set_action_name("win.add-share")

            header = Adw.HeaderBar()
            header.pack_start(add_button)
            header.pack_end(self.menu_button)
            header.pack_end(refresh_button)

            self.toast_overlay = Adw.ToastOverlay()

            # Content area; Tasks 6-8 replace the list/empty children inside it.
            self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.toast_overlay.set_child(self.content_box)

            self.empty_page = Adw.StatusPage()
            self.empty_page.set_icon_name("network-server-symbolic")
            self.empty_page.set_title("No SMB shares")
            self.empty_page.set_description('Click "Add Share" to mount one')
            self.empty_page.set_vexpand(True)

            empty_action = Gtk.Button(label="Add Share")
            empty_action.set_halign(Gtk.Align.CENTER)
            empty_action.add_css_class("suggested-action")
            empty_action.add_css_class("pill")
            empty_action.set_action_name("win.add-share")
            self.empty_page.set_child(empty_action)

            self.preferences_page = Adw.PreferencesPage()
            self.preferences_page.set_vexpand(True)

            self.mount_group = Adw.PreferencesGroup()
            self.preferences_page.add(self.mount_group)

            self.content_box.append(self.preferences_page)
            self.content_box.append(self.empty_page)

            toolbar_view = Adw.ToolbarView()
            toolbar_view.add_top_bar(header)
            toolbar_view.set_content(self.toast_overlay)
            self.set_content(toolbar_view)

            self.refresh()

        def _open_primary_menu(self) -> None:
            self.menu_button.popup()

        def show_toast(self, message: str) -> None:
            self.toast_overlay.add_toast(Adw.Toast(title=message))

        def refresh(self) -> None:
            while True:
                row = self.mount_group.get_row(0)
                if row is None:
                    break
                self.mount_group.remove(row)

            mounts = load_displayed_mounts()
            self.empty_page.set_visible(not mounts)
            self.preferences_page.set_visible(bool(mounts))

            for mount in mounts:
                self.mount_group.add(self.row_for(mount))

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

        def show_add_dialog(self) -> None:
            AddShareDialog(self).present(self)

        def show_about_dialog(self) -> None:
            about = Adw.AboutDialog(
                application_name=APP_NAME,
                application_icon=APP_ICON_NAME,
                website=APP_WEBSITE,
                issue_url=f"{APP_WEBSITE}/issues",
                license_type=Gtk.License.GPL_3_0_ONLY,
                comments="Create and manage on-demand SMB mounts.",
            )
            about.set_developers(APP_DEVELOPERS)
            about.present(self)

        def open_mount_folder(self, record: ManagedMount) -> None:
            if not record.mount_point.exists():
                self.show_toast(f"Mount folder does not exist: {record.mount_point}")
                return
            try:
                run_command(["xdg-open", str(record.mount_point)])
            except MountManagerError as exc:
                self.show_toast(f"Could not open {record.mount_point}: {exc}")

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
            self.show_toast(f"{record.source} upgraded")

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

        def confirm_delete(self, record: ManagedMount) -> None:
            alert = Adw.AlertDialog(
                heading="Delete this SMB mount?",
                body=(
                    f"Removes {record.source} and its systemd units. "
                    "The encrypted credentials will also be deleted."
                ),
            )
            alert.add_response("cancel", "Cancel")
            alert.add_response("delete", "Delete Share")
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
            self.show_toast(f"{record.source} removed")

    class MountManagerApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

            quit_action = Gio.SimpleAction.new("quit", None)
            quit_action.connect("activate", lambda _a, _p: self.quit())
            self.add_action(quit_action)
            self.set_accels_for_action("app.quit", ["<Primary>q"])

            shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
            shortcuts_action.connect("activate", lambda _a, _p: self._show_shortcuts())
            self.add_action(shortcuts_action)
            self.set_accels_for_action("app.shortcuts", ["<Primary>question"])

        def _show_shortcuts(self) -> None:
            window = self.props.active_window
            if window is None:
                return
            dialog = build_shortcuts_dialog()
            dialog.present(window)

        def do_activate(self) -> None:
            window = self.props.active_window
            if window is None:
                window = MainWindow(self)
            window.present()

    app = MountManagerApplication()
    return app.run(sys.argv)
