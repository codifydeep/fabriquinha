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


def scale_files():
    """Fixed synthetic input only; no product, environment, I/O or credentials."""
    # 563,066 bytes: at least the current native snapshot's 552,750 bytes,
    # without exporting any product content or private file identities.
    return {f'scale/file-{n:03}.py':''.join(f'# fixture line {i}'.ljust(36,'x')+'\n'
        for i in range(868 if n==0 else 205)).encode() for n in range(71)}


def validate_scale(value):
    expected=dict(operation='real_hermes_review_scale_compaction_v1',files=71,pages=219,
        main_provider_calls=23,max_iterations=40,complete_files=71,
        duplicate_reads=0,eof_reads=0,snapshot_unchanged=True,
        model_calls=0,tests_approved=False,delivery_approval=False)
    if not isinstance(value,dict) or set(value)!=set(expected)|{'dropped_read_pairs','summary_provider_calls','compactions'}:
        raise ValueError('exact real-Hermes scale and compaction evidence required')
    for key,item in expected.items():
        if type(value[key]) is not type(item) or value[key]!=item:
            raise ValueError('exact real-Hermes scale and compaction evidence required')
    if type(value['dropped_read_pairs']) is not int or not 1<=value['dropped_read_pairs']<=219:
        raise ValueError('actual read removal required, not an invoked no-op compressor')
    if (type(value['compactions']) is not int or not 1<=value['compactions']<=4
            or type(value['summary_provider_calls']) is not int or value['summary_provider_calls']!=value['compactions']):
        raise ValueError('each bounded compaction requires one successful fixed summary')
    return value
