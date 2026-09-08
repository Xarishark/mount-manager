"""Smoke test ensuring the test harness can import the main module."""

import unittest


class ImportSmokeTest(unittest.TestCase):
    def test_import_mount_manager(self) -> None:
        import mount_manager  # noqa: F401

        self.assertTrue(hasattr(mount_manager, "main"))


if __name__ == "__main__":
    unittest.main()
