from pathlib import Path
target=Path('/opt/hermes/gateway/kanban_watchers.py')
text=target.read_text()
if "__import__('board_scope').list_boards" not in text:
    text=text.replace("__import__('board_scope').scoped(_kb.list_boards(include_archived=False))","_kb.list_boards(include_archived=False)")
    text=text.replace("__import__('board_scope').scoped([_kb.read_board_metadata(_kb.DEFAULT_BOARD)])","[_kb.read_board_metadata(_kb.DEFAULT_BOARD)]")
    expressions=[('_kb.list_boards(include_archived=False)',4),
                 ('[_kb.read_board_metadata(_kb.DEFAULT_BOARD)]',4)]
    for expression,count in expressions:
        if text.count(expression)!=count:
            raise SystemExit('unexpected native board enumeration; refusing patch')
        replacement="__import__('board_scope').list_boards(_kb)" if expression.startswith('_kb.list') else "__import__('board_scope').scoped("+expression+")"
        text=text.replace(expression,replacement)
    target.write_text(text)
