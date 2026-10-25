"""Isolated Tushare page fixture: fake credentials, fake DNS and no supplier traffic.
Run python3 tests/run_data_settings_fixture.py --port 13189 [--mixed-results].
Login token: quant-fixture-token (synthetic only).
"""
import argparse
import json
from pathlib import Path
import socket
import sys
import tempfile
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deck.data_settings import DataSettings
from deck.deck_server import Handler as QuantHandler
from deck.web_security import Security


class Handler(QuantHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            if self._gate():
                self.send_response(303)
                self.send_header('Location', '/data-settings')
                self.send_header('Content-Length', '0')
                self.end_headers()
            return
        if path in ('/api/build_mode', '/api/live/portal_dash'):
            if self._gate():
                self._send_json({'mode':'fixture','data_date':'合成测试','timing':{}})
            return
        allowed = {'/login','/data-settings','/api/auth/status','/api/navigation','/api/data-settings/tushare'}
        if path in allowed or path.startswith(('/v2/assets/','/v2/core/','/v2/components/')):
            return super().do_GET()
        self._send_json({'ok':False,'error':'Fixture route unavailable'},404)

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path in ('/api/auth/login','/api/auth/logout','/api/data-settings/tushare','/api/data-settings/tushare/verify'):
            return super().do_POST()
        self._send_json({'ok':False,'error':'Fixture route unavailable'},404)


def write_metadata(root):
    # Synthetic copy: never read the repository's config/data_sources.json.
    path = Path(root) / 'data_sources.json'
    path.write_text(json.dumps({'testSymbol': '000001.SZ', 'checks': [
        {'id': 'daily', 'label': '日线行情', 'api': 'daily', 'fields': 'ts_code,trade_date,close'},
        {'id': 'adj_factor', 'label': '复权因子', 'api': 'adj_factor', 'fields': 'ts_code,trade_date,adj_factor'},
        {'id': 'fina_indicator', 'label': '财务指标', 'api': 'fina_indicator', 'fields': 'ts_code,end_date,roe'}]}, ensure_ascii=False), encoding='utf-8')
    path.chmod(0o600)
    return path


def fake_dns(*args, **kwargs):
    return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]


def fake_transport(mixed=False):
    def request(endpoint, payload, resolved_ip, timeout, max_response):
        if mixed and payload['api_name']=='fina_indicator':
            return {'code':2002,'msg':'synthetic 权限不足 (not returned to browser)'}
        return {'code':0,'data':{'items':[[1]]}}
    return request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=13189)
    parser.add_argument('--mixed-results',action='store_true')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='quant-data-fixture-') as directory:
        root=Path(directory)
        token=root/'management-token'
        token.write_text('quant-fixture-token')
        token.chmod(0o600)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
        server.security=Security(token)
        server.data_settings=DataSettings(root/'params.yaml',metadata_path=write_metadata(root),transport=fake_transport(args.mixed_results),resolver=fake_dns,cooldown_seconds=0)
        print(f'Fixture: http://127.0.0.1:{args.port}/data-settings (synthetic login token: quant-fixture-token)',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__=='__main__':
    main()
