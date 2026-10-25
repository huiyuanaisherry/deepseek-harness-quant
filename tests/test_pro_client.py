import socket
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


class ProClientTests(unittest.TestCase):
    def client(self, result=None, endpoint='https://relay.example/pro/', **kwargs):
        from data.pro_client import ProClient
        self.calls = []
        def transport(*args):
            self.calls.append(args)
            return result if result is not None else {'code': 0, 'data': {'fields': ['ts_code', 'close'], 'items': [['000938.SZ', 12.5]]}}
        resolver = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        return ProClient('synthetic-secret', endpoint, transport=transport, resolver=resolver, **kwargs)

    def test_sdk_style_call_uses_exact_endpoint_and_standard_json(self):
        result = self.client().daily(ts_code='000938.SZ', fields='ts_code,close', limit=3)
        self.assertEqual([{'ts_code': '000938.SZ', 'close': 12.5}], result.to_dict('records'))
        endpoint, body, ip, timeout, cap = self.calls[0]
        self.assertEqual('https://relay.example/pro/', endpoint)
        self.assertEqual({'api_name': 'daily', 'token': 'synthetic-secret', 'params': {'ts_code': '000938.SZ', 'limit': 3}, 'fields': 'ts_code,close'}, body)
        self.assertEqual('8.8.8.8', ip)
        self.assertLessEqual(timeout, 15)
        self.assertLessEqual(cap, 16 * 1024 * 1024)

    def test_http_requires_explicit_acknowledgement(self):
        from deck.model_settings import SettingsError
        with self.assertRaises(SettingsError) as caught:
            self.client(endpoint='http://relay.example/').daily()
        self.assertEqual('INSECURE_HTTP_CONFIRMATION_REQUIRED', caught.exception.code)
        self.assertFalse(self.calls)
        self.client(endpoint='http://relay.example/', allow_insecure_http=True).daily()
        self.assertEqual(1, len(self.calls))

    def test_private_destination_rejected_before_transport(self):
        from deck.model_settings import SettingsError
        with self.assertRaises(SettingsError):
            self.client(endpoint='https://127.0.0.1/').daily()
        self.assertFalse(self.calls)

    def test_upstream_error_and_exception_never_expose_secrets(self):
        from deck.model_settings import SettingsError
        client = self.client({'code': -1, 'msg': 'token synthetic-secret rejected at private/path'})
        with self.assertRaises(SettingsError) as caught:
            client.daily()
        self.assertEqual('CREDENTIALS', caught.exception.code)
        self.assertNotIn('synthetic-secret', str(caught.exception))
        client = self.client()
        with patch.object(client, '_transport', side_effect=RuntimeError('synthetic-secret')):
            with self.assertRaises(SettingsError) as caught:
                client.daily()
        self.assertNotIn('synthetic-secret', str(caught.exception))

    def test_malformed_table_rejected_and_valid_empty_table_preserved(self):
        from deck.model_settings import SettingsError
        for data in ({'fields': ['a'], 'items': [[1, 2]]}, {'fields': ['a', 'a'], 'items': [[1, 2]]}, {'fields': 'a', 'items': []}):
            with self.subTest(data=data), self.assertRaises(SettingsError):
                self.client({'code': 0, 'data': data}).query('daily')
        frame = self.client({'code': 0, 'data': {'fields': ['a'], 'items': []}}).query('daily')
        self.assertTrue(frame.empty)
        self.assertEqual(['a'], list(frame.columns))

    def test_environment_proxy_does_not_change_transport(self):
        from data.pro_client import ProClient
        from deck.data_settings import PinnedTransport
        class Response:
            status = 200
            def read(self, size):
                # Real transport accepts runtime responses above settings' cap.
                return json.dumps({'code': 0, 'data': {'fields': ['name'], 'items': [['a' * 300000]]}}).encode()
        class Connection:
            def __init__(self, *args):
                self.args = args
            def request(self, method, path, body, headers):
                self.request_path = path
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch.dict('os.environ', {'HTTPS_PROXY': 'http://127.0.0.1:9'}), patch('deck.data_settings._PinnedHTTPSConnection', Connection):
            client = self.client()
            client._transport = PinnedTransport()
            result = client.daily()
        self.assertEqual(300000, len(result.name.iloc[0]))

    def test_stock_list_cache_respects_selected_data_directory(self):
        import pandas as pd
        from data import fetcher_tushare as fetcher
        from types import SimpleNamespace
        frame = pd.DataFrame([{'ts_code': '000938.SZ', 'symbol': '000938', 'name': 'sample', 'industry': 'sample', 'list_date': '20000101'}])
        client = SimpleNamespace(stock_basic=lambda **kw: frame)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'LWQUANT_CACHE_DIR': tmp}), patch.object(fetcher, '_pro', return_value=client):
            result = fetcher.get_stock_list(use_cache=False)
            self.assertEqual(frame.to_dict('records'), result.to_dict('records'))
            self.assertTrue((Path(tmp) / 'stock_list.csv').is_file())


if __name__ == '__main__':
    unittest.main()
