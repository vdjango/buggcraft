"""Private loopback federation for the launcher's diagnostics UI acceptance.

Run as a subprocess so the node's test package and asyncio loop cannot replace
the launcher's tests or its Qt event loop. No production accounts are accessed.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys


async def main():
    native = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(native / 'compatibility'))
    sys.path.insert(0, str(native / 'compatibility/src'))
    from tests.test_web_accounts import WebAccountTests

    fixture = WebAccountTests()
    await fixture.asyncSetUp()
    try:
        user = await fixture.create_user('diagnostics-ui-reporter')
        await fixture.login_user(fixture.clients[0], user)
        profile = (await (await fixture.clients[0].post('/api/profile', json={})).json())['profile']
        print(json.dumps({'profile': profile}), flush=True)
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            if request['op'] == 'close':
                break
            try:
                issues = fixture.portals[0].feedback.snapshot()
                result = {'count': len(issues)}
                if request['op'] == 'verify':
                    issue_id = request['issue']
                    issue = fixture.portals[0].feedback.issue(issue_id)
                    attachment, = issue['attachments']
                    source = fixture.portals[0].feedback.root / issue_id / (attachment['id'] + '.bin')
                    payload = source.read_bytes()
                    url = '/api/feedback/' + issue_id + '/attachments/' + attachment['id']
                    result['anonymous_status'] = (await fixture.clients[0].get(url)).status
                    for index in range(2):
                        if index:
                            await fixture.portals[index].feedback.sync_once()
                        client = fixture.clients[index]
                        login = await client.post('/api/login', json={'username': 'admin', 'password': fixture.password})
                        if login.status != 200:
                            raise AssertionError('Fixture admin could not log in')
                        response = await client.get(url)
                        if response.status != 200 or await response.read() != payload:
                            raise AssertionError('Node attachment download differs from upload')
                    destination = Path(request['destination'])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    result.update(title=issue['title'], description=issue['description'], sha256=hashlib.sha256(payload).hexdigest(),
                                  bytes=len(payload), nodes_verified=2, attachments=len(issue['attachments']))
                print(json.dumps(result), flush=True)
            except Exception as error:
                print(json.dumps({'error': type(error).__name__ + ': ' + str(error)}), flush=True)
    finally:
        await fixture.asyncTearDown()
        fixture.doCleanups()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
    asyncio.run(main())
