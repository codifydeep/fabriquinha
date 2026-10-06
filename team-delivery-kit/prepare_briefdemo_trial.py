"""Generate only pinned operator QA templates for a fresh autonomous brief.

No implementation, model call, issue creation or agent handoff occurs here.
"""
import copy
import json
from pathlib import Path
import subprocess
from generate_dependent_contract import save_generated
from portable_contract import is_test_path, validate
from portable_run_spec import validate as validate_spec
from planned_delivery import load_configuration

ROOT=Path(__file__).resolve().parent
BASE='e96392f78e4c537ea0d6890ff0eca98bd859958f'
PREFIX='descartavel2-briefdemo-2'


def derive(tracked, template, runs):
    baseline=set(tracked)
    if not {'test_service_status_indicator.py','app/server.py','app/static/app.js'} <= baseline:
        raise ValueError('homologated service-status baseline required')
    outputs={}
    for index, kind in enumerate(('api','ui')):
        placeholder='tests/test_demo_mode_'+kind+'_template.py'
        if placeholder in baseline:raise ValueError('trial not fresh')
        files=baseline|{placeholder}
        editable={placeholder}|({'app/server.py'} if index==0 else
            {'app/static/app.js','app/static/index.html','app/static/style.css'})
        contract=copy.deepcopy(template)
        contract.update(files=sorted(files),required_files=sorted(files),editable_files=sorted(editable),
            protected_files=sorted(files-editable),
            test_files=sorted(p for p in files if is_test_path(p,'.','python3')))
        contract['qa_cases'] += [dict(path=path,status=200,expected_json={'mode':'demo'},bind_source_sha=False)
                               for path in ('/service-mode','/service-mode?probe=1')]
        if index:
            contract['qa_cases'].append(dict(path='/',status=200,content_type='text/html',
                                             text_contains=['id="service-mode"']))
        validate(contract)
        run={**runs[index],'label':('DEMOAPI-2','DEMOUI-2')[index],
            'qa_host_port':19459+index,
            'review_instruction':'Review immutable delivery and full TDD evidence independently. No edits or generic commands. Require all acceptance and unchanged baseline tests. Run ONLY cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>.',
            'browser_qa':{**runs[index]['browser_qa'],
                          'scenario':'feedback-board-demo-mode-'+kind+'-v1'}}
        validate_spec(run,contract)
        outputs[PREFIX+'-'+kind+'.qa.contract.json']=contract
        outputs[PREFIX+'-'+kind+'.qa.run.json']=run
    outputs[PREFIX+'.planning.json']=dict(name='BRIEFDEMO-2',brief=PREFIX+'.brief.md',minimum_calls=64,base_sha=BASE)
    outputs[PREFIX+'.delivery.json']=dict(name='BRIEFDEMO-2',prefix=PREFIX,project_config='descartavel2.json',
        planning_config=PREFIX+'.planning.json',minimum_calls=256,
        stages=[dict(contract=PREFIX+'-'+k+'.qa.contract.json',run_spec=PREFIX+'-'+k+'.qa.run.json') for k in ('api','ui')])
    return outputs


def main():
    checkout=ROOT/'sandbox-github2'
    actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','origin/main'],text=True).strip()
    if actual!=BASE:raise ValueError('trial base drift')
    tracked=subprocess.check_output(['git','-C',str(checkout),'ls-tree','-r','--name-only',BASE],text=True).splitlines()
    folder=ROOT/'projects'
    template=json.loads((folder/'descartavel2-briefstatus-1-api.qa.contract.json').read_text())
    runs=[json.loads((folder/('descartavel2-briefstatus-1-'+k+'.qa.run.json')).read_text()) for k in ('api','ui')]
    for name,value in derive(tracked,template,runs).items():save_generated(folder/name,value)
    config=load_configuration(folder/(PREFIX+'.delivery.json'))
    from planning_intake import brief_body
    brief_body(config['selection']['brief'].read_text())
    print(json.dumps(dict(name=config['name'],input_sha256=config['sha256'],minimum_calls=config['minimum_calls'],
                         base_sha=BASE,dispatched=False)))


if __name__=='__main__':main()
