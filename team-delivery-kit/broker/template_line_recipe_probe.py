"""Fixed read-only feasibility probe, not a worker grant or author delivery."""
import hashlib,json,sys
from pathlib import Path
from r3_snapshot_probe import probe as verify_snapshot
from surgical_test_edit import prepare_template_lines
try:from service_mode_observation_hypothesis import OLD,NEW
except ImportError:from broker.service_mode_observation_hypothesis import OLD,NEW


def recipe(source):
    text=source.decode('utf-8');lines=text.splitlines(keepends=True)
    if text.count(OLD)!=1:raise ValueError('one controller-proven observation anchor required')
    matches=[(i,line) for i,line in enumerate(lines,1) if OLD in line]
    if len(matches)!=1:raise ValueError('one bounded physical observation line required')
    number,line=matches[0]
    args=dict(expected_sha256=hashlib.sha256(source).hexdigest(),
        edits=[dict(start_line=number,end_line=number,new=line.replace(OLD,NEW,1))])
    result=prepare_template_lines(source,args)
    return args,result


def run(root,manifest,expected_variant_sha):
    root=Path(root);identity=verify_snapshot(root,manifest)
    source=(root/'tests/test_service_mode_indicator.py').read_bytes()
    args,result=recipe(source)
    if hashlib.sha256(result).hexdigest()!=expected_variant_sha:
        raise ValueError('line result differs from executed diagnostic experiment')
    verify_snapshot(root,manifest)
    return dict(operation='template_line_recipe_feasibility_v1',status='prepared',
        original_manifest_sha256=identity['manifest_sha256'],original_test_sha256=args['expected_sha256'],
        variant_test_sha256=expected_variant_sha,recipe=args,
        file_bytes=len(source),proposed_bytes=len(result),growth_bytes=len(result)-len(source),
        file_limit_bytes=32768,available_growth_bytes=32768-len(source),
        exact_experiment_variant=True,inputs_unchanged=True,diagnostic_only=True,
        valid_red_green_receipt=False,author_retry_authorized=False,delivery_approval=False)


if __name__=='__main__':
    if len(sys.argv)!=4:raise ValueError('fixed snapshot identity and variant required')
    print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
