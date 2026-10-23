"""Opt-in v2-only coordination; historical workflows stay inert and preserved.

This boundary does not resolve old incidents or authorize extra native roles.
It excludes legacy coordinators entirely, not merely their currently known rows.
"""
try:
    from . import quality_lifecycle_enrollment as enrollment,controller_maintenance as maintenance
except ImportError:
    import quality_lifecycle_enrollment as enrollment
    import controller_maintenance as maintenance


def require_enrolled(b,issue_id):
    enrollment.canonical(issue_id)
    with b.db() as con:record=enrollment.lookup(con,issue_id)
    if record is None or record['namespace']!=b.PREFIX:
        raise ValueError('exclusive v2 runtime rejects unenrolled historical issues')
    return record


def tick(b,*,team=None,progress=None):
    if getattr(b,'QUALITY_EXCLUSIVE_ENABLED',False) is not True:
        raise ValueError('exclusive coordinator requires explicit operator mode')
    flags=('QUALITY_V2_ENABLED','QUALITY_REVIEW_ENABLED','QUALITY_IMPLEMENTATION_ENABLED','QUALITY_TEAM_ENABLED')
    if any(getattr(b,k,False) is not True for k in flags):
        return dict(stage='configuration_blocked',missing=[k for k in flags if getattr(b,k,False) is not True],
            owner=getattr(b,'QUALITY_CTO',None) or 'cto',delivery_approval=False)
    if not maintenance.begin_cycle(b):return dict(stage='maintenance',delivery_approval=False)
    try:
        if team is None:
            try:from . import quality_team_progress as team
            except ImportError:import quality_team_progress as team
        if progress is None:
            try:from . import quality_progress as progress
            except ImportError:import quality_progress as progress
        team_result=team.tick(b);progress_result=progress.tick(b)
        return dict(stage='observed',team=team_result,progress=progress_result,delivery_approval=False)
    finally:maintenance.end_cycle(b)
