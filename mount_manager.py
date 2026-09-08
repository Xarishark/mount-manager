#!/usr/bin/env python3
"""GTK4 SMB mount manager.

Run directly with:

    python3 mount_manager.py

The GUI runs as the desktop user. Create/delete actions call a hidden helper
mode through pkexec so only the system-changing work runs as root.
"""

import argparse
import dataclasses
import hashlib
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


APP_NAME = "SMB Mount Manager"
APP_ID = "io.github.xarishark.mount-manager"
APP_CREATOR = "Zacharias Xenakis (Xarishark)"
APP_DEVELOPERS = [APP_CREATOR]
APP_WEBSITE = "https://github.com/Xarishark/mount-manager"
APP_ICON_NAME = APP_ID

MANAGED_ROOT = Path("/etc/mount-manager")
CREDENTIALS_DIR = MANAGED_ROOT / "credentials"
METADATA_DIR = MANAGED_ROOT / "mounts"
MOUNT_ROOT = Path("/mnt/mount-manager").resolve(strict=False)
SYSTEMD_DIR = Path("/etc/systemd/system")
SMB_PORT = 445
CONNECT_TIMEOUT_SECONDS = 4.0
MOUNT_TIMEOUT_SECONDS = 5

# Used with systemd credentials, the filename and --name argument must match or decryption fails
CREDENTIAL_NAME = "smbcreds"

# Mount-unit credentials (LoadCredentialEncrypted=) require this systemd version.
MIN_SYSTEMD_VERSION = 258

# Adw.ShortcutsDialog and Adw.Spinner require libadwaita 1.8 or newer.
MIN_LIBADWAITA_VERSION: tuple[int, int] = (1, 8)


def libadwaita_supports(major: int, minor: int) -> bool:
    """Return True if the given libadwaita (major, minor) meets the app's minimum."""
    return (major, minor) >= MIN_LIBADWAITA_VERSION


HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
SHARE_RE = re.compile(r"^[A-Za-z0-9._$-]{1,80}$")
SMB_PATH_RE = re.compile(r"^//([^/\\]+)/([^/\\]+)$")
MANAGER_ID_RE = re.compile(r"^[a-f0-9]{16}$")


class MountManagerError(Exception):
    """Base exception for user-facing errors."""


class ValidationError(MountManagerError):
    """Raised when user input is not acceptable."""


class CommandError(MountManagerError):
    """Raised when an external command fails."""


@dataclasses.dataclass(frozen=True)
class SharePath:
    host: str
    share: str

    @property
    def source(self) -> str:
        return f"//{self.host}/{self.share}"


@dataclasses.dataclass(frozen=True)
class ManagedMount:
    manager_id: str
    source: str
    host: str
    share: str
    mount_point: Path
    unit_name: str
    automount_unit_name: str
    credential_path: Path
    metadata_path: Path
    creator_uid: int
    creator_gid: int
    mounted: bool = False
    active: bool = False
    needs_upgrade: bool = False
    status: str = "Unknown"


@dataclasses.dataclass(frozen=True)
class DisplayedMount:
    source: str
    mount_point: Path
    status: str
    active: bool
    openable: bool
    needs_upgrade: bool
    managed: bool
    managed_record: ManagedMount | None = None


def parse_share_path(raw_value: str) -> SharePath:
    value = raw_value.strip()
    if not value:
        raise ValidationError("Enter a share path like //nas.local/media.")
    if "\\" in value:
        raise ValidationError("Use forward slashes only, for example //nas.local/media.")
    if not value.startswith("//"):
        raise ValidationError("Share path must start with //, for example //nas.local/media.")

    match = SMB_PATH_RE.fullmatch(value)
    if not match:
        raise ValidationError("Use exactly //hostname/share with no extra path segments.")

    host, share = match.groups()
    host = host.lower()

    if host in {".", ".."} or share in {".", ".."}:
        raise ValidationError("Host and share names cannot be . or ...")
    if ".." in host.split("."):
        raise ValidationError("Host name is not valid.")
    if not HOST_RE.fullmatch(host):
        raise ValidationError("Host must be a hostname or IPv4 address, such as nas.local.")
    if not SHARE_RE.fullmatch(share):
        raise ValidationError("Share may contain only letters, numbers, dots, underscores, dashes, and $.")

    return SharePath(host=host, share=share)


