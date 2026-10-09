import contextlib,sqlite3,tempfile,unittest
from unittest.mock import Mock
from pathlib import Path
from types import SimpleNamespace
from broker import helper_cleanup as cleanup

class HelperCleanupTests(unittest.TestCase):
    def test_snapshot_and_controls_cleanup_require_exact_source_identity(self):
        b=SimpleNamespace(PREFIX='delivery-kit-test')
        task='01a10c6e-5179-7928-ba96-c78ebc1f242f'
        self.assertEqual(cleanup.identity_label(b,b.PREFIX+'-snapshot-job-'+task,task),'delivery-kit.source-task')
        self.assertEqual(cleanup.identity_label(b,b.PREFIX+'-controls-job-'+'a'*12,task),'delivery-kit.source-task')
        with self.assertRaises(ValueError):cleanup.identity_label(b,b.PREFIX+'-snapshot-job-'+task,'different-task')
    def test_new_preparation_has_unique_cleanup_identity(self):
        b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner',docker=Mock(return_value=[]))
        first=cleanup.new_name(b,'seed','issue','scope');second=cleanup.new_name(b,'seed','issue','scope')
        self.assertNotEqual(first,second)
        self.assertTrue(first.startswith('delivery-kit-test-seed-'))
        with self.assertRaises(ValueError):cleanup.new_name(b,'arbitrary','issue','scope')
    def test_active_preparation_cannot_be_overlapped(self):
        b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner',docker=Mock(return_value=[{'Names':['/delivery-kit-test-seed-existing']}]))
        with self.assertRaises(ValueError):cleanup.new_name(b,'seed','issue','scope')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.sqlite'
        self.name='delivery-kit-test-seed-'+'a'*32
        self.calls=[];self.running=False;self.foreign=False;self.timeout=False
        self.b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner',db=self.db,docker=self.docker,
            STATE=Path(self.tmp.name),docker_stdout=lambda *args,**kwargs:'private helper diagnostics')
    @contextlib.contextmanager
    def db(self):
        con=sqlite3.connect(self.path);con.row_factory=sqlite3.Row
        try:
            with con:yield con
        finally:con.close()
    def docker(self,method,path):
        self.calls.append(method)
        if method=='GET':return {'Id':'a'*64,'Image':'sha256:'+'b'*64,'Config':{'Env':['PRIVATE_SECRET=not-for-metadata'],'Labels':{'delivery-kit.owner':'other' if self.foreign else 'owner','delivery-kit.issue-id':'issue'}},'State':{'Running':self.running}}
        if self.timeout:raise TimeoutError('slow Docker deletion')
    def status(self):
        with self.db() as con:return con.execute('SELECT status FROM helper_cleanup').fetchone()[0]
    def test_schedule_has_no_docker_io_and_is_durable(self):
        cleanup.schedule(self.b,self.name,'issue');cleanup.schedule(self.b,self.name,'issue')
        self.assertEqual(self.calls,[]);self.assertEqual(self.status(),'pending')
        cleanup.tick(self.b);self.assertEqual(self.status(),'done');self.assertEqual(self.calls,['GET','GET','DELETE'])
        folder=Path(self.tmp.name)/'helper-archives'/('a'*64)
        self.assertEqual((folder/'logs.txt').read_text(),'private helper diagnostics')
        self.assertNotIn('PRIVATE_SECRET',(folder/'metadata.json').read_text())
        self.assertEqual((folder/'logs.txt').stat().st_mode & 0o777,0o600)
        self.assertEqual(folder.stat().st_mode & 0o777,0o700)
    def test_delete_timeout_cannot_invalidate_successful_bootstrap(self):
        cleanup.schedule(self.b,self.name,'issue');self.timeout=True;cleanup.tick(self.b)
        self.assertEqual(self.status(),'pending')
        self.assertEqual(self.calls,['GET','GET','DELETE'])
        with self.db() as con:con.execute('UPDATE helper_cleanup SET next_try=0')
        cleanup.tick(self.b)
        self.assertEqual(self.calls,['GET','GET','DELETE','GET'])
        self.assertEqual(self.status(),'pending')
    def test_running_or_foreign_helper_never_deleted(self):
        for field in ('running','foreign'):
            with self.subTest(field=field):
                with self.db() as con:cleanup.initialize(con);con.execute('DELETE FROM helper_cleanup')
                self.calls=[];self.running=False;self.foreign=False;setattr(self,field,True)
                cleanup.schedule(self.b,self.name,'issue');cleanup.tick(self.b)
                self.assertEqual(self.status(),'blocked');self.assertEqual(self.calls,['GET'])
    def test_arbitrary_name_or_ownership_reassignment_rejected(self):
        with self.assertRaises(ValueError):cleanup.schedule(self.b,'unrelated-container','issue')
        cleanup.schedule(self.b,self.name,'issue')
        with self.assertRaises(ValueError):cleanup.schedule(self.b,self.name,'other')

    def test_active_lease_or_failed_archive_prevents_retirement(self):
        cleanup.schedule(self.b,self.name,'issue')
        with self.db() as con:
            con.execute('CREATE TABLE leases(status TEXT)');con.execute("INSERT INTO leases VALUES('running')")
        cleanup.tick(self.b);self.assertEqual(self.calls,[])
        with self.db() as con:con.execute('DELETE FROM leases')
        self.b.docker_stdout=Mock(side_effect=RuntimeError('log capture unavailable'))
        cleanup.tick(self.b)
        self.assertNotIn('DELETE',self.calls)
        self.assertEqual(self.status(),'pending')

    def test_identity_change_after_archive_and_symlink_archive_block_delete(self):
        cleanup.schedule(self.b,self.name,'issue')
        original=self.docker('GET','unused');self.calls=[]
        changed={**original,'Id':'c'*64}
        self.b.docker=Mock(side_effect=[original,changed])
        cleanup.tick(self.b)
        self.assertEqual(self.status(),'blocked')
        self.assertTrue(all(call.args[0]!='DELETE' for call in self.b.docker.call_args_list))
        with self.db() as con:con.execute("UPDATE helper_cleanup SET status='pending',next_try=0")
        self.b.docker=Mock(return_value=original)
        folder=Path(self.tmp.name)/'helper-archives'/('a'*64)
        (folder/'logs.txt').unlink();(folder/'logs.txt').symlink_to(Path(self.tmp.name)/'state.sqlite')
        cleanup.tick(self.b)
        self.assertEqual(self.status(),'blocked')
        self.assertTrue(all(call.args[0]!='DELETE' for call in self.b.docker.call_args_list))
