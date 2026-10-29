"""UI error text must remain readable even for stored failures from old builds."""
import json
from pathlib import Path
import sys
import unittest

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.downloads import download_error_message


class DownloadErrorPresentationTests(unittest.TestCase):
    def test_wrapped_timeout_keeps_filename_and_recovery_action(self):
        error = RuntimeError("下载 asm-util-9.10.1.jar 失败：HTTPSConnectionPool(host='mirror.invalid', port=443): "
                             'Max retries exceeded (Caused by ReadTimeoutError(read timeout=20))')
        text = download_error_message(error)
        self.assertIn('asm-util-9.10.1.jar', text)
        self.assertIn('超时', text)
        self.assertIn('重试', text)
        self.assertIn('进度会保留', text)
        for raw in ('ConnectionPool', 'mirror.invalid', 'ReadTimeoutError', 'port='):
            self.assertNotIn(raw, text)

    def test_json_payloads_and_wrapped_parser_errors_do_not_leak(self):
        errors = [json.JSONDecodeError('Expecting value', '', 0),
                  RuntimeError('整合包下载失败：Expecting value: line 1 column 1 (char 0)'),
                  '{"code": "FAILED", "message": "upstream failure"}',
                  "下载失败：{'httpCode': 403, 'message': 'token expired'}",
                  '[{"error": "unavailable"}]']
        for error in errors:
            with self.subTest(error=str(error)):
                text = download_error_message(error)
                self.assertIn('重试', text)
                for raw in ('{', 'Expecting value', 'httpCode', 'upstream failure'):
                    self.assertNotIn(raw, text)

    def test_network_status_and_friendly_local_errors_remain_actionable(self):
        for error in (requests.HTTPError('404 Client Error for url: https://mirror.invalid/a.jar'),
                      requests.ConnectionError('HTTPSConnectionPool(host=mirror.invalid)')):
            text = download_error_message(error)
            self.assertIn('下载源', text)
            self.assertIn('重试', text)
            self.assertNotIn('mirror.invalid', text)
        for text in ('没有写入权限，请选择其他目录。', '安装已取消', '正在下载 client.json',
                     '[1/5] 正在解析 Buggcraft 文件清单…', '[3/5] 正在并行安装 Minecraft 和加载器…', ''):
            self.assertEqual(download_error_message(text), text)
