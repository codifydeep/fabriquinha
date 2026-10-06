"""Independent artifact audit; a green final suite alone never passes TDD."""
import argparse
import json
from pathlib import Path


def audit(root):
    result=json.loads((root/'result.json').read_text())
    work=root/'work'
    def read(name):
        path=work/name
        return path.read_text() if path.exists() else ''
    red,green=read('red.log'),read('green.log')
    denied='Write denied:' in (root/'agent.log').read_text()
    problems=[]
    if result.get('timed_out') or result.get('agent_exit_code')!=0:
        problems.append('agent execution failed or timed out')
    if not result.get('existing_test_unchanged'):
        problems.append('preexisting regression test changed')
    if result.get('suite_exit_code')!=0 or result.get('oracle_exit_code')!=0:
        problems.append('implementation or final suite failed')
    if not result.get('new_test_exists'):
        problems.append('new tests absent')
    if 'FAILED (' not in red:
        problems.append('missing observed Red failure in durable log')
    if '\nOK' not in green:
        problems.append('missing observed Green success in durable log')
    if denied:
        problems.append('permission denial occurred; requires trace review, not automatic approval')
    return dict(artifact_checks_pass=not problems,problems=problems,
        requires_tool_trace_chronology_review=True,team_rehearsal_passed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    args=parser.parse_args()
    print(json.dumps(audit(args.root),indent=2))
