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