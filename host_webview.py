# -*- coding: utf-8 -*-
"""KirKpr 5.0.01 — pywebview + Edge WebView2 (vzorec Trops Studio 5).

HTTP API + statični ui/; js_api Bridge samo za datotečne dialoge / zapiranje.
Poslovni klici gredo skozi kirkpr_webview_service.KirKprService.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UI = ROOT / "ui"
HOST = "127.0.0.1"
WEBVIEW_PROFILE_DIR = Path.home() / "AppData" / "Local" / "KirKpr" / "WebViewProfile"

from kirkpr_webview_jobs import JobManager  # noqa: E402
from kirkpr_webview_service import APP_TITLE, APP_VERSION, KirKprService  # noqa: E402

log = logging.getLogger("kirkpr.host")


class BadRequest(ValueError):
    pass


class NotFound(LookupError):
    pass


class Bridge:
    """Datotečni izbirnik in zapiranje — brez Tk (kot Trops)."""

    def _dialog(self, kind_name: str, file_types: Any = None, directory: bool = False) -> str:
        try:
            import webview
        except Exception:
            return ""
        wins = webview.windows
        if not wins:
            return ""
        fd = getattr(webview, "FileDialog", None)
        if directory:
            kind = getattr(fd, "FOLDER", None) if fd else None
            if kind is None:
                kind = getattr(webview, "FOLDER_DIALOG", 20)
        else:
            kind = getattr(fd, kind_name, None) if fd else None
            if kind is None:
                kind = getattr(webview, "OPEN_DIALOG" if kind_name == "OPEN" else "SAVE_DIALOG", 10)
        kwargs: Dict[str, Any] = {}
        if file_types:
            kwargs["file_types"] = tuple(file_types) if isinstance(file_types, (list, tuple)) else (file_types,)
        result = wins[0].create_file_dialog(kind, **kwargs)
        if not result:
            return ""
        if isinstance(result, (list, tuple)):
            return str(result[0] or "")
        return str(result)

    def pick_file(self, file_types: Any = None) -> str:
        return self._dialog(
            "OPEN",
            file_types or ("KIR/KPR (*.zip;*.json;*.xml;*.csv)", "Vse (*.*)"),
        )

    def pick_folder(self) -> str:
        return self._dialog("FOLDER", directory=True)

    def pick_settings_file(self) -> str:
        return self._dialog("OPEN", ("JSON (*.json)", "Vse (*.*)"))

    def close_window(self) -> None:
        try:
            import webview
            if webview.windows:
                webview.windows[0].destroy()
        except Exception:
            pass


def _json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, service: KirKprService | None = None) -> None:
        self.service = service or KirKprService()
        self.jobs = JobManager()
        self.token = secrets.token_urlsafe(32)
        super().__init__((HOST, 0), Handler)
        self.allowed_host = f"{HOST}:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: AppServer

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _ok_origin(self) -> bool:
        host = (self.headers.get("Host") or "").split("%")[0]
        return host == self.server.allowed_host

    def _ticket_ok(self) -> bool:
        if not self._ok_origin():
            return False
        cookie = self.headers.get("Cookie") or ""
        if f"kirkpr5={self.server.token}" in cookie:
            return True
        q = parse_qs(urlparse(self.path).query)
        tickets = q.get("ticket") or []
        return bool(tickets) and tickets[0] == self.server.token

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_resp(self, code: int, obj: Any, extra: Optional[Dict[str, str]] = None) -> None:
        if isinstance(obj, dict) and obj.get("ok") is False:
            obj = normalize_result(obj)
        self._send(code, _json(obj), "application/json; charset=utf-8", extra)

    def _error(self, code: int, message: str) -> None:
        self._json_resp(code, {"ok": False, "error": message, "msg": message})

    def _exception(self, exc: Exception) -> None:
        if isinstance(exc, BadRequest):
            self._error(400, str(exc))
        elif isinstance(exc, NotFound):
            self._error(404, str(exc))
        elif isinstance(exc, RuntimeError) and "Druga naloga" in str(exc):
            self._error(409, str(exc))
        else:
            log.error("Napaka v API: %s\n%s", exc, traceback.format_exc())
            self._error(500, f"Notranja napaka: {exc}")

    def _read_json(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or "0")
        if n < 0 or n > 4_000_000:
            return {}
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        q = parse_qs(parsed.query)
        extra = {"Set-Cookie": f"kirkpr5={self.server.token}; HttpOnly; SameSite=Strict; Path=/"}

        if path.startswith("/ui/"):
            if not self._ok_origin():
                self._json_resp(403, {"ok": False, "msg": "Ni veljavne seje."})
                return
            rel = path[4:].lstrip("/")
            fp = (UI / rel).resolve()
            if UI.resolve() not in fp.parents and fp != UI.resolve():
                self._json_resp(403, {"ok": False})
                return
            if not fp.is_file():
                self._json_resp(404, {"ok": False, "msg": "Datoteka ni najdena."})
                return
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            self._send(200, fp.read_bytes(), ctype)
            return

        if not self._ticket_ok():
            self._json_resp(403, {"ok": False, "msg": "Ni veljavne seje."})
            return

        if path in ("/", "/index.html"):
            html = (UI / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8", extra)
            return

        s = self.server.service
        try:
            if path == "/api/boot":
                self._json_resp(200, s.boot())
                return
            if path == "/api/companies":
                search = (q.get("q") or [""])[0]
                self._json_resp(200, s.list_companies(search))
                return
            if path == "/api/ir":
                self._json_resp(200, s.list_ir((q.get("q") or [""])[0]))
                return
            if path == "/api/pr":
                self._json_resp(200, s.list_pr((q.get("q") or [""])[0]))
                return
            if path == "/api/ddvo":
                self._json_resp(200, s.ddvo((q.get("q") or [""])[0]))
                return
            if path == "/api/paths":
                self._json_resp(200, s.path_settings())
                return
            if path == "/api/job":
                job = self.server.jobs.get((q.get("id") or [""])[0])
                if job is None:
                    self._json_resp(404, {"ok": False, "error": "Naloga ne obstaja.", "msg": "Naloga ne obstaja."})
                    return
                job["ok"] = job.get("state") != "error"
                if job.get("result") is not None:
                    job["result"] = normalize_result(job["result"])
                self._json_resp(200, job)
                return
            self._error(404, f"Neznan GET: {path}")
        except Exception as exc:
            self._exception(exc)

    def do_POST(self) -> None:
        if not self._ticket_ok():
            self._json_resp(403, {"ok": False, "msg": "Ni veljavne seje."})
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        body = self._read_json()
        s = self.server.service
        try:
            if path == "/api/action":
                self._json_resp(200, dispatch_action(s, body, self.server.jobs))
                return
            if path == "/api/company/select":
                self._json_resp(200, s.select_company(str(body.get("key") or "")))
                return
            if path == "/api/period":
                self._json_resp(
                    200,
                    s.set_period(
                        period_from=str(body.get("from") or body.get("period_from") or ""),
                        period_to=str(body.get("to") or body.get("period_to") or ""),
                        label=str(body.get("label") or ""),
                    ),
                )
                return
            if path == "/api/paths/save":
                self._json_resp(
                    200,
                    s.save_path_settings(
                        company_registry_path=str(body.get("company_registry_path") or ""),
                        trops_root=str(body.get("trops_root") or ""),
                        minimax_settings_path=str(body.get("minimax_settings_path") or ""),
                    ),
                )
                return
            self._error(404, f"Neznan POST: {path}")
        except Exception as exc:
            self._exception(exc)


LONG_ACTIONS = {
    "load_source": "Nalaganje KIR/KPR",
    "open_last_source": "Odpiranje zadnje datoteke",
}


def _actions(s: KirKprService) -> Dict[str, Callable[[Dict[str, Any]], Any]]:
    return {
        "refresh": lambda b: s.boot(),
        "shift_period": lambda b: s.shift_period(-1 if int(b.get("delta") or 1) < 0 else 1),
        "reset_period": lambda b: s.reset_period(),
        "load_source": lambda b: s.load_source(str(b.get("path") or "")),
        "open_last_source": lambda b: s.open_last_source(),
    }


def normalize_result(res: Any) -> Any:
    if isinstance(res, dict):
        if res.get("ok") is False:
            err = str(res.get("error") or res.get("msg") or res.get("message") or "Napaka.")
            res["error"] = err
            res["msg"] = err
        elif "msg" not in res and res.get("message"):
            res["msg"] = str(res.get("message"))
    return res


def dispatch_action(s: KirKprService, body: Dict[str, Any], jobs: Optional[JobManager] = None) -> Dict[str, Any]:
    name = str(body.get("name") or "").strip()
    if not name:
        raise BadRequest("Manjka name.")
    table = _actions(s)
    fn = table.get(name)
    if fn is None:
        raise NotFound(f"Neznana akcija: {name}")
    if jobs is not None and name in LONG_ACTIONS and not body.get("sync"):
        return jobs.start(LONG_ACTIONS[name], lambda payload: normalize_result(fn(payload)), dict(body))
    if jobs is not None and jobs.busy:
        raise BadRequest("Naloga v ozadju še teče — počakaj na zaključek.")
    return normalize_result(fn(body))


def desktop() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    if sys.platform != "win32":
        raise SystemExit("Namizni zagon je namenjen Windows 10/11.")
    if not (UI / "index.html").is_file():
        raise SystemExit(f"Manjka UI: {UI / 'index.html'}")
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "Manjka pywebview. Namestitev: py -3.10 -m pip install pywebview"
        ) from exc

    WEBVIEW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    server = AppServer()
    threading.Thread(target=server.serve_forever, name="kirkpr-5-api", daemon=True).start()
    url = f"http://{server.allowed_host}/?ticket={server.token}"
    webview.create_window(
        f"{APP_TITLE} v{APP_VERSION}",
        url,
        width=1480,
        height=940,
        min_size=(1100, 720),
        background_color="#f4f7fc",
        text_select=True,
        js_api=Bridge(),
    )
    webview.start(
        gui="edgechromium",
        debug=False,
        private_mode=False,
        storage_path=str(WEBVIEW_PROFILE_DIR),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(desktop() or 0)