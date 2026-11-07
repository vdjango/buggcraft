"""A single hash plan routes duplicate files without probing each publisher."""
import hashlib
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'buggcraft'))
from core.client_file_source import lookup,mapped_url
from core.downloads import MinecraftDownloader


class BatchPlanCase(unittest.TestCase):
    def test_verified_repository_routes_are_not_restricted_to_mod_cdns(self):
        url='https://maven.aliyun.com/repository/public/org/example/lib/1/lib.jar'
        file=dict(path='libraries/lib.jar',size=4,hashes={'sha1':'a'*40})
        response=MagicMock()
        response.__enter__.return_value=response
        response.iter_content.return_value=[json.dumps(dict(protocol='room-content-cache-v1',files=[
            dict(sha1='a'*40,size=4,action='redirect',downloads=[url])])).encode()]
        with patch('core.client_file_source.requests.post',return_value=response):
            self.assertEqual(lookup([file],threading.Event()),{file['path']:url})
        for bad in ('http://maven.aliyun.com/file','https://127.0.0.1/file',
                    'https://user:pass@example.org/file','https://example.org/../file',
                    'https://foo.local/file','https://example.org/file?token=secret'):
            self.assertFalse(mapped_url(bad),bad)

    def test_duplicate_bytes_at_different_paths_share_one_request(self):
        digest=hashlib.sha1(b'file').hexdigest()
        url='https://edge.forgecdn.net/files/1/2/file.jar'
        files=[dict(path=path,size=4,hashes={'sha1':digest}) for path in ['mods/a.jar','mods/b.jar']]
        response=MagicMock()
        response.__enter__.return_value=response
        response.iter_content.return_value=[json.dumps(dict(protocol='room-content-cache-v1',files=[
            dict(sha1=digest,size=4,action='redirect',downloads=[url])])).encode()]
        with patch('core.client_file_source.requests.post',return_value=response) as post:
            self.assertEqual(lookup(files,threading.Event()),dict.fromkeys(['mods/a.jar','mods/b.jar'],url))
        self.assertEqual(post.call_args.kwargs['json'],{'wanted':[digest]})
        post.assert_called_once()

    def test_batch_routes_all_jobs_before_workers_start(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            downloader=MinecraftDownloader(folder)
            downloader.content_source='Buggcraft';downloader.resolve_content_sources=True
            jobs=[('https://cdn.modrinth.com/a.jar','mods/a.jar','a'*40,10),
                  ('https://cdn.modrinth.com/b.jar','mods/b.jar','b'*40,20)]
            routes={'mods/a.jar':'https://edge.forgecdn.net/files/1/2/a.jar'}
            with patch('core.client_file_source.lookup',return_value=routes) as plan,patch.object(downloader,'fetch') as fetch:
                downloader._batch(jobs,'download')
            plan.assert_called_once();self.assertEqual(fetch.call_count,2)
            self.assertEqual(downloader._content_plan,{jobs[0][0]:routes['mods/a.jar']})
