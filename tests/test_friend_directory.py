"""An untrusted node must not bind a lookup to an unrelated or malformed identity."""
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from hookup.rooms import lookup_account


class FriendDirectoryTests(unittest.IsolatedAsyncioTestCase):
    async def query(self, result, identifier='Alice'):
        connection = AsyncMock()
        connection.__aenter__.return_value = connection
        with patch('hookup.rooms.connect_directory', AsyncMock(return_value=connection)), \
                patch('hookup.rooms.request', AsyncMock(return_value=result)):
            return await lookup_account(object(), identifier)

    async def test_accepts_exact_case_insensitive_name_or_full_id(self):
        account = 'a' * 32 + '.' + 'b' * 32
        result = {'accounts': [{'account': account, 'username': 'Alice'}]}
        self.assertEqual(await self.query(result, ' ALICE '), result['accounts'])
        self.assertEqual(await self.query(result, account), result['accounts'])
        self.assertEqual(await self.query({'accounts': []}), [])

    async def test_rejects_unrelated_identity_duplicate_and_unbounded_response(self):
        account = 'a' * 32 + '.' + 'b' * 32
        valid = {'account': account, 'username': 'Alice'}
        for accounts in (None, {}, [None], [{'account': account, 'username': 'Bob'}],
                         [{'account': 'invalid', 'username': 'Alice'}],
                         [{'account': account, 'username': '<script>'}],
                         [valid, valid], [valid] * 9):
            with self.subTest(accounts=accounts), self.assertRaises(ValueError):
                await self.query({'accounts': accounts})


if __name__ == '__main__':
    unittest.main()
