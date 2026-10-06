import copy
import unittest
from cleanup_port2_history import eligible


class RetiredContainerSelectionTests(unittest.TestCase):
    def fixture(self):return {'Name':'/delivery-kit-port2-old-probe','Config':{'Labels':{
        'com.docker.compose.project':'delivery-kit-port2-tests'}},
        'HostConfig':{'ReadonlyRootfs':True},'State':{'Status':'exited'},'Mounts':[]}
    def test_only_stopped_readonly_owned_tests(self):
        self.assertTrue(eligible(self.fixture()))
        for state in ('running','paused','restarting','removing'):
            c=self.fixture();c['State']['Status']=state;self.assertFalse(eligible(c))
        for name in ('/toso-local-old-probe','/reforma-old-probe','/delivery-kit-port2-u3-coverage-qa'):
            c=self.fixture();c['Name']=name;self.assertFalse(eligible(c))
        c=self.fixture();c['HostConfig']['ReadonlyRootfs']=False;self.assertFalse(eligible(c))
    def test_only_exact_retired_homologation_with_retained_volume(self):
        c=self.fixture();c['Name']='/delivery-kit-port2-testrev123abc-1-qa'
        c['Config']['Labels']={'com.docker.compose.project':'delivery-kit-port2-homologation',
            'delivery-kit.source-sha':'a'*40}
        c['State']['Status']='running';c['Mounts']=[{'Type':'volume','Destination':'/opt/data'}]
        self.assertTrue(eligible(c))
        for destination in ('/project','/broker-state'):
            bad=copy.deepcopy(c);bad['Mounts'][0]['Destination']=destination;self.assertFalse(eligible(bad))
        bad=copy.deepcopy(c);bad['Mounts'][0]['Type']='bind';self.assertFalse(eligible(bad))
