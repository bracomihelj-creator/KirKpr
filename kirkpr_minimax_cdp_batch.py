# -*- coding: utf-8 -*-
"""Serija PR prek CDP na že odprtem Chromu (prijavljen Minimax) — konto iz listine."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = (9222, 9223, 9333)
MINIMAX_PREJET_LIST = (
    "https://moj.minimax.si/SI/VA/WebUI/PrejetRacun/PrejetRacunBeta.aspx"
)
MINIMAX_ZACETEK = "https://moj.minimax.si/SI/VA/WebUI/Zacetek/Zacetek.aspx?login=1"


def _python_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_pr_browser_path() -> None:
    root = str(_python_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def debug_port_available(host: str = DEFAULT_HOST, port: int = 9222, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def find_open_debug_port(host: str = DEFAULT_HOST) -> Optional[tuple[str, int]]:
    for port in DEFAULT_PORTS:
        if debug_port_available(host, port):
            return host, int(port)
    return None


def find_chrome_executable() -> Optional[Path]:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def kirkpr_chrome_profile_dir() -> Path:
    base = (
        Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))
        / "MinimaxKirKpr"
        / "ChromeCdpProfile"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def launch_chrome_cdp_minimax(
    url: str = MINIMAX_PREJET_LIST,
    *,
    port: int = 9222,
    wait_sec: float = 20.0,
) -> tuple[bool, str]:
    """Odpre ločen Chrome profil z CDP — enkratna prijava, potem serija na isti seji."""
    chrome = find_chrome_executable()
    if chrome is None:
        return False, "Chrome.exe ni najden."
    if debug_port_available(DEFAULT_HOST, port):
        return True, f"CDP že teče na :{port}"
    profile = kirkpr_chrome_profile_dir()
    args = [
        str(chrome),
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--remote-debugging-port={int(port)}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        url or MINIMAX_ZACETEK,
    ]
    try:
        subprocess.Popen(args, close_fds=True)
    except Exception as exc:
        return False, f"Zagon Chrome ni uspel: {exc}"
    deadline = time.time() + max(wait_sec, 5.0)
    while time.time() < deadline:
        if debug_port_available(DEFAULT_HOST, port):
            return True, f"Chrome CDP odprt (:{port}), profil {profile.name}"
        time.sleep(0.35)
    return False, f"Chrome zagnan, a CDP :{port} ni odgovoril v {wait_sec:.0f}s."


def _cdp_json(host: str, port: int, path: str) -> Any:
    with urlrequest.urlopen(f"http://{host}:{int(port)}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def cdp_find_minimax_tab_ws(host: str, port: int) -> Optional[str]:
    try:
        targets = _cdp_json(host, port, "/json/list")
    except (urlerror.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(targets, list):
        return None
    scored: list[tuple[int, dict]] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        u = str(t.get("url") or "").lower()
        if "moj.minimax.si" not in u:
            continue
        score = 0
        if "prejetracun" in u:
            score += 40
        if "zacetek" in u:
            score += 10
        if t.get("type") == "page":
            score += 1
        scored.append((score, t))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return str(scored[0][1].get("webSocketDebuggerUrl") or "").strip() or None


def detect_open_minimax_firm(
    host: str = DEFAULT_HOST,
    port: int | None = None,
) -> dict[str, Any]:
    """Zazna firmo v že odprtem Minimax zavihku (CDP)."""
    found = (host, port) if port else find_open_debug_port(host)
    if not found:
        return {
            "ok": False,
            "message": (
                "Chrome CDP ni odprt (:9222). "
                "Trenutni brskalnik (brez debug porta) ni dosegljiv za avtomatiko."
            ),
            "org_name": "",
            "url": "",
            "port": 0,
        }
    h, p = found[0], int(found[1])
    ws = cdp_find_minimax_tab_ws(h, p)
    if not ws:
        return {
            "ok": False,
            "message": f"CDP :{p} teče, a ni Minimax zavihka. Odpri Prejeti računi.",
            "org_name": "",
            "url": "",
            "port": p,
        }
    _ensure_pr_browser_path()
    try:
        from kirkpr_minimax_pw.minimax_cdp import CdpSession, _js_active_org_name
    except Exception as exc:
        return {"ok": False, "message": str(exc), "org_name": "", "url": "", "port": p}

    try:
        with CdpSession(ws) as cdp:
            cdp.call("Page.enable")
            href = str(cdp.evaluate("location.href") or "")
            name = str(cdp.evaluate(_js_active_org_name()) or "").strip()
            if not name:
                name = str(
                    cdp.evaluate(
                        "(() => { const t = String(document.body && document.body.innerText || '');"
                        " const m = t.match(/KLUG[^\\n]{0,40}/i); return m ? m[0].trim() : ''; })()"
                    )
                    or ""
                ).strip()
        return {
            "ok": True,
            "message": f"Zaznana firma: {name or '?'} (CDP :{p})",
            "org_name": name,
            "url": href,
            "port": p,
            "host": h,
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc), "org_name": "", "url": "", "port": p}


def firm_matches(detected_name: str, expected_name: str, expected_org_id: str = "") -> bool:
    det = "".join(ch for ch in str(detected_name or "").casefold() if ch.isalnum())
    exp = "".join(ch for ch in str(expected_name or "").casefold() if ch.isalnum())
    if det and exp and (det in exp or exp in det or det[:6] == exp[:6]):
        return True
    oid = str(expected_org_id or "").strip()
    return bool(oid and oid in str(detected_name or ""))


def _plain(value: Any) -> str:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text or text in {".", "-", "-."}:
        return ""
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return ""


def confirm_pr_drafts_batch_cdp(
    items: list[dict[str, Any]],
    *,
    auto_confirm: bool = True,
    host: str = DEFAULT_HOST,
    port: int | None = None,
    progress: Callable[[str], None] | None = None,
    expected_org_name: str = "",
    expected_org_id: str = "",
) -> list[dict[str, Any]]:
    """Serija na že odprtem Chromu (CDP). Konto/osnove iz vsake listine."""
    _ensure_pr_browser_path()
    from minimax_pr_browser import ReceivedInvoiceJob, confirm_received_invoice, debug_port_available

    found = (host, port) if port else find_open_debug_port(host)
    if not found or not debug_port_available(found[0], int(found[1])):
        return [
            {
                "ok": False,
                "confirmed": False,
                "message": "CDP ni na voljo — najprej odpri Minimax v Chrome z :9222.",
                "ref": str(it.get("document_reference") or ""),
                "method": "cdp",
            }
            for it in items
        ]
    h, p = found[0], int(found[1])

    det = detect_open_minimax_firm(h, p)
    if det.get("ok") and expected_org_name and progress:
        if firm_matches(str(det.get("org_name") or ""), expected_org_name, expected_org_id):
            progress(f"CDP: že v {det.get('org_name')} — odpiram osnutke…")
        else:
            progress(
                f"CDP firma »{det.get('org_name')}« ≠ »{expected_org_name}« — poskusim preklop…"
            )

    out: list[dict[str, Any]] = []
    total = len(items)
    for idx, it in enumerate(items, 1):
        ref = str(it.get("document_reference") or "")
        acct = str(it.get("expense_account") or "").strip()
        if progress:
            progress(f"[CDP {idx}/{total}] {ref} konto {acct}…")
        job = ReceivedInvoiceJob(
            org_id=str(it.get("org_id") or "").strip(),
            org_name=str(it.get("org_name") or expected_org_name or "").strip(),
            received_invoice_id=str(it.get("received_invoice_id") or "").strip(),
            document_reference=ref,
            expense_account=acct or "4190",
            confirm=bool(auto_confirm),
            vat_base_22=_plain(it.get("base_22")),
            vat_base_95=_plain(it.get("base_95")),
            vat_base_5=_plain(it.get("base_5")),
            logout=False,
        )
        res = confirm_received_invoice(job, host=h, port=p, reuse_tab=True)
        msg = str(getattr(res, "message", "") or "")
        ok = bool(getattr(res, "ok", False))
        confirmed = ok and (
            "potrdi" in msg.casefold()
            or "potrjen" in msg.casefold()
            or (auto_confirm and ok)
        )
        out.append(
            {
                "ok": ok,
                "confirmed": confirmed,
                "need_login": "prijav" in msg.casefold(),
                "message": msg,
                "ref": ref,
                "received_invoice_id": job.received_invoice_id,
                "expense_account": acct,
                "ref_key": it.get("ref_key"),
                "method": "cdp",
            }
        )
        if idx < total:
            time.sleep(0.8)
    return out
