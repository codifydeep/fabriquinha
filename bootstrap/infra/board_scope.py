"""Explicit deployment scope for native multi-board background watchers."""
import os
import re

def scoped(boards):
    allowed=os.environ.get('HERMES_ALLOWED_KANBAN_BOARD')
    if not allowed:
        return boards
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',allowed):
        raise ValueError('invalid deployment board scope')
    return [board for board in boards if board.get('slug')==allowed]


def list_boards(kb):
    allowed=os.environ.get('HERMES_ALLOWED_KANBAN_BOARD')
    if allowed:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',allowed):
            raise ValueError('invalid deployment board scope')
        # Do not enumerate inaccessible, archived or unrelated databases first.
        return scoped([kb.read_board_metadata(allowed)])
    return kb.list_boards(include_archived=False)
