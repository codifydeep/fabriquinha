"""Fixed full-suite Red observer; run in the controller's isolated test sandbox.

No positive calibration/reference implementation, test selection, worker command,
artifact editing or delivery authority. This first adapter supports the pinned
Python unittest discovery command; other frameworks fail closed.
"""
import ast
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import unittest
import uuid

try:
    import quality_lifecycle_v2 as quality
    from test_first_protocol import _regular,NEW_TEST_MAX_BYTES,validate_test_framework
except ImportError:
    from broker import quality_lifecycle_v2 as quality
    from broker.test_first_protocol import _regular,NEW_TEST_MAX_BYTES,validate_test_framework
from portable_contract import validate as validate_contract
from r3_snapshot_probe import probe
from calibration_frozen_harness_probe import Results,OutputDigest,cases


class Rejected(ValueError):
    def __init__(self,category):
        self.category=category
        super().__init__(category)


def require(condition,category):
    if not condition:raise Rejected(category)


def inputs(base,snapshot,plan,base_manifest,snapshot_manifest):
    quality.validate(plan)
    require(not base.is_symlink() and base.is_dir(),'base_identity_invalid')
    probe(snapshot,snapshot_manifest)
    raw=_regular(base,'manifest.json')
    require(hashlib.sha256(raw).hexdigest()==base_manifest,'base_manifest_mismatch')
    original=json.loads(raw)
    require(set(original)=={'base_sha','files'} and original['base_sha']==plan['base_sha'],
        'base_identity_invalid')
    spec=validate_contract(json.loads(_regular(base,'contract.json')))
    require(quality.digest(spec)==plan['contract_sha256'],'contract_mismatch')
    require(spec['test_command']==['python3','-m','unittest','discover','-s',spec['test_roots'][0],'-q'],
        'runner_not_supported')
    expected=original['files'];frozen=json.loads((snapshot/'manifest.json').read_bytes())['files']
    require(isinstance(expected,dict) and set(expected)==set(spec['files'])-set(plan['new_tests'])|{'contract.json'}
        and set(frozen)==set(spec['files'])
        and set(plan['baseline_tests'])|set(plan['new_tests'])==set(spec['test_files']),
        'test_or_file_inventory_mismatch')
    require(expected['contract.json']==hashlib.sha256(_regular(base,'contract.json')).hexdigest(),
        'contract_mismatch')
    for path,sha in expected.items():
        actual=hashlib.sha256(_regular(base,path)).hexdigest()
        require(actual==sha,'base_file_hash_mismatch')
        if path!='contract.json':
            require(frozen[path]['sha256']==sha and _regular(snapshot,path)==_regular(base,path),
                'base_bytes_changed_before_red')
    tests={p:frozen[p]['sha256'] for p in spec['test_files']}
    require(all(tests[p]==h for p,h in plan['baseline_tests'].items()),'baseline_test_hash_mismatch')
    inventory=set()
    for path in sorted(tests):
        raw=_regular(snapshot,path)
        require(path.endswith('.py'),'runner_not_supported')
        if path in plan['new_tests']:
            require(0<len(raw)<=NEW_TEST_MAX_BYTES,'new_test_size_invalid')
            validate_test_framework(path,raw,spec['test_command'])
        tree=ast.parse(raw,filename=path)
        require(not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='load_tests'
            for n in tree.body),'test_selection_hook_forbidden')
        entries={(path,n.name,m.name) for n in tree.body if isinstance(n,ast.ClassDef)
            for m in n.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef)) and m.name.startswith('test_')}
        require(bool(entries),'test_inventory_empty')
        inventory.update(entries)
    for witnesses in plan['criterion_tests'].values():
        for witness in witnesses:
            require(sum(p==witness['path'] and m==witness['method'] for p,c,m in inventory)==1,
                'criterion_witness_missing_or_ambiguous')
    return spec,tests,inventory


class Observations(Results):
    def __init__(self,root):
        super().__init__();self.root=root;self.events=[]
    def record(self,test,outcome,error=None):
        if not isinstance(test,unittest.TestCase):
            self.events.append(dict(path=None,method=None,phase='framework',kind='exception',outcome=outcome))
            return
        temporary=Results();temporary.record(test,outcome,error)
        value=temporary.observations[0]
        module=sys.modules[test.__class__.__module__]
        path=Path(module.__file__).resolve().relative_to(self.root).as_posix()
        item=dict(path=path,method=test._testMethodName,outcome=outcome)
        if error:
            item.update(phase=value['phase'],kind='assertion' if issubclass(error[0],AssertionError) else 'exception')
            frame=error[2];body=False
            while frame is not None:
                if (Path(frame.tb_frame.f_code.co_filename).resolve()==Path(module.__file__).resolve()
                        and frame.tb_frame.f_code.co_name==test._testMethodName):body=True
                frame=frame.tb_next
            item['test_body_frame']=body
        self.events.append(item)
        super().record(test,outcome,error)


