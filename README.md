# SMB Mount Manager

Small GTK app for creating SMB mounts that come back on startup.

The app checks the host, asks for credentials, tests the mount, then creates a
systemd mount unit. Managed shares are mounted under:

```text
/mnt/mount-manager
```

Credentials and app metadata are stored under:

```text
/etc/mount-manager
```

## Encrypted credentials

When creating a share, you can optionally encrypt the credentials with
`systemd-creds`. The plaintext password never touches disk; the encrypted blob
is decrypted by systemd at unit start and exposed to `mount.cifs` via
`LoadCredentialEncrypted=`. The blob is bound to the host, so it cannot be
decrypted on a different machine.

Requires systemd 258 or newer. The option is disabled in the dialog when
unavailable.

Encrypted credentials live alongside plaintext ones in
`/etc/mount-manager/credentials/`, distinguished by suffix:

- `<id>.cred` — plaintext
- `<id>.cred.enc` — `systemd-creds` encrypted blob

## Test as an installed app on Bazzite

From the repository root, enable a transient `/usr` overlay:

```bash
sudo rpm-ostree usroverlay
```

Install the app files into the overlay:

```bash
sudo install -D -m 0755 mount_manager.py /usr/bin/mount-manager
sudo install -D -m 0644 data/applications/io.github.ublue_os.mount-manager.desktop /usr/share/applications/io.github.ublue_os.mount-manager.desktop
sudo install -D -m 0644 data/icons/hicolor/scalable/apps/io.github.ublue_os.mount-manager.svg /usr/share/icons/hicolor/scalable/apps/io.github.ublue_os.mount-manager.svg
sudo install -D -m 0644 data/metainfo/io.github.ublue_os.mount-manager.metainfo.xml /usr/share/metainfo/io.github.ublue_os.mount-manager.metainfo.xml
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
