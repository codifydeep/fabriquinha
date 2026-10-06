"""Run the fixed offline canary; NOT a Multica dispatch adapter."""
import subprocess
from evalctl import ROOT, process_env
from docker_grouping import args as docker_group_args


def main():
    subprocess.run([
        'docker', 'run', '--rm', '--name', 'delivery-kit-eval-isolation-canary',
        *docker_group_args('isolation-canary',namespace='delivery-kit-eval'),
        '--network', 'none', '--read-only', '--user', '10000:10000',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--pids-limit', '64', '--memory', '256m', '--cpus', '1',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m,mode=1777',
        '--mount', f'type=bind,source={ROOT / "tests/fixtures/delivery"},target=/delivery,readonly',
        '--mount', f'type=bind,source={ROOT / "tests/isolation_canary.py"},target=/probe.py,readonly',
        '--entrypoint', 'python', 'delivery-kit-hermes-runtime:20260921.1', '/probe.py',
    ], check=True, env=process_env(), timeout=60)


if __name__ == '__main__':
    main()
