"""Untrusted archive metadata cannot escape an offline private inspection."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_installation_backup import verify

class BackupInspection(unittest.TestCase):
    def test_rejects_traversal_symlinks_and_external_hardlinks_before_extraction(self):
        for kind in ('traversal','symlink','hardlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                base=Path(folder);archive=base/'backup.tar.gz'
                info=tarfile.TarInfo('installation/../../escaped' if kind=='traversal' else 'installation/entry')
                if kind=='symlink':info.type=tarfile.SYMTYPE;info.linkname=str(base/'escaped')
                if kind=='hardlink':info.type=tarfile.LNKTYPE;info.linkname='../../escaped'
                with tarfile.open(archive,'w:gz') as stream:stream.addfile(info,io.BytesIO())
                with self.assertRaises(ValueError):verify(archive,base/'inspection',base/'unused-counter')
                self.assertFalse((base/'escaped').exists())
                self.assertFalse((base/'inspection/installation').exists())
    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);destination=base/'inspection';destination.mkdir()
            sentinel=destination/'keep';sentinel.write_text('keep')
            with self.assertRaises(ValueError):verify(base/'unused',destination,base/'unused-counter')
            self.assertEqual(sentinel.read_text(),'keep')

if __name__=='__main__':unittest.main()
