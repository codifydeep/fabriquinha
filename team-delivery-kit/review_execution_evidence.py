"""Strict facts from fixed Hermes execution controls, never review approval."""


def validate(value):
    def require(ok):
        if not ok:raise ValueError('exact real-Hermes execution control evidence required')
    require(isinstance(value,dict) and set(value)=={'operation','stall','budget',
        'preflight_then_dispatch','direct_duplicate_denied','snapshot_unchanged','model_calls'}
        and value['operation']=='real_hermes_review_execution_controls_v1'
        and type(value['model_calls']) is int and value['model_calls']==0
        and all(value[k] is True for k in ('preflight_then_dispatch','direct_duplicate_denied','snapshot_unchanged')))
    for mode,calls,iterations,category in [('stall',3,40,'read_progress_stalled'),
            ('budget',1,1,'iteration_budget_exhausted')]:
        case=value[mode]
        require(isinstance(case,dict) and set(case)=={'provider_calls','category','fixture_iterations'}
            and type(case['provider_calls']) is int and case['provider_calls']==calls
            and type(case['fixture_iterations']) is int and case['fixture_iterations']==iterations
            and case['category']==category)
    return value
