from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from broker.fenced_file_write import write_fenced


class FencedFileWriteTests(unittest.TestCase):
    def test_invalid_python_quote_patch_preserves_last_good_bytes_before_open(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py'
            original=b"QUERY = 'calls.length'\n";target.write_bytes(original)
            invalid=b"QUERY = 'calls.filter(c => c.url === '/service-mode').length'\n"
            with patch('broker.fenced_file_write.os.open') as opened:
                with self.assertRaisesRegex(ValueError,'Python syntax rejected.*No bytes were changed') as error:
                    write_fenced(target,invalid,root)
                opened.assert_not_called()
            self.assertEqual(target.read_bytes(),original)
            self.assertNotIn('/service-mode',str(error.exception))
            self.assertIsNone(error.exception.__cause__)

    def test_invalid_encoding_and_null_bytes_do_not_truncate_python(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'code.py';target.write_bytes(b'VALUE = 0\n')
            for content in (b'VALUE = \x00\n',b'# coding: utf-8\nVALUE = "\xff"\n'):
                with self.assertRaisesRegex(ValueError,'Python syntax rejected'):
                    write_fenced(target,content,root)
                self.assertEqual(target.read_bytes(),b'VALUE = 0\n')

    def test_valid_python_is_parsed_without_import_or_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'code.py';target.write_bytes(b'VALUE = 0\n')
            marker=root/'must-not-exist'
            source=('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n').encode()
            with patch('broker.fenced_file_write.os.fstat',return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG|0o666,st_uid=0,st_nlink=1)):
                write_fenced(target,source,root)
            self.assertEqual(target.read_bytes(),source);self.assertFalse(marker.exists())

    def test_other_file_types_remain_under_original_write_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'fixture.txt';target.write_bytes(b'old')
            with patch('broker.fenced_file_write.os.fstat',return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG|0o666,st_uid=0,st_nlink=1)):
                write_fenced(target,b'not Python: {',root)
            self.assertEqual(target.read_bytes(),b'not Python: {')

    def test_oversized_write_is_rejected_before_changing_existing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / 'test_new.py'
            target.write_bytes(b'preserved')
            with self.assertRaisesRegex(ValueError, 'size'):
                write_fenced(target, b'x' * 32769, root)
            self.assertEqual(target.read_bytes(), b'preserved')

    def test_size_error_identifies_limit_without_payload_and_path_error_is_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py';target.write_bytes(b'unchanged')
            with self.assertRaisesRegex(ValueError,'size exceeds 32768 bytes; received at least 32769'):
                write_fenced(target,b'x'*32769,root)
            with self.assertRaisesRegex(ValueError,'invalid fenced write target'):
                write_fenced(root/'..'/'forbidden.py',b'x',root)
            self.assertEqual(target.read_bytes(),b'unchanged')

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
