"""Host supervisors defer dispatch while controller maintenance is active.

This is a conservative preflight, not a distributed admission lease. The broker
still independently fences grants; a maintenance change after this read is a
separate race that must not be treated as a functional author failure.
"""
import json
import subprocess
from controller_maintenance_cli import arguments


def maintenance_active(namespace,*,read=None):
    command=arguments(namespace,'status','')
    if read is None:
        labels=json.loads(subprocess.check_output(['docker','inspect','--format',
            '{{json .Config.Labels}}',command[4]],text=True,timeout=20))
        if (labels.get('com.docker.compose.project')!=namespace
                or labels.get('com.docker.compose.service')!='execution-broker'):
            raise ValueError('owned exact controller required')
        def read(command):
            return subprocess.check_output(command,text=True,timeout=20)
    value=json.loads(read(command))
    if value is None:return False
    if (not isinstance(value,dict) or value.get('namespace')!=namespace
            or value.get('stage') not in ('draining','sealed') or not value.get('operation_id')):
        raise ValueError('exact current maintenance observation required')
    return True
