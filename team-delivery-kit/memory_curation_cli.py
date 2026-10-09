"""Credential-free operator entrypoint; resume one curation, never replay author."""
import argparse
import json
import re
import time
from bootstrap_multica import PRIVATE
from evalctl import PROJECT
from project_selection import current
from planning_intake import issue_for
from start_eval import cli,check_model_budget
from memory_curation import tick


def publish_terminal(state,call):
    """Curation completion is not product delivery; failure stays visible."""
    if state['stage'] not in ('approved','rejected','blocked'):return
    issue=state.get('issue_id')
    if not issue:return
    call('metadata','set',issue,'--key','memory_curation_state','--value',state['stage'],'--type','string')
    if state['stage']=='blocked':
        call('metadata','set',issue,'--key','memory_curation_error','--value',
             state.get('category','curation_requires_diagnosis'),'--type','string')
    call('status',issue,'blocked' if state['stage']=='blocked' else 'done','--no-start')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nomination',required=True)
    parser.add_argument('--wait',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{64}',args.nomination):raise ValueError('exact nomination hash required')
    registry=json.loads((PRIVATE/'planning-agents.json').read_text())
    reviewer=registry['agents']['techlead'];project=current()
    def create(*a,**kw):check_model_budget();return issue_for(*a,**kw)
    deadline=time.monotonic()+1800;last=None
    while True:
        result=tick(PRIVATE,'https://github.com/'+project['repository'],PROJECT,args.nomination,
                    reviewer,cli=cli,create=create,now=int(time.time()))
        publish_terminal(result,cli)
        if result!=last:print(json.dumps(result,sort_keys=True),flush=True);last=result
        if result['stage'] in ('approved','rejected','blocked') or not args.wait:return
        if time.monotonic()>=deadline:
            print(json.dumps({'stage':'observation_pending','issue_id':result['issue_id'],
                              'restart_author':False}),flush=True)
            return
        time.sleep(5)


if __name__=='__main__':main()
