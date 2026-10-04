"""Credential-safe trusted WEB probe and official redirect policy fixtures."""
import base64
import hmac
import http.server
import importlib.util
from pathlib import Path
import secrets
import struct
import sys
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('protocol_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)


class Protocol(s.UpdateWEBProbe):
    def __init__(self,defect=None,ping=False,conveyor=True):
        self.key=secrets.token_hex(16)
        super().__init__({'web':{'vhosts':[{'host':'proxy.example.com'}]},'access':{'users':{'web-user':self.key}}})
        self.defect=defect; self.ping=ping; self.conveyor=conveyor; self.calls=[]; self.bootstrap='b'*43; self.session='s'*43
    def request(self,method,path,body=None,headers=None,timeout=5):
        self.calls.append((method,path,body,dict(headers or {}))); headers=headers or {}
        if method=='GET':
            expected=base64.urlsafe_b64encode(hmac.digest(b'\xdd'+bytes.fromhex(self.key),
                b'tdesktop-web-proxy-bridge-v1\nproxy.example.com','sha256')).decode().rstrip('=')
            assert path=='/?bridge='+expected
            return 200,{},b'bootstrap = "'+self.bootstrap.encode()+b'"'
        if path=='/api/v1/session' and method=='POST':
            assert headers['Authorization']=='Bearer '+self.bootstrap
            assert body==self.frame(0x10,b'\x01')
            fields={'x-session-token':self.session,'x-telemt-up-window':'4'}
            if not self.conveyor: fields.pop('x-telemt-up-window')
            if self.defect=='token': fields['x-session-token']='invalid'
            if self.defect=='window': fields['x-telemt-up-window']='2'
            if self.defect=='session-replay' and len(self.calls)>2: fields['x-session-token']='z'*43
            return 200,fields,self.frame(0x10) if self.defect=='welcome' else self.frame(0x11)
        assert headers['Authorization']=='Bearer '+self.session
        if path=='/api/v1/up':
            assert headers['X-Up-Seq'] in ('1','2')
            return 204,{'x-up-ack':'999' if self.defect=='ack' else headers['X-Up-Seq']},b''
        if path=='/api/v1/down':
            if self.defect=='down-decoy': return 200,{},b''
            if self.defect=='down-malformed': return 200,{'x-down-cursor':'1'},b'badframe'
            if self.ping:
                frame=self.frame(5,b'probe')
                if self.defect=='down-replay' and sum(c[1]=='/api/v1/down' for c in self.calls)>1: frame=self.frame(5,b'changed')
                return 200,{'x-down-cursor':'1'},frame
            return 204,{'x-down-cursor':'0'},b''
        if method=='DELETE': return (500 if self.defect=='close' else 204),{},b''
        raise AssertionError('unexpected trusted protocol request')


class ProtocolTests(unittest.TestCase):
    def test_legacy_without_conveyor_still_requires_uplink_sequence_ack_and_replay(self):
        for ping in (False,True):
            probe=Protocol(conveyor=False,ping=ping); probe.run()
            uplinks=[c for c in probe.calls if c[1]=='/api/v1/up']
            self.assertEqual([c[3]['X-Up-Seq'] for c in uplinks],['1','1','2'] if ping else ['1','1'])
            self.assertTrue(all('X-Telemt-Up-Confirmed' not in c[3] for c in uplinks))
    def test_authenticated_hello_replay_conveyor_idle_poll_and_close(self):
        probe=Protocol(); probe.run()
        self.assertEqual([c[1] for c in probe.calls].count('/api/v1/up'),2)
        self.assertEqual(probe.calls[-1][0],'DELETE')
        self.assertNotIn(probe.key,repr(probe.calls))
    def test_ping_replay_and_pong_when_server_emits_ping(self):
        probe=Protocol(ping=True); probe.run()
        self.assertEqual([c[1] for c in probe.calls].count('/api/v1/down'),2)
        self.assertIn(probe.frame(6,b'probe'),[c[2] for c in probe.calls])
    def test_ambiguous_bad_auth_session_window_replay_downlink_close_fail(self):
        for defect in ('welcome','token','window','session-replay','ack','down-decoy','down-malformed','down-replay','close'):
            probe=Protocol(defect,ping=defect=='down-replay')
            with self.subTest(defect=defect),self.assertRaises(ValueError) as error: probe.run()
            self.assertNotIn(probe.key,str(error.exception))
            self.assertNotIn(probe.session,str(error.exception))
    def test_truncated_unknown_oversized_or_too_many_frames_fail(self):
        for raw in (b'123',s.UpdateWEBProbe.frame(0xff),b'\x05\0\0\0'+struct.pack('>I',65537),
                    s.UpdateWEBProbe.frame(5)*33,b'\0'*(256*1024+1)):
            with self.assertRaises(ValueError): s.UpdateWEBProbe.frames(raw)
    def test_real_http_transport_duplicate_headers_and_large_body_fail(self):
        for kind in ('duplicate','large'):
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    if kind=='duplicate': self.send_header('X-Down-Cursor','1'); self.send_header('X-Down-Cursor','2')
                    self.end_headers()
                    if kind=='large':
                        try: self.wfile.write(b'x'*(256*1024+1))
                        except (ConnectionError,BrokenPipeError): pass
                def log_message(self,*args): pass
            server=http.server.HTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever); thread.start()
            try:
                probe=Protocol(); probe.address=server.server_address
                with self.assertRaises(ValueError): s.UpdateWEBProbe.request(probe,'GET','/')
            finally: server.shutdown();thread.join();server.server_close()
    def test_redirect_destination_refused_before_any_connection(self):
        for url in ('http://github.com/telemt/telemt','https://api.github.com.evil.invalid/repos/telemt/telemt',
                    'https://user@github.com/telemt/telemt','https://github.com:444/telemt/telemt',
                    'https://github.com/foreign/releases/download/asset'):
            with self.assertRaises(ValueError): s.UpdateHTTP.official_url(url)
        with patch.object(s.urllib.request.HTTPRedirectHandler,'redirect_request') as follow:
            with self.assertRaises(ValueError): s.UpdateRedirect().redirect_request(None,None,302,'',{},'https://foreign.invalid/')
            follow.assert_not_called()


if __name__=='__main__': unittest.main()
