"""Require the latest successful five-platform launcher build for this commit."""
import json
import os
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PLATFORMS = {
    'windows-x64', 'linux-x86_64', 'linux-arm64', 'macos-x86_64', 'macos-arm64',
}


def _get_json(url, token):
    request = Request(url, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def require_success(repository, sha, token, get_json=_get_json):
    base = 'https://api.github.com/repos/' + repository
    query = urlencode({'per_page': 100})
    runs = get_json(base + '/actions/runs?' + query, token).get('workflow_runs', [])
    matching = [run for run in runs if run.get('path') == '.github/workflows/package.yml'
                and run.get('event') == 'push' and run.get('head_branch') == 'main'
                and run.get('head_sha') == sha]
    if not matching:
        raise RuntimeError('No Package launcher push build exists for this main commit')
    run = max(matching, key=lambda item: (item.get('run_number', 0), item.get('run_attempt', 0)))
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        raise RuntimeError('The latest Package launcher build for this commit did not succeed')
    jobs = get_json(base + f"/actions/runs/{run['id']}/jobs?per_page=100", token).get('jobs', [])
    package_jobs = [job for job in jobs if job.get('name', '').startswith('package (')]
    # Matrix job names vary with runner and Python version; match each target
    # by its stable platform identifier within the full job name.
    actual = {platform for platform in PLATFORMS
              if any(platform in job.get('name', '') for job in package_jobs)}
    if actual != PLATFORMS or any(job.get('conclusion') != 'success' for job in package_jobs):
        missing = ', '.join(sorted(PLATFORMS - actual)) or 'a failed platform'
        raise RuntimeError('Five-platform launcher build is incomplete: ' + missing)
    return run


def release_exists(repository, tag, token, get_json=_get_json):
    url = 'https://api.github.com/repos/' + repository + '/releases/tags/' + quote(tag, safe='')
    try:
        get_json(url, token)
    except HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    sha = os.environ['GITHUB_SHA']
    token = os.environ['GH_TOKEN']
    run = require_success(repository, sha, token)
    print(f"Verified Package launcher run #{run['run_number']} for {sha}; all five platforms passed.")


if __name__ == '__main__':
    try:
        main()
    except (KeyError, RuntimeError, HTTPError, URLError, OSError, ValueError) as error:
        raise SystemExit(str(error))
