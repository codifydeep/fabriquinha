"""Controller-owned QA recipes, never paths or commands supplied by agents.

New feature recipes remain disabled until their baseline composition and failure
cases have been qualified. The legacy recipe is preserved byte-for-byte.
"""
from pathlib import Path

LEGACY_SCENARIOS = (
    'feedback-board-v1', 'feedback-board-pending-v1',
    'feedback-board-pending-accessibility-v1', 'feedback-board-keyboard-dismiss-v1',
    'feedback-board-status-filter-api-v1', 'feedback-board-filter-v1',
    'feedback-board-sort-v1', 'feedback-board-search-api-v1',
    'feedback-board-search-v1', 'feedback-board-search-generation-v1',
    'feedback-board-service-status-api-v1', 'feedback-board-service-status-ui-v1',
    'feedback-board-demo-mode-api-v1', 'feedback-board-demo-mode-ui-v1',
)
DETAIL_SCENARIOS = ('feedback-board-detail-api-v1', 'feedback-board-detail-ui-v1')
SCENARIOS = LEGACY_SCENARIOS + DETAIL_SCENARIOS


def recipe_for(scenario):
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise ValueError('unqualified browser QA recipe')
    return Path(__file__).with_name('browser_feedback_detail.py' if scenario in DETAIL_SCENARIOS
                                   else 'browser_feedback_acceptance.py')


def baseline_for(scenario):
    if scenario in DETAIL_SCENARIOS:
        return 'feedback-board-demo-mode-ui-v1'
    return None
