import unittest
import json,subprocess
from service_mode_harness_qualification import CASES,fixture,validate_controls
from inherited_harness_probe import syntax


class HarnessQualificationTests(unittest.TestCase):
    def facts(self,**changes):
        return dict(tests=1,failures=1,errors=0,skipped=0,unexpected_successes=0,expected_failures=0,**changes)

    def test_all_fixed_controls_compile_and_have_distinct_bytes(self):
        values=[fixture(case) for case in ['positive',*CASES]]
        self.assertEqual(len(values),len(set(values)))
        for value in values:self.assertEqual(syntax(value)['exit_code'],0)
        with self.assertRaises(ValueError):fixture('agent-supplied-code')

    def test_positive_success_and_every_actual_negative_assertion_required(self):
        positive=dict(tests=15,failures=0,errors=0,skipped=0,unexpected_successes=0,expected_failures=0)
        negative={case:self.facts() for case in CASES}
        validate_controls(positive,negative)
        for field,value in [('failures',1),('errors',1),('skipped',1),('tests',14),('expected_failures',1)]:
            with self.assertRaises(ValueError):validate_controls({**positive,field:value},negative)
        for field,value in [('failures',0),('errors',1),('skipped',1),('tests',0),('expected_failures',1)]:
            altered={**negative,'duplicate_request':{**negative['duplicate_request'],field:value}}
            with self.assertRaises(ValueError):validate_controls(positive,altered)
        with self.assertRaises(ValueError):validate_controls(positive,{})

    def test_reference_controls_have_real_observable_defects_not_runtime_errors(self):
        driver=r'''
const nodes={}; let calls=0; const timers=[];
function el(id){return nodes[id]||(nodes[id]={textContent:'Checking environment\u2026',value:''});}
const document={getElementById:el};
const outcome=process.argv[1];
function fetch(){calls++;if(outcome==='network')return Promise.reject(new Error('network'));
 if(outcome==='pending')return new Promise(function(){});
 return Promise.resolve({status:outcome==='non200'?500:200,json:function(){
 if(outcome==='malformed')return Promise.reject(new Error('json'));
 return Promise.resolve(outcome==='extra'?{mode:'demo',extra:1}:outcome==='other'?{mode:'staging'}:outcome==='empty'?{}:{mode:'demo'});}});}
function setInterval(fn){timers.push(fn);} function setTimeout(fn){timers.push(fn);}
__FIXTURE__
Promise.resolve().then(async function(){for(let i=0;i<16;i++)await Promise.resolve();
 timers.forEach(fn=>fn());for(let i=0;i<16;i++)await Promise.resolve();
 console.log(JSON.stringify({text:el('service-mode').textContent,calls: calls,timers:timers.length,
 title:el('title').value,health:el('service-status').textContent}));});
'''
        outcomes={'extra_key_accepted':'extra','other_mode_accepted':'other','missing_key_accepted':'empty',
            'http_error_accepted':'non200','malformed_json_accepted':'malformed','network_error_accepted':'network',
            'pending_premature':'pending'}
        for case in ['positive',*CASES]:
            outcome=outcomes.get(case,'ok')
            p=subprocess.run(['node','-e',driver.replace('__FIXTURE__',fixture(case)),outcome],
                             capture_output=True,timeout=5,check=True)
            facts=json.loads(p.stdout)
            if case=='positive':
                self.assertEqual(facts,dict(text='Demo environment',calls=1,timers=0,title='',health='Service available'))
            elif case in outcomes:self.assertEqual(facts['text'],'Demo environment')
            elif case=='duplicate_request':self.assertEqual(facts['calls'],2)
            elif case.startswith('probe_'):
                self.assertEqual(facts['timers'],1);self.assertEqual(facts['calls'],2)
            elif case=='form_interference':self.assertEqual(facts['title'],'Changed by probe')
            elif case=='health_indicator_removed':self.assertEqual(facts['health'],'Broken')
