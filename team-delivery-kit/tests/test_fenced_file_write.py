from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from broker.fenced_file_write import write_fenced


class FencedFileWriteTests(unittest.TestCase):
    def test_oversized_write_is_rejected_before_changing_existing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / 'test_new.py'
            target.write_bytes(b'preserved')
            with self.assertRaisesRegex(ValueError, 'size'):
                write_fenced(target, b'x' * 32769, root)
            self.assertEqual(target.read_bytes(), b'preserved')

    def test_writes_existing_target_and_rejects_symlink_and_unowned_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / 'code.py'
            target.write_text('old')
            with patch('broker.fenced_file_write.os.fstat', return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o666, st_uid=0, st_nlink=1)):
                write_fenced(target, b'new', root)
            self.assertEqual(target.read_bytes(), b'new')
            link = root / 'link.py'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                write_fenced(link, b'bad', root)
            with patch('broker.fenced_file_write.os.fstat', return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o666, st_uid=10000, st_nlink=1)):
                with self.assertRaises(ValueError):
                    write_fenced(target, b'bad', root)
            self.assertEqual(target.read_bytes(), b'new')
