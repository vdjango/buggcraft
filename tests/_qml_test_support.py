"""Isolated launcher fixture: no user config, games, or external requests."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))

from PySide6.QtCore import QObject, QPoint, Qt, QUrl, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickWidgets import QQuickWidget
import shiboken6
import config.settings as settings
from windows.main_window import MinecraftLauncher


class LauncherQmlCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='buggcraft-qml-test-')
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.game_dir = self.directory / 'games'
        for name in ('1.20.1', '1.21.8', '长名称测试-' + 'instance-' * 6):
            target = self.game_dir / 'versions' / name / (name + '.json')
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(dict(id=name, type='release', releaseTime='2026-01-01')), encoding='utf-8')
        self.manager = settings.SettingsManager(self.directory / 'config')
        self.manager.set_setting('onboarding.completed', True)
        self.manager.set_setting('minecraft.directory.enable', str(self.game_dir))
        self.manager.set_setting('minecraft.directory.installed', [str(self.game_dir)])
        self.manager.set_setting('minecraft.version.enable', '1.21.8')
        self.manager.set_setting('java.path', sys.executable)
        self.manager.set_setting('java.installations', [[sys.executable, 'Java fixture 21', [21, 0, 0]]])
        self.patches = [
            patch.object(settings, '_settings_manager_instance', self.manager),
            patch.object(settings, 'get_conf_or_cache_manager', return_value=('isolated-test', str(self.directory / 'config'))),
            patch.object(MinecraftLauncher, 'minecraft_not_java_runtime'),
            patch('ui.pages.qml_start.StartGamePage._start_background_social'),
            patch('ui.pages.qml_games.GameCatalogueController.refresh'),
            patch('core.content.ContentCatalogue.search', return_value=[dict(project_id='fixture', title='示例项目', description='资源简介', source='Modrinth')]),
            patch('core.content.ContentCatalogue.versions', return_value=[dict(name='示例版本', files=[], source='Modrinth')]),
            patch('core.content.ContentCatalogue.project', return_value=dict(description='资源简介', body='项目介绍', game_versions=['1.20.1', '1.21.8'])),
            patch('core.loaders.available_versions', return_value=['47.4.0']),
            patch('ui.pages.qml_lists.catalogue', return_value=[]),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.messages = []
        self.previous_handler = qInstallMessageHandler(lambda kind, context, message: self.messages.append(message))
        self.window = MinecraftLauncher(str(ROOT), str(self.directory / 'cache'), str(self.directory / 'config'), str(ROOT / 'resources'))
        self.window.show()
        self.pump()

    def tearDown(self):
        # All expected requests in this fixture are local stubs.
        self.window.download_page.content_page.controller.pool.waitForDone(2000)
        self.window.download_page.games_page.controller.pool.waitForDone(2000)
        self.window.close()
        # Destroy each QQuickWidget while its QWidget parent still exists.
        # Qt's Windows software renderer can hang when their QObject parent
        # destroys several live scene graphs at once.
        self.pump()
        for quick in self.window.findChildren(QQuickWidget):
            if shiboken6.isValid(quick):
                quick.setSource(QUrl())
                shiboken6.delete(quick)
        self.window.deleteLater()
        self.pump()
        qInstallMessageHandler(self.previous_handler)

    def pump(self, milliseconds=30):
        QTest.qWait(milliseconds)
        self.app.processEvents()

    def wait_until(self, condition):
        for _ in range(200):
            if condition():
                return
            self.pump(10)
        self.fail('Timed out waiting for the isolated UI worker')

    def item(self, page, name):
        root = page.quick.rootObject()
        self.assertIsNotNone(root, str(page.quick.errors()))
        def find(item):
            if item.objectName() == name:
                return item
            for child in item.childItems():
                match = find(child)
                if match is not None:
                    return match
            return None
        found = find(root)
        if found is None and root.window() is not None:
            found = find(root.window().contentItem())
        self.assertIsNotNone(found, name)
        return found

    def click(self, page, name):
        item = self.item(page, name)
        self.assertTrue(item.isVisible(), name)
        point = item.mapToScene(item.boundingRect().center()).toPoint()
        QTest.mouseClick(page.quick, Qt.LeftButton, Qt.NoModifier, point)
        self.pump()

    def assert_no_qml_errors(self):
        errors = [message for message in self.messages if any(token in message for token in (
            'ReferenceError', 'TypeError', 'Cannot assign', 'Unable to assign', 'Binding loop',
            'is not a type', 'unavailable', 'Unexpected token', 'read-only property',
            'Cannot load', 'failed to load', 'Failed to create', 'not supported for this style'))]
        self.assertEqual(errors, [])

    def snapshot(self, name, widget=None):
        self.pump()
        folder = os.environ.get('BUGGCRAFT_QML_SNAPSHOTS')
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            (widget or self.window).grab().save(str(target / (name + '.png')))
