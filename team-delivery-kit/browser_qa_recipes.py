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


def recipe_for(scenario):
    if not isinstance(scenario, str) or scenario not in LEGACY_SCENARIOS:
        raise ValueError('unqualified browser QA recipe')
    return Path(__file__).with_name('browser_feedback_acceptance.py')
