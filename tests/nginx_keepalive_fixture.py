#!/usr/bin/env python3
"""Real Nginx/TLS/Telemt WEB and SYN counts on an already isolated runner.

The caller owns the Telemt process. Only private Nginx files/ports are used;
packet capture retains TCP identities, never HTTP payloads or credentials.
"""
import http.client
import importlib.util
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('keepalive_runtime',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)


class HTTPSProbe(s.UpdateWEBProbe):
    def request(self,method,path,body=None,headers=None,timeout=5):
        connection=http.client.HTTPSConnection(self.host,14445,timeout=timeout,context=self.context)
        # Connect to private loopback while retaining verified SNI/hostname.
        connection._create_connection=lambda address,timeout,source_address=None: socket.create_connection(('127.0.0.1',14445),timeout)
        try:
            connection.request(method,path,body,{'Host':self.host,**(headers or {})})
            response=connection.getresponse(); fields={}
            s.require(len(response.getheaders())<=64)
            for key,value in response.getheaders():
                key=key.lower(); s.require(key not in fields and len(value)<=8192)
                fields[key]=value
            raw=response.read(256*1024+1); s.require(len(raw)<=256*1024)
            self.requests+=1
            return response.status,fields,raw
        finally: connection.close()


class SYNs:
    def __enter__(self):
        self.socket=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x0800))
        self.socket.bind(('lo',0)); self.socket.settimeout(.1)
        self.stop=threading.Event(); self.seen=set()
        def capture():
            while not self.stop.is_set():
                try: packet=self.socket.recv(96)
                except socket.timeout: continue
                if len(packet)<54 or packet[14]>>4!=4 or packet[23]!=6: continue
                tcp=14+(packet[14]&15)*4
                if len(packet)<tcp+20 or int.from_bytes(packet[tcp+2:tcp+4],'big')!=18080: continue
                if packet[tcp+13]&0x12==0x02:
                    # The same loopback SYN is seen on ingress and egress.
                    self.seen.add((packet[26:34],packet[tcp:tcp+8]))
        self.thread=threading.Thread(target=capture); self.thread.start()
        return self
    def __exit__(self,*args):
        self.stop.set(); self.thread.join(timeout=2)
        s.require(not self.thread.is_alive()); self.socket.close()


def main():
    s.require(os.geteuid()==0)
    config=s.read_config(sys.argv[1]); host=config['web']['vhosts'][0]['host']
    probe=HTTPSProbe(config); probe.requests=0
    with tempfile.TemporaryDirectory(prefix='twm-real-keepalive-') as directory:
        root=Path(directory)
        cert=root/'cert.pem'; key=root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-subj','/CN='+host,'-addext','subjectAltName=DNS:'+host,
            '-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        key.chmod(0o600); probe.context=ssl.create_default_context(cafile=str(cert))
        main_config=root/'nginx.conf'; vhost=root/'vhost.conf'
        main_config.write_text('load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n'
            f'worker_processes 1; pid {root}/nginx.pid; error_log {root}/error.log crit;\n'
            'events { worker_connections 1024; }\n'
            'stream { server { listen 127.0.0.1:14445; proxy_protocol on; proxy_pass 127.0.0.1:17445; } }\n'
            f'http {{ access_log off; include {vhost}; }}\n')
        counts=[]
        for keepalive in (False,True):
            content=s.render_vhost(host,keepalive=keepalive).replace('127.0.0.1:7444','127.0.0.1:17445')
            content=content.replace(f'/etc/letsencrypt/live/{host}/fullchain.pem',str(cert))
            content=content.replace(f'/etc/letsencrypt/live/{host}/privkey.pem',str(key))
            vhost.write_text(content)
            command=['nginx','-p',str(root)+'/', '-c',str(main_config)]
            subprocess.run([*command,'-t'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            process=subprocess.Popen([*command,'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    s.require(process.poll() is None)
                    try:
                        with socket.create_connection(('127.0.0.1',14445),.1): break
                    except OSError: time.sleep(.05)
                else: raise ValueError('private Nginx readiness failed')
                start=time.monotonic(); requests=probe.requests
                with SYNs() as capture:
                    for _ in range(32): probe.run(full=False)
                requests=probe.requests-requests; counts.append(len(capture.seen))
                s.require(requests==192)
                print(f'REAL HTTPS WEB: keepalive={keepalive}; 32 authenticated sessions; '
                      f'{requests} requests; new backend TCP SYN={counts[-1]}; '
                      f'elapsed={time.monotonic()-start:.3f}s',flush=True)
            finally:
                if process.poll() is None: process.send_signal(signal.SIGQUIT)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(); raise
                s.require(process.returncode==0)
        s.require(counts[0]>=192 and 0<counts[1]<counts[0]/10,'real connection reuse regression')
        print(f'REAL backend connection reduction: {100*(1-counts[1]/counts[0]):.2f}%; '
              'same Telemt process, request sequence and TLS/WEB checks',flush=True)


if __name__=='__main__':
    try: main()
    except Exception:
        raise SystemExit('Real Nginx keepalive/WEB regression failed; credentials withheld') from None
