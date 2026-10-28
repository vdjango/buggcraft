"""Operate the live log console with mouse and keyboard, and verify its output."""
from unittest.mock import patch

from _qml_test_support import LauncherQmlCase, QTest, Qt
from ui.dialog.game_log import GameLogModel, highlight, parse_line


LINES = [
    '[12:01:00] [main/INFO] [minecraft/Main]: Starting Minecraft 1.21.8',
    '[12:01:01] [main/WARN] [examplemod/]: Missing examplemod:block at "config/test.toml"',
    '[12:01:02] [main/ERROR] [examplemod/]: java.lang.IllegalStateException: broken',
    '    at examplemod.Client.start(Client.java:42)',
    '[12:01:03] [main/DEBUG] [net.minecraft/]: connecting https://example.org:443',
]


class GameLogUiTests(LauncherQmlCase):
    def open_console(self):
        self.window._debug_output = list(LINES)
        self.window._show_debug_output()
        self.pump(150)
        return self.window._debug_dialog

    def choose(self, dialog, name, index):
        self.click(dialog.host, name)
        QTest.keyClick(dialog.quick, Qt.Key_Home)
        for _ in range(index):
            QTest.keyClick(dialog.quick, Qt.Key_Down)
        QTest.keyClick(dialog.quick, Qt.Key_Return)
        self.pump()

    def test_search_level_category_logger_pause_copy_and_export(self):
        dialog = self.open_console()
        self.assertEqual(dialog.logs.rowCount(), 5)
        self.assertEqual(dialog.logs.entries[3]['logger'], 'examplemod')
        self.assertEqual(dialog.logs.entries[3]['level'], 'ERROR')
        self.click(dialog.host, 'debug-search')
        QTest.keyClicks(dialog.quick, 'broken')
        self.pump()
        self.assertEqual(dialog.logs.rowCount(), 1)
        self.assertIn('color=', dialog.logs.data(dialog.logs.index(0), Qt.UserRole + 2))
        QTest.keyClick(dialog.quick, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClick(dialog.quick, Qt.Key_Backspace)
        self.choose(dialog, 'debug-level', 1)
        self.assertEqual(dialog.logs.rowCount(), 3)
        self.choose(dialog, 'debug-category', 1)
        self.assertEqual(dialog.logs.rowCount(), 3)
        self.choose(dialog, 'debug-logger', dialog.logs.view['loggers'].index('examplemod'))
        self.assertEqual(dialog.logs.rowCount(), 3)
        self.click(dialog.host, 'debug-pause')
        dialog.appendPlainText('[12:02:00] [main/ERROR] [examplemod/]: next failure')
        self.pump(150)
        self.assertEqual(dialog.logs.rowCount(), 3)
        self.assertEqual(dialog.logs.view['total'], 6)
        self.click(dialog.host, 'debug-pause')
        self.assertEqual(dialog.logs.rowCount(), 4)
        self.click(dialog.host, 'debug-follow')
        self.assertFalse(dialog.logs.follow)
        with patch('ui.dialog.game_log.copy_text') as copier:
            self.click(dialog.host, 'debug-copy')
        self.assertIn('next failure', copier.call_args.args[1])
        self.assertNotIn('Starting Minecraft', copier.call_args.args[1])
        target = self.directory / 'filtered.log'
        with patch('ui.dialog.game_log.QFileDialog.getSaveFileName', return_value=(str(target), '')):
            self.click(dialog.host, 'debug-export')
        self.assertEqual(target.read_text(encoding='utf-8').rstrip(), dialog.logs.filtered_text())
        self.snapshot('game-log-filtered', dialog)
        self.click(dialog.host, 'dialog-action-0')
        self.assertFalse(dialog.isVisible())
        self.assert_no_qml_errors()

    def test_regex_error_is_visible_and_recovers_without_dropping_buffer(self):
        dialog = self.open_console()
        self.click(dialog.host, 'debug-regex')
        self.click(dialog.host, 'debug-search')
        QTest.keyClicks(dialog.quick, '[')
        self.pump()
        self.assertIn('正则', dialog.logs.view['error'])
        self.assertEqual(dialog.logs.rowCount(), 0)
        QTest.keyClick(dialog.quick, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(dialog.quick, 'broken|Missing')
        self.pump()
        self.assertFalse(dialog.logs.view['error'])
        self.assertEqual(dialog.logs.rowCount(), 2)
        self.assertEqual(dialog.logs.view['total'], 5)
        self.assert_no_qml_errors()

    def test_bounded_model_escapes_markup_and_classifies_stacktraces(self):
        model = GameLogModel(self.window)
        model.append(['[main/INFO] <img src="file:///secret">'] * 5010)
        self.assertEqual(model.rowCount(), 5000)
        self.assertEqual(model.visible_rows[0]['number'], 11)
        rendered = highlight('<b>java.lang.RuntimeException</b> examplemod:block 42')
        self.assertIn('&lt;b&gt;', rendered)
        self.assertNotIn('<b>', rendered)
        self.assertIn('#ff8f9c', rendered)
        first = parse_line(LINES[2])
        self.assertEqual(parse_line(LINES[3], first)['category'], '模组')
        prefix = '[游戏 2 · roundtrip-standard] '
        first = parse_line(prefix + LINES[2])
        frame = parse_line(prefix + LINES[3], first)
        self.assertEqual((frame['level'], frame['category'], frame['logger']),
                         ('ERROR', '模组', 'examplemod'))
        self.assertTrue(frame['text'].startswith(prefix))
        render_mod = parse_line('[12:03:00] [Render thread/WARN] [examplemod/]: network connection failed')
        self.assertEqual((render_mod['category'], render_mod['logger']), ('模组', 'examplemod'))
