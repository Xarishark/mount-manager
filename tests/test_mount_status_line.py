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
