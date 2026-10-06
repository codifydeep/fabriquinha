import copy
import hashlib
import unittest
import c10_micro_drain as micro
import surgical_test_edit as surgical


def fixture():
    lines=['// frozen\n']*679
    lines[0:4]=['import unittest\n','DRIVER_PREAMBLE="frozen"\n','DRIVER_BODY=r"""\n','function drive(){\n']
    lines[548:553]=['return flush().then(function(){\n',micro.OBSERVATION.decode(),micro.ANCHOR.decode(),'});\n','}\n']
    lines[676:679]=['"""\n','class T(unittest.TestCase):\n',' def test_ok(self): self.assertTrue(True)\n']
    return ''.join(lines).encode()


class MicroDrainTests(unittest.TestCase):
    def setUp(self):
        self.source=fixture();self.digest=hashlib.sha256(self.source).hexdigest()
    def args(self,operation='resolveNewest'):
        return {'expected_sha256':self.digest,'edits':[{'start_line':551,'end_line':551,'new':micro.recipe(operation)}]}
    def test_exact_recipe_preserves_every_other_byte_and_non_driver_ast(self):
        for operation in ('resolveNewest','resolveOldest'):
            args=self.args(operation)
            micro.validate(args,operation,self.source)
            result=surgical.prepare_driver_lines(self.source,args)
            self.assertTrue(micro.verify(self.source,result,operation))
            self.assertEqual(result.splitlines()[:550],self.source.splitlines()[:550])
            self.assertEqual(result.splitlines()[554:],self.source.splitlines()[551:])
    def test_comments_wrong_scope_constants_or_wrong_resolver_are_rejected(self):
        for mutation in ('comment','line','constant','resolver','suffix'):
            args=self.args()
            if mutation=='comment':args['edits'][0]['new']='// perform the correction\n'
            if mutation=='line':args['edits'][0]['start_line']=550
            if mutation=='constant':args['edits'][0]['new']=micro.recipe('resolveNewest').replace('pending.length','0')
            if mutation=='resolver':args['edits'][0]['new']=micro.recipe('resolveOldest')
            if mutation=='suffix':args['edits'][0]['new']+='pending=[];\n'
            with self.assertRaises(ValueError):micro.validate(args,'resolveNewest',self.source)
        with self.assertRaises(ValueError):micro.verify(self.source,self.source,'resolveNewest')
        with self.assertRaises(ValueError):micro.verify(self.source,self.source.replace(b'// frozen',b'// changed',1),'resolveNewest')
    def test_narrow_schema_and_proxy_marker_keep_same_contract(self):
        cfg={'path':'/workspace/test_micro.py','expected_sha256':self.digest,'protocol':'typed_driver_lines_v4',
            'drain_resolver':'resolveNewest'}
        schema=surgical.typed_schema(cfg);item=schema['parameters']['properties']['edits']['items']['properties']
        self.assertEqual(item['start_line']['enum'],[551]);self.assertEqual(item['end_line']['enum'],[551])
        self.assertEqual(item['new']['enum'],[micro.recipe('resolveNewest')])
        marker={'messages':[{'role':'user','content':'DELIVERY_SURGICAL_TEST_V4:'+cfg['path']+':'+self.digest+'\nDELIVERY_STATUS_DRAIN_V1:resolveNewest'}]}
        self.assertEqual(surgical.marker_config(marker),cfg)
        bad=copy.deepcopy(marker);bad['messages'][0]['content']+='\nDELIVERY_STATUS_DRAIN_V1:resolveOldest'
        with self.assertRaises(ValueError):surgical.marker_config(bad)
    def test_direct_locked_handler_rejects_before_writing(self):
        import tempfile,os
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();target=root/'test_micro.py';target.write_bytes(self.source)
            bad=self.args();bad['edits'][0]['new']='// no executable code\n'
            with self.assertRaises(ValueError):surgical.edit_file(target,bad,root=root,observed_read=True,
                required_uid=os.getuid(),driver_only=True,line_ranges=True,micro_resolver='resolveNewest')
            self.assertEqual(target.read_bytes(),self.source)
            result=surgical.edit_file(target,self.args(),root=root,observed_read=True,required_uid=os.getuid(),
                driver_only=True,line_ranges=True,micro_resolver='resolveNewest')
            self.assertTrue(result['verified']);self.assertFalse(result['delivery_approval'])
