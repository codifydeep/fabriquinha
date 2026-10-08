"""Fresh operator QA inputs only; agents still author all product and TDD code."""
import copy
from portable_contract import is_test_path,validate
from portable_run_spec import validate as validate_spec

BASE='90fac1054a263be42ec2545b3f82f0785f9de87d'
PREFIX='descartavel2-briefdetail-1'
NAME='BRIEFDETAIL-1'


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
