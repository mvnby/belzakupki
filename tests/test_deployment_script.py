"""Exercise remote deployment failure paths with an isolated Docker simulator."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('weak_secret', [True, False])
def test_deployment_preflight_and_build_failure_restore(tmp_path, weak_secret):
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.env').write_text('')
    sha = 'a' * 40
    (project / 'releases' / sha).mkdir(parents=True)
    archive = tmp_path / 'release.tar'
    archive.touch()
    lock = tmp_path / 'lock'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    trace = tmp_path / 'calls.jsonl'
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'scheduler-id': True, 'worker-id': True, 'telegram-id': True}))
    docker = bin_dir / 'docker'
    docker.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['TRACE'], 'a') as out: out.write(json.dumps(args) + '\\n')
state_file = Path(os.environ['STATE'])
state = json.loads(state_file.read_text())
if args[0] == 'compose':
    if 'config' in args and '--format' in args:
        print(json.dumps({'services': {'api': {'environment': {'API_SECRET_KEY': os.environ['TEST_SECRET']}}}}))
    if 'build' in args: sys.exit(3)
elif args[0] == 'ps':
    for arg in args:
        if arg.startswith('label=com.docker.compose.service='): print(arg.split('=')[-1] + '-id')
elif args[0] == 'kill':
    assert args[1:3] == ['--signal', 'TERM']
    state[args[-1]] = False
elif args[0] == 'inspect':
    if '-f' in args: print(str(state[args[-1]]).lower())
elif args[0] == 'start': state[args[-1]] = True
else: raise AssertionError(args)
state_file.write_text(json.dumps(state))
''')
    docker.chmod(0o755)
    for name, content in [('stat', 'echo 0:600'), ('flock', 'exit 0')]:
        executable = bin_dir / name
        executable.write_text('#!/bin/sh\n' + content + '\n')
        executable.chmod(0o755)
    remote = (ROOT / 'deploy.sh').read_text().split("<<'REMOTE'\n", 1)[1].rsplit('\nREMOTE', 1)[0]
    remote = remote.replace('project_dir=/opt/belzakupki', f'project_dir={project}')
    remote = remote.replace('lock=/var/lock/mvn-shared-host-belzakupki.lock', f'lock={lock}')
    result = subprocess.run(['bash', '-s', '--', sha, str(archive)], input=remote, text=True, capture_output=True,
        env={**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'], 'TRACE': str(trace), 'STATE': str(state), 'TEST_SECRET': 'short' if weak_secret else 'x' * 40})
    assert result.returncode != 0
    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    assert all('stop' not in call and 'prune' not in call for call in calls)
    if weak_secret:
        assert 'API_SECRET_KEY' in result.stderr
        assert not any(call[0] in ('kill', 'start') or 'build' in call for call in calls)
    else:
        assert 'recovery record retained' in result.stderr
        assert sum(call[0] == 'kill' for call in calls) == 3
        assert sum(call[0] == 'start' for call in calls) == 3
        assert all(json.loads(state.read_text()).values())
        assert len(list(project.glob('deploy-recovery.*'))) == 1
