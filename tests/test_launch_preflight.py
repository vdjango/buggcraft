"""Memory warnings use installed mods and the JVM heap which will actually run."""

import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))

from core.launch_preflight import (LaunchMemoryWarning, check_launch_memory,
                                   effective_heap_mib)


class LaunchPreflightTests(unittest.TestCase):
    def test_modded_1024_mib_warns_but_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as folder:
            mods = Path(folder) / 'mods'
            mods.mkdir()
            for index in range(44):
                (mods / f'mod-{index}.jar').touch()
            (mods / 'disabled.jar.disabled').touch()
            with self.assertRaisesRegex(LaunchMemoryWarning, '44 个已启用模组.*建议至少 4096 MiB'):
                check_launch_memory(folder, ['java', '-Xmx1024M'], [], 16384)
            self.assertEqual(check_launch_memory(folder, ['java', '-Xmx4096M'], [], 16384),
                             (44, 4096, 4096))

    def test_advanced_override_and_system_reserve(self):
        with tempfile.TemporaryDirectory() as folder:
            mods = Path(folder) / 'mods'
            mods.mkdir()
            for index in range(10):
                (mods / f'mod-{index}.JAR').touch()
            self.assertEqual(effective_heap_mib(['java', '-Xmx4G', '-Xmx2G'], []), 2048)
            with self.assertRaisesRegex(LaunchMemoryWarning, '建议至少 3072 MiB'):
                check_launch_memory(folder, ['java', '-Xmx4G', '-Xmx2G'], [], 16384)
            with self.assertRaisesRegex(LaunchMemoryWarning, '系统当前可用约 3500 MiB'):
                check_launch_memory(folder, ['java', '-Xmx3G'], [], 3500)

    def test_unmodded_legacy_instance_has_no_mod_floor(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(check_launch_memory(folder, ['fake-game'], ['-Xmx1024M'], 8192),
                             (0, 1024, 0))


if __name__ == '__main__':
    unittest.main()
