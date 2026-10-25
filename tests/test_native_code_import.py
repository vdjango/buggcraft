import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/buggcraft'))
from hookup.nodes import import_code

class NativeCodeImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_bridge_redeems_and_temporary_handle_is_released(self):
        profile={'server_host':'127.0.0.1','server_port':3333,'token':'x'*48,'server_public_key':'ssh-ed25519 AAAA'}
        routes=SimpleNamespace(request=AsyncMock(side_effect=[{'node':'temporary','name':'Test'}, {'profile':profile,'backups':[]}, {'removed':True}]))
        with patch('hookup.native_routes.manager',return_value=routes):
            result=await import_code(' buggnode2-random-reference ')
        self.assertEqual(result.server_port,3333)
        self.assertEqual(routes.request.await_args_list[0].args,('node.add',{'code':'buggnode2-random-reference'}))
        self.assertEqual(routes.request.await_args.args,('node.remove',{'node':'temporary'}))

    async def test_failed_selection_still_releases_temporary_native_handle(self):
        routes=SimpleNamespace(request=AsyncMock(side_effect=[{'node':'temporary'},ConnectionError('offline'),{'removed':True}]))
        with patch('hookup.native_routes.manager',return_value=routes), self.assertRaises(ConnectionError):
            await import_code('buggnode2-reference')
        self.assertEqual(routes.request.await_args.args[0],'node.remove')

if __name__=='__main__':
    unittest.main()
