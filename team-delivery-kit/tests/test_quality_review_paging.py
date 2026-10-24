"""Bounded worker-advisory journal, never native approval or invented reads."""
import hashlib
import json
import unittest
import quality_review_paging as paging


class QualityReviewPagingTests(unittest.TestCase):
    def setUp(self):
        self.files={'a.py':b'a\nb\nc\n','b.py':b'x\n','empty.py':b''}
        self.inventory={p:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for p,raw in self.files.items()}
        self.manifest=hashlib.sha256(json.dumps(dict(files=self.inventory),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.paths=['/delivery/'+p for p in self.files];self.request='60000000-0000-4000-8000-000000000001'
        self.journal=paging.Journal(self.request,self.inventory,self.manifest,self.paths)

    def page(self,path,key,offset,total,content,limit=100):
        return [dict(type='tool_use',tool='read_file',call_id=key,input=dict(path='/delivery/'+path,offset=offset,limit=limit)),
            dict(type='tool_result',tool='read_file',call_id=key,output=json.dumps(dict(content=content,total_lines=total)))]

    def test_plan_selects_only_missing_pages_with_one_exact_offset(self):
        self.journal.add(self.page('a.py','a',1,3,'1|a\n2|b'))
        plan=self.journal.plan();self.assertEqual(plan['pages'],[
            dict(path='/delivery/b.py',offset=1,limit=100),dict(path='/delivery/empty.py',offset=1,limit=100)])
        self.journal.add(self.page('b.py','b',1,1,'1|x'))
        self.journal.add(self.page('empty.py','e',1,0,''))
        self.assertEqual(self.journal.plan()['pages'],[dict(path='/delivery/a.py',offset=3,limit=100)])
        self.journal.add(self.page('a.py','c',3,3,'3|c'))
        self.assertEqual(self.journal.plan()['pages'],[])

    def test_priority_finishes_new_test_before_larger_unrelated_cohort(self):
        self.journal.add(self.page('a.py','a',1,3,'1|a'))
        plan=self.journal.plan(priority_paths=['/delivery/a.py'])
        self.assertEqual(plan['pages'],[dict(path='/delivery/a.py',offset=2,limit=100)])
        self.journal.add(self.page('a.py','b',2,3,'2|b\n3|c'))
        self.assertEqual(self.journal.plan(priority_paths=['/delivery/a.py'])['pages'],[
            dict(path='/delivery/b.py',offset=1,limit=100),dict(path='/delivery/empty.py',offset=1,limit=100)])

    def test_priority_orders_but_does_not_shrink_same_offset_cohort(self):
        plan=self.journal.plan(priority_paths=['/delivery/empty.py'])
        self.assertEqual([p['path'] for p in plan['pages']],
            ['/delivery/empty.py','/delivery/a.py','/delivery/b.py'])
        for paths in ('/delivery/a.py',['/delivery/unknown.py'],['/delivery/a.py']*2):
            with self.assertRaises(ValueError):self.journal.plan(priority_paths=paths)
        with self.assertRaises(ValueError):
            self.journal.plan(required_paths=['/delivery/b.py'],priority_paths=['/delivery/a.py'])

    def test_journal_survives_context_drop_and_does_not_alias_mutable_messages(self):
        messages=self.page('a.py','a',1,3,'1|a\n2|b');self.journal.add(messages)
        messages[1]['output']='changed conversation';saved=self.journal.messages();saved.clear()
        self.assertEqual(len(self.journal.messages()),2)
        self.assertEqual(self.journal.plan(required_paths=['/delivery/a.py'])['pages'],[dict(path='/delivery/a.py',offset=3,limit=100)])

    def test_partial_lines_are_progress_but_duplicate_call_or_prose_is_not(self):
        first=self.journal.plan()['progress_sha256'];page=self.page('a.py','a',1,3,'1|a')
        self.journal.add(page);second=self.journal.plan()['progress_sha256'];self.assertNotEqual(first,second)
        self.journal.add(page);self.assertEqual(self.journal.plan()['progress_sha256'],second)
        self.journal.add(self.page('a.py','b',2,3,'2|b'))
        self.assertNotEqual(self.journal.plan()['progress_sha256'],second)
        with self.assertRaises(ValueError):self.journal.add([dict(role='assistant',content='I read it')])

    def test_duplicate_id_drift_foreign_path_and_wrong_complete_bytes_fail_closed(self):
        self.journal.add(self.page('a.py','a',1,3,'1|a'))
        for messages in (self.page('a.py','a',1,3,'1|wrong'),self.page('../secret','other',1,1,'1|x')):
            with self.assertRaises(ValueError):self.journal.add(messages)
        self.journal.add(self.page('b.py','bad',1,1,'1|wrong'))
        with self.assertRaises(ValueError):self.journal.plan()

    def test_rejection_scope_does_not_force_unrelated_approval_paths(self):
        self.journal.add(self.page('b.py','b',1,1,'1|x'))
        plan=self.journal.plan(required_paths=['/delivery/b.py'])
        self.assertEqual(plan['pages'],[]);self.assertFalse(plan['tests_approved']);self.assertFalse(plan['delivery_approval'])

    def test_paging_and_storage_are_bounded_without_eviction_or_false_completion(self):
        with self.assertRaises(ValueError):self.journal.add(self.page('a.py','a',1,3,'1|a'),max_pairs=0)
        with self.assertRaises(ValueError):self.journal.add(self.page('a.py','a',1,3,'1|a'),max_bytes=1)
        self.assertEqual(self.journal.messages(),[])

    def test_progress_is_unique_source_coverage_not_call_ids_or_transport(self):
        self.journal.add(self.page('a.py','a',1,3,'1|a'))
        before=self.journal.plan()['progress_sha256']
        self.journal.add(self.page('a.py','another',1,3,'1|a'))
        self.assertEqual(self.journal.plan()['progress_sha256'],before)
        self.assertEqual(len(self.journal.messages()),4)

    def test_overlapping_conflicts_totals_and_empty_nonempty_mixes_fail_closed(self):
        for changed in (self.page('a.py','b',1,3,'1|wrong'),
                self.page('a.py','b',2,4,'2|b')):
            journal=paging.Journal(self.request,self.inventory,self.manifest,self.paths)
            journal.add(self.page('a.py','a',1,3,'1|a'))
            journal.add(changed)
            with self.assertRaises(ValueError):journal.plan()
        self.journal.add(self.page('empty.py','e',1,0,''))
        self.journal.add(self.page('empty.py','f',1,1,'1|x'))
        with self.assertRaises(ValueError):self.journal.plan()

    def test_invalid_dedup_eof_truncated_and_unpaired_results_never_enter_journal(self):
        for output in (dict(dedup=True,content_returned=False),
                dict(total_lines=3,content=''),dict(error='denied'),
                dict(total_lines=3,content='1|a... [truncated]')):
            messages=self.page('a.py','a',4,3,'')
            messages[1]['output']=json.dumps(output)
            with self.assertRaises(ValueError):self.journal.add(messages)
            self.assertEqual(self.journal.messages(),[])
        with self.assertRaises(ValueError):self.journal.add(self.page('a.py','a',1,3,'1|a')[:1])

    def test_add_is_atomic_on_later_invalid_pair_and_capacity_cannot_be_disabled(self):
        good=self.page('a.py','a',1,3,'1|a')
        with self.assertRaises(ValueError):self.journal.add(good+self.page('../secret','b',1,1,'1|x'))
        self.assertEqual(self.journal.messages(),[])
        for limit in (True,-1,513,10**9):
            with self.assertRaises(ValueError):self.journal.add(good,max_pairs=limit)
        with self.assertRaises(ValueError):self.journal.add(good,max_bytes=9*1024*1024)

    def test_context_and_scope_are_copied_and_bound_to_canonical_identity(self):
        self.inventory['a.py']['sha256']='0'*64;self.paths.clear()
        self.assertEqual(len(self.journal.plan()['pages']),3)
        for request in ('arbitrary','60000000-0000-4000-8000-00000000000Z'):
            with self.assertRaises(ValueError):paging.Journal(request,{},self.manifest,[])
        for paths in ([],['/delivery/../secret'],['/delivery/a.py']*2):
            with self.assertRaises(ValueError):self.journal.plan(required_paths=paths)

    def test_unicode_crlf_no_final_newline_and_empty_are_byte_verified(self):
        files={'unicode.py':'ação\r\n東京'.encode(),'empty.py':b''}
        inventory={p:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for p,raw in files.items()}
        manifest=hashlib.sha256(json.dumps(dict(files=inventory),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        journal=paging.Journal(self.request,inventory,manifest,['/delivery/'+p for p in files])
        journal.add(self.page('unicode.py','u',1,2,'1|ação\n2|東京'))
        journal.add(self.page('empty.py','e',1,0,''))
        self.assertEqual(journal.plan()['pages'],[])
        self.assertFalse(journal.plan()['execution_authorized'])

    def test_large_snapshot_pages_finish_within_original_budget_without_repeat_or_eof(self):
        # Comparable cardinality and longest file to the native blocked review,
        # but synthetic content only: not a model/native qualification receipt.
        files={f'file-{n:03}.py':(''.join(f'line {i}\n' for i in range(868 if n==0 else 205 if n==1 else 23))).encode()
            for n in range(71)}
        inventory={p:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for p,raw in files.items()}
        manifest=hashlib.sha256(json.dumps(dict(files=inventory),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        journal=paging.Journal(self.request,inventory,manifest,['/delivery/'+p for p in files])
        calls=set();steps=0
        while journal.plan()['remaining_files']:
            self.assertLess(steps,40)
            plan=journal.plan();self.assertTrue(plan['pages']);self.assertLessEqual(len(plan['pages']),16)
            self.assertEqual(len({p['offset'] for p in plan['pages']}),1)
            before=plan['progress_sha256']
            for page in plan['pages']:
                identity=(page['path'],page['offset'],page['limit'])
                self.assertNotIn(identity,calls);calls.add(identity)
                path=page['path'].removeprefix('/delivery/');lines=files[path].decode().splitlines()
                self.assertLessEqual(page['offset'],len(lines))
                selected=lines[page['offset']-1:page['offset']+page['limit']-1]
                content='\n'.join(f'{number}|{text}' for number,text in enumerate(selected,start=page['offset']))
                journal.add(self.page(path,f'call-{len(calls)}',page['offset'],len(lines),content))
            steps+=1
            self.assertNotEqual(journal.plan()['progress_sha256'],before)
        self.assertLessEqual(steps,16)
        self.assertEqual(journal.plan()['complete_files'],71)
        self.assertEqual(len(calls),81)
        self.assertFalse(journal.plan()['tests_approved'])

    def test_partial_progress_fingerprint_is_order_independent_and_hides_source(self):
        other=paging.Journal(self.request,self.inventory,self.manifest,self.paths)
        first=self.page('a.py','a',1,3,'1|a');second=self.page('b.py','b',1,1,'1|x')
        self.journal.add(first+second);other.add(second+first)
        self.assertEqual(self.journal.plan()['progress_sha256'],other.plan()['progress_sha256'])
        self.assertNotIn('line_content',json.dumps(self.journal.plan()))


if __name__=='__main__':unittest.main()
