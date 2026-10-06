"""Exact executable drain recipe, not generated code or evidence of execution."""
INDENT=' '*30
ANCHOR=(INDENT+'out.pending_left = pending.length;\n').encode()
OBSERVATION=(INDENT+'out.rendered_after_stale_status = renderedTitles();\n').encode()


class MicroDrainError(ValueError):pass


def recipe(operation):
    if operation not in ('resolveNewest','resolveOldest'):raise MicroDrainError('invalid micro drain resolver')
    return (INDENT+operation+'({items:[]});\n'+INDENT+'return flush().then(function () {\n'+
        INDENT+'  out.pending_left = pending.length;\n'+INDENT+'});\n')


def candidate(source,operation):
    lines=source.splitlines(keepends=True)
    if len(lines)<554 or lines[549]!=OBSERVATION or lines[550]!=ANCHOR:
        raise MicroDrainError('micro drain source anchor mismatch')
    return b''.join(lines[:550])+recipe(operation).encode()+b''.join(lines[551:])


def validate(args,operation,source=None):
    expected=[{'start_line':551,'end_line':551,'new':recipe(operation)}]
    if not isinstance(args,dict) or args.get('edits')!=expected:
        raise MicroDrainError('micro drain requires exact executable recipe')
    if source is not None:candidate(source,operation)


def verify(source,result,operation):
    if result!=candidate(source,operation):raise MicroDrainError('micro drain changed outside exact recipe')
    return True


def verify_snapshot(seed,result,expected_seed,expected_manifest,operation):
    from pathlib import Path
    import hashlib
    try:import maintenance_snapshot_validate as snapshots
    except ImportError:from broker import maintenance_snapshot_validate as snapshots
    seed,result=map(Path,(seed,result));_,before=snapshots.manifest(seed);raw,after=snapshots.manifest(result)
    if (before[snapshots.TEST]['sha256']!=expected_seed or hashlib.sha256(raw).hexdigest()!=expected_manifest
            or set(before)!=set(after) or any(before[p]!=after[p] for p in before if p!=snapshots.TEST)):
        raise MicroDrainError('micro drain snapshot identity mismatch')
    return verify(snapshots.product.regular_within(seed,snapshots.TEST),
        snapshots.product.regular_within(result,snapshots.TEST),operation)
