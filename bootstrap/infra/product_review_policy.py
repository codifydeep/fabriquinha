"""Contextual policy for registered product cards; legacy boards stay unchanged."""
import json
from pathlib import Path

def validate(author,reviewer,card=None):
    if card and card.get('policy_version'):
        from product_policy import review_error
        return review_error(author,reviewer,card)
    from review_policy import validate_review
    return validate_review(author,reviewer)

def native_error(conn,task,author,reviewer):
    row=next((r for r in conn.execute('PRAGMA database_list') if r[1]=='main'),None)
    path=Path(row[2]).parent/'product-adapter.json' if row and row[2] else None
    card=None
    if path and path.is_file():card=json.loads(path.read_text()).get('cards',{}).get(task)
    return validate(author,reviewer,card)
