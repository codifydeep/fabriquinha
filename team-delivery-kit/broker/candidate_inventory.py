"""Fixed metadata-only inventory of validated editable product files.

Runs offline on controller-owned read-only volumes. Does not execute tests,
approve a delivery or alter the legacy Python diagnostic inventory.
"""
import hashlib
import json
try:
    from . import portable_snapshot_validate as structural
except ImportError:
    import portable_snapshot_validate as structural
from portable_contract import is_test_path


def inventory():
    proof=structural.verify()
    if proof.get('error'):raise ValueError('complete structural validation required')
    encoded=structural.regular_within(structural.DELIVERY,'manifest.json')
    if hashlib.sha256(encoded).hexdigest()!=proof['manifest_sha256']:
        raise ValueError('immutable candidate manifest changed during inventory')
    manifest=json.loads(encoded)
    contract=json.loads(structural.regular_within(structural.BASE,'contract.json'))
    names=set(contract['editable_files'])-set(contract['test_files'])-set(contract['protected_files'])
    products={name:manifest['files'][name]['sha256'] for name in sorted(names & set(manifest['files']))
        if not any(is_test_path(name,root,contract['test_command'][0]) for root in contract['test_roots'])}
    if not products:raise ValueError('declared product inventory required')
    return dict(proof,product_file_sha256=products,delivery_approval=False,tests_executed=False)


if __name__=='__main__':
    try:
        print(json.dumps(inventory(),sort_keys=True),flush=True)
    except Exception as error:
        print(json.dumps({'error':'candidate_inventory_failed','category':type(error).__name__}),flush=True)
        raise SystemExit(1)
