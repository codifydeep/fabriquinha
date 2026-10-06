import copy
import unittest
import json
import sqlite3

from execution_context import freeze, reference, resolve, validate, registered


class ExecutionContextTests(unittest.TestCase):
    def setUp(self):
        self.description = 'Approved CEO request: ' + 'complete requirement\n' * 240
        self.review = 'Independent review: ' + 'complete criterion\n' * 180
        self.capsule = freeze(self.description, self.review)

    def test_lossless_reference_and_exact_mode(self):
        for mode, expected in [('implementation', self.description), ('review', self.review)]:
            ref = reference(self.capsule, mode)
            self.assertLess(len(ref), 4000)
            self.assertEqual(resolve(self.capsule, ref, mode), expected)
        self.assertEqual(validate(self.capsule), self.capsule)

    def test_tampering_and_wrong_reference_fail_closed(self):
        changed = copy.deepcopy(self.capsule)
        changed['description'] += 'changed'
        with self.assertRaises(ValueError):
            validate(changed)
        for mode, ref in [('review', reference(self.capsule, 'implementation')),
                          ('implementation', 'unregistered issue text')]:
            with self.assertRaises(ValueError):
                resolve(self.capsule, ref, mode)

    def test_no_extra_fields_or_unbounded_payload(self):
        with self.assertRaises(ValueError):
            validate({**self.capsule, 'permissions': ['shell']})
        for value in ('', 'x' * 12001, None):
            with self.assertRaises(ValueError):
                freeze(value, self.review)

    def test_hash_binds_both_implementation_and_review(self):
        changed = freeze(self.description, self.review + ' another criterion')
        self.assertNotEqual(changed['sha256'], self.capsule['sha256'])
        with self.assertRaises(ValueError):
            resolve(changed, reference(self.capsule, 'implementation'), 'implementation')

    def test_registered_context_requires_exact_issue_role_and_enabled_route(self):
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT, config TEXT)')
        route = dict(author='author', reviewer='reviewer', techlead='lead', cto='cto',
                     enabled=True, execution_context=self.capsule)
        con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('issue', json.dumps(route)))
        ref = reference(self.capsule, 'implementation')
        self.assertEqual(registered(con, 'implementation', 'issue', 'author', ref), self.capsule)
        for mode, agent, issue in [('implementation', 'reviewer', 'issue'),
                                   ('review', 'author', 'issue'),
                                   ('implementation', 'author', 'different')]:
            with self.assertRaises(ValueError):
                registered(con, mode, issue, agent, ref)
        route['enabled'] = False
        con.execute('UPDATE delivery_routes SET config=?', (json.dumps(route),))
        with self.assertRaises(ValueError):
            registered(con, 'implementation', 'issue', 'author', ref)

    def test_ordinary_context_unchanged_and_unregistered_marker_rejected(self):
        con = sqlite3.connect(':memory:')
        self.assertIsNone(registered(con, 'implementation', 'unknown', 'author', 'ordinary brief'))
        with self.assertRaises(ValueError):
            registered(con, 'implementation', 'unknown', 'author', reference(self.capsule, 'implementation'))
