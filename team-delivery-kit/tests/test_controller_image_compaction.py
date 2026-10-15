import copy
import unittest
from qualify_controller_image_compaction import compare


class ImageCompactionTests(unittest.TestCase):
    def test_expected_update_and_empty_command_are_the_only_code_config_changes(self):
        old=dict(Env=['SAFE=known'],User='root',Entrypoint=['python','/broker.py'],Cmd=None)
        before={'broker.py':dict(sha256='a'*64,mode=420),'changed.py':dict(sha256='b'*64,mode=420)}
        after=copy.deepcopy(before);after['changed.py']['sha256']='c'*64
        compare(old,{**old,'Cmd':[]},before,after,{'changed.py':'c'*64})
        for key,value in (('Env',['SAFE=drift']),('User','10000'),('Entrypoint',['shell']),('Cmd',['something'])):
            with self.assertRaises(ValueError):compare(old,{**old,key:value},before,after,{'changed.py':'c'*64})
        after['broker.py']['sha256']='d'*64
        with self.assertRaises(ValueError):compare(old,old,before,after,{'changed.py':'c'*64})

    def test_file_deletion_permissions_or_unexpected_updates_fail_closed(self):
        before={'broker.py':dict(sha256='a'*64,mode=420)}
        for after in ({},{'broker.py':dict(sha256='a'*64,mode=511)},{**before,'extra.py':dict(sha256='a'*64,mode=420)}):
            with self.assertRaises(ValueError):compare({}, {}, before,after,{})
