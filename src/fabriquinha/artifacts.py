"""Controller-owned content-addressed snapshots and receipts, outside workspaces."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

EXCLUDED = {'.git', '.venv', 'node_modules', '__pycache__'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('content identity required')
    return value


def files(root):
    root = Path(root)
    result = {}
    total = 0
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for name in [*dirs, *names]:
            path = Path(folder) / name
            if path.is_symlink():
                raise ValueError('snapshot cannot contain symlinks')
        for name in sorted(names):
            if name.endswith(('.pyc', '.pyo')) or name == '.env' or name.startswith('.env.') and name != '.env.example':
                continue
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            if any(ord(c) < 32 for c in relative):
                raise ValueError('invalid artifact path')
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
                raise ValueError('bounded regular artifact required')
            total += info.st_size
            if total > 128 * 1024 * 1024:
                raise ValueError('snapshot exceeds initial project bound')
            result[relative] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    bytes=info.st_size, executable=bool(info.st_mode & 0o111))
    return result


def protected_unchanged(before, after, *, prefixes):
    for path, value in before.items():
        if any(path == p or path.startswith(p) for p in prefixes):
            if after.get(path) != value:
                raise ValueError('protected baseline changed: ' + path)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('objects', 'receipts'):
            (self.root / name).mkdir(mode=0o700, exist_ok=True)

    def capture(self, source):
        source = Path(source).resolve()
        if self.root.is_relative_to(source) or source.is_relative_to(self.root):
            raise ValueError('artifact store must be outside author workspace')
        manifest = files(source)
        key = digest(manifest)
        target = self.root / 'objects' / key
        if target.exists():
            self.tree(key)
            return key
        temporary = Path(tempfile.mkdtemp(prefix='.capture-', dir=self.root / 'objects'))
        tree = temporary / 'tree'
        tree.mkdir()
        try:
            for relative, info in manifest.items():
                destination = tree / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, destination, follow_symlinks=False)
                destination.chmod(0o555 if info['executable'] else 0o444)
            if files(tree) != manifest:
                raise ValueError('source changed during capture')
            (temporary / 'manifest.json').write_bytes(encoded(manifest))
            for directory, _, _ in os.walk(tree):
                Path(directory).chmod(0o555)
            try:
                os.rename(temporary, target)
            except FileExistsError:
                self.tree(key)
            return key
        finally:
            if temporary.exists():
                for directory, _, _ in os.walk(temporary):
                    Path(directory).chmod(0o700)
                shutil.rmtree(temporary)

    def manifest(self, key):
        raw = (self.root / 'objects' / identity(key) / 'manifest.json').read_bytes()
        value = json.loads(raw)
        if digest(value) != key:
            raise ValueError('artifact manifest changed')
        return value

    def tree(self, key):
        path = self.root / 'objects' / identity(key) / 'tree'
        if files(path) != self.manifest(key):
            raise ValueError('immutable snapshot changed')
        return path

    def checkout(self, key, destination):
        """Seed only an empty assigned workspace; never reset ongoing work."""
        destination = Path(destination)
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('refusing to overwrite existing work')
        source = self.tree(key)
        manifest = self.manifest(key)
        destination.mkdir(parents=True, exist_ok=True)
        for relative in manifest:
            path = destination/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source/relative, path)
            path.chmod(0o777 if manifest[relative]['executable'] else 0o666)
        for folder, _, _ in os.walk(destination):
            Path(folder).chmod(0o777)
        return destination

    def record(self, kind, binding, payload):
        value = dict(version=1, kind=kind, binding=binding, payload=payload)
        key = digest(value)
        path = self.root / 'receipts' / (key + '.json')
        fd, name = tempfile.mkstemp(prefix='.receipt-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded(value))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(name, path)
            except FileExistsError:
                self.receipt(key)
        finally:
            os.unlink(name)
        return key

    def receipt(self, key, *, kind=None):
        path = self.root / 'receipts' / (identity(key) + '.json')
        if path.is_symlink():
            raise ValueError('controller receipt cannot be a symlink')
        value = json.loads(path.read_bytes())
        if digest(value) != key or kind is not None and value.get('kind') != kind:
            raise ValueError('controller receipt changed or has wrong kind')
        return value
