"""Versioned storage fixtures are not review admission/approval authority."""
import copy
import json
import sqlite3
import unittest
from broker import quality_review_history as history,quality_review_attestation as attest
import test_quality_review_attestation as fixture


class QualityReviewHistoryTests(unittest.TestCase):
    def setUp(self):
        f=fixture.QualityReviewAttestationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.source=f.source;self.q=attest.quality
        self.original=f.call()
        with self.b.db() as con:history.initialize(con)

    def receipt(self,request):
        result={**self.original,'request_id':request,'review_task':'review-'+request}
        identity=dict(namespace=self.b.PREFIX,source_task=self.source,request_id=request)
        with self.b.db() as con:
            con.execute('INSERT INTO quality_review_successor_attestations VALUES(?,?,?,?,?,?)',
                (self.source,request,json.dumps(identity),json.dumps(result),self.q.digest(identity),self.q.digest(result)))
        return result

    def select(self,request):
        with self.b.db() as con:
            raw=con.execute('SELECT state FROM quality_test_reviews WHERE source_task=?',(self.source,)).fetchone()[0]
            state={**json.loads(raw),'request_id':request}
            con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=? WHERE source_task=?',
                (json.dumps(state),self.q.digest(state),self.source))

    def test_multiple_receipts_coexist_and_current_or_historical_selection_is_exact(self):
        first=self.receipt('future-1');second=self.receipt('future-2')
        self.select('future-2')
        self.assertEqual(attest.load(self.b,self.source),second)
        self.assertEqual(attest.load(self.b,self.source,request_id='future-1'),first)
        self.assertEqual(attest.load(self.b,self.source,request_id=self.original['request_id']),self.original)
        with self.b.db() as con:
            selected=attest.stored_row(con,self.source)
            self.assertEqual(json.loads(selected[0]),second)
            self.assertEqual(json.loads(con.execute('SELECT receipt FROM quality_review_attestations').fetchone()[0]),self.original)

    def test_inactive_corruption_still_blocks_current_and_transactional_consumers(self):
        self.receipt('future-1');self.receipt('future-2');self.select('future-2')
        with self.b.db() as con:con.execute("UPDATE quality_review_successor_attestations SET receipt='{}' WHERE request_id='future-1'")
        with self.assertRaises(ValueError):attest.load(self.b,self.source)
        with self.b.db() as con,self.assertRaises(ValueError):attest.stored_row(con,self.source)

    def test_successor_windows_are_request_scoped_and_never_reset_old_clocks(self):
        with self.b.db() as con:
            for request in ('future-1','future-2'):
                con.execute('INSERT INTO quality_review_successor_admissions VALUES(?,?,?,?,?)',
                    (self.source,'task-'+request,request,'{}',self.q.digest({})))
                self.assertEqual(history.window_table(con,self.source,request),'quality_review_successor_windows')
                con.execute('INSERT INTO quality_review_successor_windows VALUES(?,?,?,?,?)',
                    (self.source,request,'identity',json.dumps(dict(deadline=100 if request=='future-1' else 200)),'sha'))
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_successor_windows').fetchone()[0],2)
            self.assertEqual(history.window_table(con,self.source,'original'),'quality_review_observation_windows')

    def test_read_only_archives_need_no_new_schema_or_migration(self):
        with self.b.db() as con:
            for table in ('quality_review_successor_admissions','quality_review_successor_attestations','quality_review_successor_windows'):
                con.execute('DROP TABLE '+table)
            con.execute('PRAGMA query_only=ON')
            rows=history.rows(con,'attestation',source=self.source)
            self.assertEqual(len(rows),1)

    def test_unknown_history_kind_is_rejected_without_sql_interpretation(self):
        with self.b.db() as con,self.assertRaises(ValueError):history.rows(con,'unknown; DROP TABLE grants',source=self.source)


if __name__=='__main__':unittest.main()
