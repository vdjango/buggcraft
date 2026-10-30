"""Keep reported regressions runnable from the standard test and CI entries."""
import ast
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RegressionWiringTests(unittest.TestCase):
    def test_documented_launcher_cases_resolve_to_real_test_methods(self):
        document = (ROOT / 'docs/technical/已报告问题回归-20261029.md').read_text(encoding='utf-8')
        references = re.findall(r'`(test_\w+\.py(?:::\w+)*)`', document)
        self.assertTrue(references, 'The regression document must identify runnable cases')
        for reference in references:
            with self.subTest(reference=reference):
                filename, *names = reference.split('::')
                file = ROOT / 'tests' / filename
                # Native cases belong to the separately pinned node repository.
                if not file.exists():
                    self.assertIn(filename, {
                        'test_resource_metadata.py', 'test_peer_heartbeat.py', 'test_peer_reconnect.py',
                        'test_peer_signaling_attempt.py', 'test_peer_stun_fallback.py',
                        'test_ipv4_p2p.py', 'test_route_selection.py', 'test_room_lobby.py',
                    })
                    native = os.environ.get('BUGGCRAFT_NATIVE_SOURCE')
                    if not native:
                        continue
                    file = Path(native) / 'tests' / filename
                    self.assertTrue(file.is_file(), reference + ' is missing from the native checkout')
                tree = ast.parse(file.read_text(encoding='utf-8-sig'))
                body = tree.body
                for name in names:
                    node = next((item for item in body if isinstance(item, (
                        ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name), None)
                    self.assertIsNotNone(node, reference + ' is no longer discoverable')
                    body = node.body

    def test_ci_uses_one_pinned_native_revision_and_keeps_reported_regressions(self):
        workflows = ROOT / '.github/workflows'
        pins = []
        for name in ('package.yml', 'bridge.yml', 'client-regression.yml'):
            contents = (workflows / name).read_text(encoding='utf-8')
            match = re.search(r'repository: vdjango/minecraft-tunnel-native\s+ref: ([0-9a-f]{40})\b', contents)
            self.assertIsNotNone(match, name + ' must pin the tested native commit')
            pins.append(match.group(1))
        self.assertEqual(len(set(pins)), 1, 'Packaging and regression must test the same native code')
        regression = (workflows / 'client-regression.yml').read_text(encoding='utf-8')
        for module in ('test_native_cutover', 'test_native_routes', 'test_native_bridge_runtime', 'test_diagnostics_ui',
                       'test_room_lobby_live_ui', 'test_download_transport', 'test_download_locks',
                       'test_instance_modpack_entry', 'test_modpack_drop', 'test_download_ui',
                       'test_friend_entry_ui',
                       'test_java_downloads', 'test_update_client', 'test_room_launch_flow',
                       'test_peer_heartbeat', 'test_peer_reconnect', 'test_peer_signaling_attempt',
                       'test_peer_stun_fallback', 'test_room_lobby', 'test_feedback_native'):
            with self.subTest(module=module):
                self.assertRegex(regression, r'\b' + module + r'\b')
        self.assertIn('BUGGCRAFT_BRIDGE_PACKAGE=package', regression)
        self.assertIn('actions/upload-artifact@v4', regression)
        package = (workflows / 'package.yml').read_text(encoding='utf-8')
        self.assertIn("'scripts/require_main_build.py'", package)
        release_gate = (ROOT / 'scripts/require_main_build.py').read_text(encoding='utf-8')
        self.assertIn(".github/workflows/client-regression.yml", release_gate)
        self.assertIn("regression (windows-latest)", release_gate)
        self.assertIn("regression (ubuntu-24.04)", release_gate)

    def test_release_packaging_and_regression_have_matching_push_path_filters(self):
        paths = []
        for name in ('package.yml', 'client-regression.yml'):
            contents = (ROOT / '.github/workflows' / name).read_text(encoding='utf-8')
            push = contents.split('  push:\n', 1)[1].split('  workflow_dispatch:', 1)[0]
            push = push.split('  pull_request:', 1)[0].split('    paths:', 1)[1]
            paths.append(set(re.findall(r"^      - '([^']+)'", push, re.M)))
        self.assertTrue(paths[0])
        self.assertEqual(paths[0], paths[1], 'Every main packaging commit must also trigger regression')


if __name__ == '__main__':
    unittest.main()
