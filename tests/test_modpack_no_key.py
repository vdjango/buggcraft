import json
from zipfile import ZipFile
from unittest.mock import patch
from _qml_test_support import LauncherQmlCase


class ModpackNoKeyTests(LauncherQmlCase):
    def test_import_form_requires_no_credentials_and_opens_progress(self):
        archive = self.directory / '整合包.zip'
        with ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps({
                'name': 'Fixture', 'version': '1', 'manifestType': 'minecraftModpack',
                'manifestVersion': 1, 'minecraft': {'version': '1.20.1', 'modLoaders': []},
                'files': [], 'overrides': 'overrides'}))
        downloads = self.window.download_page
        downloads.open_content('modpack', 'import')
        controller = downloads.content_page.controller
        self.assertFalse(hasattr(controller, 'api_key'))
        self.assertFalse(hasattr(controller, 'key_input'))
        controller.inspectPack(str(archive))
        self.wait_until(lambda: not controller.pack_inspecting)
        self.assertEqual(controller.pack_error, '')
        controller.setPackName('Fixture')
        with patch.object(downloads.tasks_page, 'start_install', return_value=True) as start:
            controller.importPack()
        start.assert_called_once_with('Fixture', str(self.game_dir), modpack=str(archive.resolve()))
        self.assertEqual(self.window.content_stack.currentIndex(), 1)
        self.assertIs(downloads.stack.currentWidget(), downloads.tasks_page)

    def test_unsuccessful_enqueue_keeps_import_form_visible(self):
        downloads = self.window.download_page
        downloads.open_content('modpack', 'import')
        controller = downloads.content_page.controller
        controller.pack_path, controller.pack_name = 'fixture.zip', 'Fixture'
        with patch.object(downloads.tasks_page, 'start_install', return_value=False):
            controller.importPack()
        self.assertIs(downloads.stack.currentWidget(), downloads.content_page)
