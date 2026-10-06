"""Narrow citation choices to actual completed reads; never assess a verdict."""
import ast
import json
import re
from artifact_read_evidence import coverage

MARKER='DELIVERY_OBSERVED_FINDINGS_V1'


def constrain(item, messages, paths):
    reads=coverage(messages,wire=True,include_content=True)
    choices=[]
    for path in sorted(paths):
        match=re.fullmatch(r'/evidence/(candidate|previous)/([A-Za-z0-9_./-]+)',path)
        read=reads.get(path) or {}
        if (not match or '/../' in path or not read.get('lines')
                or read.get('lines')!=read.get('total_lines')):
            raise ValueError('complete observed citation source required')
        lines=read['line_content'];methods=[]
        if path.endswith('.py'):
            try:
                tree=ast.parse('\n'.join(lines[i] for i in range(1,read['total_lines']+1)))
            except SyntaxError:
                tree=None  # broken source can only be cited as module evidence
            def visit(nodes,prefix=''):
                for node in nodes:
                    if isinstance(node,ast.ClassDef):visit(node.body,prefix+node.name+'.')
                    elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                        methods.append((prefix+node.name,node.lineno,node.end_lineno))
            if tree:visit(tree.body)
        for number,text in sorted(lines.items()):
            quote=text.strip()
            if not quote:continue
            # The fixed findings contract allows <=500 characters. Any exact
            # observed prefix is a legitimate substring, never a repaired quote.
            quote=quote[:500]
            symbols=['__module__']+[symbol for symbol,start,end in methods if start<=number<=end]
            choices.append({'properties':{
                'tree':{'enum':[match[1]]},'path':{'enum':[match[2]]},
                'test':{'enum':symbols},'line':{'enum':[number]},'quote':{'enum':[quote]}}})
    if not choices or len(choices)>2048 or len(json.dumps(choices))>500000:
        raise ValueError('observed citation index exceeds fixed bound')
    # All original kind/expected/observed/length/required-field constraints stay.
    return {**item,'anyOf':choices}
