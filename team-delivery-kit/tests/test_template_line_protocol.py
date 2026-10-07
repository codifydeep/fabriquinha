import hashlib,json,os,tempfile,unittest
from pathlib import Path
from surgical_test_edit import marker_config,typed_schema,validate_typed,edit_file
from tests.test_template_only_edit import SOURCE


class TemplateLineProtocolTests(unittest.TestCase):
    def config(self,version='V6'):
        return marker_config({'messages':[{'role':'user','content':f'DELIVERY_SURGICAL_TEST_{version}:/workspace/test_template.py:'+hashlib.sha256(SOURCE).hexdigest()+'\n'}]})

    def args(self):
        return dict(path='/workspace/test_template.py',expected_sha256=hashlib.sha256(SOURCE).hexdigest(),
            edits=[dict(start_line=7,end_line=7,new=' const after_ok = {text: "terminal"};\n')])

    def test_v6_schema_and_validator_are_line_only_and_do_not_amplify_v5(self):
        cfg=self.config();self.assertEqual(cfg['protocol'],'typed_template_lines_v6')
        schema=typed_schema(cfg)
        self.assertEqual(set(schema['parameters']['properties']),{'path','expected_sha256','edits'})
        self.assertEqual(schema['parameters']['properties']['edits']['items']['required'],['start_line','end_line','new'])
        self.assertIn('NODE_HARNESS_TEMPLATE',schema['description'])
        validate_typed(self.args(),cfg)
        with self.assertRaises(ValueError):validate_typed(self.args(),self.config('V5'))
        with self.assertRaises(ValueError):validate_typed({**self.args(),'template_name':'OTHER'},cfg)
        with self.assertRaises(ValueError):typed_schema({**cfg,'atomic_contract':'fake'})
        body={'messages':[{'role':'user','content':'DELIVERY_SURGICAL_TEST_V5:/workspace/test_template.py:'+'a'*64+'\nDELIVERY_SURGICAL_TEST_V6:/workspace/test_template.py:'+'a'*64+'\n'}]}
        with self.assertRaises(ValueError):marker_config(body)

    def test_file_handler_requires_read_and_preserves_original_on_scope_or_syntax_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();path=root/'test_template.py';path.write_bytes(SOURCE)
            envelope={k:self.args()[k] for k in ('expected_sha256','edits')}
            with self.assertRaises(ValueError):edit_file(path,envelope,root=root,line_ranges=True,template_only=True)
            for line,new in [(2,'CONTROL="changed"\n'),(11,' def test_ok(self): pass\n'),(7,' const after_ok = ;\n')]:
                bad={**envelope,'edits':[dict(start_line=line,end_line=line,new=new)]}
                with self.assertRaises(ValueError):edit_file(path,bad,root=root,observed_read=True,
                    required_uid=os.getuid(),line_ranges=True,template_only=True)
                self.assertEqual(path.read_bytes(),SOURCE)
            result=edit_file(path,envelope,root=root,observed_read=True,required_uid=os.getuid(),line_ranges=True,template_only=True)
            self.assertTrue(result['verified']);self.assertTrue(result['test_bodies_preserved'])
            self.assertFalse(result['delivery_approval'])
            changed=path.read_bytes()
            with self.assertRaises(ValueError):edit_file(path,envelope,root=root,observed_read=True,line_ranges=True,template_only=True)
            self.assertEqual(path.read_bytes(),changed)

    def test_proxy_selects_actual_v6_tool_after_complete_reads(self):
        from test_artifact_schema import apply
        cfg=self.config();target=cfg['path']
        body=dict(messages=[dict(role='user',content='DELIVERY_TEST_ARTIFACT_V1:'+target+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_SURGICAL_TEST_V6:'+target+':'+cfg['expected_sha256']+'\n')],
            tools=[{'type':'function','function':typed_schema(cfg)},
                   {'type':'function','function':{'name':'read_file','parameters':{}}},
                   {'type':'function','function':{'name':'write_file','parameters':{}}}])
        for i,path in enumerate(('/workspace/app.py',target)):
            body['messages'] += [dict(role='assistant',tool_calls=[dict(id=str(i),function=dict(name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=128))))]),
                dict(role='tool',tool_call_id=str(i),content=json.dumps(dict(content='1|source',total_lines=1)))]
        selected=apply(body)
        self.assertEqual(selected['tool_choice']['function']['name'],'surgical_test_edit')
        self.assertIn('CURRENT HARNESS-ONLY LINE CORRECTION',selected['messages'][-1]['content'])
        chosen=next(t['function'] for t in selected['tools'] if t['function']['name']=='surgical_test_edit')
        self.assertNotIn('old',chosen['parameters']['properties']['edits']['items']['properties'])
