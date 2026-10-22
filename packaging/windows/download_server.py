"""Small read-only HTTPS origin for temporary Windows release files."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import threading
from urllib.parse import unquote, urlsplit


class Handler(SimpleHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(20)
        super().setup()

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        parts = path.split('/')
        if any(p in ('.', '..') or '\\' in p or ':' in p for p in parts):
            self.send_error(404)
            return None
        if path == '/':
            self.path = '/index.html'
        elif Path(path).name not in ('Buggcraft-Setup.exe', 'Buggcraft-runtime-windows-x64.zip',
                                     'release.json', 'index.html', 'collect-launcher-diagnostics.ps1'):
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header('Cache-Control', 'no-cache' if self.path.endswith('.html') else 'public, max-age=3600')
        super().end_headers()

    def log_message(self, format, *args):
        # Never include arbitrary URL query strings in release server logs.
        print(self.command, urlsplit(self.path).path[:160], flush=True)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args, **kwargs):
        self.capacity = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, *args):
        try:
            super().process_request_thread(*args)
        finally:
            self.capacity.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--port', type=int, default=18446)
    args = parser.parse_args()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server = Server(('0.0.0.0', args.port), partial(Handler, directory=str(args.root.resolve())))
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    server.serve_forever()


if __name__ == '__main__':
    main()
