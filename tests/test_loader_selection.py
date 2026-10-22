"""Selection commits, removal and compatibility must agree with the UI."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from PySide6.QtWidgets import QApplication, QWidget
from core.loader_rules import LOADERS, COMPONENTS, incompatibility
from ui.dialog.MinecraftInstallDialog import MinecraftInstallDialog


class LoaderSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.parent.resource_path = str(Path(__file__).resolve().parents[1] / 'resources')
        self.dialog = MinecraftInstallDialog(self.parent)
        self.addCleanup(self.dialog.close)
        self.dialog.set_version('1.20.1', 'Release')
        self.pool = patch.object(self.dialog.loader_pool, 'start')
        self.pool.start()
        self.addCleanup(self.pool.stop)

    def choose(self, loader, version):
        self.dialog.open_loader_list(loader)
        self.dialog.on_loader_versions(loader, self.dialog.version, True, [version])
        self.dialog.select_loader_version()

    def test_matrix_matches_requested_combinations(self):
        allowed = {'Forge': {'Forge', 'OptiFine'}, 'NeoForge': {'NeoForge'},
                   'Fabric': {'Fabric', 'Fabric API'}, 'Quilt': {'Quilt', 'Fabric API', 'QSL/QFAPI'}}
        for loader in LOADERS:
            for component in COMPONENTS:
                self.assertEqual(not incompatibility(component, loader), component in allowed[loader])

    def test_commit_blocks_others_remove_restores_and_version_change_clears(self):
        self.choose('Forge', '47.4.0')
        self.assertEqual(self.dialog.loader, 'Forge')
        self.assertTrue(self.dialog.flow_neoforge.is_disabled)
        self.assertEqual(self.dialog.flow_fabric_api.description, '与 Forge 不兼容')
        self.dialog.open_loader_list('Fabric')
        self.assertEqual(self.dialog.pending_loader, 'Forge')
        self.dialog.clear_loader()
        self.assertFalse(self.dialog.flow_fabric.is_disabled)
        self.choose('Quilt', '0.28.0')
        self.assertEqual(self.dialog.flow_optifine.description, '与 Quilt 不兼容')
        self.assertEqual(self.dialog.flow_fabric_api.description, '需手动添加模组')
        self.dialog.set_version('1.21.1', 'Release')
        self.assertEqual(self.dialog.loader, '')
        self.assertFalse(self.dialog.flow_forge.is_selected)
        self.assertFalse(self.dialog.flow_forge.is_disabled)

    def test_browsing_and_cancelling_preserves_committed_selection(self):
        self.choose('Forge', '47.4.0')
        self.dialog.open_loader_list('Forge')
        self.dialog.on_loader_versions('Forge', '1.20.1', False, 'offline')
        self.dialog.content_stack.setCurrentIndex(0)
        self.assertEqual((self.dialog.loader, self.dialog.loader_version), ('Forge', '47.4.0'))
        self.dialog.clear_loader()
        self.dialog.open_loader_list('Fabric')
        self.assertEqual(self.dialog.loader, '')


if __name__ == '__main__':
    unittest.main()
