import sqlite3,json,unittest
from broker import read_stream_receipts as receipts
from artifact_read_evidence import observations


class ReadStreamReceiptTests(unittest.TestCase):
    def pair(self,identifier,content):
        path='/evidence/candidate/test.py'
        return [{'type':'tool_use','tool':'read_file','call_id':identifier,'input':{'path':path}},
                {'type':'tool_result','tool':'read_file','call_id':identifier,'output':
                 'Read '+path+' — 1 total lines\n\n```\n1|'+content+'\n```'}]

    def test_same_call_full_transport_replaces_ui_render_without_double_count(self):
        native=self.pair('call','rendered differently');durable=self.pair('call','full original')
        merged=receipts.merge(native,durable)
        self.assertEqual(merged,durable)
        self.assertEqual(observations(merged)['/evidence/candidate/test.py']['lines'],1)

    def test_different_calls_contradictory_reads_still_rejected(self):
        self.assertEqual(observations(receipts.merge(self.pair('ui','different'),self.pair('full','original'))),{})

    def test_missing_malformed_duplicate_durable_pairs_fail_closed(self):
        valid=self.pair('call','original')
        for invalid in (valid[:1],valid+valid,[{**valid[0],'tool':'terminal'},valid[1]]):
            with self.assertRaises(ValueError):receipts.merge([],invalid)
        self.assertEqual(receipts.merge(valid,[]),valid)

    def test_remapped_ui_ids_do_not_conflict_with_task_bound_full_transport(self):
        full=self.pair('provider-call','original')
        ui=self.pair('new-transcript-uuid','rendered differently')
        self.assertEqual(receipts.observed(ui,full),observations(full))

    def test_conflicting_durable_calls_never_fall_back_to_ui_approval(self):
        full=self.pair('one','original')+self.pair('two','contradiction')
        self.assertEqual(receipts.observed(self.pair('ui','original'),full),{})

    def test_incomplete_durable_file_cannot_borrow_ui_lines_but_other_files_remain(self):
        path='/evidence/candidate/test.py'
        partial=self.pair('provider','first');partial[1]['output']=partial[1]['output'].replace('1 total lines','2 total lines')
        self.assertEqual(receipts.observed(self.pair('ui','complete'),partial),{})
        other=self.pair('other','real')
        for m in other:
            if m['type']=='tool_use':m['input']['path']='/evidence/candidate/other.py'
            else:m['output']=m['output'].replace(path,'/evidence/candidate/other.py')
        self.assertIn('/evidence/candidate/other.py',receipts.observed(other,partial))
    def frames(self,text):
        path='/evidence/candidate/test.py'
        return [{'method':'session/update','params':{'update':v}} for v in (
            {'sessionUpdate':'tool_call','toolCallId':'call','kind':'read','title':'read: '+path},
            {'sessionUpdate':'tool_call_update','toolCallId':'call','kind':'read','status':'completed',
             'content':[{'type':'content','content':{'type':'text','text':text}}]})]

    def test_full_page_survives_ui_truncation_and_restart_with_task_binding(self):
        con=sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT)')
        con.execute('INSERT INTO native_bindings VALUES (?,?)',('request','task'))
        page='Read /evidence/candidate/test.py (from line 1, limit 1) — 1 total lines\n\n```\n1|'+('x'*16000)+'\n```'
        binding={'task_id':'task','request_id':'request'}
        receipts.store(con,binding,self.frames(page),'planning')
        receipts.store(con,binding,self.frames(page),'planning')
        self.assertEqual(con.execute('SELECT count(*) FROM observed_read_stream').fetchone()[0],1)
        self.assertIn('/evidence/candidate/test.py',observations(receipts.load(con,'task')))
        self.assertEqual(receipts.load(con,'other'),[])
        con.execute('DELETE FROM native_bindings')
        self.assertEqual(receipts.load(con,'task'),[])

    def test_missing_start_cut_page_or_wrong_mode_never_proves_read(self):
        con=sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        binding={'task_id':'task','request_id':'request'}
        page='Read /evidence/candidate/test.py — 1 total lines\n\n```\n1|partial'
        self.assertEqual(receipts.extract(self.frames(page)[1:]),[])
        receipts.store(con,binding,self.frames(page),'planning')
        self.assertEqual(con.execute('SELECT count(*) FROM observed_read_stream').fetchone()[0],0)
        receipts.store(con,binding,self.frames(page),'implementation')
        self.assertEqual(con.execute('SELECT count(*) FROM observed_read_stream').fetchone()[0],0)
