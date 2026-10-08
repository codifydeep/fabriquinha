import unittest
from broker import test_first_handoffs as h
from broker import handoff_runtime


class PreRedLineageTests(unittest.TestCase):
    def test_provider_failure_does_not_query_historical_format_image(self):
        effect=handoff_runtime.Effects(None,{})
        result=effect.pre_red_format_rejection({}, {'failure_reason':'agent_error.provider_server_error'})
        self.assertEqual(result['category'],'provider_failure_not_format_rejection')
        self.assertFalse(result['delivery_approval'])

    def fixture(self):
        diagnostic={'kind':'unchanged_seed','files':{'new.py':'hash'}}
        current={'phase':'test_first','error':'test_author_execution_failed',
                 'control_error':'ValueError:handoff identity drift','diagnostic':diagnostic}
        historical={'phase':'test_first','error':'test_first_cto_execution_failed',
                    'test_first_cto_wakeup':'wake','diagnostic':diagnostic}
        runs=[{'id':'cto-failed','agent_id':'cto','status':'failed','wakeup_id':'wake'}]
        return current,historical,runs

    def test_unique_failed_cto_lineage_restored_without_retry_authority(self):
        current,historical,runs=self.fixture()
        restored=h.lost_lineage(current,[historical],runs,'cto')
        self.assertEqual(restored['test_first_cto_wakeup'],'wake')
        self.assertEqual(restored['error'],'test_first_cto_execution_failed')
        self.assertFalse(restored['lineage_repair']['author_retry_authorized'])
        self.assertFalse(restored['lineage_repair']['delivery_approval'])
        self.assertEqual(current['error'],'test_author_execution_failed')

    def test_no_restore_for_drift_active_or_ambiguous_recipient(self):
        current,historical,runs=self.fixture()
        for altered in ({**historical,'diagnostic':{}}, {**historical,'phase':'implementation'}):
            self.assertIsNone(h.lost_lineage(current,[altered],runs,'cto'))
        self.assertIsNone(h.lost_lineage(current,[historical],[{**runs[0],'status':'running'}],'cto'))
        self.assertIsNone(h.lost_lineage(current,[historical],runs+[{**runs[0],'id':'duplicate'}],'cto'))
        self.assertIsNone(h.lost_lineage(current,[historical,{**historical,'test_first_cto_wakeup':'other'}],runs,'cto'))

    def test_existing_pointer_or_different_incident_never_restored(self):
        current,historical,runs=self.fixture()
        for altered in ({**current,'test_first_cto_wakeup':'new'},
                        {**current,'control_error':'ValueError:other'}):
            self.assertIsNone(h.lost_lineage(altered,[historical],runs,'cto'))
