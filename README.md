# SMB Mount Manager

> This app is made specifically for Bazzite.

Small GTK app for managing SMB mounts.

The app checks the host, asks for credentials, tests the mount, then creates
matching systemd mount and automount units. Only the automount unit is enabled,
so shares are mounted when accessed instead of during boot. Managed shares live
under:

```text
/mnt/mount-manager
```

Credentials and app metadata are stored under:

```text
/etc/mount-manager
```

## Requirements

systemd 258 or newer with `systemd-creds` available. The app refuses to start
on older systems.

Credentials are always stored encrypted via `systemd-creds` and decrypted by
systemd at unit start, exposed to `mount.cifs` through `LoadCredentialEncrypted=`.
The plaintext password never touches disk, and the encrypted blob is bound to
the host so it cannot be decrypted on a different machine.

Encrypted credential files live in `/etc/mount-manager/credentials/` as
`<id>.cred.enc`.

## RPM

The RPM package is available through Terra.

Enable Terra first:

```bash
sudo sed -i 's/^enabled=0/enabled=1/' /etc/yum.repos.d/terra.repo
```

Install it on Bazzite with:

```bash
rpm-ostree install mount-manager
```

Reboot after installation to boot into the new deployment.

## AppImage

Release AppImages are Bazzite-focused. They are intended for Bazzite and similar
Fedora-based systems that already provide the desktop and system integration this
app needs, including GTK4/PyGObject, polkit with `pkexec`, `mount.cifs`, and
systemd 258 or newer with `systemd-creds`.

The AppImage is not intended to be a fully self-contained cross-distro package.
It packages the app entrypoint and desktop assets while relying on the host for
the system tools required to create and manage SMB mounts.

## Test as an installed app on Bazzite

From the repository root, enable a transient `/usr` overlay:

```bash
sudo rpm-ostree usroverlay
```

Install the app files into the overlay:

```bash
sudo install -D -m 0755 mount_manager.py /usr/bin/mount-manager
sudo install -D -m 0644 data/applications/io.github.xarishark.mount-manager.desktop /usr/share/applications/io.github.xarishark.mount-manager.desktop
sudo install -D -m 0644 data/icons/hicolor/scalable/apps/io.github.xarishark.mount-manager.svg /usr/share/icons/hicolor/scalable/apps/io.github.xarishark.mount-manager.svg
sudo install -D -m 0644 data/metainfo/io.github.xarishark.mount-manager.metainfo.xml /usr/share/metainfo/io.github.xarishark.mount-manager.metainfo.xml
```

Refresh desktop and icon caches:

```bash
sudo update-desktop-database /usr/share/applications
sudo gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor
```

Run the installed desktop entry:

```bash
mount-manager
```

As the overlay is temporary its cleaned up just by rebooting.
