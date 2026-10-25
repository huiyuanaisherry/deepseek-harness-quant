"""Ensure browser fixture cannot reach live business or real configuration."""
import http.client
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from deck.data_settings import DataSettings
from deck.web_security import Security

spec=importlib.util.spec_from_file_location('data_fixture',Path(__file__).with_name('run_data_settings_fixture.py'))
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class FixtureIsolationTests(unittest.TestCase):
    def test_no_real_dispatch_or_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            server=ThreadingHTTPServer(('127.0.0.1',0),fixture.Handler)
            server.security=Security(root/'token')
            metadata=fixture.write_metadata(root)
            server.data_settings=DataSettings(root/'params.yaml',metadata_path=metadata,transport=fixture.fake_transport(),resolver=fixture.fake_dns,cooldown_seconds=0)
            self.assertEqual(root,metadata.parent)
            self.assertEqual('000001.SZ',server.data_settings.describe()['testSymbol'])
            session=server.security.login(server.security.token,'fixture')
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                with patch.object(fixture.Handler,'_private_GET',side_effect=AssertionError('real read')), patch.object(fixture.Handler,'_private_POST',side_effect=AssertionError('real write')):
                    for method,path in [('GET','/api/pool'),('GET','/api/proxy/quantapi/sessions'),('GET','/api/model-settings'),('POST','/api/manual_update'),('POST','/api/chat/session'),('POST','/api/model-settings/provider')]:
                        with self.subTest(method=method,path=path):
                            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
                            conn.request(method,path,'{}' if method=='POST' else None,{'Cookie':'quant_session='+session,'Origin':f'http://127.0.0.1:{server.server_port}','X-Quant-Request':'1','Content-Type':'application/json'})
                            response=conn.getresponse()
                            self.assertEqual(response.status,404)
                            response.read();conn.close()
            finally:
                server.shutdown();server.server_close()
