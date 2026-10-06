import sys
import hashlib
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planning_corrections import validate


class CorrectionsTests(unittest.TestCase):
    def test_editorial_correction_cannot_rewrite_approved_body(self):
        expected='# Histórias\n**Tarefa:** t_12345678\nApproved unchanged requirements.'
        card=dict(role='stories',correction_gate=True,exact_content_sha256=hashlib.sha256(expected.encode()).hexdigest())
        self.assertTrue(validate(card,expected)['passed'])
        with self.assertRaises(ValueError): validate(card,expected+'\nAdditional unrequested requirements.')
    def plan(self):
        return '\n'.join(f'- **TDD-{i:02d}** — entrega | backend_data → techlead | depende de: '+
            ('—' if i==1 else f'TDD-{i-1:02d}')+' | verificação: Red/Green e regressão' for i in range(1,22))
    def test_matrix_and_graph(self):
        self.assertTrue(validate(dict(role='plan',correction_gate=True),self.plan())['passed'])
        with self.assertRaises(ValueError): validate(dict(role='plan',correction_gate=True),self.plan().replace('backend_data → techlead','backend_data → devops',1))
    def test_cycle_and_missing_task(self):
        with self.assertRaises(ValueError): validate(dict(role='plan',correction_gate=True),self.plan().replace('depende de: —','depende de: TDD-21',1))
        with self.assertRaises(ValueError): validate(dict(role='plan',correction_gate=True),'\n'.join(self.plan().splitlines()[:-1]))
    def test_design_identifier(self):
        card=dict(role='design',correction_gate=True)
        with self.assertRaises(ValueError): validate(card,'BRIEF-TRUCO-v0.1-R1-202616')
        self.assertTrue(validate(card,'BRIEF-TRUCO-v0.1-R1-20260916')['passed'])
        self.assertTrue(validate(card,'BRIEF-TRUCO-v0.1-R1-20260916\n## Change log\nCorrected old BRIEF-TRUCO-v0.1-R1-202616 and briefly.')['passed'])
    def test_english_plan_format(self):
        self.assertTrue(validate(dict(role='plan',correction_gate=True),self.plan().replace('depende de:','depends on:'))['passed'])
