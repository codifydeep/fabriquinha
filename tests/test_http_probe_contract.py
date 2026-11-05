from types import SimpleNamespace
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.http_probe import probe_source,probe_diff,check_offer

class ProbeContract(unittest.TestCase):
    def setUp(self):
        self.spec=dict(case='spec.C.test_rule',prefix='/api/rooms/',action='play',pair='pair',resource='room_id',actor='guest',peer='host',payload={'rank':['held',0],'suit':['held',1]})
        self.old='class C:\n    def test_rule(self):\n        pair = self.setup()\n        held = (4, 5)\n        self.assertTrue(self.visible)\n'
        self.new=self.old+''.join('        '+line+'\n' for line in probe_source(self.spec).splitlines())
    def test_exact_error_distinguishes_two_409_responses(self):
        spec={**self.spec,'expected_error':'That card is not in your hand.'}
        candidate=self.old+''.join('        '+line+'\n' for line in probe_source(spec).splitlines())
        probe_diff(self.old,candidate,spec)
        with self.assertRaises(ValueError):
            probe_diff(self.old,candidate.replace('That card is not in your hand.', 'It is not your turn.'),spec)

    def test_exact_suffix(self):
        probe_diff(self.old,self.new,self.spec)
    def test_rejects_other_origin_actor_card_or_weaker_expectation(self):
        for new in (self.new.replace('self.target +','"https://example.com" +'),self.new.replace("['guest']","['host']"),
                    self.new.replace('409','200'),self.new.replace('self.assertTrue(self.visible)','pass'),self.new+'        self.fail()\n'):
            with self.subTest(new=new),self.assertRaises(ValueError):probe_diff(self.old,new,self.spec)
    def test_no_urls_or_python_from_descriptor(self):
        for key,bad in [('prefix','//host/'),('action','../other'),('pair','a()'),('actor',"x\' + bad()")]:
            with self.subTest(key=key),self.assertRaises(ValueError):probe_source({**self.spec,key:bad})

    def test_probe_offer_rejects_foreign_incident_or_inconclusive_mutation(self):
        project=SimpleNamespace(fingerprint=lambda:'project')
        binding={'actor':'controller','release':'release'}
        author={'kind':'tests','release':'release','reviewing':False}
        records={'offer':('http_probe_offer',binding,dict(spec=self.spec,project='project',incident='incident',parent='parent',freeze='freeze',qualification='trial',delivery_approval=False)),
                 'incident':('incident',author,dict(snapshot='rejected',submission_refusal='refusal')),
                 'refusal':('submission_refusal',author,dict(baseline='baseline',snapshot='rejected',error='only explicit product calls and local literal setup allowed')),
                 'freeze':('tests_frozen',{},dict(snapshot='baseline')),
                 'trial':('offline_http_probe_qualification',binding,dict(project='project',spec=self.spec,green='product',mutant='bad-product',delivery_approval=False,
                       results={'green':dict(count=1,errors=[],failures=[]),'mutant':dict(count=1,errors=[],failures=['AssertionError: 200 != 409'])}))}
        def receipt(key,kind):
            actual,b,payload=records[key];self.assertEqual(kind,actual)
            return dict(binding=b,payload=payload)
        store=SimpleNamespace(receipt=receipt)
        def validate():return check_offer(store,project,'offer','incident','parent','freeze')
        self.assertEqual(validate(),self.spec)
        records['offer'][2]['incident']='other'
        with self.assertRaises(ValueError):validate()
        records['offer'][2]['incident']='incident'
        records['trial'][2]['results']['mutant']['failures']=[]
        with self.assertRaises(ValueError):validate()
