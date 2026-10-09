"""In-place write to one precreated phase-writable file in the fenced workspace."""
import os
import ast
from pathlib import Path
import stat
import sys
from portable_contract import MAX_FILE_BYTES

# New tests retain the Red-capture bound; product artifacts use the contract cap.
MAX_BYTES = 32768


def write_limit(target, root):
    relative=target.relative_to(root)
    name=relative.name
    test=(name.startswith('test_') and name.endswith('.py')
          or name.endswith(('.test.js','.spec.js','.test.ts','.spec.ts','.test.tsx','.spec.tsx'))
          or any(part in ('tests','__tests__') for part in relative.parts[:-1]))
    return MAX_BYTES if test else MAX_FILE_BYTES


def write_fenced(path, content, root=Path('/workspace')):
    target = Path(path)
    if (not target.is_absolute() or '..' in target.parts or target.resolve() != target
            or root not in target.parents):
        raise ValueError('invalid fenced write target')
    limit=write_limit(target,root)
    if len(content)>limit:
        raise ValueError('fenced write size exceeds '+str(limit)+' bytes; received at least '+str(len(content))+
            ' bytes. Keep the declared artifact within its bound; preserve all test methods, '
            'assertions and acceptance. No bytes were changed.')
    if target.suffix == '.py':
        try:
            # Parse proposed bytes only: never import, compile to disk or execute.
            ast.parse(content)
        except (SyntaxError, ValueError, UnicodeError):
            # Do not leak the source line through SyntaxError's traceback.
            raise ValueError('fenced Python syntax rejected. Correct the proposed patch using '
                'the existing file; preserve assertions and baseline. No bytes were changed.') from None
    descriptor = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or not info.st_mode & 0o222):
            raise ValueError('target is not a controller-owned writable regular file')
        os.ftruncate(descriptor, 0)
        remaining = memoryview(content)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise OSError('incomplete fenced write')
            remaining = remaining[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise ValueError('one exact path required')
    write_fenced(sys.argv[1], sys.stdin.buffer.read(MAX_FILE_BYTES + 1))
