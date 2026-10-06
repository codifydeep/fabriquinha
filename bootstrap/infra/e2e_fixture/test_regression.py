import unittest
from app import winner
class Regression(unittest.TestCase):
    def test_zero(self): self.assertIsNone(winner(0,0))
