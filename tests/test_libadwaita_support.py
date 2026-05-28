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
