"""Classify fixed witness measurements without rerunning or approving a test.

The legacy stale_witness_selectivity_passed field aggregates ordering AND request
counts. Frozen assertion bindings remain authoritative: do not mistake a count
failure for failed stale-response discrimination or lower the required count.
"""
from generic_harness_calibration import require


def assess(config,inspection):
    bound=config['counterexample']['facts']['assertion_bindings']
    expected,minimum,wanted=(bound[k] for k in ('initial_expected','poll_minimum','stale_expected'))
    require(type(expected) is int and type(minimum) is int and 0<=expected<=100 and 0<=minimum<=100
        and isinstance(wanted,str) and set(inspection['reports'])=={'guarded','unguarded'}
        and type(inspection['stale_witness_selectivity_passed']) is bool)
    reports=inspection['reports']
    for report in reports.values():
        require(set(report)=={'initial_requests','poll_requests','stale_guard_text'}
            and type(report['initial_requests']) is int and type(report['poll_requests']) is int
            and isinstance(report['stale_guard_text'],str))
    ordering=reports['guarded']['stale_guard_text']==wanted and reports['unguarded']['stale_guard_text']!=wanted
    initial=all(r['initial_requests']==expected for r in reports.values())
    polling=all(r['poll_requests']>=minimum for r in reports.values())
    passed=ordering and initial and polling
    require(inspection['stale_witness_selectivity_passed'] is passed)
    return dict(operation='literal_witness_assessment_v1',stale_ordering_passed=ordering,
        initial_requests_passed=initial,poll_requests_passed=polling,all_protocol_checks_passed=passed,
        expected_initial_requests=expected,minimum_poll_requests=minimum,expected_stale_text=wanted,
        measurements={name:dict(report) for name,report in reports.items()},
        delivery_approval=False,functional_red=False)
