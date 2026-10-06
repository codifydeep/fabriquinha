import unittest
from app import winner
class Acceptance(unittest.TestCase):
    def test_a(self): self.assertEqual(winner(12,0),'A')
    def test_b(self): self.assertEqual(winner(0,12),'B')
    def test_priority(self): self.assertEqual(winner(12,13),'A')
    def test_none(self): self.assertIsNone(winner(11,11))
    def test_over(self): self.assertEqual(winner(13,0),'A')
    def test_b_over(self): self.assertEqual(winner(0,13),'B')
