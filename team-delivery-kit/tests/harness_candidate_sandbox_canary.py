"""Controller test fixture only: never register this synthetic tree as delivery.

Run in a credential-free container with /fixture read-only and /tmp writable.
Qualifies the admission mechanism, NOT author work or independent approval.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from harness_candidate_probe import TEST, run


def main():
    root=Path(tempfile.mkdtemp(prefix='harness-gate-canary-'))/'candidate'
    shutil.copytree('/fixture',root)
    # Only the throwaway COPY is writable, never the read-only fixture mount.
    root.chmod(0o700)
    for path in root.rglob('*'):
        if not path.is_symlink():path.chmod(0o700 if path.is_dir() else 0o600)
    original=(root/TEST).read_text()
    tree=ast.parse(original)
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='NODE_HARNESS_TEMPLATE' for t in n.targets))
    template=ast.literal_eval(assignment.value)
    methods=list(re.finditer(r'querySelectorAll\s*[:=]\s*function\s*\(([A-Za-z_$][A-Za-z0-9_$]*)\)\s*\{',template))
    for method in reversed(methods):
        adapter=('\nconst _canaryMatch=/^([a-zA-Z][a-zA-Z0-9_-]*)\\[([a-zA-Z][a-zA-Z0-9_-]*)='
            '(?:"([^"]*)"|\'([^\']*)\'|([^\\]]+))\\]$/.exec('+method[1]+');'
            'if(_canaryMatch){const value=_canaryMatch[3]??_canaryMatch[4]??_canaryMatch[5];'
            'return this.querySelectorAll(_canaryMatch[1]).filter(el=>el.getAttribute(_canaryMatch[2])===value);}\n')
        template=template[:method.end()]+adapter+template[method.end():]
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FeedbackSearchClientTests')
    lines=original.splitlines(keepends=True)
    # Insert before the old class's last line boundary; offsets use original AST.
    lines.insert(cls.end_lineno,'\n    def test_controller_canary_negative(self):\n        self.assertNotEqual("search", "not-real")\n')
    lines[assignment.value.lineno-1:assignment.value.end_lineno]=[repr(template)+'\n']
    # Retain the assignment prefix; original template is a multiline literal.
    lines[assignment.value.lineno-1]='NODE_HARNESS_TEMPLATE = '+lines[assignment.value.lineno-1]
    (root/TEST).write_text(''.join(lines))
    manifest=json.loads((root/'manifest.json').read_text())
    raw=(root/TEST).read_bytes()
    manifest['files'][TEST]['sha256']=hashlib.sha256(raw).hexdigest()
    if 'bytes' in manifest['files'][TEST]:manifest['files'][TEST]['bytes']=len(raw)
    (root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
    accepted=run(root,'/fixture')
    if accepted['delivery_approval'] is not False:raise ValueError('canary cannot approve delivery')
    # Changed bytes with the ORIGINAL defective harness must fail real controls.
    negative=original.splitlines(keepends=True)
    negative.insert(cls.end_lineno,'\n    def test_controller_canary_negative(self):\n        self.assertNotEqual("search", "not-real")\n')
    (root/TEST).write_text(''.join(negative))
    raw=(root/TEST).read_bytes();manifest['files'][TEST]['sha256']=hashlib.sha256(raw).hexdigest()
    (root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
    try:run(root,'/fixture')
    except ValueError as error:
        if str(error)!='candidate positive selector control failed':raise
        print(json.dumps(dict(operation='harness_admission_sandbox_canary_v1',
            valid_adapter_controls=True,unchanged_harness_rejected=True,
            delivery_approval=False,synthetic_fixture=True)))
    else:raise ValueError('defective harness unexpectedly accepted')


if __name__=='__main__':main()
