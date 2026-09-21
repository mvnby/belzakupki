"""Exercise remote deployment failure paths with an isolated Docker simulator."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(('weak_secret', 'redis_mode'), [(True, 'ready'), (False, 'ready'), (False, 'mismatch'), (False, 'disabled'), (False, 'rewrite'), (False, 'failed'), (False, 'new'), (False, 'success'), (False, 'unsafe_owner'), (False, 'unsafe_group'), (False, 'unsafe_world')])
def test_deployment_preflight_and_build_failure_restore(tmp_path, weak_secret, redis_mode):
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.env').write_text('')
    sha = 'a' * 40
    (project / 'releases' / sha).mkdir(parents=True)
    archive = tmp_path / 'release.tar'
    archive.touch()
    lock = project / '.kitlane-deploy.lock'
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
        print(json.dumps({'services': {'api': {'environment': {'API_SECRET_KEY': os.environ['TEST_SECRET']}}}, 'volumes': {'redis_data': {'name': 'retained-volume'}}}))
    if 'build' in args and os.environ['REDIS_MODE'] != 'success': sys.exit(3)
    if 'run' in args:
        # Reproduce Compose run's default stdin consumption when not disabled.
        if '--interactive=false' not in args: sys.stdin.read()
        assert '-T' in args
    if 'up' in args:
        state = {key: True for key in state}
    if 'ps' in args: print(args[-1] + '-id')
elif args[0] == 'ps':
    for arg in args:
        if arg.startswith('label=com.docker.compose.service='):
            service = arg.split('=')[-1]
            if service != 'redis' or os.environ['REDIS_MODE'] != 'new': print(service + '-id')
elif args[0] == 'kill':
    assert args[1:3] == ['--signal', 'TERM']
    state[args[-1]] = False
elif args[0] == 'inspect':
    if '--format' in args:
        print(json.dumps([{'Destination': '/data', 'Type': 'volume', 'Name': 'other-volume' if os.environ['REDIS_MODE'] == 'mismatch' else 'retained-volume'}]))
    if '-f' in args: print(str(state[args[-1]]).lower())
elif args[0] == 'start': state[args[-1]] = True
elif args[0] == 'exec':
    mode = os.environ['REDIS_MODE']
    print('aof_enabled:' + ('0' if mode == 'disabled' else '1'))
    print('aof_rewrite_in_progress:' + ('1' if mode == 'rewrite' else '0'))
    print('aof_rewrite_scheduled:0')
    print('aof_last_bgrewrite_status:' + ('err' if mode == 'failed' else 'ok'))
    print('aof_last_write_status:ok')
elif args[0] == 'volume': assert args == ['volume', 'create', 'retained-volume']
else: raise AssertionError(args)
state_file.write_text(json.dumps(state))
''')
    docker.chmod(0o755)
    for name, content in [('stat', 'case "$*" in *.kitlane-deploy.lock) echo 0:600 ;; *) echo "$TEST_PROJECT_META" ;; esac'), ('flock', 'exit 0')]:
        executable = bin_dir / name
        executable.write_text('#!/bin/sh\n' + content + '\n')
        executable.chmod(0o755)
    remote = (ROOT / 'deploy.sh').read_text().split("<<'REMOTE' | tee \"$deploy_output\"\n", 1)[1].rsplit('\nREMOTE', 1)[0]
    remote = remote.replace('project_dir=/opt/belzakupki', f'project_dir={project}')
    result = subprocess.run(['bash', '-s', '--', sha, str(archive)], input=remote, text=True, capture_output=True,
        env={**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'], 'TRACE': str(trace), 'STATE': str(state), 'TEST_SECRET': 'short' if weak_secret else 'x' * 40, 'REDIS_MODE': redis_mode, 'TEST_PROJECT_META': {'unsafe_owner': '501:755', 'unsafe_group': '0:775', 'unsafe_world': '0:777'}.get(redis_mode, '0:755')})
    if redis_mode == 'success':
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
    calls = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    if redis_mode.startswith('unsafe_'):
        assert 'root-owned and not writable' in result.stderr
        assert not lock.exists()
        assert not calls
        return
    assert all('stop' not in call and 'prune' not in call for call in calls)
    if weak_secret:
        assert 'API_SECRET_KEY' in result.stderr
        assert not any(call[0] in ('kill', 'start') or 'build' in call for call in calls)
    elif redis_mode in ('mismatch', 'disabled', 'rewrite', 'failed'):
        assert ('Redis volume mismatch' if redis_mode == 'mismatch' else 'Redis AOF is not ready') in result.stderr
        assert not any(call[0] in ('kill', 'start', 'volume') or 'build' in call for call in calls)
    elif redis_mode == 'success':
        assert f'Deployed and verified {sha}' in result.stdout
        assert (project / 'deployed-sha').read_text().strip() == sha
        assert not list(project.glob('deploy-recovery.*'))
        migrations = [call for call in calls if call[0] == 'compose' and 'run' in call]
        assert len(migrations) == 1
        assert '--interactive=false' in migrations[0]
    else:
        if redis_mode == 'new':
            assert ['volume', 'create', 'retained-volume'] in calls
        else:
            assert not any(call[0] == 'volume' for call in calls)
        assert 'recovery record retained' in result.stderr
        assert sum(call[0] == 'kill' for call in calls) == 3
        assert sum(call[0] == 'start' for call in calls) == 3
        assert all(json.loads(state.read_text()).values())
        assert len(list(project.glob('deploy-recovery.*'))) == 1


@pytest.mark.parametrize('completed', [False, True])
def test_local_deploy_requires_remote_completion_marker(tmp_path, completed):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in {
        'git': 'exit 0',
        'scp': 'exit 0',
        'ssh': '''case "$*" in
  *mktemp*) echo /tmp/belzakupki-release.TEST123 ;;
  *) cat >/dev/null
     if [ "$TEST_COMPLETED" = yes ]; then echo "Deployed and verified $TEST_SHA"; fi ;;
esac''',
    }.items():
        executable = bin_dir / name
        executable.write_text('#!/bin/sh\n' + body + '\n')
        executable.chmod(0o755)
    sha = 'b' * 40
    result = subprocess.run(['bash', str(ROOT / 'deploy.sh'), sha, 'fake-host'],
        capture_output=True, text=True,
        env={**os.environ, 'TMPDIR': str(tmp_path), 'PATH': str(bin_dir) + ':' + os.environ['PATH'], 'TEST_SHA': sha, 'TEST_COMPLETED': 'yes' if completed else 'no'})
    assert (result.returncode == 0) is completed
    if not completed:
        assert 'without its verified completion marker' in result.stderr
