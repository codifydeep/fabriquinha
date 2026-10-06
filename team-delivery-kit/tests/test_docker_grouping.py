import unittest
from docker_grouping import labels, args, grouped_create


class DockerGroupingTests(unittest.TestCase):
    def test_jobs_are_separate_from_core_and_preserve_ownership(self):
        original = {'Labels': {'delivery-kit.owner': 'owner', 'com.docker.compose.project': 'old'}}
        grouped = grouped_create('POST', '/containers/create?name=worker', original, 'delivery-kit-port2')
        self.assertEqual(grouped['Labels']['com.docker.compose.project'], 'delivery-kit-port2-tests')
        self.assertEqual(grouped['Labels']['delivery-kit.owner'], 'owner')
        self.assertEqual(original['Labels']['com.docker.compose.project'], 'old')

    def test_non_container_operations_unchanged_and_bad_namespace_rejected(self):
        payload = {'Name': 'volume'}
        self.assertIs(grouped_create('POST', '/volumes/create', payload, 'delivery-kit-port2'), payload)
        with self.assertRaises(ValueError):
            labels(namespace='toso-other')
        self.assertIn('com.docker.compose.project=delivery-kit-port2-homologation',
                      args(namespace='delivery-kit-port2', kind='homologation'))