def run(base,snapshot,plan,task_id,base_manifest,snapshot_manifest):
    if not isinstance(task_id,str) or str(uuid.UUID(task_id))!=task_id:
        raise ValueError('canonical controller-bound source task required')
    base,snapshot=Path(base),Path(snapshot)
    spec,tests,inventory=inputs(base,snapshot,plan,base_manifest,snapshot_manifest)
    root=snapshot.resolve();previous_path=list(sys.path);previous_cwd=os.getcwd()
    bytecode=sys.dont_write_bytecode;sys.dont_write_bytecode=True;output=OutputDigest()
    result=Observations(root);before_modules=set(sys.modules)
    try:
        # Avoid observing another delivery's cached modules as this snapshot.
        for path in spec['files']:
            if not path.endswith('.py'):continue
            names={Path(path).stem,path.removesuffix('.py').replace('/','.')}
            for name in names:
                if name in sys.modules:
                    actual=getattr(sys.modules[name],'__file__',None)
                    require(actual is not None and Path(actual).resolve()==root/path,'module_cache_collision')
        sys.path.insert(0,str(root));os.chdir(root)
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            loader=unittest.TestLoader()
            try:suite=loader.discover(str(root/spec['test_roots'][0]))
            except Exception:raise Rejected('suite_import_or_infrastructure_failure') from None
            selected=list(cases(suite));actual=set()
            require(not loader.errors,'suite_import_or_infrastructure_failure')
            for test in selected:
                require(isinstance(test,unittest.TestCase),'test_inventory_mismatch')
                module=sys.modules[test.__class__.__module__]
                try:path=Path(module.__file__).resolve().relative_to(root).as_posix()
                except (ValueError,TypeError,AttributeError):raise Rejected('test_inventory_mismatch') from None
                actual.add((path,test.__class__.__name__,test._testMethodName))
            require(actual==inventory and len(selected)==len(inventory),'test_inventory_mismatch')
            suite.run(result)
        require(not result.errors and not result.skipped and not result.expectedFailures
            and not result.unexpectedSuccesses,'suite_import_or_infrastructure_failure')
        failures=[v for v in result.events if v['outcome']=='failure']
        require(result.testsRun==len(inventory),'incomplete_suite')
        require(bool(failures),'suite_not_behavioral_red')
        require(all(v['path'] in plan['new_tests'] for v in failures),'baseline_regression')
        require(all(v['phase']=='test_body' and v['kind']=='assertion' and v['test_body_frame'] for v in failures),
            'failure_outside_new_test_body')
        observed=dict(operation='observed_red_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),task_id=task_id,
            manifest_sha256=snapshot_manifest,tests=tests,suite_complete=True,tests_run=result.testsRun,
            skipped=0,errors=0,exit_code=1,
            failures=[{k:v[k] for k in ('path','method','phase','kind')} for v in failures])
        quality.red(plan,observed)
        return dict(operation='full_suite_red_observation_v2',red=observed,
            base_manifest_sha256=base_manifest,captured_output_sha256=output.hash.hexdigest(),
            captured_output_bytes=output.bytes,snapshot_unchanged=True,
            execution_authorized=False,delivery_approval=False)
    finally:
        os.chdir(previous_cwd);sys.path[:]=previous_path;sys.dont_write_bytecode=bytecode
        for name in set(sys.modules)-before_modules:
            actual=getattr(sys.modules[name],'__file__',None)
            if actual:
                try:Path(actual).resolve().relative_to(root)
                except ValueError:continue
                del sys.modules[name]
        # Detect even accidental edits when used by a test outside read-only Docker.
        inputs(base,snapshot,plan,base_manifest,snapshot_manifest)


def load_request():
    # Controller-owned bounded metadata, never an agent command. File input is
    # retained for baked synthetic probes; live fixed jobs bind Env in their
    # immutable validation identity and mount only base/snapshot read-only.
    raw=os.environ.get('QUALITY_RED_INPUT_JSON')
    if raw is None:
        path=Path('/policy/input.json')
        if path.is_symlink() or path.stat().st_size>262144:raise ValueError('bounded fixed input required')
        raw=path.read_bytes()
    elif len(raw.encode())>65536:raise ValueError('bounded fixed input required')
    request=json.loads(raw)
    if not isinstance(request,dict) or set(request)!={'plan','task_id','base_manifest_sha256','snapshot_manifest_sha256'}:
        raise ValueError('exact fixed input required')
    return request


if __name__=='__main__':
    try:
        if len(sys.argv)!=1:raise ValueError('fixed runner takes no commands')
        signal.alarm(180)
        request=load_request()
        print(json.dumps(run('/base','/snapshot',request['plan'],request['task_id'],
            request['base_manifest_sha256'],request['snapshot_manifest_sha256']),sort_keys=True),flush=True)
    except Exception as error:
        print(json.dumps(dict(operation='rejected_red_observation_v2',category=getattr(error,'category',type(error).__name__),
            execution_authorized=False,delivery_approval=False)),flush=True)
        sys.exit(2)
