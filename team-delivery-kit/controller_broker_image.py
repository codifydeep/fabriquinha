"""Use the installed broker's immutable image for controller helper containers."""
import json
import re
import subprocess


def installed_image(project):
    details = json.loads(subprocess.check_output(
        ['docker', 'inspect', project + '-execution-broker-1'], text=True))
    if len(details) != 1:
        raise ValueError('expected one installed broker')
    broker = details[0]
    if (not broker.get('State', {}).get('Running')
            or broker.get('Config', {}).get('Labels', {}).get('com.docker.compose.project') != project
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', broker.get('Image', ''))):
        raise ValueError('installed broker image identity mismatch')
    return broker['Image']
