"""Real read-only validator mount proof; no model calls or product edits."""
import sys,json,pathlib,tempfile,subprocess,hashlib,argparse
from dataclasses import replace
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.executor import validation_files
from fabriquinha.hermes import command
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=pathlib.Path,required=True)
root=parser.parse_args().root.resolve()
p=Project.parse(json.loads((root/'project.json').read_bytes()));p=replace(p,namespace='delivery-kit-observer-environment-proof')
original=Project.parse(json.loads((root/'project.json').read_bytes()));store=Store(root/'private');bundle,files=validation_files(original,store)
with tempfile.TemporaryDirectory() as folder:
 expected=dict(binding={'task':'readonly-mount-proof'},workspace=folder,phase='review',baseline_tests=[],validation_browser=str(files['browser.py']))
 args=command(p,expected);args[0]='run';args.insert(1,'--rm');i=args.index('--entrypoint');args=args[:i]+['--entrypoint','python3',p.validation_image,'-c',"from pathlib import Path; import hashlib,errno; p=Path('/opt/fabriquinha/browser.py'); print(hashlib.sha256(p.read_bytes()).hexdigest());\ntry:p.write_text('forbidden')\nexcept OSError as e: assert e.errno==errno.EROFS; print('readonly confirmed')\nelse:raise AssertionError('mount writable')"]
 result=subprocess.run(['docker',*args],capture_output=True,text=True,check=True)
 expected_hash=hashlib.sha256(files['browser.py'].read_bytes()).hexdigest();assert expected_hash in result.stdout and 'readonly confirmed' in result.stdout
 print(json.dumps(dict(passed=True,bundle=bundle,readonly=True,network='none',model_calls=0,delivery_approval=False)))
