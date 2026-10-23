"""Read-page byte/manifest binding, not self-reported inspection."""
import copy
import hashlib
import json
import unittest
from broker import quality_review_reads as reads


class QualityReviewReadTests(unittest.TestCase):
    def setUp(self):
        self.files={'app.py':b'VALUE=0\n','tests/test_new.py':b'one\ntwo\nthree\n'}
        self.inventory={p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in self.files.items()}
        self.manifest=hashlib.sha256(json.dumps({'files':self.inventory},sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def pair(self,path,identifier,offset,total,body):
        return [dict(type='tool_use',tool='read_file',call_id=identifier,input=dict(path='/delivery/'+path)),
            dict(type='tool_result',tool='read_file',call_id=identifier,
                output=f'Read /delivery/{path} (from line {offset}, limit 100) — {total} total lines\n\n```\n{body}\n```')]

    def messages(self):
        return self.pair('app.py','a',1,1,'1|VALUE=0')+self.pair('tests/test_new.py','b',1,3,'1|one\n2|two')+self.pair('tests/test_new.py','c',3,3,'3|three')

    def call(self,messages=None):
        return reads.observe(self.inventory,self.manifest,['/delivery/'+p for p in self.files],self.messages() if messages is None else messages)

    def test_complete_pages_reconstruct_exact_frozen_file_bytes(self):
        result=self.call()
        self.assertEqual(set(result),{'/delivery/'+p for p in self.files})
        self.assertEqual(result['/delivery/tests/test_new.py']['sha256'],self.inventory['tests/test_new.py']['sha256'])
        self.assertNotIn('line_content',json.dumps(result))

    def test_partial_conflicting_clipped_or_duplicate_calls_are_not_reads(self):
        messages=self.messages()
        clipped=copy.deepcopy(messages);clipped[-1]['output']=clipped[-1]['output'].replace('3|three','3|thr... [truncated]')
        conflict=messages+self.pair('tests/test_new.py','d',3,3,'3|different')
        duplicate=messages+messages[-2:]
        for value in (messages[:-2],clipped,conflict,duplicate):
            with self.subTest(value=value[-1]['call_id']),self.assertRaises(ValueError):self.call(value)

    def test_manifest_or_actual_content_drift_is_not_coverage(self):
        bad=self.messages();bad[1]['output']=bad[1]['output'].replace('VALUE=0','VALUE=1')
        with self.assertRaises(ValueError):self.call(bad)
        with self.assertRaises(ValueError):reads.observe(self.inventory,'0'*64,['/delivery/'+p for p in self.files],self.messages())

    def test_claim_of_reading_without_handler_results_is_not_evidence(self):
        with self.assertRaises(ValueError):self.call([dict(type='text',content='I read every file')])

    def test_unicode_paths_and_crlf_are_bound_to_their_actual_byte_hash(self):
        name='src/ação.py';raw='olá\r\nlinha\r\n'.encode()
        inventory={name:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))}
        manifest=hashlib.sha256(json.dumps({'files':inventory},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result=reads.observe(inventory,manifest,['/delivery/'+name],self.pair(name,'a',1,2,'1|olá\n2|linha'))
        self.assertEqual(result['/delivery/'+name]['sha256'],inventory[name]['sha256'])

    def test_empty_file_requires_an_actual_successful_empty_read(self):
        inventory={'empty.py':dict(sha256=hashlib.sha256(b'').hexdigest(),bytes=0)}
        manifest=hashlib.sha256(json.dumps({'files':inventory},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        pair=self.pair('empty.py','a',1,0,'')
        self.assertEqual(reads.observe(inventory,manifest,['/delivery/empty.py'],pair)['/delivery/empty.py']['bytes'],0)
        with self.assertRaises(ValueError):reads.observe(inventory,manifest,['/delivery/empty.py'],[])

    def test_assessment_lists_all_missing_files_without_authorizing_anything(self):
        paths=['/delivery/'+p for p in self.files]
        result=reads.assessment(self.inventory,self.manifest,paths,[])
        self.assertEqual(result['required_files'],2);self.assertEqual(result['complete_files'],0)
        self.assertEqual({r['path'] for r in result['rejected_files']},set(self.files))
        self.assertFalse(result['execution_authorized']);self.assertFalse(result['delivery_approval'])
        with self.assertRaises(ValueError):self.call([])

    def test_assessment_does_not_promote_partial_or_conflicting_pages(self):
        paths=['/delivery/'+p for p in self.files]
        for messages in (self.messages()[:-2],self.messages()+self.pair('tests/test_new.py','d',3,3,'3|wrong')):
            result=reads.assessment(self.inventory,self.manifest,paths,messages)
            self.assertEqual(result['complete_paths'],['app.py'])
            self.assertEqual(result['rejected_files'][0]['path'],'tests/test_new.py')
        result=reads.assessment(self.inventory,self.manifest,paths,self.messages())
        self.assertEqual(result['complete_files'],2);self.assertEqual(result['rejected_files'],[])
        self.assertFalse(result['delivery_approval'])

    def test_invalid_stream_or_manifest_cannot_claim_coverage(self):
        paths=['/delivery/'+p for p in self.files]
        result=reads.assessment(self.inventory,self.manifest,paths,self.messages()+self.messages()[:2])
        self.assertEqual(result['complete_files'],0)
        self.assertTrue(all(r['category']=='read_stream_invalid' for r in result['rejected_files']))
        with self.assertRaises(ValueError):reads.assessment(self.inventory,'0'*64,paths,[])


if __name__=='__main__':unittest.main()
