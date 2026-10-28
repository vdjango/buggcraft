"""Loopback HTTP responses for the real update parser and downloader.

Only HTTPS socket transport is replaced. Canonical production URLs still pass
through the shipping URL checks, redirect handlers, streaming and digest code.
This fixture does not claim to validate public TLS or the deployed CDN.
"""
from __future__ import annotations

import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, build_opener
from urllib.response import addinfourl


class LauncherUpdateUiFixtures:
    origin = "https://download.bugg.icu"
    asset_path = "/api/launcher/assets/9.9.9/Buggcraft.exe"

    def __init__(self):
        self.payload = b"UI update package\n" * 100_000
        self.requests = []
        self.available = True
        self.include_ticket = True
        self.check_failure = False
        self.cdn_failure = False
        self.stable_failure = False
        self.corrupt = False
        self.ticket_count = 0
        self.pause_download = False
        self.download_paused = Event()
        self.release_download = Event()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path
                fixture.requests.append({
                    "path": path, "query": parse_qs(parsed.query),
                    "userAgent": self.headers.get("User-Agent"),
                })
                if path == "/api/launcher/update":
                    if fixture.check_failure:
                        self.send_error(503, "Update check temporarily unavailable")
                    else:
                        self.send_json(fixture.manifest())
                elif path == fixture.asset_path + "/ticket":
                    fixture.ticket_count += 1
                    self.send_json({
                        "url": "https://kodo.bugg.icu/cdn/Buggcraft.exe?ticket=" + str(fixture.ticket_count),
                        "transport": "https", "expires_in": 600,
                        "size": len(fixture.payload),
                        "sha256": hashlib.sha256(fixture.payload).hexdigest(),
                    })
                elif path in (fixture.asset_path, "/cdn/Buggcraft.exe"):
                    if fixture.cdn_failure if path.startswith("/cdn/") else fixture.stable_failure:
                        self.send_error(503, "Package temporarily unavailable")
                        return
                    body = fixture.payload
                    if fixture.corrupt:
                        body = b"X" + body[1:]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    try:
                        # Exceed one production read chunk so the UI can observe
                        # actual intermediate progress before releasing the rest.
                        split = 1024 * 1024
                        self.wfile.write(body[:split])
                        self.wfile.flush()
                        if fixture.pause_download:
                            fixture.download_paused.set()
                            if not fixture.release_download.wait(15):
                                return
                        self.wfile.write(body[split:])
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                else:
                    self.send_error(404)

            def send_json(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        class LoopbackHttpsHandler(HTTPSHandler):
            def https_open(self, request):
                parsed = urlsplit(request.full_url)
                if parsed.hostname not in ("download.bugg.icu", "kodo.bugg.icu"):
                    raise AssertionError("Unexpected update UI request host: " + str(parsed.hostname))
                connection = HTTPConnection("127.0.0.1", fixture.server.server_port, timeout=request.timeout)
                target = parsed.path + ("?" + parsed.query if parsed.query else "")
                connection.request(request.get_method(), target, headers=dict(request.header_items()))
                response = connection.getresponse()
                wrapped = addinfourl(response, response.headers, request.full_url, response.status)
                wrapped.msg = response.reason
                return wrapped

        self.https_handler = LoopbackHttpsHandler

    def manifest(self):
        asset = {
            "name": "Buggcraft.exe", "platform": "windows-x64",
            "url": self.origin + self.asset_path,
            "size": len(self.payload), "sha256": hashlib.sha256(self.payload).hexdigest(),
        }
        if self.include_ticket:
            asset["ticket_url"] = asset["url"] + "/ticket"
        return {"update_available": self.available, "version": "9.9.9",
                "notes": "UI fixture: update delivery compatibility.", "asset": asset}

    def build_opener(self, *handlers):
        return build_opener(ProxyHandler({}), self.https_handler(), *handlers)

    def urlopen(self, request, timeout=8):
        return self.build_opener().open(request, timeout=timeout)

    def count(self, path):
        return sum(item["path"] == path for item in self.requests)

    def close(self):
        self.release_download.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
