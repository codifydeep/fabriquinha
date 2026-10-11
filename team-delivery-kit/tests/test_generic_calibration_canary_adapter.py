import unittest
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import generic_calibration_materialization_canary as canary


class CanaryAdapterTests(unittest.TestCase):
    def connection(self,status,data):
        con=MagicMock();con.getresponse.return_value=SimpleNamespace(status=status,read=lambda limit:data)
        return con

    def test_absence_is_only_authoritative_http_404_not_error_prose(self):
        con=self.connection(404,b'{"message":"no such volume"}')
        with patch.object(canary,'LocalConnection',return_value=con):
            self.assertIsNone(canary.docker('GET','/volumes/owned'))
        self.assertEqual(con.request.call_args.args[1],'/v1.45/volumes/owned')
        con.close.assert_called_once()

    def test_observation_failure_is_not_treated_as_absence(self):
        con=self.connection(503,b'{"message":"no such"}')
        with patch.object(canary,'LocalConnection',return_value=con):
            with self.assertRaises(ValueError):canary.docker('GET','/volumes/owned')
        con.close.assert_called_once()

    def test_raw_api_keeps_network_flag_instead_of_inventing_it_from_cli_projection(self):
        con=self.connection(200,b'{"Config":{"NetworkDisabled":false}}')
        with patch.object(canary,'LocalConnection',return_value=con):
            self.assertIs(canary.docker('GET','/containers/owned/json')['Config']['NetworkDisabled'],False)
