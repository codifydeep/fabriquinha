"""Fresh operator QA inputs only; agents still author all product and TDD code."""
import copy
import json
from pathlib import Path
import subprocess
from generate_dependent_contract import save_generated
from portable_contract import is_test_path,validate
from portable_run_spec import validate as validate_spec

BASE='90fac1054a263be42ec2545b3f82f0785f9de87d'
PREFIX='descartavel2-briefdetail-1'
NAME='BRIEFDETAIL-1'
ROOT=Path(__file__).resolve().parent


def derive(tracked,template,runs):
    baseline=set(tracked)
    if not {'app/server.py','app/static/app.js','app/static/index.html','Dockerfile.feedback-bootstrap'}<=baseline:
        raise ValueError('homologated web baseline required')
    outputs={}
    for index,kind in enumerate(('api','ui')):
        placeholder='tests/test_feedback_detail_'+kind+'_template.py'
        if placeholder in baseline:raise ValueError('fresh detail trial required')
        files=baseline|{placeholder}
        editable={placeholder}|({'app/server.py'} if index==0 else
            {'app/static/app.js','app/static/index.html','app/static/style.css'})
        contract=copy.deepcopy(template)
        contract.update(files=sorted(files),required_files=sorted(files),editable_files=sorted(editable),
            protected_files=sorted(files-editable),test_files=sorted(p for p in files if is_test_path(p,'.','python3')))
        # Negative HTTP responses and seeded detail reads belong to the isolated
        # browser recipe, not the positive-only deployment health contract.
        validate(contract)
        run={**runs[index],'label':('DETAILAPI-1','DETAILUI-1')[index],'qa_host_port':19461+index,
            'browser_qa':{**runs[index]['browser_qa'],'scenario':'feedback-board-detail-'+kind+'-v1'}}
        validate_spec(run,contract)
        outputs[PREFIX+'-'+kind+'.qa.contract.json']=contract
        outputs[PREFIX+'-'+kind+'.qa.run.json']=run
    outputs[PREFIX+'.planning.json']=dict(name=NAME,brief=PREFIX+'.brief.md',minimum_calls=64,base_sha=BASE)
    outputs[PREFIX+'.delivery.json']=dict(name=NAME,prefix=PREFIX,project_config='descartavel2.json',
        planning_config=PREFIX+'.planning.json',minimum_calls=256,
        stages=[dict(contract=PREFIX+'-'+k+'.qa.contract.json',run_spec=PREFIX+'-'+k+'.qa.run.json') for k in ('api','ui')])
    return outputs


def main():
    checkout=ROOT/'sandbox-github2'
    actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','origin/main'],text=True).strip()
    if actual!=BASE:raise ValueError('detail trial base drift')
    tracked=subprocess.check_output(['git','-C',str(checkout),'ls-tree','-r','--name-only',BASE],text=True).splitlines()
    folder=ROOT/'projects'
    template=json.loads((folder/'descartavel2-briefdemo-2-api.qa.contract.json').read_text())
    runs=[json.loads((folder/('descartavel2-briefdemo-2-'+k+'.qa.run.json')).read_text()) for k in ('api','ui')]
    for name,value in derive(tracked,template,runs).items():save_generated(folder/name,value)
    from planned_delivery import load_configuration
    from planning_intake import brief_body
    config=load_configuration(folder/(PREFIX+'.delivery.json'))
    brief_body(config['selection']['brief'].read_text())
    print(json.dumps(dict(name=NAME,input_sha256=config['sha256'],minimum_calls=config['minimum_calls'],
                         base_sha=BASE,dispatched=False)))


if __name__=='__main__':main()
