"""GTK 4 GUI for SMB Mount Manager.

This module is imported lazily from ``mount_manager.run_gui``. Keeping it
separate from ``mount_manager.py`` lets the helper subprocess avoid importing
GTK when invoked with ``--helper``.
"""

from __future__ import annotations

import sys
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402


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

    class AddShareWindow(Gtk.Window):
        def __init__(self, parent: Gtk.Window, on_complete: Any) -> None:
            super().__init__(title="Add SMB Share")
            self.set_transient_for(parent)
            self.set_modal(True)
            self.set_default_size(560, -1)
            self.set_resizable(False)
            self.on_complete = on_complete
            self.share_path: SharePath | None = None

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            root.set_margin_top(18)
            root.set_margin_bottom(18)
            root.set_margin_start(18)
            root.set_margin_end(18)
            self.set_child(root)

            self.path_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            root.append(self.path_box)

            path_label = Gtk.Label(label="Please add share path")
            path_label.set_xalign(0)
            self.path_box.append(path_label)

            self.path_entry = Gtk.Entry()
            self.path_entry.set_placeholder_text("//hostname/share")
            self.path_entry.set_hexpand(True)
            self.path_entry.connect("activate", lambda _entry: self.on_next_clicked())
            self.path_box.append(self.path_entry)

            path_help = Gtk.Label(label="Example: //192.168.1.2/sharename or //hostname/sharename")
            path_help.set_xalign(0)
            path_help.add_css_class("dim-label")
            self.path_box.append(path_help)

            self.credentials_box = Gtk.Grid(column_spacing=12, row_spacing=10)
            self.credentials_box.set_visible(False)
            root.append(self.credentials_box)

            host_status_label = Gtk.Label(label="")
            host_status_label.set_xalign(0)
            host_status_label.add_css_class("success")
            self.credentials_box.attach(host_status_label, 0, 0, 2, 1)
            self.host_status_label = host_status_label

            user_label = Gtk.Label(label="Username")
            user_label.set_xalign(0)
            self.credentials_box.attach(user_label, 0, 1, 1, 1)

            self.user_entry = Gtk.Entry()
            self.user_entry.set_hexpand(True)
            self.user_entry.connect("activate", lambda _entry: self.password_entry.grab_focus())
            self.credentials_box.attach(self.user_entry, 1, 1, 1, 1)

            password_label = Gtk.Label(label="Password")
            password_label.set_xalign(0)
            self.credentials_box.attach(password_label, 0, 2, 1, 1)

            self.password_entry = Gtk.PasswordEntry()
            self.password_entry.set_hexpand(True)
            self.password_entry.connect("activate", lambda _entry: self.on_next_clicked())
            self.credentials_box.attach(self.password_entry, 1, 2, 1, 1)

            self.status_label = Gtk.Label()
            self.status_label.set_xalign(0)
            self.status_label.set_wrap(True)
            self.status_label.add_css_class("dim-label")
            self.status_label.set_visible(False)
            root.append(self.status_label)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            buttons.set_halign(Gtk.Align.END)
            root.append(buttons)

            cancel_button = Gtk.Button(label="Cancel")
            cancel_button.connect("clicked", lambda _button: self.close())
            buttons.append(cancel_button)

            self.back_button = Gtk.Button(label="Back")
            self.back_button.set_visible(False)
            self.back_button.connect("clicked", lambda _button: self.show_path_step())
            buttons.append(self.back_button)

            self.next_button = Gtk.Button(label="Check host")
            self.next_button.add_css_class("suggested-action")
            self.next_button.connect("clicked", lambda _button: self.on_next_clicked())
            buttons.append(self.next_button)

            self.path_entry.grab_focus()

        def set_status(self, message: str, css_class: str) -> None:
            self.status_label.remove_css_class("error")
            self.status_label.remove_css_class("success")
            self.status_label.add_css_class(css_class)
            self.status_label.set_text(message)
            self.status_label.set_visible(True)

        def show_path_step(self) -> None:
            self.share_path = None
            self.path_entry.set_sensitive(True)
            self.path_box.set_visible(True)
            self.credentials_box.set_visible(False)
            self.back_button.set_visible(False)
            self.next_button.set_label("Check host")
            self.status_label.set_visible(False)
            self.path_entry.grab_focus()

        def show_credentials_step(self, share_path: SharePath) -> None:
            self.share_path = share_path
            self.path_entry.set_sensitive(False)
            self.path_box.set_visible(True)
            self.credentials_box.set_visible(True)
            self.host_status_label.set_text("Host is reachable. Please enter credentials.")
            self.back_button.set_visible(True)
            self.next_button.set_label("Create")
            self.status_label.set_visible(False)
            self.user_entry.grab_focus()

        def on_next_clicked(self) -> None:
            if self.share_path is None:
                self.check_host()
            else:
                self.create_share()

        def check_host(self) -> None:
            try:
                share_path = check_smb_host_reachable(self.path_entry.get_text())
            except MountManagerError as exc:
                self.set_status(str(exc), "error")
                return
            except Exception as exc:
                self.set_status(f"Unexpected error: {exc}", "error")
                return

            self.show_credentials_step(share_path)

        def create_share(self) -> None:
            if self.share_path is None:
                self.set_status("Check the share path before entering credentials.", "error")
                return

            share = self.share_path.source
            username = self.user_entry.get_text()
            password = self.password_entry.get_text()

            try:
                validate_credentials(username, password)
                self.set_status("Creating encrypted on-demand mount...", "success")
                request_helper_create(share, username, password)
            except MountManagerError as exc:
                self.set_status(str(exc), "error")
                return
            except Exception as exc:
                self.set_status(f"Unexpected error: {exc}", "error")
                return

            self.close()
            self.on_complete(share)

    class MessageWindow(Gtk.Window):
        def __init__(self, parent: Gtk.Window, title: str, message: str) -> None:
            super().__init__(title=title)
            self.set_transient_for(parent)
            self.set_modal(True)
            self.set_default_size(420, -1)
            self.set_resizable(False)

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            root.set_margin_top(18)
            root.set_margin_bottom(18)
            root.set_margin_start(18)
            root.set_margin_end(18)
            self.set_child(root)

            heading = Gtk.Label(label=title)
            heading.add_css_class("title-3")
            heading.set_xalign(0)
            root.append(heading)

            label = Gtk.Label(label=message)
            label.set_wrap(True)
            label.set_xalign(0)
            root.append(label)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            buttons.set_halign(Gtk.Align.END)
            root.append(buttons)

            ok_button = Gtk.Button(label="OK")
            ok_button.add_css_class("suggested-action")
            ok_button.connect("clicked", lambda _button: self.close())
            buttons.append(ok_button)

    class DeleteMountWindow(Gtk.Window):
        def __init__(self, parent: Gtk.Window, record: ManagedMount, on_complete: Any) -> None:
            super().__init__(title="Delete SMB Mount")
            self.set_transient_for(parent)
            self.set_modal(True)
            self.set_default_size(460, -1)
            self.set_resizable(False)
            self.record = record
            self.on_complete = on_complete

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            root.set_margin_top(18)
            root.set_margin_bottom(18)
            root.set_margin_start(18)
            root.set_margin_end(18)
            self.set_child(root)

            heading = Gtk.Label(label="Delete SMB Mount")
            heading.add_css_class("title-3")
            heading.set_xalign(0)
            root.append(heading)

            label = Gtk.Label(label=f"Delete {record.source} and remove its systemd units?")
            label.set_wrap(True)
            label.set_xalign(0)
            root.append(label)

            self.error_label = Gtk.Label()
            self.error_label.set_xalign(0)
            self.error_label.set_wrap(True)
            self.error_label.add_css_class("error")
            self.error_label.set_visible(False)
            root.append(self.error_label)

            buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            buttons.set_halign(Gtk.Align.END)
            root.append(buttons)

            cancel_button = Gtk.Button(label="Cancel")
            cancel_button.connect("clicked", lambda _button: self.close())
            buttons.append(cancel_button)

            delete_button = Gtk.Button(label="Delete")
            delete_button.add_css_class("destructive-action")
            delete_button.connect("clicked", lambda _button: self.delete_share())
            buttons.append(delete_button)

        def show_error(self, message: str) -> None:
            self.error_label.set_text(message)
            self.error_label.set_visible(True)

        def delete_share(self) -> None:
            try:
                request_helper_delete(self.record)
            except MountManagerError as exc:
                self.show_error(str(exc))
                return
            except Exception as exc:
                self.show_error(f"Unexpected error: {exc}")
                return

            self.close()
            self.on_complete()

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

            self.preferences_page = Adw.PreferencesPage()
            self.preferences_page.set_vexpand(True)

            self.mount_group = Adw.PreferencesGroup()
            self.mount_group.set_title("SMB Shares")
            self.preferences_page.add(self.mount_group)

            self.content_box.append(self.preferences_page)
            self.content_box.append(self.empty_label)

            toolbar_view = Adw.ToolbarView()
            toolbar_view.add_top_bar(header)
            toolbar_view.set_content(self.toast_overlay)
            self.set_content(toolbar_view)

            self.refresh()

        def show_toast(self, message: str) -> None:
            self.toast_overlay.add_toast(Adw.Toast(title=message))

        def refresh(self) -> None:
            while True:
                row = self.mount_group.get_row(0)
                if row is None:
                    break
                self.mount_group.remove(row)

            mounts = load_displayed_mounts()
            self.empty_label.set_visible(not mounts)
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
            AddShareWindow(self, self.mount_created).present()

        def show_about_dialog(self) -> None:
            dialog = Gtk.AboutDialog()
            dialog.set_transient_for(self)
            dialog.set_modal(True)
            dialog.set_program_name(APP_NAME)
            dialog.set_logo_icon_name(APP_ICON_NAME)
            dialog.set_comments("Create and manage on-demand SMB mounts.")
            dialog.set_authors(APP_DEVELOPERS)
            dialog.add_credit_section("Developed by", APP_DEVELOPERS)
            dialog.set_website(APP_WEBSITE)
            dialog.set_website_label("Project homepage")
            dialog.set_license_type(Gtk.License.GPL_3_0_ONLY)
            dialog.present()

        def mount_created(self, share: str) -> None:
            self.refresh()
            MessageWindow(self, "SMB Mount Created", f"{share} will mount when accessed.").present()

        def open_mount_folder(self, record: ManagedMount) -> None:
            if not record.mount_point.exists():
                MessageWindow(self, "Open Folder Failed", f"Mount folder does not exist: {record.mount_point}").present()
                return

            try:
                run_command(["xdg-open", str(record.mount_point)])
            except MountManagerError as exc:
                MessageWindow(self, "Open Folder Failed", f"Could not open {record.mount_point}: {exc}").present()

        def upgrade_mount(self, record: ManagedMount) -> None:
            try:
                request_helper_upgrade(record)
            except MountManagerError as exc:
                MessageWindow(self, "Upgrade Failed", str(exc)).present()
                return
            except Exception as exc:
                MessageWindow(self, "Upgrade Failed", f"Unexpected error: {exc}").present()
                return

            self.refresh()
            MessageWindow(self, "SMB Mount Upgraded", f"{record.source} will mount when accessed.").present()

        def toggle_mount(self, record: ManagedMount, switch: Gtk.Switch) -> None:
            enabled = switch.get_active()
            switch.set_sensitive(False)
            try:
                request_helper_set_enabled(record, enabled)
            except MountManagerError as exc:
                MessageWindow(self, "Mount Toggle Failed", str(exc)).present()
            except Exception as exc:
                MessageWindow(self, "Mount Toggle Failed", f"Unexpected error: {exc}").present()
            finally:
                self.refresh()

        def confirm_delete(self, record: ManagedMount) -> None:
            DeleteMountWindow(self, record, self.refresh).present()

    class MountManagerApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        def do_activate(self) -> None:
            window = self.props.active_window
            if window is None:
                window = MainWindow(self)
            window.present()

    app = MountManagerApplication()
    return app.run(sys.argv)
