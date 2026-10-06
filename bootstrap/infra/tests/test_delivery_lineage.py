import unittest,sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from product_delivery_lineage import integrated_index
from product_planning_watch import watch

class LineageTests(unittest.TestCase):
    def setUp(self):
        self.cards={'original':{},'revalidated':{'base_update_source':{'task':'original'}},'corrected':{'original_source_task':'revalidated','rework_pr':31}}
        self.pub=dict(state='INTEGRATED',source_task='corrected',pr=31,head='a'*40,merge='b'*40)
    def test_explicit_multi_step_lineage_resolves_all_ancestors(self):
        index=integrated_index(self.cards,[self.pub])
        self.assertEqual(set(index),set(self.cards))
        self.assertEqual(index['original']['source_task'],'corrected')
        self.assertEqual(index['original']['merge'],'b'*40)
    def test_snapshot_or_unmerged_pr_never_counts(self):
        self.assertEqual(integrated_index(self.cards,[dict(self.pub,state='CI_WAIT')]),{})
    def test_unrelated_done_card_never_counts(self):
        self.cards['unrelated']={}
        self.assertNotIn('unrelated',integrated_index(self.cards,[self.pub]))
    def test_wrong_pr_cycle_and_missing_ancestor_rejected(self):
        for changed in ({'original_source_task':'missing'},{'original_source_task':'corrected'},{'original_source_task':'revalidated','rework_pr':99}):
            with self.assertRaises(PermissionError):integrated_index(dict(self.cards,corrected=changed),[self.pub])
    def test_conflicting_merges_not_guessed(self):
        with self.assertRaises(PermissionError):integrated_index(self.cards,[self.pub,dict(self.pub,merge='c'*40)])

class WatchTests(unittest.TestCase):
    def test_idle_alert_is_delayed_deduplicated_and_rearms_after_progress(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('create table tasks(id text,status text)');db.execute("insert into tasks values('t','blocked')")
        records={'planning-frontier':dict(eligible=['TDD-01'],busy=['TDD-01'],selectable=[],integrated_children={})}
        c=SimpleNamespace(cfg=dict(dag_planning=True,cards={'t':{}}),native=db,board='board',get=records.get,put=lambda k,v:records.__setitem__(k,v))
        with patch('product_lane.emit') as emit:
            watch(c,0);watch(c,599);emit.assert_not_called()
            watch(c,600);watch(c,900);self.assertEqual(emit.call_count,1)
            db.execute("update tasks set status='running'");watch(c,901)
            self.assertEqual(records['planning-idle']['state'],'ACTIVITY_RESUMED')
            db.execute("update tasks set status='blocked'");watch(c,902);watch(c,1502)
            self.assertEqual(emit.call_count,2)
