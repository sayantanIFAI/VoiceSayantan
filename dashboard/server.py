"""The dashboard's web server: a page and four JSON endpoints, read-only, standard library only.

  GET /                      the page
  GET /api/summary           ?days=1&lang=bn            counts for the period
  GET /api/calls             ?days=1&lang=&tag=&limit=  the calls, newest first; tag: attention, dropped, transferred, clarified, said_wrong, ...
  GET /api/call              ?day=YYYY-MM-DD&id=<id>    one call: what the agent recorded, and what the recogniser heard
  GET /api/health            when the last ingest ran

A transcript is personal data. The server listens on the loopback address unless told otherwise, and refuses to listen on any other address
without a user name and password (HTTP basic authentication, compared in constant time).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from dashboard.config import Config
from dashboard.store import Store, clinic_today

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
TAGS = frozenset(
    {
        "",
        "attention",
        "dropped",
        "transferred",
        "clarified",
        "said_wrong",
        "unhappy",
        "booking",
        "booked",
        "changed",
        "answered",
        "ended",
        "quiet",
        "live",
    }
)
LANGS = frozenset({"", "bn", "hi", "en"})
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[0-9A-Za-z_-]{1,80}$")
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def _int(values: list[str], default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(values[0])))
    except (IndexError, ValueError):
        return default


def make_handler(cfg: Config, store: Store):
    expected = None
    if cfg.user or cfg.password:
        expected = "Basic " + base64.b64encode(f"{cfg.user}:{cfg.password}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "CallDashboard"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - the method name is fixed by the base class
            pass  # a request line can carry a call id; the access log is not kept

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
            )
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _allowed(self) -> bool:
            if expected is None:
                return True
            got = self.headers.get("Authorization", "")
            if hmac.compare_digest(got.encode(), expected.encode()):
                return True
            self._send(
                401, b"sign in", "text/plain; charset=utf-8", {"WWW-Authenticate": 'Basic realm="Call dashboard"'}
            )
            return False

        def do_GET(self) -> None:  # noqa: N802 - the method name is fixed by the base class
            if not self._allowed():
                return
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    with open(STATIC, "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                elif url.path == "/api/summary":
                    days, lang = _int(q.get("days", []), 1, 1, 90), q.get("lang", [""])[0]
                    if lang not in LANGS:
                        return self._json({"error": "lang must be bn, hi or en"}, 400)
                    self._json(store.summary(days, lang, clinic_today()))
                elif url.path == "/api/calls":
                    days, lang, tag = _int(q.get("days", []), 1, 1, 90), q.get("lang", [""])[0], q.get("tag", [""])[0]
                    if lang not in LANGS or tag not in TAGS:
                        return self._json({"error": "unknown lang or tag"}, 400)
                    self._json(
                        {
                            "calls": store.list_calls(
                                days, lang, tag, _int(q.get("limit", []), 100, 1, 500), clinic_today()
                            )
                        }
                    )
                elif url.path == "/api/call":
                    day, call_id = q.get("day", [""])[0], q.get("id", [""])[0]
                    if not _DAY.match(day) or not _ID.match(call_id):
                        return self._json({"error": "day and id are required"}, 400)
                    detail = store.call_detail(day, call_id)
                    if detail is None:
                        return self._json({"error": "no such call"}, 404)
                    self._json(detail)
                elif url.path == "/api/health":
                    self._json(
                        {
                            "last_ingest": store.get_meta("last_ingest"),
                            "today": clinic_today(),
                            "transcripts": cfg.keep_transcripts,
                        }
                    )
                else:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
            except BrokenPipeError:
                pass
            except Exception:  # noqa: BLE001 - one bad request must not stop the server
                self._json({"error": "server error"}, 500)

    return Handler


def serve(cfg: Config, store: Store) -> ThreadingHTTPServer:
    if cfg.host not in LOOPBACK and not (cfg.user and cfg.password):
        raise SystemExit("refusing to listen on a non-loopback address without DASHBOARD_USER and DASHBOARD_PASSWORD")
    return ThreadingHTTPServer((cfg.host, cfg.port), make_handler(cfg, store))
