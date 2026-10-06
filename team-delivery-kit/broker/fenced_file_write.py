"""In-place write to one precreated phase-writable file in the fenced workspace."""
import os
from pathlib import Path
import stat
import sys

# Match the immutable snapshot/workspace reader, not the larger ACP payload cap.
MAX_BYTES = 32768


def write_fenced(path, content, root=Path('/workspace')):
    target = Path(path)
    if (not target.is_absolute() or '..' in target.parts or target.resolve() != target
            or root not in target.parents or len(content) > MAX_BYTES):
        raise ValueError('invalid fenced write target or size')
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
    write_fenced(sys.argv[1], sys.stdin.buffer.read(MAX_BYTES + 1))
