import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from config.settings import SettingsManager


class ModpackSettingsTests(unittest.TestCase):
    def test_imported_pack_stays_isolated_if_global_isolation_is_disabled(self):
        with TemporaryDirectory() as root:
            manager = SettingsManager(root)
            manager.set_setting('minecraft.directory.enable', root)
            manager.set_setting('minecraft.version.enable', 'pack-instance')
            manager.set_setting('minecraft.isolation', False)
            metadata = Path(root) / 'versions' / 'pack-instance' / 'pack-instance.json'
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({'buggcraftModpack': {'name': 'pack'}}), encoding='utf-8')
            self.assertEqual(manager.get_minecraft_isolation_directory(), str(metadata.parent))


if __name__ == '__main__':
    unittest.main()
