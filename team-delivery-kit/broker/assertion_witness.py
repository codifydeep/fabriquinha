"""Fixed offline extractor: only fixture literals from hash-verified NEW tests."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re


def extract(root, hashes, output):
    if not isinstance(output, str) or len(output.encode()) > 65536:
        raise ValueError('bounded saved output required')
    manifest_raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)['files']
    literals = {}
    for name, digest in hashes.items():
        if not re.fullmatch(r'tests/[A-Za-z0-9_/]+\.py', name) or '..' in name:
            raise ValueError('frozen test path required')
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ValueError('bounded regular frozen test required')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest or manifest[name]['sha256'] != digest:
            raise ValueError('frozen test hash mismatch')
        literals[name[:-3].replace('/', '.')] = {
            n.value for n in ast.walk(ast.parse(raw))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    witnesses = []
    current = None
    for line in output.splitlines():
        header = re.fullmatch(r'(?:FAIL|ERROR): test_[A-Za-z0-9_]+ \(([A-Za-z0-9_.]+)\)', line)
        if header:
            current = header[1]
            continue
        if not current or not line.startswith('AssertionError: Lists differ: '):
            continue
        names = [module for module in literals if current.startswith(module + '.')]
        if len(names) != 1 or len(line) > 1600:
            continue
        parts = line.removeprefix('AssertionError: Lists differ: ').split(' != ', 1)
        if len(parts) != 2:
            continue
        try:
            observed, expected = [ast.literal_eval(value) for value in parts]
        except (ValueError, SyntaxError, RecursionError, MemoryError):
            continue
        def safe(value):
            return (type(value) is list and len(value) <= 4 and all(
                isinstance(item, str) and 1 <= len(item) <= 80
                and re.fullmatch(r'[\w .-]+', item) and item in literals[names[0]]
                for item in value))
        if not safe(observed) or not safe(expected):
            continue
        witnesses.append({'qualified_name': current, 'observed': observed, 'expected': expected})
        if len(witnesses) == 4:
            break
    return {'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
            'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
            'witnesses': witnesses, 'fixture_literals_only': True}


def extract_trace(root,hashes,output):
    """Hash-verified assertion locations and field identifiers, never raw log text."""
    proof=extract(root,hashes,output)
    trees={p:ast.parse((root/p).read_bytes()) for p in hashes}
    anchors=[];current=None;frame=None
    for line in output.splitlines():
        header=re.fullmatch(r'(?:FAIL|ERROR): (test_[A-Za-z0-9_]+) \(([A-Za-z0-9_.]+)\)',line)
        if header:current=(header[1],header[2]);frame=None;continue
        match=re.fullmatch(r'  File "(/delivery/[^"\n]+)", line ([0-9]{1,6}), in (test_[A-Za-z0-9_]+)',line)
        if match and current and match[3]==current[0]:
            path=match[1].removeprefix('/delivery/')
            if path in hashes and current[1].startswith(path[:-3].replace('/','.')+'.'):
                frame=(path,int(match[2]))
        if not line.startswith('AssertionError:') or not current or not frame:continue
        path,number=frame;tree=trees[path]
        methods=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==current[0] and n.lineno<=number<=n.end_lineno]
        calls=[n for m in methods for n in ast.walk(m) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
               and n.func.attr in ('assertTrue','assertFalse','assertEqual','assertIn','assertNotIn','assertIsNone','assertIsNotNone','assertNotEqual',
                                   'assertGreaterEqual','assertGreater','assertLessEqual','assertLess')
               and n.lineno<=number<=n.end_lineno]
        if len(methods)!=1 or len(calls)!=1:continue
        call=calls[0]
        fields=sorted({n.slice.value for arg in call.args[:2] for n in ast.walk(arg)
            if isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str)
            and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',n.slice.value)})[:16]
        anchor=dict(qualified_name=current[1],file=path,line=number,assertion=call.func.attr,fields=fields,
            assertion_ast_sha256=hashlib.sha256(ast.dump(call,include_attributes=False).encode()).hexdigest())
        if line.startswith('AssertionError: False is not true'):anchor['observed_boolean']=False
        elif line.startswith('AssertionError: True is not false'):anchor['observed_boolean']=True
        if call.func.attr=='assertIn' and call.args and isinstance(call.args[0],ast.Constant) and type(call.args[0].value) is str:
            expected=call.args[0].value
            # Parse only bounded literal operands. Never expose arbitrary messages,
            # runtime strings, expressions, or values absent from this assertion.
            pieces=line.removeprefix('AssertionError: ').split(' not found in ',1)
            if len(pieces)==2 and len(line)<=1600 and re.fullmatch(r'[\w .-]{1,80}',expected):
                try: member,container=(ast.literal_eval(v) for v in pieces)
                except (ValueError,SyntaxError,MemoryError,RecursionError): member=container=None
                fixture_literals={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and type(n.value) is str}
                if member==expected and type(container) is list and len(container)<=4 and all(type(v) is str and v in fixture_literals and re.fullmatch(r'[\w .-]{1,80}',v) for v in container):
                    anchor['membership']=dict(expected_member=expected,observed_container=container)
        anchors.append(anchor);frame=None
        if len(anchors)>=16:break
    return {**proof,'anchors':anchors,'operation':'frozen_assertion_trace_anchors_v1','approval':False}


if __name__ == '__main__':
    operation=extract_trace if os.environ.get('ASSERTION_TRACE')=='1' else extract
    print(json.dumps(operation(Path('/delivery'), json.loads(os.environ['FROZEN_TEST_HASHES']),
                            json.loads(os.environ['SAVED_OUTPUT'])), sort_keys=True), flush=True)
