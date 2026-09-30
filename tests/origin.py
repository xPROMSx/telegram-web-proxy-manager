"""Private integration origin: validate exactly the headers Telemt relies on."""
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        valid = (self.request_version == "HTTP/1.1"
                 and self.headers.get_all("X-Forwarded-For") == ["127.0.0.1"]
                 and self.headers.get("Host") == "proxy.example.com")
        self.send_response(200 if valid else 400)
        self.end_headers()
        self.wfile.write(b"canonical\n" if valid else b"invalid\n")

    def log_message(self, *_):
        pass


HTTPServer(("127.0.0.1", 18081), Handler).serve_forever()
