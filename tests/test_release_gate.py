import os
import unittest
from unittest.mock import patch

from urllib.error import HTTPError

from scripts.require_main_build import PLATFORMS, release_exists, require_success
from scripts import release_launcher_tag


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
        jobs.append({'name': 'validate', 'conclusion': 'success'})
        self.assertEqual(self.run_gate([run], jobs), run)

    def test_preflight_must_pass_on_the_same_main_commit(self):
        run = dict(id=123, run_number=47, run_attempt=1,
                   path='.github/workflows/package.yml', event='push',
                   head_branch='main', head_sha='commit-sha', status='completed', conclusion='success')
        jobs = [{'name': 'package (' + platform + ', runner)', 'conclusion': 'success'}
                for platform in sorted(PLATFORMS)]
        for validation in ([], [{'name': 'validate', 'conclusion': 'failure'}],
                           [{'name': 'validate', 'conclusion': 'skipped'}],
                           [{'name': 'validate', 'conclusion': 'success'}] * 2):
            with self.subTest(validation=validation), self.assertRaisesRegex(RuntimeError, 'preflight validation'):
                self.run_gate([run], jobs + validation)

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
        jobs.append({'name': 'validate', 'conclusion': 'success'})
        with self.assertRaisesRegex(RuntimeError, 'incomplete: macos-arm64'):
            self.run_gate([run], jobs)

    def test_existing_github_release_blocks_retagging(self):
        def existing_release(url, token):
            return {'tag_name': 'v1.0.1-alpha.1'}
        self.assertTrue(release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', existing_release))

    def test_missing_release_allows_requested_tag(self):
        def missing_release(url, token):
            if '/releases/tags/' in url:
                raise HTTPError(url, 404, 'Not Found', {}, None)
            return []
        self.assertFalse(release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', missing_release))

    def test_hidden_draft_release_still_blocks_retagging(self):
        def hidden_draft(url, token):
            if '/releases/tags/' in url:
                raise HTTPError(url, 404, 'Not Found', {}, None)
            return [{'tag_name': 'v1.0.1-alpha.1', 'draft': True}]
        self.assertTrue(release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', hidden_draft))

    def test_release_lookup_auth_failure_does_not_look_like_missing_release(self):
        def denied(url, token):
            raise HTTPError(url, 403, 'Forbidden', {}, None)
        with self.assertRaises(HTTPError):
            release_exists('owner/repo', 'v1.0.1-alpha.1', 'test-token', denied)

    def test_tag_workflow_uses_explicit_version_lease_and_dispatches_launcher(self):
        environment = dict(GITHUB_REF='refs/heads/main', RELEASE_VERSION='1.0.1-alpha.1',
                           GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='commit-sha', GH_TOKEN='test-token',
                           GITHUB_STEP_SUMMARY='')
        with patch.dict(os.environ, environment), \
                patch.object(release_launcher_tag.os.path, 'isfile', return_value=True), \
                patch.object(release_launcher_tag, 'require_success', return_value={'run_number': 47}), \
                patch.object(release_launcher_tag, 'release_exists', return_value=False), \
                patch.object(release_launcher_tag.subprocess, 'check_output',
                             side_effect=['commit-sha\trefs/heads/main\n', 'old-tag-sha\trefs/tags/v1.0.1-alpha.1\n']), \
                patch.object(release_launcher_tag.subprocess, 'run') as run:
            release_launcher_tag.main()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(['git', 'tag', '--force', '--annotate', 'v1.0.1-alpha.1', 'commit-sha',
                       '--message', 'Buggcraft 1.0.1-alpha.1'], commands)
        self.assertIn(['git', 'push', '--force-with-lease=refs/tags/v1.0.1-alpha.1:old-tag-sha',
                       'origin', 'refs/tags/v1.0.1-alpha.1'], commands)
        self.assertEqual(commands[-1], ['gh', 'workflow', 'run', 'package.yml', '--ref', 'v1.0.1-alpha.1'])

    def test_tag_workflow_does_not_tag_unvalidated_or_published_code(self):
        environment = dict(GITHUB_REF='refs/heads/main', RELEASE_VERSION='1.0.1-alpha.1',
                           GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='commit-sha', GH_TOKEN='test-token',
                           GITHUB_STEP_SUMMARY='')
        with patch.dict(os.environ, environment), \
                patch.object(release_launcher_tag.os.path, 'isfile', return_value=True), \
                patch.object(release_launcher_tag.subprocess, 'check_output',
                             return_value='commit-sha\trefs/heads/main\n'), \
                patch.object(release_launcher_tag.subprocess, 'run') as run:
            with patch.object(release_launcher_tag, 'require_success', side_effect=RuntimeError('main failed')):
                with self.assertRaisesRegex(RuntimeError, 'main failed'):
                    release_launcher_tag.main()
            run.assert_not_called()
            with patch.object(release_launcher_tag, 'require_success', return_value={'run_number': 47}), \
                    patch.object(release_launcher_tag, 'release_exists', return_value=True):
                with self.assertRaisesRegex(SystemExit, 'already has a GitHub release'):
                    release_launcher_tag.main()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
