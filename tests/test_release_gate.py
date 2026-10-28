import unittest

from urllib.error import HTTPError

from scripts.require_main_build import PLATFORMS, release_exists, require_success


class ReleaseGateTests(unittest.TestCase):
    def run_gate(self, runs, jobs):
        def get_json(url, token):
            self.assertEqual(token, 'test-token')
            if '/actions/runs?' in url:
                return {'workflow_runs': runs}
            return {'jobs': jobs}
        return require_success('owner/repo', 'commit-sha', 'test-token', get_json)

    def test_requires_latest_main_push_build_and_every_platform(self):
        run = {
            'id': 123, 'run_number': 47, 'run_attempt': 1,
            'path': '.github/workflows/package.yml', 'event': 'push',
            'head_branch': 'main', 'head_sha': 'commit-sha',
            'status': 'completed', 'conclusion': 'success',
        }
        jobs = [{'name': 'package (' + platform + ', runner)', 'conclusion': 'success'}
                for platform in sorted(PLATFORMS)]
        self.assertEqual(self.run_gate([run], jobs), run)

    def test_does_not_accept_a_different_commit_or_unrelated_workflow(self):
        run = {
            'id': 123, 'path': '.github/workflows/bridge.yml', 'event': 'push',
            'head_branch': 'main', 'head_sha': 'commit-sha',
            'status': 'completed', 'conclusion': 'success',
        }
        with self.assertRaisesRegex(RuntimeError, 'No Package launcher push build'):
            self.run_gate([run], [])

    def test_failed_latest_build_blocks_retagging(self):
        successful = {
            'id': 123, 'run_number': 46, 'run_attempt': 1,
            'path': '.github/workflows/package.yml', 'event': 'push',
            'head_branch': 'main', 'head_sha': 'commit-sha',
            'status': 'completed', 'conclusion': 'success',
        }
        failed = dict(successful, id=124, run_number=47, conclusion='failure')
        with self.assertRaisesRegex(RuntimeError, 'latest Package launcher build'):
            self.run_gate([successful, failed], [])

    def test_incomplete_platform_matrix_blocks_retagging(self):
        run = {
            'id': 123, 'run_number': 47, 'run_attempt': 1,
            'path': '.github/workflows/package.yml', 'event': 'push',
            'head_branch': 'main', 'head_sha': 'commit-sha',
            'status': 'completed', 'conclusion': 'success',
        }
        jobs = [{'name': 'package (' + platform + ', runner)', 'conclusion': 'success'}
                for platform in sorted(PLATFORMS - {'macos-arm64'})]
        with self.assertRaisesRegex(RuntimeError, 'incomplete: macos-arm64'):
            self.run_gate([run], jobs)

    def test_existing_github_release_blocks_retagging(self):
        def existing_release(url, token):
            return {'tag_name': 'v1.0.1-alpha.1'}
        self.assertTrue(release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', existing_release))

    def test_missing_release_allows_requested_tag(self):
        def missing_release(url, token):
            raise HTTPError(url, 404, 'Not Found', {}, None)
        self.assertFalse(release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', missing_release))

    def test_release_lookup_auth_failure_does_not_look_like_missing_release(self):
        def denied(url, token):
            raise HTTPError(url, 403, 'Forbidden', {}, None)
        with self.assertRaises(HTTPError):
            release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', denied)


if __name__ == '__main__':
    unittest.main()
