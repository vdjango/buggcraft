"""Create or retarget only the explicitly requested launcher release tag."""
import os
import re
import subprocess

from require_main_build import release_exists, require_success


VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?\Z')


def main():
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise SystemExit('Release tags can only be created from main')
    version = os.environ.get('RELEASE_VERSION', '')
    if not VERSION.fullmatch(version):
        raise SystemExit('Enter an explicit semantic version such as 1.0.1-alpha.1')
    if not os.path.isfile(f'docs/releases/{version}.md'):
        raise SystemExit('Release notes are missing for the requested version')

    repository = os.environ['GITHUB_REPOSITORY']
    sha = os.environ['GITHUB_SHA']
    token = os.environ['GH_TOKEN']
    run = require_success(repository, sha, token)
    tag = 'v' + version
    print(f"Main build #{run['run_number']} passed; preparing {tag} at {sha}.", flush=True)

    # A release draft already has immutable platform assets; retry its Actions
    # job instead of moving a tag away from published build metadata.
    if release_exists(repository, tag, token):
        raise SystemExit(f'{tag} already has a GitHub release; rerun its failed workflow job')

    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True)
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
    subprocess.run(['git', 'tag', '--force', '--annotate', tag, sha,
                    '--message', f'Buggcraft {version}'], check=True)
    subprocess.run(['git', 'push', '--force', 'origin', f'refs/tags/{tag}'], check=True)
    subprocess.run(['gh', 'workflow', 'run', 'package.yml', '--ref', tag], check=True)
    print(f'Pushed {tag} and dispatched the launcher build for validated main commit {sha}.')


if __name__ == '__main__':
    main()
