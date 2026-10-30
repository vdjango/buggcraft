"""Fail early when release workflows drift from the checked-in test contract."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / '.github/workflows/package.yml'
REGRESSION = ROOT / '.github/workflows/client-regression.yml'
workflows = {path.name: path.read_text(encoding='utf-8') for path in (PACKAGE, REGRESSION)}
errors = []

for name, body in workflows.items():
    if name == 'package.yml' and not re.search(r'^  pull_request:', body, re.MULTILINE):
        errors.append(f'{name}: missing pre-merge pull_request gate')
    if name == 'client-regression.yml' and (re.search(r'^  (?:pull_request|push):', body, re.MULTILINE)
                                            or not re.search(r'^  workflow_dispatch:', body, re.MULTILINE)):
        errors.append(f'{name}: deep tests must run only on manual dispatch')
    if 'requirements-test.txt' not in body:
        errors.append(f'{name}: missing pinned test dependencies')
    if name == 'package.yml' and 'scripts/check_ci_contract.py' not in body:
        errors.append(f'{name}: CI contract scan must trigger on its own changes')
    for module in set(re.findall(r"['\"](test_[a-z0-9_]+)['\"]", body)):
        if module == 'test_feedback_native':
            continue  # This is a native-source compatibility command.
        if not (ROOT / 'tests' / (module + '.py')).is_file():
            errors.append(f'{name}: missing tests/{module}.py')
    for relative in set(re.findall(r'tests/(test_[a-z0-9_]+\.py)', body)):
        if not (ROOT / 'tests' / relative).is_file():
            errors.append(f'{name}: missing tests/{relative}')

refs = {name: re.findall(r'^          ref: ([a-f0-9]{40})$', body, re.MULTILINE)
        for name, body in workflows.items()}
if any(len(values) != 1 for values in refs.values()) or len({value for values in refs.values() for value in values}) != 1:
    errors.append('Native source SHA must be pinned identically in both workflows')
if 'actions/cache@v4' not in workflows['package.yml'] or 'steps.native-cache.outputs.cache-hit' not in workflows['package.yml']:
    errors.append('Launcher package must reuse the pinned native runtime cache')
if ('run-id: ${{ needs.validate.outputs.main_run_id }}' not in workflows['package.yml']
        or 'github-token: ${{ github.token }}' not in workflows['package.yml']
        or 'if: "!startsWith(github.ref, \'refs/tags/v\')"' not in workflows['package.yml']):
    errors.append('Release tags must promote the validated main artifacts without rebuilding')

for name in ('requirements.txt', 'requirements-build.txt', 'requirements-test.txt'):
    for number, raw in enumerate((ROOT / name).read_text(encoding='utf-8').splitlines(), 1):
        line = raw.split('#', 1)[0].split(';', 1)[0].strip()
        if line and not re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+', line):
            errors.append(f'{name}:{number}: dependency must have an exact version')

if errors:
    raise SystemExit('CI contract errors:\n' + '\n'.join(errors))
print('CI contracts OK: required package preflight, optional deep tests, native cache and dependencies')
