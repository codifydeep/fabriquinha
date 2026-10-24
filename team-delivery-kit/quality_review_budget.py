"""Bounded whole-page transport for the authenticated immutable review phase.

Not a tool grant, content capture or approval. Ordinary Hermes budgets remain
unchanged. The existing read journal's hard byte cap also bounds one tool turn;
the independent transport/context limits and controller attestation still apply.
"""
from dataclasses import is_dataclass,replace
from quality_review_paging import MAX_BYTES


def for_review(base,environment=None):
    from quality_review_stop import enabled
    if not enabled(environment):return base
    if (not is_dataclass(base) or isinstance(base,type)
            or type(getattr(base,'turn_budget',None)) is not int
            or not 0<base.turn_budget<=MAX_BYTES):
        raise ValueError('bounded immutable-review tool budget required')
    # read_file is already exempt from per-result spill upstream. Aggregate
    # spill must not replace its bytes with an unreadable /tmp preview either.
    # Actual pairs remain subject to MAX_PAIRS/MAX_BYTES, complete byte hashes,
    # real context compression and the unchanged model-proxy request ceiling.
    return replace(base,turn_budget=MAX_BYTES)
