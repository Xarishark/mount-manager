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

libadwaita 1.8 or newer. The app refuses to start on older versions.

Credentials are always stored encrypted via `systemd-creds` and decrypted by
systemd at unit start, exposed to `mount.cifs` through `LoadCredentialEncrypted=`.
The plaintext password never touches disk, and the encrypted blob is bound to
the host so it cannot be decrypted on a different machine.

Encrypted credential files live in `/etc/mount-manager/credentials/` as
`<id>.cred.enc`.

## AppImage

Download the latest `SMB-Mount-Manager-<version>-x86_64.AppImage` from [Releases](https://github.com/Xarishark/mount-manager/releases).

You can run the AppImage directly, or integrate it with your application menu using [Gear Lever](https://flathub.org/apps/it.mijorus.gearlever). Gear Lever will automatically detect and offer updates when a new release is published.

### Notes on AppImage Support

Release AppImages are Bazzite-focused. They are intended for Bazzite and similar
Fedora-based systems that already provide the desktop and system integration this
app needs, including GTK4/PyGObject, polkit with `pkexec`, `mount.cifs`, and
systemd 258 or newer with `systemd-creds`.

The AppImage is not intended to be a fully self-contained cross-distro package.
It packages the app entrypoint and desktop assets while relying on the host for
the system tools required to create and manage SMB mounts.
