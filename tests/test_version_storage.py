"""Safe version discovery and deletion behavior."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.minecraft.version import delete_minecraft_version
from utils.instances import installed_instance_ids


class VersionStorageTests(unittest.TestCase):
    def test_discovery_requires_a_version_directory_and_matching_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / 'versions/good/good.json'
            good.parent.mkdir(parents=True)
            good.write_text('{}')
            (root / 'versions/no-metadata').mkdir()
            (root / 'versions/file-version.json').write_text('{}')
            self.assertEqual(installed_instance_ids(str(root)), ['good'])
            self.assertEqual(installed_instance_ids(None), [])

    def test_delete_removes_only_selected_version_and_preserves_shared_game_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for version in ('one', 'two'):
                directory = root / 'versions' / version
                directory.mkdir(parents=True)
                (directory / (version + '.json')).write_text('{}')
            for relative in ('saves/world/level.dat', 'assets/indexes/shared.json', 'libraries/shared.jar'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('preserved')
            self.assertTrue(delete_minecraft_version(str(root), 'one'))
            self.assertFalse((root / 'versions/one').exists())
            self.assertTrue((root / 'versions/two/two.json').is_file())
            for relative in ('saves/world/level.dat', 'assets/indexes/shared.json', 'libraries/shared.jar'):
                self.assertEqual((root / relative).read_text(), 'preserved')

    def test_path_traversal_and_missing_version_do_not_delete_outside_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / 'outside'
            outside.mkdir()
            marker = outside / 'keep.txt'
            marker.write_text('keep')
            (root / 'versions').mkdir()
            self.assertFalse(delete_minecraft_version(str(root), '../outside'))
            self.assertFalse(delete_minecraft_version(str(root), 'missing'))
            self.assertEqual(marker.read_text(), 'keep')

    def test_filesystem_failure_returns_false_and_keeps_selection_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / 'versions/test'
            version.mkdir(parents=True)
            data = version / 'test.json'
            data.write_text('{}')
            with patch('core.minecraft.version.shutil.rmtree', side_effect=PermissionError('locked')):
                self.assertFalse(delete_minecraft_version(str(root), 'test'))
            self.assertEqual(data.read_text(), '{}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
