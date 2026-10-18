"""One declared Python literal may change; every surrounding byte is immutable.

This validates a separate author submission, never edits the frozen source and
never qualifies product Red/Green. Node witnesses measure harness selectivity,
not a product implementation or admitted calibration references.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from generic_harness_calibration import require,relative
from r3_snapshot_probe import probe
import calibration_harness_protocol_probe as protocol


def sha(value):return hashlib.sha256(value).hexdigest()


def slot(raw,name):
    require(isinstance(raw,bytes) and 1<=len(raw)<=32768 and bool(re.fullmatch('[A-Z][A-Z0-9_]{0,119}',name)))
    try:tree=ast.parse(raw.decode('utf-8'))
    except (UnicodeError,SyntaxError):raise ValueError('valid bounded Python source required') from None
    selected=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
        and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
    require(len(selected)==1);value=selected[0].value
    require(isinstance(value,ast.Constant) and type(value.value) is str)
    lines=raw.splitlines(keepends=True)
    start=sum(len(line) for line in lines[:value.lineno-1])+value.col_offset
    end=sum(len(line) for line in lines[:value.end_lineno-1])+value.end_col_offset
    normalized=copy.deepcopy(tree)
    target=next(n for n in normalized.body if isinstance(n,ast.Assign) and len(n.targets)==1
        and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name)
    target.value=ast.Constant(value='<IMMUTABLE_LITERAL_SLOT>')
    methods=sorted(cls.name+'.'+method.name for cls in tree.body if isinstance(cls,ast.ClassDef)
        for method in cls.body if isinstance(method,ast.FunctionDef) and method.name.startswith('test_'))
    require(methods)
    return dict(prefix=raw[:start],suffix=raw[end:],literal=value.value,
        normalized=ast.dump(normalized,include_attributes=False),methods=methods)


def compare(previous,candidate,literal):
    old,new=slot(previous,literal),slot(candidate,literal)
    require(previous!=candidate and old['literal']!=new['literal']
        and old['prefix']==new['prefix'] and old['suffix']==new['suffix']
        and old['normalized']==new['normalized'] and old['methods']==new['methods'])
    return dict(operation='immutable_literal_maintenance_structure_v1',literal=literal,
        previous_test_sha256=sha(previous),candidate_test_sha256=sha(candidate),
        previous_literal_sha256=sha(old['literal'].encode()),candidate_literal_sha256=sha(new['literal'].encode()),
        outside_literal_sha256=sha(old['prefix']+b'\0'+old['suffix']),outside_literal_bytes_preserved=True,
        test_methods=old['methods'],python_ast_preserved_except_literal=True,functional_red=False,delivery_approval=False)


def guarded_witness(prefix):
    driver=protocol.witness(prefix)
    replacements={"let status = 'all';":"let status = 'all'; let generation = 0;",
        'function refresh() {':'function refresh() { const ticket = ++generation;',
        '.then(body => { line.textContent':'.then(body => { if (ticket !== generation) return; line.textContent',
        '.catch(() => { line.textContent':'.catch(() => { if (ticket !== generation) return; line.textContent'}
    for old,new in replacements.items():
        require(driver.count(old)==1);driver=driver.replace(old,new)
    return driver


def inspect(previous,candidate,previous_manifest,candidate_manifest,test_path,literal):
    previous,candidate=Path(previous),Path(candidate);relative(test_path);require(test_path.endswith('.py') and literal=='NODE_HARNESS')
    probe(previous,previous_manifest);probe(candidate,candidate_manifest)
    old=json.loads((previous/'manifest.json').read_text())['files'];new=json.loads((candidate/'manifest.json').read_text())['files']
    require(set(old)==set(new) and test_path in old and all(old[p]==new[p] for p in old if p!=test_path))
    before=(previous/test_path).read_bytes();after=(candidate/test_path).read_bytes();structure=compare(before,after,literal)
    bound=protocol.bind(after.decode());formatted=bound['harness']%dict(source_path=json.dumps('/diagnostic/reference.js'),source_name=json.dumps('/diagnostic/reference.js'))
    syntax=subprocess.run(['node','--check'],input=formatted.encode(),stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,timeout=20,check=False)
    require(syntax.returncode==0)
    try:
        # The same frozen revised harness must distinguish these actual drivers.
        reports={};hashes={}
        with tempfile.TemporaryDirectory(prefix='harness-selectivity-') as directory:
            for label,driver in (('unguarded',protocol.witness(bound['prefix'])),('guarded',guarded_witness(bound['prefix']))):
                target=Path(directory)/(label+'.js');target.write_text(driver);hashes[label]=sha(driver.encode())
                report=protocol.node(bound['harness']%dict(source_path=json.dumps(str(target)),source_name=json.dumps(str(target))))
                require(report.get('executed') is True and type(report.get('initial_requests')) is int
                    and type(report.get('poll_requests')) is int and isinstance(report.get('stale_guard_text'),str))
                reports[label]={k:report[k] for k in ('initial_requests','poll_requests','stale_guard_text')}
        sensitivity=(reports['guarded']['stale_guard_text']==bound['stale_expected']
            and reports['unguarded']['stale_guard_text']!=bound['stale_expected']
            and all(r['initial_requests']==bound['initial_expected'] and r['poll_requests']>=bound['poll_minimum'] for r in reports.values()))
        return dict(operation='immutable_literal_maintenance_inspection_v1',previous_manifest_sha256=previous_manifest,
            candidate_manifest_sha256=candidate_manifest,test_path=test_path,structure=structure,non_target_files_unchanged=True,
            node_syntax_valid=True,reports=reports,witness_sha256=hashes,stale_witness_selectivity_passed=sensitivity,
            snapshot_unchanged=True,**{k:False for k in protocol.FALSE_FLAGS})
    finally:probe(previous,previous_manifest);probe(candidate,candidate_manifest)


def main(arguments):
    try:
        require(len(arguments)==6);signal.alarm(120)
        require(not Path('/var/run/docker.sock').exists())
        require(not any(os.environ.get(k) for k in ('OPENROUTER_API_KEY','OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN')))
        previous,candidate,old_manifest,new_manifest,test_path,literal=arguments
        if new_manifest=='observe':new_manifest=sha((Path(candidate)/'manifest.json').read_bytes())
        print(json.dumps(inspect(previous,candidate,old_manifest,new_manifest,test_path,literal),sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps(dict(operation='immutable_literal_maintenance_inspection_v1',
            failure=type(error).__name__,**{k:False for k in protocol.FALSE_FLAGS}),sort_keys=True))
        return 1


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
