import sys
from pathlib import Path
import unittest
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.historical import AcceptedHistory

class HistoricalScope(unittest.TestCase):
    def records(self):
        binding=dict(actor='controller',task='release',release='old')
        qa_binding=dict(actor='qa',release='old',task='integration')
        return {'accepted':dict(binding=binding,payload=dict(graph='graph',final_qa='qa',project='p',state='HOMOLOGADA',commit='sha',qualification=False,delivery_approval=True)),
            'graph':dict(binding=binding,payload=dict(project='p',validation_bundle='old-bundle')),
            'qa':dict(binding=qa_binding,payload=dict(project='p',qa_job='job',commit='sha')),
            'job':dict(payload=dict(identity=dict(validation_bundle='old-bundle',browser_contract=2,binding=qa_binding),exit_code=0,report=dict(status='passed',source_sha='sha')))}

    def test_only_accepted_matching_qa_and_graph_can_select_history(self):
        records=self.records();project=NS(fingerprint=lambda:'p',qualification=False)
        store=NS(root=Path('/private/evidence'),receipt=lambda key,**kw:records[key],
                 manifest=lambda key:{'suite.py':{},'browser.py':{}},tree=lambda key:key)
        view=AcceptedHistory(project,store,'accepted')
        self.assertEqual(view.installation['validation_bundle'],'old-bundle')
        for method in ['capture','record','checkout']:
            with self.assertRaises(ValueError):getattr(view,method)()
        records['job']['payload']['identity']['validation_bundle']='foreign'
        with self.assertRaises(ValueError):AcceptedHistory(project,store,'accepted')
        records=self.records();records['accepted']['payload']['state']='ATIVA'
        with self.assertRaises(ValueError):AcceptedHistory(project,store,'accepted')
        records=self.records();records['qa']['payload']['commit']='other'
        with self.assertRaises(ValueError):AcceptedHistory(project,store,'accepted')
