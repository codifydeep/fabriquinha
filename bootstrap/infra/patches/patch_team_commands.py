from pathlib import Path
TARGET=Path('/opt/hermes/gateway/slash_commands.py')
ANCHOR='        from hermes_cli.kanban import run_slash\n'
BLOCK='''        from team_control import handle_command
        team_result = await asyncio.to_thread(handle_command, event.text or "", event.source)
        if team_result is not None:
            return team_result
'''


def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR)!=1:
        raise ValueError('unknown kanban command entry')
    return source.replace(ANCHOR,ANCHOR+BLOCK)


if __name__=='__main__':
    TARGET.write_text(apply(TARGET.read_text()))
