"""Settings scope and Minecraft data-directory rules."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from config.settings import SettingsManager


class SettingsIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = SettingsManager(self.temporary.name)
        self.root = str(Path(self.temporary.name) / 'minecraft')
        self.manager.set_setting('minecraft.directory.enable', self.root)
        self.manager.set_setting('minecraft.version.enable', '1.21.8-forge-58.0.0')

    def test_isolated_and_shared_data_dirs_follow_game_setting(self):
        expected = str(Path(self.root) / 'versions' / '1.21.8-forge-58.0.0')
        self.assertEqual(self.manager.get_minecraft_isolation_directory(), expected)
        self.manager.set_setting('minecraft.isolation', False)
        self.assertEqual(self.manager.get_minecraft_isolation_directory(), self.root)

    def test_imported_modpack_stays_isolated_when_global_isolation_is_disabled(self):
        identity = 'Imported-Pack'
        self.manager.set_setting('minecraft.version.enable', identity)
        self.manager.set_setting('minecraft.isolation', False)
        path = Path(self.root) / 'versions' / identity / (identity + '.json')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'id': identity, 'buggcraftModpack': {'name': 'pack'}}), encoding='utf-8')
        self.assertEqual(self.manager.get_minecraft_isolation_directory(), str(path.parent))

    def test_independent_version_setting_overrides_isolation_without_changing_global(self):
        self.manager.set_setting('minecraft.isolation', True)
        self.manager.set_version_setting_enable(True)
        self.manager.set_version_setting('minecraft.isolation', False)
        self.assertEqual(self.manager.get_minecraft_isolation_directory(), self.root)
        self.assertTrue(self.manager.get_setting('minecraft.isolation'))
        self.manager.set_version_setting('minecraft.isolation', True)
        self.assertEqual(self.manager.get_minecraft_isolation_directory(),
                         str(Path(self.root) / 'versions' / '1.21.8-forge-58.0.0'))

    def test_independent_settings_inherit_global_and_survive_reload(self):
        self.manager.set_setting('memory.allocation', 4096)
        self.manager.set_version_setting_enable(True)
        self.assertEqual(self.manager.get_version_setting('memory.allocation'), 4096)
        self.manager.set_version_setting('memory.allocation', 6144)
        self.assertTrue(self.manager.save_settings())
        reloaded = SettingsManager(self.temporary.name)
        self.assertEqual(reloaded.get_setting('memory.allocation'), 4096)
        self.assertEqual(reloaded.get_version_setting('memory.allocation'), 6144)

    def test_missing_version_uses_root_even_when_isolation_is_enabled(self):
        self.manager.set_setting('minecraft.version.enable', None)
        self.assertEqual(self.manager.get_minecraft_isolation_directory(), self.root)

    def test_denied_settings_directory_reports_failure_without_retries_or_data_loss(self):
        original = Path(self.manager.config_file).read_bytes()
        self.manager.set_setting('memory.allocation', 8192)
        with patch('config.settings.os.open', side_effect=PermissionError('read-only')) as create:
            self.assertFalse(self.manager.save_settings())
        self.assertEqual(create.call_count, 1)
        self.assertEqual(Path(self.manager.config_file).read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
