"""Operator regression: real PR24 source, no Git/board writes or credentials in tests."""
import json,subprocess,tempfile,hashlib,shutil
from pathlib import Path
from product_recovery import CONFIGS
from product_validation_jobs import BASE

def main():
    root=Path(__file__).resolve().parent;runtime=root.parent/'lobby-runtime'/'snapshots'
    runtime.mkdir(parents=True,exist_ok=True)
    script="from product_autonomy import Coordinator; import json; c=Coordinator(); print(json.dumps({'head':c.source_files('f9395466840f1965cc338de1389038e93021321a'),'base':c.source_files('89d0ae0ec1adb51a0aab11cb1ff47974d3d1c24c')}))"
    # Use updated module read-only, since live coordinator still runs old code.
    script="import base64,json; from product_autonomy import api; heads=['f9395466840f1965cc338de1389038e93021321a','89d0ae0ec1adb51a0aab11cb1ff47974d3d1c24c']; out={}; configs="+repr(CONFIGS)+"\nfor label,head in zip(['head','base'],heads):\n names=[f['path'] for f in api('git/trees/'+head+'?recursive=1')['tree'] if f['type']=='blob' and (f['path'].startswith(('server/','tests/','shared/')) or f['path'] in configs)]\n out[label]={n:base64.b64decode(api('contents/'+n+'?ref='+head)['content']).decode() for n in names}\nprint(json.dumps(out))"
    data=json.loads(subprocess.check_output(['docker','exec','truco-online-lobby-coordinator','python','-c',script],text=True))
    with tempfile.TemporaryDirectory(prefix='validator-proof-',dir=runtime) as folder:
        context=Path(folder);head=data['head']
        for n in CONFIGS:(context/n).write_text(head[n])
        (context/'project-contract.json').write_text(json.dumps({n:hashlib.sha256(head[n].encode()).hexdigest() for n in CONFIGS}))
        for n in ('run.mjs','vitest.config.mjs'):shutil.copyfile(root/'lobby-toolchain'/n,context/n)
        (context/'Dockerfile').write_text('FROM '+BASE+'\nWORKDIR /opt/toolchain\nCOPY package.json package-lock.json ./\nRUN npm ci --ignore-scripts --no-audit --no-fund\nCOPY run.mjs vitest.config.mjs project-contract.json ./\nUSER 10000:10000\nENTRYPOINT ["node","/opt/toolchain/run.mjs"]\n')
        subprocess.run(['docker','build','-t','truco-online-project-validation:regression-proof',str(context)],check=True)
        image=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','truco-online-project-validation:regression-proof'],text=True).strip()
        from product_docker_runner import DockerRunner
        run=DockerRunner(str(runtime),'lobby-ts');results={}
        for label,files in data.items():
            result=run(files,image);results[label]=result
            print(label,result['exit_code'],result['output'][-3500:],flush=True)
        assert results['head']['exit_code']!=0 and 'No test suite found' in results['head']['output']
        assert results['base']['exit_code']==0 and 'PROJECT_GATES_PASSED' in results['base']['output']
        (root.parent/'lobby-runtime'/'validator-regression-20260918.json').write_text(json.dumps(dict(image=image,results=results),indent=2))
        print('VALIDATOR_REGRESSION_PROVED',image)
if __name__=='__main__':main()
