import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

spec=importlib.util.spec_from_file_location('sync_platform_release',Path(__file__).resolve().parents[1]/'scripts/sync_platform_release.py')
sync=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class ReleasePlatformSyncTests(unittest.TestCase):
    def run_sync(self,responses):
        requests=[]
        def open_request(request,**kwargs):
            requests.append(request)
            response=next(responses)
            if isinstance(response,Exception):raise response
            return contextlib.closing(io.BytesIO(json.dumps(response).encode()))
        env={'RELEASE_TAG':'v1.2.3','GH_TOKEN':'temporary-job-token',
             'ACTIONS_ID_TOKEN_REQUEST_URL':'https://actions.example/identity?existing=1',
             'ACTIONS_ID_TOKEN_REQUEST_TOKEN':'identity-request-token'}
        output=io.StringIO()
        with patch.dict(sync.os.environ,env),patch.object(sync,'urlopen',side_effect=open_request),patch.object(sync.time,'sleep'),contextlib.redirect_stdout(output):
            sync.main()
        return requests,output.getvalue()

    def test_success_waits_for_own_tag_and_sends_job_token_only_on_import(self):
        requests,_=self.run_sync(iter([
            {'value':'signed-identity'},{'sync':{'status':'running'}},
            {'sync':{'status':'success','items':[{'tag':'v1.2.2','result':'imported'}]}},
            {'sync':{'status':'success','items':[{'tag':'v1.2.3','result':'imported'}]}},
        ]))
        self.assertEqual(len(requests),4)
        self.assertIn('audience=https%3A%2F%2Fdownload.bugg.icu',requests[0].full_url)
        self.assertEqual(json.loads(requests[1].data)['github_token'],'temporary-job-token')
        self.assertNotIn('github_token',json.loads(requests[-1].data))
        self.assertEqual(requests[-1].get_header('Authorization'),'Bearer signed-identity')

    def test_connection_retry_refreshes_identity_without_printing_secrets(self):
        _,output=self.run_sync(iter([
            {'value':'signed-identity'},URLError('temporary-job-token'),
            {'value':'replacement-identity'},{'sync':{'status':'running'}},
            {'sync':{'status':'success','items':[{'tag':'v1.2.3','result':'existing'}]}},
        ]))
        self.assertNotIn('temporary-job-token',output)
        self.assertNotIn('signed-identity',output)
        self.assertIn('retrying',output)

    def test_http_errors_report_status_without_exposing_url_or_credentials(self):
        error=HTTPError('https://platform.example/secret-token',403,'Forbidden',{},None)
        requests,output=self.run_sync(iter([
            {'value':'signed-identity'},error,
            {'value':'replacement-identity'},{'sync':{'status':'running'}},
            {'sync':{'status':'success','items':[{'tag':'v1.2.3','result':'imported'}]}},
        ]))
        self.assertIn('HTTP 403',output)
        self.assertNotIn('secret-token',output)
        self.assertNotIn('temporary-job-token',output)
        self.assertEqual(requests[2].get_header('Authorization'),'Bearer identity-request-token')

    def test_platform_failure_message_exposes_github_status_for_diagnosis(self):
        _,output=self.run_sync(iter([{'value':'identity'},
            {'sync':{'status':'running'}},
            {'sync':{'status':'failed','message':'GitHub 返回 403'}},
            {'sync':{'status':'running'}},
            {'sync':{'status':'success','items':[{'tag':'v1.2.3','result':'existing'}]}},
        ]))
        self.assertIn('GitHub 返回 403',output)

    def test_failed_import_does_not_report_success(self):
        with self.assertRaisesRegex(SystemExit,'did not confirm'):
            self.run_sync(iter([{'value':'identity'}]+[
                item for _ in range(3) for item in ({'sync':{'status':'running'}},{'sync':{'status':'failed'}})
            ]))


if __name__=='__main__':unittest.main()
