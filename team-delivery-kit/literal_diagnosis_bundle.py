"""Fixed, read-only-source evidence packaging; never executes delivered code.

The output is a diagnostic projection, NOT a new delivery or a replacement for
any original snapshot. Every copied byte and the lineage report are bound to
three independently verified source manifests.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from generic_harness_calibration import require,relative
from r3_snapshot_probe import probe


def sha(raw):return hashlib.sha256(raw).hexdigest()


def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def projection(original,seed,candidate,manifests,path):
    from literal_test_maintenance import compare,slot
    relative(path);require(path.endswith('.py') and set(manifests)=={'original','seed','candidate'})
    roots=dict(original=Path(original),seed=Path(seed),candidate=Path(candidate));raw={};bounds={}
    for name,root in roots.items():
        probe(root,manifests[name]);raw[name]=(root/path).read_bytes();slot(raw[name],'NODE_HARNESS')
        node=next(n.value for n in ast.parse(raw[name].decode()).body if isinstance(n,ast.Assign)
            and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='NODE_HARNESS')
        bounds[name]=dict(start_line=node.lineno,end_line=node.end_lineno,
            test_sha256=sha(raw[name]),total_lines=len(raw[name].splitlines()))
    inherited=compare(raw['original'],raw['seed'],'NODE_HARNESS')
    current=compare(raw['seed'],raw['candidate'],'NODE_HARNESS')
    aggregate=compare(raw['original'],raw['candidate'],'NODE_HARNESS')
    report=dict(operation='literal_diagnosis_projection_v1',source_manifests=manifests,test_path=path,
        literal='NODE_HARNESS',literal_ranges=bounds,
        inherited_delta=dict(added_net_lines=bounds['seed']['total_lines']-bounds['original']['total_lines'],
            outside_literal_bytes_preserved=inherited['outside_literal_bytes_preserved']),
        current_delta=dict(added_net_lines=bounds['candidate']['total_lines']-bounds['seed']['total_lines'],
            outside_literal_bytes_preserved=current['outside_literal_bytes_preserved']),
        outside_literal_sha256=aggregate['outside_literal_sha256'],
        limitation='Structural scope facts only; no semantic review, execution, TDD or approval.',
        source_reset=False,delivery_approval=False,model_calls=0)
    files={'original/'+path:raw['original'],'seed/'+path:raw['seed'],'report.json':encoded(report)}
    manifest=encoded(dict(files={p:dict(bytes=len(v),sha256=sha(v)) for p,v in files.items()}))
    return roots,files,manifest,report


def build(original,seed,candidate,target,manifests,path,mode):
    require(mode in ('create','verify'));target=Path(target)
    require(target.is_dir() and not target.is_symlink())
    roots,files,manifest,report=projection(original,seed,candidate,manifests,path)
    files={**files,'manifest.json':manifest}
    expected_dirs={str(parent) for name in files for parent in Path(name).parents if str(parent)!='.'}
    for entry in target.rglob('*'):
        name=entry.relative_to(target).as_posix()
        require(not entry.is_symlink() and ((entry.is_file() and name in files) or (entry.is_dir() and name in expected_dirs)))
    for name,raw in files.items():
        dest=target/name
        if dest.exists():require(dest.is_file() and not dest.is_symlink() and dest.read_bytes()==raw)
        else:
            require(mode=='create');dest.parent.mkdir(parents=True,exist_ok=True)
            with os.fdopen(os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444),'wb') as out:
                out.write(raw);out.flush();os.fsync(out.fileno())
    probe(target,sha(manifest))
    for name,root in roots.items():probe(root,manifests[name])
    return dict(operation='literal_diagnosis_bundle_v1',manifest_sha256=sha(manifest),report=report,
        source_unchanged=True,source_reset=False,delivery_approval=False,model_calls=0)


def main(args):
    try:
        require(len(args)==9);signal.alarm(120)
        require(not Path('/var/run/docker.sock').exists())
        require(not any(os.environ.get(k) for k in ('OPENROUTER_API_KEY','OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN')))
        original,seed,candidate,target,old_sha,seed_sha,new_sha,path,mode=args
        print(json.dumps(build(original,seed,candidate,target,dict(original=old_sha,seed=seed_sha,candidate=new_sha),path,mode),sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps(dict(operation='literal_diagnosis_bundle_v1',failure=type(error).__name__,
            source_reset=False,delivery_approval=False,model_calls=0)))
        return 1


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
