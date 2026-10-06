"""Fixed, credential-free probe. Run only in a disposable evaluation container."""
import errno
import json
import os
from pathlib import Path
import subprocess


def main():
    artifact = Path('/delivery/artifact.txt')
    before = artifact.read_bytes()
    denied = {}
    for operation in ('write', 'unlink', 'chmod'):
        try:
            if operation == 'write':
                artifact.write_bytes(b'changed')
            elif operation == 'unlink':
                artifact.unlink()
            else:
                artifact.chmod(0o777)
            denied[operation] = False
        except OSError as error:
            denied[operation] = error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
    shell = subprocess.run(['sh', '-c', 'printf changed > /delivery/artifact.txt'],
                           capture_output=True)
    denied['shell_write'] = shell.returncode != 0
    Path('/tmp/test-output').write_text('temporary test output')
    result = {
        'uid': os.getuid(), 'denied': denied,
        'artifact_unchanged': artifact.read_bytes() == before,
        'owner_config_absent': not Path('/eval-state/.multica/config.json').exists(),
        'docker_socket_absent': not Path('/var/run/docker.sock').exists(),
        'other_task_absent': not Path('/other-task').exists(),
        'temporary_output_works': Path('/tmp/test-output').read_text() == 'temporary test output',
    }
    print(json.dumps(result, sort_keys=True))
    assert all(denied.values()) and all(v for k, v in result.items() if k not in ('uid', 'denied'))


if __name__ == '__main__':
    main()
