"""Run against the real sibling source service in a temporary HTTP fixture.

PYTHONPATH must include bugg-source/src and bugg-source/tests/platform.
The launcher does not depend on this Python test or the source implementation.
"""
import unittest

from test_room_cache import RoomCacheCase


class RenamedCacheCase(RoomCacheCase):
    async def test_renamed_content_reuses_one_cloud_identity(self):
        first = await self.plan()
        self.assertEqual(len(first["upload"]), 1)
        self.assertEqual((await self.upload()).status, 200)
        renamed = dict(self.file, path="mods/my-renamed-file.jar")
        same_room = await self.plan([renamed])
        self.assertEqual(same_room["upload"], [])
        self.assertEqual(same_room["files"][0]["action"], "cached")
        # Another host/room and another display name still address the same
        # verified object; an active lease keeps those bytes available.
        another = dict(self.file, path="mods/another-name.jar")
        other_room = await self.plan([another], room="b" * 32)
        self.assertEqual(other_room["upload"], [])
        self.assertEqual(other_room["files"][0]["sha256"], self.file["sha256"])
        self.assertEqual(other_room["files"][0]["action"], "cached")
        response = await self.client.get(self.url())
        self.assertEqual(await response.read(), self.payload)
        count = await self.cache.one("SELECT count(*) AS n FROM objects")
        self.assertEqual(count["n"], 1)


if __name__ == "__main__":
    unittest.main(defaultTest="RenamedCacheCase.test_renamed_content_reuses_one_cloud_identity")
