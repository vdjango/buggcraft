"""Ask the platform to pull this tagged build using short-lived Actions identity."""
import json
import os
import time
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = 'https://download.bugg.icu/api/launcher/github-sync'


def main():
    tag = os.environ['RELEASE_TAG']
    github_token = os.environ['GH_TOKEN']
    identity = ''
    identity_until = 0

    def invoke(action):
        nonlocal identity, identity_until
        if time.time() >= identity_until:
            url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']
            url += ('&' if '?' in url else '?') + urlencode({'audience': ENDPOINT})
            request = Request(url, headers={'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
            with urlopen(request, timeout=30) as response:
                identity = json.load(response)['value']
            identity_until = time.time() + 120
        payload = {'tag': tag, 'action': action}
        if action == 'sync':
            payload['github_token'] = github_token
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers={
            'Authorization': 'Bearer ' + identity, 'Content-Type': 'application/json',
            'User-Agent': 'Buggcraft-Actions-Release-Sync'})
        with urlopen(request, timeout=40) as response:
            return json.load(response)['sync']

    # Keep this job alive until the platform has downloaded the assets: GITHUB_TOKEN
    # expires when the job finishes. Neither token is saved on the platform.
    for attempt in range(3):
        try:
            invoke('sync')
            for _ in range(120):
                time.sleep(8)
                state = invoke('status')
                completed = any(item.get('tag') == tag and item.get('result') in ('imported', 'existing')
                                for item in state.get('items', []))
                if state.get('status') == 'success' and completed:
                    print(f'{tag}: 平台已缓存，按后台审核设置处理。')
                    return
                if state.get('status') in ('failed', 'interrupted'):
                    message = state.get('message', '')
                    if isinstance(message, str) and message.startswith('GitHub 返回 ') and message[10:].isdigit():
                        print(f'Platform sync attempt {attempt + 1} failed: {message}; retrying.')
                    else:
                        print(f'Platform sync attempt {attempt + 1} failed; retrying.')
                    break
        except HTTPError as error:
            # HTTPError is a URLError subclass. Include only its numeric status,
            # never its URL, headers or response body, which can contain secrets.
            print(f'Platform returned HTTP {error.code}; retrying.')
            if error.code in (401, 403):
                identity_until = 0
        except (URLError, OSError, ValueError, KeyError):
            # Do not print request URLs, headers or credentials in build logs.
            print(f'Platform connection attempt {attempt + 1} failed; retrying.')
            identity_until = 0
            time.sleep(8)
    raise SystemExit('Platform did not confirm release import. Re-run the release job to retry.')


if __name__ == '__main__':
    main()
