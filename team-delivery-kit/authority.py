"""Small, executable authority boundary for project-team decisions.

Routing a question is not permission to merge, bypass controls or use a tool.
The CEO is consulted only for product choices, scope/brief approval, explicit
test-contract exceptions, or a credential supplied through a secure channel.
"""
from dataclasses import dataclass
from enum import Enum
import re


class Kind(str, Enum):
    PRODUCT_BEHAVIOR = 'product_behavior'
    BRIEF_APPROVAL = 'brief_approval'
    SCOPE_CHANGE = 'scope_change'
    TECHNICAL_BLOCKER = 'technical_blocker'
    ARCHITECTURE = 'architecture'
    SECURITY_DESIGN = 'security_design'
    TEST_CONTRACT_EXCEPTION = 'test_contract_exception'
    CREDENTIAL_NEEDED = 'credential_needed'


ROUTE = {
    Kind.PRODUCT_BEHAVIOR: ('produto', 'ceo'),
    Kind.BRIEF_APPROVAL: ('produto', 'ceo'),
    Kind.SCOPE_CHANGE: ('produto', 'ceo'),
    Kind.TECHNICAL_BLOCKER: ('techlead', 'cto'),
    Kind.ARCHITECTURE: ('cto',),
    Kind.SECURITY_DESIGN: ('quality_security', 'cto'),
    Kind.TEST_CONTRACT_EXCEPTION: ('quality_security', 'techlead', 'ceo'),
    Kind.CREDENTIAL_NEEDED: ('techlead', 'ceo'),
}


@dataclass(frozen=True)
class Question:
    question_id: str
    release_id: str
    kind: Kind
    summary: str
    options: tuple[str, ...]

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{2,63}', self.question_id):
            raise ValueError('stable question id required')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,63}', self.release_id):
            raise ValueError('stable release id required')
        if not self.summary.strip() or not 2 <= len(self.options) <= 4 \
                or any(not option.strip() for option in self.options):
            raise ValueError('question needs context and two to four explicit options')


def route(question: Question, attempted_roles: tuple[str, ...] = ()) -> str:
    """Escalate only after the prior owner made an attempt with evidence."""
    chain = ROUTE[question.kind]
    if attempted_roles != chain[:len(attempted_roles)]:
        raise ValueError('non-sequential or duplicate escalation')
    if len(attempted_roles) >= len(chain):
        raise ValueError('all authorized decision owners exhausted')
    return chain[len(attempted_roles)]


def ceo_answer_scope(question: Question, selected_option: str) -> dict:
    if route(question, ROUTE[question.kind][:-1]) != 'ceo':
        raise ValueError('CEO is not an owner for this decision')
    if selected_option not in question.options:
        raise ValueError('answer must select an offered option')
    return {'question_id': question.question_id, 'release_id': question.release_id,
            'selected_option': selected_option, 'scope': question.kind.value,
            'authorizes_merge': False, 'authorizes_tools': False,
            'waives_security': False}


def independent_review(author: str, reviewer: str, approved_head: str, current_pr_head: str) -> None:
    if not author or not reviewer or author == reviewer:
        raise ValueError('independent reviewer required')
    if not re.fullmatch(r'[0-9a-f]{40}', approved_head) or approved_head != current_pr_head:
        raise ValueError('review must cover exact PR head')