def validate_credentials(username: str, password: str) -> tuple[str, str]:
    username = username.strip()
    if not username:
        raise ValidationError("Username is required.")
    if not password:
        raise ValidationError("Password is required.")
    for label, value in (("Username", username), ("Password", password)):
        if "\n" in value or "\r" in value or "\0" in value:
            raise ValidationError(f"{label} cannot contain line breaks or null bytes.")
    return username, password


def original_user_ids() -> tuple[int, int]:
    uid_text = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    gid_text = os.environ.get("SUDO_GID")

    uid = int(uid_text) if uid_text is not None else os.getuid()
    if gid_text is not None:
        gid = int(gid_text)
    else:
        gid = pwd.getpwuid(uid).pw_gid
    return uid, gid


def manager_id_for(share_path: SharePath) -> str:
    digest = hashlib.sha256(share_path.source.encode("utf-8")).hexdigest()
    return digest[:16]


def run_command(
    args: list[str],
    *,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"Required command not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"{args[0]} timed out.") from exc

    if check and result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        if not details:
            details = f"exit code {result.returncode}"
        raise CommandError(f"{args[0]} failed: {details}")

    return result


def systemd_unit_name_for(mount_point: Path, suffix: str) -> str:
    result = run_command(
        ["systemd-escape", f"--suffix={suffix}", "--path", str(mount_point)],
        check=True,
    )
    unit_name = result.stdout.strip()
    if not unit_name.endswith(f".{suffix}"):
        raise CommandError(f"systemd-escape returned an invalid {suffix} unit name.")
    return unit_name


def credential_path_for(manager_id: str) -> Path:
    """Return the on-disk path of the encrypted credential blob for *manager_id*."""
    return CREDENTIALS_DIR / f"{manager_id}.cred.enc"


def build_mount_record(share_path: SharePath, creator_uid: int, creator_gid: int) -> ManagedMount:
    manager_id = manager_id_for(share_path)
    mount_point = MOUNT_ROOT / share_path.host / share_path.share
    unit_name = systemd_unit_name_for(mount_point, "mount")
    automount_unit_name = systemd_unit_name_for(mount_point, "automount")
    credential_path = credential_path_for(manager_id)
    metadata_path = METADATA_DIR / f"{manager_id}.json"
    return ManagedMount(
        manager_id=manager_id,
        source=share_path.source,
        host=share_path.host,
        share=share_path.share,
        mount_point=mount_point,
        unit_name=unit_name,
        automount_unit_name=automount_unit_name,
        credential_path=credential_path,
        metadata_path=metadata_path,
        creator_uid=creator_uid,
        creator_gid=creator_gid,
    )


def mount_unit_text(record: ManagedMount) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=Mount SMB share {record.source}",
            "Documentation=man:mount.cifs(8)",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Mount]",
            f"What={record.source}",
            f"Where={record.mount_point}",
            "Type=cifs",
            f"Options={mount_options(f'%d/{CREDENTIAL_NAME}', record.creator_uid, record.creator_gid)}",
            f"TimeoutSec={MOUNT_TIMEOUT_SECONDS}s",
            f"LoadCredentialEncrypted={CREDENTIAL_NAME}:{record.credential_path}",
            "",
        ]
    )


def automount_unit_text(record: ManagedMount) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=Automount SMB share {record.source}",
            "Documentation=man:systemd.automount(5)",
            "",
            "[Automount]",
            f"Where={record.mount_point}",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def metadata_for(record: ManagedMount) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "manager_id": record.manager_id,
        "source": record.source,
        "host": record.host,
        "share": record.share,
        "mount_point": str(record.mount_point),
        "unit_name": record.unit_name,
        "automount_unit_name": record.automount_unit_name,
        "credential_path": str(record.credential_path),
        "creator_uid": record.creator_uid,
        "creator_gid": record.creator_gid,
        "created_at": int(time.time()),
    }


def ensure_runtime_directories() -> None:
    MANAGED_ROOT.mkdir(mode=0o755, exist_ok=True)
    CREDENTIALS_DIR.mkdir(mode=0o700, exist_ok=True)
    METADATA_DIR.mkdir(mode=0o755, exist_ok=True)
    MOUNT_ROOT.mkdir(mode=0o755, exist_ok=True)
    os.chmod(MANAGED_ROOT, 0o755)
    os.chmod(CREDENTIALS_DIR, 0o700)
    os.chmod(METADATA_DIR, 0o755)


