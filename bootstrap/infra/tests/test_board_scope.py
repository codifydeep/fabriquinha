import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from board_scope import scoped
from board_scope import list_boards
from unittest.mock import Mock

class BoardScopeTests(unittest.TestCase):
    def test_rehearsal_does_not_enumerate_product_or_default(self):
        with patch.dict(os.environ,{'HERMES_ALLOWED_KANBAN_BOARD':'rehearsal'}):
            self.assertEqual(scoped([{'slug':'default'},{'slug':'product'},{'slug':'rehearsal'}]),[{'slug':'rehearsal'}])
            self.assertEqual(scoped([{'slug':'default'}]),[])

    def test_unconfigured_legacy_scope_is_preserved(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(scoped([{'slug':'default'}]),[{'slug':'default'}])

    def test_targeted_lookup_never_enumerates_inaccessible_other_boards(self):
        kb=Mock()
        kb.list_boards.side_effect=PermissionError('unrelated private board')
        kb.read_board_metadata.return_value={'slug':'rehearsal'}
        with patch.dict(os.environ,{'HERMES_ALLOWED_KANBAN_BOARD':'rehearsal'}):
            self.assertEqual(list_boards(kb),[{'slug':'rehearsal'}])
        kb.list_boards.assert_not_called()
