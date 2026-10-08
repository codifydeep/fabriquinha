import copy
import json
import unittest
import model_proxy
from probe_seed_patch_provider import fixture,validate_reply,remote_program,rejection_diagnostic,TARGET,OLD,NEW

class SeedPatchProbeTests(unittest.TestCase):
    def test_rejection_receipt_classifies_without_private_content(self):
        raw=b'private model response'
        result=rejection_diagnostic(ValueError('proposed artifact exceeds file limit'),raw)
        self.assertEqual(result['constraint'],'artifact_size')
        self.assertEqual(result['response_bytes'],len(raw))
        self.assertFalse(result['tools_executed'])
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('proposed artifact',json.dumps(result))
    def test_unknown_error_never_leaks_exception_or_key(self):
        for error in (ValueError('SECRET_VALUE'),KeyError('SECRET_VALUE'),TypeError('SECRET_VALUE')):
            result=rejection_diagnostic(error)
            self.assertEqual(result['constraint'],'unclassified_local_validation')
            self.assertNotIn('SECRET_VALUE',json.dumps(result))
            self.assertNotIn('response_sha256',result)
    def test_all_frozen_rejection_constraints_are_distinct_and_allowlisted(self):
        messages=['one matching proposed fragment required','proposed Python syntax rejected',
            'proposed artifact exceeds file limit','proposed assertions changed',
            'proposed discovery or assertion execution shape changed']
        constraints=[rejection_diagnostic(ValueError(message))['constraint'] for message in messages]
        self.assertEqual(len(set(constraints)),len(messages))
        self.assertNotIn('unclassified_local_validation',constraints)
    def test_actual_remote_program_compiles_and_does_not_call_host_main(self):
        import ast
        source=remote_program('11111111-1111-4111-8111-111111111111')
        compile(source,'isolated-probe','exec');tree=ast.parse(source)
        calls=[n for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)]
        self.assertEqual(len(calls),1);self.assertEqual(calls[0].value.func.id,'print')
        with self.assertRaises(ValueError):remote_program('bad')
    def reply(self):
        return dict(choices=[dict(index=0,finish_reason='tool_calls',message=dict(tool_calls=[dict(
            id='actual-model-call',type='function',function=dict(name='patch',arguments=json.dumps(
                dict(path=TARGET,old_string=OLD,new_string=NEW))))]))])
    def test_fixture_selects_actual_seed_patch_schema(self):
        body=model_proxy.validate_request(fixture(model_proxy.MODEL))
        self.assertEqual(body['tool_choice'],dict(type='function',function=dict(name='patch')))
        spec=next(t['function']['parameters'] for t in body['tools'] if t['function']['name']=='patch')
        self.assertEqual(spec['properties']['path']['enum'],[TARGET])
        self.assertFalse(spec['additionalProperties'])
    def test_single_actual_response_is_not_execution_or_historical_cause_proof(self):
        result=validate_reply(self.reply());self.assertTrue(result['actual_single_patch']);self.assertFalse(result['tools_executed'])
        self.assertNotIn(OLD,json.dumps(result));self.assertNotIn(NEW,json.dumps(result))
    def test_prose_duplicate_wrong_target_and_wrong_replacement_rejected(self):
        records=[]
        duplicate=self.reply();duplicate['choices'][0]['message']['tool_calls']*=2;records.append(duplicate)
        records.append(dict(choices=[dict(index=0,finish_reason='stop',message=dict(content='done'))]))
        for args in (dict(path='/workspace/app.py',old_string=OLD,new_string=NEW),
                dict(path=TARGET,old_string=OLD,new_string='assert True')):
            record=self.reply();record['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(args);records.append(record)
        for record in records:
            with self.assertRaises(ValueError):validate_reply(record)
