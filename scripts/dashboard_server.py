#!/usr/bin/env python3
"""
개발용: 정적 파일 + 시세 API.
  python3 scripts/dashboard_server.py
  http://127.0.0.1:8765/dashboard.html?live=1
"""
from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from _bootstrap import ROOT, setup

setup()

from dashboard_config import prefer_kis_quotes, quotes_path
from holdings_quotes import sync_holdings_quotes


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/quotes":
            self._json_response(self._quotes_payload())
            return
        super().do_GET()

    def _quotes_payload(self) -> dict:
        meta = sync_holdings_quotes(prefer_kis=prefer_kis_quotes())
        return meta["quotes_payload"]

    def _json_response(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    port = int(os.getenv("DASHBOARD_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"http://127.0.0.1:{port}/dashboard.html")
    print(f"http://127.0.0.1:{port}/reports/dashboard_eod.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
