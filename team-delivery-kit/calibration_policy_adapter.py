"""Closed version dispatch for calibration policies; never upgrade evidence.

This module does not authorize execution. Controller-owned phase, identity,
image and immutable delivery checks remain required by callers.
"""
from generic_harness_calibration import require,digest


def _adapter(p):
    require(isinstance(p,dict))
    identity=(p.get('version'),p.get('engine'))
    if identity==('generic_harness_calibration_v1','unittest_path_fixture_v1'):
        import generic_harness_calibration as adapter
        return adapter,'/generic_harness_calibration.py','generic_calibration_inputs_v1'
    if identity==('generic_harness_calibration_v2','unittest_path_fixtures_v2'):
        import generic_harness_calibration_v2 as adapter
        return adapter,'/generic_harness_calibration_v2.py','generic_calibration_inputs_v2'
    raise ValueError('unsupported calibration policy version/engine')


def validate_policy(p,expected):
    return _adapter(p)[0].validate_policy(p,expected)


def validate_receipt(r,p,expected):
    return _adapter(p)[0].validate_receipt(r,p,expected)


def executor(p):
    validate_policy(p,digest(p))
    return _adapter(p)[1]


def input_operation(p):
    validate_policy(p,digest(p))
    return _adapter(p)[2]


def product_paths(p):
    validate_policy(p,digest(p))
    if p['version']=='generic_harness_calibration_v1':
        return {m['product_path'] for m in p['modules']}
    return {f['product_path'] for m in p['modules'] for f in m['fixtures']}


def fixture_paths(p):
    validate_policy(p,digest(p))
    if p['version']=='generic_harness_calibration_v1':
        return {m['positive_fixture'] for m in p['modules']}|{n['fixture'] for n in p['negatives']}
    return ({f['positive_fixture'] for m in p['modules'] for f in m['fixtures']}
        |{r['fixture'] for n in p['negatives'] for r in n['replacements']})
