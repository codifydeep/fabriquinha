"""Necessary STATUS observation shape, never a semantic test or approval."""
import re

CONTRACT='c10-status-observations-v1'


class StatusAtomicError(ValueError):pass


def validate(args):
    edits=args.get('edits',[]) if isinstance(args,dict) else []
    if (len(edits)!=1 or edits[0].get('start_line')!=534 or edits[0].get('end_line')!=536
            or not isinstance(edits[0].get('new'),str) or '\n' not in edits[0]['new']):
        raise StatusAtomicError('atomic STATUS requires one complete multiline window')
    source=edits[0]['new']
    # Strip comments and mask quoted code. Only the actual filter ID literals
    # survive; a comment/string listing report names cannot satisfy this guard.
    tokens=re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`")
    def mask(match):
        value=match.group()
        if value in ("'filter-open'",'"filter-open"'):return "'filter-open'"
        if value in ("'filter-completed'",'"filter-completed"'):return "'filter-completed'"
        return ' ' if value.startswith(('/', '`')) else "'_'"
    code=tokens.sub(mask,source)
    patterns=[r"click\s*\(\s*byId\s*\[\s*'filter-open'\s*\]\s*\)",
        r"click\s*\(\s*byId\s*\[\s*'filter-completed'\s*\]\s*\)",
        r'out\.status_genA_urls\s*=\s*calls\.slice\s*\(',
        r'out\.status_genB_urls\s*=\s*calls\.slice\s*\(',
        r'out\.rendered_after_current_status\s*=\s*renderedTitles\s*\(',
        r'out\.rendered_after_stale_status\s*=\s*renderedTitles\s*\(',
        r'out\.pending_left\s*=\s*pending\.length\b']
    if (any(not re.search(pattern,code) for pattern in patterns)
            or len(re.findall(r'resolve(?:Newest|Oldest)\s*\(\s*\{\s*items\s*:\s*\[',code))<2
            or len(re.findall(r'flush\s*\(\s*\)\.then\s*\(',code))<2):
        raise StatusAtomicError('atomic STATUS missing complete real observation operations')