def systemd_version() -> int | None:
    """Return the major version number of systemd, or None if it cannot be determined."""
    try:
        result = subprocess.run(
            ["systemctl", "--version"],
            check=False,
            text=True,
            capture_output=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    split_line = first_line.split()
    if len(split_line) >= 2 and split_line[0] == "systemd":
        try:
            return int(split_line[1])
        except ValueError:
            return None
    return None


def encrypted_credentials_supported() -> bool:
    """Check if the system can use systemd-creds for mount units."""
    if shutil.which("systemd-creds") is None:
        return False
    version = systemd_version()
    return version is not None and version >= MIN_SYSTEMD_VERSION


def require_systemd_support() -> None:
    """Exit if the system cannot supply credentials to mount units via systemd-creds."""
    if encrypted_credentials_supported():
        return
    version = systemd_version()
    found = f"systemd {version}" if version is not None else "systemd version unknown"
    print(
        f"{APP_NAME} requires systemd {MIN_SYSTEMD_VERSION} or newer with systemd-creds available "
        f"(found {found}).",
        file=sys.stderr,
    )
    raise SystemExit(1)


def write_encrypted_credential_file(path: Path, credential_name: str, username: str, password: str) -> None:
    """Write an encrypted cifs credentials blob via systemd-creds.

    The plaintext is piped on stdin and never touches disk. The resulting
    file at *path* is the binary systemd-creds encrypted form, bound to
    *credential_name* so that decryption succeeds only when the receiving
    unit references the same name in LoadCredentialEncrypted=.
    """

    plaintext = f"username={username}\npassword={password}\n".encode("utf-8")

    try:
        result = subprocess.run(
            [
                "systemd-creds",
                "encrypt",
                f"--name={credential_name}",
                "-",
                str(path),
            ],
            input=plaintext,
            check=False,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise CommandError("systemd-creds was not found") from exc

    if result.returncode != 0:
        details = (result.stderr or result.stdout or b"").decode("utf-8", "replace").strip()
        if not details:
            details = f"exit code {result.returncode}"
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise CommandError(f"systemd-creds encryption failed: {details}")

    # systemd-creds creates the encrypted file with 0o600 permissions, but set it explicitly to be sure
    os.chmod(path, 0o600)


def write_text_file(path: Path, text: str, mode: int) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)


def write_metadata_file(record: ManagedMount) -> None:
    text = json.dumps(metadata_for(record), indent=2, sort_keys=True) + "\n"
    write_text_file(record.metadata_path, text, 0o644)


def mount_unit_path(record: ManagedMount) -> Path:
    return SYSTEMD_DIR / record.unit_name


def automount_unit_path(record: ManagedMount) -> Path:
    return SYSTEMD_DIR / record.automount_unit_name


def write_unit_files(record: ManagedMount) -> None:
    write_text_file(mount_unit_path(record), mount_unit_text(record), 0o644)
    write_text_file(automount_unit_path(record), automount_unit_text(record), 0o644)


def ensure_mount_point(record: ManagedMount) -> None:
    if record.mount_point.exists() and not record.mount_point.is_dir():
        raise ValidationError(f"Mount path exists and is not a directory: {record.mount_point}")
    record.mount_point.mkdir(mode=0o755, parents=True, exist_ok=True)


def ensure_create_is_safe(record: ManagedMount) -> None:
    if record.metadata_path.exists():
        raise ValidationError(f"{record.source} is already managed by this app.")
    if record.credential_path.exists():
        raise ValidationError(f"A credential file already exists for this share: {record.credential_path}")
    for unit_path in (mount_unit_path(record), automount_unit_path(record)):
        if unit_path.exists():
            raise ValidationError(f"Systemd unit already exists: {unit_path}")
    if record.mount_point.exists() and not record.mount_point.is_dir():
        raise ValidationError(f"Mount path exists and is not a directory: {record.mount_point}")
    if record.mount_point.exists() and any(record.mount_point.iterdir()):
        raise ValidationError(f"Mount path is not empty: {record.mount_point}")


def check_smb_host_reachable(share_raw: str) -> SharePath:
    share_path = parse_share_path(share_raw)
    try:
        addresses = socket.getaddrinfo(
            share_path.host,
            SMB_PORT,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise CommandError("Could not find the host. Check the share path and network connection.") from exc

    for family, socktype, proto, _canonname, sockaddr in addresses:
        with socket.socket(family, socktype, proto) as sock:
            sock.settimeout(CONNECT_TIMEOUT_SECONDS)
            try:
                sock.connect(sockaddr)
            except OSError:
                continue
            return share_path

    raise CommandError("Could not connect to the host. Check the share path and network connection.")


def mount_options(
    credentials: Path | str,
    creator_uid: int,
    creator_gid: int,
) -> str:
    return ",".join(
        [
            f"credentials={credentials}",
            "iocharset=utf8",
            "nofail",
            "_netdev",
            f"uid={creator_uid}",
            f"gid={creator_gid}",
        ]
    )


def create_mount(share_raw: str, username_raw: str, password_raw: str) -> None:
    share_path = parse_share_path(share_raw)
    username, password = validate_credentials(username_raw, password_raw)
    creator_uid, creator_gid = original_user_ids()
    record = build_mount_record(share_path, creator_uid, creator_gid)

    ensure_create_is_safe(record)
    ensure_runtime_directories()

    try:
        ensure_mount_point(record)
        write_encrypted_credential_file(record.credential_path, CREDENTIAL_NAME, username, password)
        write_unit_files(record)
        write_metadata_file(record)
        run_command(["systemctl", "daemon-reload"])
        enable_and_trigger_automount(record)
    except Exception:
        rollback_failed_create(record)
        raise


def remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def enabled_unit_symlink_path(unit_name: str) -> Path:
    return SYSTEMD_DIR / "multi-user.target.wants" / unit_name


def remove_unit_symlinks(record: ManagedMount) -> None:
    remove_if_exists(enabled_unit_symlink_path(record.automount_unit_name))
    remove_if_exists(enabled_unit_symlink_path(record.unit_name))


def rmdir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def iter_findmnt_filesystems(payload: dict[str, Any]) -> list[dict[str, Any]]:
    filesystems = []
    pending = list(payload.get("filesystems") or [])
    while pending:
        filesystem = pending.pop(0)
        if isinstance(filesystem, dict):
            filesystems.append(filesystem)
            children = filesystem.get("children") or []
            if isinstance(children, list):
                pending.extend(children)
    return filesystems


def is_mounted(mount_point: Path) -> bool:
    result = run_command(["findmnt", "--json", "--types", "cifs,smb3"], check=False)
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False

    expected = str(mount_point.resolve(strict=False))
    for filesystem in iter_findmnt_filesystems(payload):
        target = str(filesystem.get("target") or "")
        if target and str(Path(target).resolve(strict=False)) == expected:
            return True
    return False


def stop_and_unmount(record: ManagedMount, *, check: bool) -> None:
    run_command(["systemctl", "stop", record.unit_name], check=False)
    if not is_mounted(record.mount_point):
        return

    if not check:
        run_command(["umount", str(record.mount_point)], check=False)
        return

    try:
        run_command(["umount", str(record.mount_point)])
    except CommandError as exc:
        raise CommandError(
            f"Could not unmount {record.mount_point}. Close any files or folders using it, then try again."
        ) from exc

    if is_mounted(record.mount_point):
        raise CommandError(
            f"Could not unmount {record.mount_point}. Close any files or folders using it, then try again."
        )


def disable_managed_units(record: ManagedMount) -> None:
    run_command(["systemctl", "disable", record.automount_unit_name], check=False)
    run_command(["systemctl", "disable", record.unit_name], check=False)
    remove_unit_symlinks(record)
    run_command(["systemctl", "stop", record.automount_unit_name], check=False)
    run_command(["systemctl", "stop", record.unit_name], check=False)


def reset_failed_units(record: ManagedMount) -> None:
    run_command(["systemctl", "reset-failed", record.automount_unit_name], check=False)
    run_command(["systemctl", "reset-failed", record.unit_name], check=False)


def trigger_automount(record: ManagedMount) -> subprocess.Popen[str]:
    script = (
        "import os, sys\n"
        "flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)\n"
        "fd = os.open(sys.argv[1], flags)\n"
        "os.close(fd)\n"
    )
    try:
        return subprocess.Popen(
            [sys.executable, "-c", script, str(record.mount_point)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"Required command not found: {sys.executable}") from exc


def finish_trigger_process(process: subprocess.Popen[str]) -> None:
    try:
        process.communicate(timeout=0.5)
        return
    except subprocess.TimeoutExpired:
        pass

    process.terminate()
    try:
        process.communicate(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass

    process.kill()
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def wait_for_mount_active(record: ManagedMount) -> None:
    deadline = time.monotonic() + MOUNT_TIMEOUT_SECONDS + 5
    while time.monotonic() < deadline:
        if is_mounted(record.mount_point) and systemd_is_active(record.unit_name):
            return
        time.sleep(0.25)
    raise CommandError("Automount did not activate the backing mount.")


def enable_and_trigger_automount(record: ManagedMount) -> None:
    run_command(["systemctl", "disable", record.unit_name], check=False)
    remove_if_exists(enabled_unit_symlink_path(record.unit_name))
    trigger_process: subprocess.Popen[str] | None = None
    try:
        run_command(["systemctl", "enable", "--now", record.automount_unit_name])
        trigger_process = trigger_automount(record)
        wait_for_mount_active(record)
    except CommandError as exc:
        raise CommandError("Could not mount the share through its automount. Check the share path, username, and password.") from exc
    finally:
        if trigger_process is not None:
            finish_trigger_process(trigger_process)


def rollback_failed_create(record: ManagedMount) -> None:
    disable_managed_units(record)
    stop_and_unmount(record, check=False)
    run_command(["systemctl", "stop", record.automount_unit_name], check=False)
    remove_if_exists(automount_unit_path(record))
    remove_if_exists(mount_unit_path(record))
    remove_if_exists(record.credential_path)
    remove_if_exists(record.metadata_path)
    rmdir_if_empty(record.mount_point)
    rmdir_if_empty(record.mount_point.parent)
    run_command(["systemctl", "daemon-reload"], check=False)
    reset_failed_units(record)


def delete_mount(record: ManagedMount) -> None:
    disable_managed_units(record)
    stop_and_unmount(record, check=True)
    run_command(["systemctl", "stop", record.automount_unit_name], check=False)

    remove_if_exists(automount_unit_path(record))
    remove_if_exists(mount_unit_path(record))
    remove_if_exists(record.credential_path)
    remove_if_exists(record.metadata_path)
    rmdir_if_empty(record.mount_point)
    rmdir_if_empty(record.mount_point.parent)
    run_command(["systemctl", "daemon-reload"])
    reset_failed_units(record)


def set_mount_enabled(record: ManagedMount, enabled: bool) -> None:
    if record.needs_upgrade:
        raise ValidationError("This mount was created by an older version. Upgrade it before enabling it.")

    if enabled:
        try:
            ensure_mount_point(record)
            write_unit_files(record)
            run_command(["systemctl", "daemon-reload"])
            run_command(["systemctl", "disable", record.unit_name], check=False)
            remove_if_exists(enabled_unit_symlink_path(record.unit_name))
            enable_and_trigger_automount(record)
        except CommandError as exc:
            raise CommandError("Could not enable the on-demand mount for this share.") from exc
        return

    disable_managed_units(record)
    stop_and_unmount(record, check=True)
    run_command(["systemctl", "stop", record.automount_unit_name], check=False)
    reset_failed_units(record)


def upgrade_mount(record: ManagedMount) -> None:
    if not record.credential_path.exists():
        raise ValidationError(f"Encrypted credentials were not found: {record.credential_path}")

    ensure_mount_point(record)
    disable_managed_units(record)
    stop_and_unmount(record, check=True)
    write_unit_files(record)
    run_command(["systemctl", "daemon-reload"])
    enable_and_trigger_automount(record)
    write_metadata_file(record)
    reset_failed_units(record)


def delete_mount_by_id(manager_id: str) -> None:
    delete_mount(load_record_by_id(manager_id))


def set_mount_enabled_by_id(manager_id: str, enabled: bool) -> None:
    set_mount_enabled(load_record_by_id(manager_id), enabled)


def upgrade_mount_by_id(manager_id: str) -> None:
    upgrade_mount(load_record_by_id(manager_id))


def load_record_by_id(manager_id: str) -> ManagedMount:
    if not MANAGER_ID_RE.fullmatch(manager_id):
        raise ValidationError("Invalid managed mount id.")

    metadata_path = METADATA_DIR / f"{manager_id}.json"
    record = load_record_from_metadata(metadata_path)
    if record is None:
        raise ValidationError("Managed mount was not found.")
    return record


def load_record_from_metadata(path: Path) -> ManagedMount | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    required = {
        "manager_id",
        "source",
        "host",
        "share",
        "mount_point",
        "unit_name",
        "credential_path",
        "creator_uid",
        "creator_gid",
    }
    if not required.issubset(payload):
        return None

    try:
        share_path = parse_share_path(str(payload["source"]))
        creator_uid = int(payload["creator_uid"])
        creator_gid = int(payload["creator_gid"])
        manager_id = str(payload["manager_id"])
    except (TypeError, ValueError, ValidationError):
        return None

    if manager_id != manager_id_for(share_path):
        return None
    if path.name != f"{manager_id}.json":
        return None

    try:
        expected = build_mount_record(share_path, creator_uid, creator_gid)
    except MountManagerError:
        return None

    unit_name = str(payload["unit_name"])
    automount_unit_name = str(payload.get("automount_unit_name") or expected.automount_unit_name)
    mount_point = Path(str(payload["mount_point"]))
    credential_path = Path(str(payload["credential_path"]))
    if unit_name != expected.unit_name:
        return None
    if automount_unit_name != expected.automount_unit_name:
        return None
    if mount_point.resolve(strict=False) != expected.mount_point.resolve(strict=False):
        return None
    if credential_path != expected.credential_path:
        return None

    try:
        schema_version = int(payload.get("schema_version", 0))
    except (TypeError, ValueError):
        schema_version = 0
    needs_upgrade = schema_version < 4 or "automount_unit_name" not in payload
    mounted = is_mounted(expected.mount_point)
    automount_active = systemd_is_active(automount_unit_name)
    mount_enabled = systemd_is_enabled(unit_name)
    active = automount_active and not needs_upgrade
    if needs_upgrade:
        status = "Old version, please upgrade"
    elif mounted and automount_active:
        status = "Mounted"
    elif mounted:
        status = "Mounted, on-demand disabled"
    elif automount_active:
        status = "Waiting for access"
    elif mount_enabled:
        status = "Startup mount still enabled"
    else:
        status = systemd_status(automount_unit_name)

    return ManagedMount(
        manager_id=manager_id,
        source=expected.source,
        host=share_path.host,
        share=share_path.share,
        mount_point=expected.mount_point,
        unit_name=expected.unit_name,
        automount_unit_name=expected.automount_unit_name,
        credential_path=expected.credential_path,
        metadata_path=path,
        creator_uid=creator_uid,
        creator_gid=creator_gid,
        mounted=mounted,
        active=active,
        needs_upgrade=needs_upgrade,
        status=status,
    )


def systemd_is_active(unit_name: str) -> bool:
    return run_command(["systemctl", "is-active", "--quiet", unit_name], check=False).returncode == 0


def systemd_is_enabled(unit_name: str) -> bool:
    return run_command(["systemctl", "is-enabled", "--quiet", unit_name], check=False).returncode == 0


def systemd_status(unit_name: str) -> str:
    result = run_command(["systemctl", "is-active", unit_name], check=False)
    status = result.stdout.strip()
    if status:
        return status.capitalize()
    return "Inactive"


def load_managed_mounts() -> list[ManagedMount]:
    if not METADATA_DIR.exists():
        return []
    records = []
    try:
        metadata_paths = sorted(METADATA_DIR.glob("*.json"))
    except OSError:
        return []
    for path in metadata_paths:
        record = load_record_from_metadata(path)
        if record is not None:
            records.append(record)
    return records


def load_current_smb_mounts() -> list[DisplayedMount]:
    result = run_command(["findmnt", "--json", "--types", "cifs,smb3"], check=False)
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []

    mounts = []
    for filesystem in iter_findmnt_filesystems(payload):
        source = str(filesystem.get("source") or "")
        target = str(filesystem.get("target") or "")
        fstype = str(filesystem.get("fstype") or "")
        if not source or not target or fstype not in {"cifs", "smb3"}:
            continue
        mounts.append(
            DisplayedMount(
                source=source,
                mount_point=Path(target),
                status="Mounted",
                active=True,
                openable=True,
                needs_upgrade=False,
                managed=False,
            )
        )
    return mounts


def load_displayed_mounts() -> list[DisplayedMount]:
    managed_records = load_managed_mounts()
    displayed = [
        DisplayedMount(
            source=record.source,
            mount_point=record.mount_point,
            status=record.status,
            active=record.active,
            openable=not record.needs_upgrade and (record.active or record.mounted),
            needs_upgrade=record.needs_upgrade,
            managed=True,
            managed_record=record,
        )
        for record in managed_records
    ]

    managed_keys = {(record.source, str(record.mount_point)) for record in managed_records}
    for mount in load_current_smb_mounts():
        if (mount.source, str(mount.mount_point)) in managed_keys:
            continue
        displayed.append(mount)

    return displayed


def run_privileged_helper(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        raise CommandError("pkexec was not found. Install polkit to manage mounts.")

    command = [
        pkexec,
        sys.executable,
        str(Path(__file__).resolve()),
        "--helper",
        action,
    ]
    result = subprocess.run(
        command,
        check=False,
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        response = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        details = (result.stderr or result.stdout).strip()
        if not details:
            details = f"helper exited with code {result.returncode}"
        raise CommandError(details) from exc

    if result.returncode != 0 or not response.get("ok"):
        message = str(response.get("error") or result.stderr or "Privilege operation failed.").strip()
        raise CommandError(message)

    return response


def request_helper_create(share: str, username: str, password: str) -> None:
    parse_share_path(share)
    validate_credentials(username, password)
    run_privileged_helper(
        "create",
        {
            "share": share,
            "username": username,
            "password": password,
        },
    )


def request_helper_delete(record: ManagedMount) -> None:
    run_privileged_helper("delete", {"manager_id": record.manager_id})


def request_helper_upgrade(record: ManagedMount) -> None:
    run_privileged_helper("upgrade", {"manager_id": record.manager_id})


def request_helper_set_enabled(record: ManagedMount, enabled: bool) -> None:
    run_privileged_helper(
        "set-enabled",
        {
            "manager_id": record.manager_id,
            "enabled": enabled,
        },
    )


def write_helper_response(ok: bool, *, error: str | None = None) -> None:
    payload: dict[str, Any] = {"ok": ok}
    if error is not None:
        payload["error"] = error
    print(json.dumps(payload), flush=True)


def read_helper_payload() -> dict[str, Any]:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("Helper received invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Helper payload must be a JSON object.")
    return payload


def helper_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValidationError(f"Helper payload field must be a boolean: {key}")
    return value


def run_helper_mode(action: str) -> int:
    if os.geteuid() != 0:
        write_helper_response(False, error="Helper must run as root.")
        return 1

    try:
        payload = read_helper_payload()
        if action == "create":
            create_mount(
                str(payload.get("share", "")),
                str(payload.get("username", "")),
                str(payload.get("password", "")),
            )
        elif action == "delete":
            delete_mount_by_id(str(payload.get("manager_id", "")))
        elif action == "upgrade":
            upgrade_mount_by_id(str(payload.get("manager_id", "")))
        elif action == "set-enabled":
            set_mount_enabled_by_id(
                str(payload.get("manager_id", "")),
                helper_bool(payload, "enabled"),
            )
        else:
            raise ValidationError("Unknown helper action.")
    except MountManagerError as exc:
        write_helper_response(False, error=str(exc))
        return 1
    except Exception as exc:
        write_helper_response(False, error=f"Unexpected helper error: {exc}")
        return 1

    write_helper_response(True)
    return 0




def run_gui() -> int:
    from mount_manager_ui import run_gui as _run_gui

    return _run_gui()

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "--helper",
        choices=("create", "delete", "upgrade", "set-enabled"),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    require_systemd_support()
    if args.helper:
        return run_helper_mode(args.helper)

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
