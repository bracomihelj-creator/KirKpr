"""Chrome DevTools Protocol — iskanje osnutka PR v Minimaxu (stdlib)."""
from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
from typing import Optional
from urllib import error as urlerror
from urllib import parse, request as urlrequest


def cdp_new_tab_ws_url(host: str, port: int, url: str) -> Optional[str]:
    encoded = parse.quote(url, safe="")
    endpoint = f"http://{host}:{int(port)}/json/new?{encoded}"
    for method in ("PUT", "GET"):
        try:
            req = urlrequest.Request(endpoint, method=method)
            with urlrequest.urlopen(req, timeout=15) as resp:
                if resp.status not in (200, 201):
                    continue
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                ws = str(data.get("webSocketDebuggerUrl") or "").strip()
                if ws:
                    return ws
        except (urlerror.URLError, OSError, ValueError, json.JSONDecodeError):
            continue
    return None


class CdpSession:
    """Minimalen sync WebSocket klient za CDP (brez odvisnosti)."""

    def __init__(self, ws_url: str, *, timeout: float = 20.0) -> None:
        self._ws_url = ws_url
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._msg_id = 0

    def __enter__(self) -> "CdpSession":
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def connect(self) -> None:
        parsed = parse.urlparse(self._ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        sock = socket.create_connection((host, port), timeout=self._timeout)
        if parsed.scheme == "wss":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                sock.close()
                raise RuntimeError("WebSocket handshake brez odgovora")
            resp += chunk
        status_line = resp.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            sock.close()
            raise RuntimeError("WebSocket upgrade ni uspel")
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _send_text(self, text: str) -> None:
        assert self._sock is not None
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(128 | length)
        elif length < 65536:
            header.append(128 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(128 | 127)
            header.extend(struct.pack(">Q", length))
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + mask + masked)

    def _recv_text(self) -> str:
        assert self._sock is not None
        hdr = self._sock.recv(2)
        if len(hdr) < 2:
            raise RuntimeError("WebSocket zaprt")
        opcode = hdr[0] & 0x0F
        masked = hdr[1] & 0x80
        length = hdr[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._sock.recv(8))[0]
        if masked:
            mask = self._sock.recv(4)
        data = self._sock.recv(length) if length else b""
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 8:
            raise RuntimeError("WebSocket zaprt")
        if opcode == 9:  # ping
            return self._recv_text()
        return data.decode("utf-8", errors="replace")

    def call(self, method: str, params: Optional[dict] = None, *, timeout: float = 12.0) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        msg: dict = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        self._send_text(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._recv_text()
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if resp.get("id") == mid:
                return resp
        return {}

    def evaluate(self, expression: str, *, timeout: float = 12.0) -> str:
        resp = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=timeout,
        )
        result = resp.get("result", {}).get("result", {})
        return str(result.get("value") if result.get("value") is not None else "")


def _js_fill_search(reference: str, invoice_id: str) -> str:
    ref = json.dumps(reference or "")
    rid = json.dumps(invoice_id or "")
    return f"""
(() => {{
  const ref = {ref};
  const rid = {rid};
  const inputs = Array.from(document.querySelectorAll('input'));
  const pick = () => inputs.find(i => {{
    if (i.disabled || !i.offsetParent) return false;
    const ph = (i.placeholder || '').toLowerCase();
    const al = (i.getAttribute('aria-label') || '').toLowerCase();
    return ph.includes('iš') || ph.includes('isk') || ph.includes('search') ||
           al.includes('iš') || al.includes('isk') || i.type === 'search';
  }}) || inputs.find(i => i.type === 'text' && !i.disabled && i.offsetParent);
  const search = pick();
  if (!search) return 'no_input';
  const val = ref || rid;
  if (!val) return 'no_ref';
  search.focus();
  search.value = val;
  search.dispatchEvent(new Event('input', {{ bubbles: true }}));
  search.dispatchEvent(new Event('change', {{ bubbles: true }}));
  search.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: 'Enter' }}));
  search.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
  return 'filled';
}})();
"""


def _js_open_matching_row(reference: str, invoice_id: str) -> str:
    ref = json.dumps(reference or "")
    rid = json.dumps(invoice_id or "")
    return f"""
(() => {{
  const ref = {ref};
  const rid = {rid};
  const hay = [ref, rid].filter(Boolean);
  if (!hay.length) return 'no_ref';
  const match = (txt) => hay.some(h => String(txt || '').includes(h));
  const rows = Array.from(document.querySelectorAll(
    'tr, [role="row"], mat-row, .mat-row, .grid-row, .table-row'
  ));
  for (const row of rows) {{
    if (match(row.textContent)) {{
      row.click();
      const link = row.querySelector('a, button, [role="button"]');
      if (link) link.click();
      return 'row';
    }}
  }}
  const cells = Array.from(document.querySelectorAll('td, [role="gridcell"], .mat-cell, span, div'));
  for (const cell of cells) {{
    if (match(cell.textContent)) {{
      cell.click();
      return 'cell';
    }}
  }}
  return 'not_found';
}})();
"""


def _js_probe_row_status(reference: str, invoice_id: str) -> str:
    """Preberi status PR v seznamu (P/potrjen ali O/osnutek) brez odpiranja vrstice."""
    ref = json.dumps(reference or "")
    rid = json.dumps(invoice_id or "")
    return f"""
(() => {{
  const ref = {ref};
  const rid = {rid};
  const hay = [ref, rid].filter(Boolean);
  if (!hay.length) return 'no_ref';
  const match = (txt) => hay.some(h => String(txt || '').includes(h));
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const classify = (txt) => {{
    const t = norm(txt);
    if (!t) return '';
    if (/\\bpotrjen\\b/.test(t) && !/\\bosnutek\\b/.test(t)) return 'potrjen';
    if (/\\bosnutek\\b/.test(t)) return 'osnutek';
    if (/\\bstatus\\s*[:=]?\\s*p\\b/.test(t)) return 'potrjen';
    if (/\\bstatus\\s*[:=]?\\s*o\\b/.test(t)) return 'osnutek';
    return '';
  }};
  const rows = Array.from(document.querySelectorAll(
    'tr, [role="row"], mat-row, .mat-row, .grid-row, .table-row'
  ));
  for (const row of rows) {{
    if (!match(row.textContent)) continue;
    const rowText = norm(row.textContent);
    const hit = classify(rowText);
    if (hit) return hit + ':row';
    if (/\\bosnutek\\b/.test(rowText)) return 'osnutek:row';
    if (/\\bpotrjen\\b/.test(rowText) || /\\buredi plačilo\\b/.test(rowText)) return 'potrjen:row';
    if (/\\bstatus\\s*[:=]?\\s*p\\b/.test(rowText)) return 'potrjen:row';
    // V seznamu poknjiženih — vrstica najdena, ni osnutka
    if (!/\\bosnutek\\b/.test(rowText)) return 'potrjen:row';
    return 'found:unknown';
  }}
  const body = norm(document.body.innerText || '');
  if (hay.some(h => body.includes(norm(h)))) {{
    const hit = classify(body);
    if (hit) return hit + ':body';
    return 'found:unknown';
  }}
  return 'not_found';
}})();
"""


def _js_is_pr_already_confirmed() -> str:
    """Na strani prejetega računa: confirmed | draft | not_view | unknown."""
    return """
(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const url = (location.href || '').toLowerCase();
  if (!url.includes('prejetracun')) return 'not_view';
  const body = norm(document.body.innerText || '');
  if (/potrjen\\s+prejetega\\s+ra/.test(body)) return 'confirmed';
  if (/osnutek\\s+prejetega\\s+ra/.test(body)) return 'draft';
  const nodes = Array.from(document.querySelectorAll('a, button, input, span, div'));
  let hasUredi = false;
  let hasPotrdi = false;
  for (const n of nodes) {
    const t = String(n.textContent || n.value || n.title || '').trim();
    if (/^uredi$/i.test(t) && n.offsetParent) hasUredi = true;
    if (/^potrdi$/i.test(t) && n.offsetParent) hasPotrdi = true;
  }
  if (hasPotrdi) return 'draft';
  if (/\\bosnutek\\b/.test(body)) return 'draft';
  if (/\\bstatus\\s*[:=]?\\s*o\\b/.test(body)) return 'draft';
  // Ročno poknjižen — ni Potrdi, pogosto le Uredi plačilo
  return 'confirmed';
})();
"""


def _js_click_uredi() -> str:
    return """
(() => {
  const clickEl = (n) => {
    try {
      if (typeof WebForm_SimulateClick === 'function') {
        WebForm_SimulateClick(n, { preventDefault() {}, stopPropagation() {} });
        return true;
      }
    } catch (e) {}
    try { n.click(); return true; } catch (e2) {}
    return false;
  };
  const nodes = Array.from(document.querySelectorAll('a, button, input, span, div'));
  for (const n of nodes) {
    const t = String(n.textContent || n.value || n.title || '').trim();
    if (/^uredi$/i.test(t) && clickEl(n)) return 'uredi';
  }
  return 'no_uredi';
})();
"""


def _js_click_by_label(pattern: str) -> str:
    pat = json.dumps(pattern)
    return f"""
(() => {{
  const re = new RegExp({pat}, 'i');
  const clickEl = (n) => {{
    try {{
      if (typeof WebForm_SimulateClick === 'function') {{
        WebForm_SimulateClick(n, {{ preventDefault() {{}}, stopPropagation() {{}} }});
        return true;
      }}
    }} catch (e) {{}}
    try {{ n.click(); return true; }} catch (e2) {{}}
    return false;
  }};
  for (const n of document.querySelectorAll('a, button, input, span, div, td')) {{
    const t = String(n.textContent || n.value || n.title || n.alt || '').trim();
    if (re.test(t) && clickEl(n)) return 'clicked';
  }}
  return 'not_found';
}})();
"""


def _js_expense_state(expense_account: str) -> str:
    acct = json.dumps(expense_account or "4190")
    return f"""
(() => {{
  const acct = {acct};
  const digits = acct.replace(/\\D/g, '');
  const re = new RegExp('\\\\b' + digits + '\\\\b');
  const body = String(document.body && document.body.innerText || '');
  // Konto je lahko v BESEDILU (celica mreže) ALI v VREDNOSTI polja (input/select).
  let inField = false;
  const flds = Array.from(document.querySelectorAll('input, select, textarea, [contenteditable]'));
  for (const el of flds) {{
    const v = String(el.value != null ? el.value : (el.textContent || ''));
    if (re.test(v)) {{ inField = true; break; }}
  }}
  const hasAcct = re.test(body) || inField;
  const balanced = /razlika[^\\d]*0[,.]00\\s*EUR/i.test(body);
  if (hasAcct && balanced) return 'ready_confirm';
  if (hasAcct) return 'has_account';
  return 'needs_expense';
}})();
"""


def _js_fill_vat_bases(base22: str = "", base95: str = "", base5: str = "") -> str:
    """Vnos osnov DDV (Beta WebUI) — isti JS kot minimax_pr_browser / Fakturiranje CDP."""
    targets: list[dict] = []
    if str(base22 or "").strip():
        targets.append(
            {
                "key": "osnova22",
                "value": str(base22).strip(),
                "patterns": [
                    r"osnova[^\d%]{0,28}22(?:\s*[,.]?\s*0*)?\s*%",
                    r"22(?:\s*[,.]\s*0+)?\s*%[^\%]{0,40}osnova",
                ],
            }
        )
    if str(base95 or "").strip():
        targets.append(
            {
                "key": "osnova95",
                "value": str(base95).strip(),
                "patterns": [
                    r"osnova[^\d%]{0,28}9\s*[,.]\s*5\s*%",
                    r"9\s*[,.]\s*5\s*%[^\%]{0,40}osnova",
                ],
            }
        )
    if str(base5 or "").strip():
        targets.append(
            {
                "key": "osnova5",
                "value": str(base5).strip(),
                "patterns": [r"osnova[^\d%]{0,28}5(?:\s*[,.]?\s*0*)?\s*%"],
            }
        )
    if not targets:
        return "(() => 'no_targets')();"
    items_json = json.dumps(
        [{"key": t["key"], "value": t["value"], "patterns": t["patterns"]} for t in targets]
    )
    return f"""
(() => {{
  const items = {items_json};
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const visible = (element) => Boolean(element && element.getClientRects().length);
  const nativeInputSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  const setMoney = (field, amount) => {{
    field.focus?.();
    if (field instanceof HTMLInputElement && nativeInputSetter) nativeInputSetter.call(field, amount);
    else if ('value' in field) field.value = amount;
    else return false;
    field.dispatchEvent(new Event('input', {{ bubbles: true }}));
    field.dispatchEvent(new Event('change', {{ bubbles: true }}));
    return true;
  }};
  const matches = (text, patterns) => patterns.some((p) => {{ try {{ return new RegExp(p, 'i').test(text); }} catch (e) {{ return false; }} }});
  let filled = 0;
  for (const item of items) {{
    const fields = [...document.querySelectorAll('input:not([type=hidden]),textarea')];
    for (const field of fields) {{
      if (!visible(field) || field.disabled || field.readOnly) continue;
      const metadata = norm([field.id, field.name, field.placeholder, field.getAttribute('aria-label'), field.closest?.('td,th,div,label')?.innerText].join(' '));
      if (/(konto|šifra kont|sifra kont)/i.test(metadata)) continue;
      if (matches(metadata, item.patterns) && setMoney(field, item.value)) {{ filled += 1; break; }}
    }}
  }}
  return filled ? ('filled:' + filled) : 'none';
}})();
"""


def _js_fill_konto(expense_account: str) -> str:
    """Vpiše konto SAMO v polje, ki je jasno 'konto' — nikoli v naključno prazno polje."""
    acct = json.dumps(expense_account or "4190")
    return f"""
(() => {{
  const acct = {acct};
  const setVal = (inp) => {{
    inp.focus();
    inp.value = acct;
    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
    inp.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: 'Enter' }}));
    inp.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
  }};
  const inputs = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
  for (const inp of inputs) {{
    if (inp.disabled || !inp.offsetParent) continue;
    if (String(inp.value || '').trim()) continue;
    const id = String(inp.id || '').toLowerCase();
    const name = String(inp.name || '').toLowerCase();
    const ph = String(inp.placeholder || '').toLowerCase();
    const near = String(inp.parentElement && inp.parentElement.textContent || '').toLowerCase();
    if (id.includes('konto') || name.includes('konto') || ph.includes('konto') || near.includes('konto')) {{
      setVal(inp);
      return 'filled_konto';
    }}
  }}
  return 'no_field';
}})();
"""


def _js_fill_konto_grid(expense_account: str) -> str:
    """Beta / mreža: poišči stolpec Konto in vpiši v zadnjo vrstico odhodka."""
    acct = json.dumps(expense_account or "4190")
    return f"""
(() => {{
  const acct = {acct};
  const setVal = (el) => {{
    el.focus();
    if ('value' in el) {{
      el.value = acct;
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }} else if (el.isContentEditable) {{
      el.textContent = acct;
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }}
    el.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: 'Enter' }}));
    el.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
  }};
  const kontoHeader = /konto|šifra\\s*kont/i;
  const tryCell = (cell) => {{
    if (!cell || !cell.offsetParent) return '';
    const inp = cell.querySelector('input:not([type=hidden]), select, textarea');
    if (inp && !inp.disabled) {{
      if (!String(inp.value || '').trim() || String(inp.value).length <= 4) {{
        setVal(inp);
        return 'filled_grid';
      }}
    }}
    try {{ cell.click(); }} catch (e) {{}}
    const active = document.activeElement;
    if (active && active !== document.body) {{
      const tag = String(active.tagName || '').toUpperCase();
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active.isContentEditable) {{
        setVal(active);
        return 'filled_grid_active';
      }}
    }}
    return '';
  }};
  const tables = Array.from(document.querySelectorAll('table'));
  for (const table of tables) {{
    const headerRow = table.querySelector('thead tr') || table.querySelector('tr');
    if (!headerRow) continue;
    const headers = Array.from(headerRow.querySelectorAll('th, td'));
    let kontoIdx = -1;
    headers.forEach((h, i) => {{
      if (kontoHeader.test(String(h.textContent || ''))) kontoIdx = i;
    }});
    if (kontoIdx < 0) continue;
    const rows = Array.from(table.querySelectorAll('tbody tr, tr')).filter(
      (r) => r !== headerRow && r.cells && r.cells.length > kontoIdx
    );
    for (let ri = rows.length - 1; ri >= 0; ri--) {{
      const hit = tryCell(rows[ri].cells[kontoIdx]);
      if (hit) return hit;
    }}
  }}
  // DevExpress / role=grid — poišči celico z naslovom stolpca Konto
  for (const grid of document.querySelectorAll('[role="grid"], .dx-datagrid, .grid')) {{
    const headers = Array.from(grid.querySelectorAll('[role="columnheader"], th, .dx-header-row td'));
    let kontoIdx = -1;
    headers.forEach((h, i) => {{
      if (kontoHeader.test(String(h.textContent || ''))) kontoIdx = i;
    }});
    if (kontoIdx < 0) continue;
    const rows = Array.from(grid.querySelectorAll('[role="row"], tr')).slice(1);
    for (let ri = rows.length - 1; ri >= 0; ri--) {{
      const cells = rows[ri].querySelectorAll('[role="gridcell"], td');
      if (cells.length <= kontoIdx) continue;
      const hit = tryCell(cells[kontoIdx]);
      if (hit) return hit;
    }}
  }}
  return 'no_field';
}})();
"""


def _cdp_expense_workflow(
    cdp: CdpSession,
    *,
    expense_account: str,
    auto_confirm: bool,
    edit_wait_sec: float = 3.0,
    vat_base_22: str = "",
    vat_base_95: str = "",
    vat_base_5: str = "",
) -> str:
    """Po Uredi: Nov odhodek (samo enkrat) → konto → osnove → (opcijsko) Potrdi."""
    acct = str(expense_account or "4190").strip() or "4190"
    time.sleep(max(edit_wait_sec, 1.0))
    added_row = False
    konto_filled = False
    vat_filled = False

    for _ in range(10):
        if not vat_filled and (vat_base_22 or vat_base_95 or vat_base_5):
            vat_res = str(
                cdp.evaluate(_js_fill_vat_bases(vat_base_22, vat_base_95, vat_base_5)) or ""
            )
            if vat_res.startswith("filled:"):
                vat_filled = True
                time.sleep(0.4)

        state = cdp.evaluate(_js_expense_state(acct))
        if state == "ready_confirm":
            if auto_confirm and cdp.evaluate(_js_click_by_label("^potrdi$")) == "clicked":
                return f"Odhodek {acct}, razlika 0 — Potrdi (avtomatsko)."
            return f"Odhodek {acct}, razlika 0 — ročno klikni Potrdi."
        if state == "has_account":
            if auto_confirm and cdp.evaluate(_js_click_by_label("^potrdi$")) == "clicked":
                return f"Odhodek {acct} vnesen — Potrdi (avtomatsko)."
            return f"Odhodek {acct} vnesen — ročno preveri zneske in Potrdi."

        # Vrstico odhodka dodamo SAMO enkrat (sicer nastane kup praznih vrstic).
        if not added_row:
            if cdp.evaluate(_js_click_by_label("nov odhodek")) == "clicked":
                added_row = True
                time.sleep(2.0)
        if cdp.evaluate(_js_fill_konto(acct)) == "filled_konto":
            konto_filled = True
        elif cdp.evaluate(_js_fill_konto_grid(acct)).startswith("filled"):
            konto_filled = True
        time.sleep(1.0)

    if konto_filled:
        return f"Odhodek {acct} vpisan, a ni samodejno potrjen — ročno preveri konto in Potrdi."
    if added_row:
        return f"Vrstica odhodka dodana — ročno vpiši konto {acct} in Potrdi."
    return f"Ročno: Uredi → + Nov odhodek → konto {acct} → Potrdi."


def _js_has_system_error() -> str:
    return """
(() => {
  const t = String(document.body && document.body.innerText || '');
  return /sistemska napaka/i.test(t) ? 'error' : 'ok';
})();
"""


def _js_active_org_name() -> str:
    """Trenutno aktivna organizacija (za preverjanje uspešnega preklopa)."""
    return """
(() => {
  const sel = ['.organisation-name', '.organizacija', '#OrganisationName',
               '[data-organisation-name]', 'header .org', '.navbar .org'];
  for (const s of sel) {
    const el = document.querySelector(s);
    if (el && el.textContent) return String(el.textContent).trim();
  }
  return '';
})();
"""


def _org_filter_term(name: str) -> str:
    """Distinktivni del imena za filter (brez pravne oblike)."""
    base = str(name or "").strip()
    low = base.lower()
    for token in (" d.o.o.", " d.o.o", " d.d.", " s.p.", " k.d.", " d.n.o.", " s.r.l."):
        idx = low.find(token)
        if idx > 0:
            return base[:idx].strip()
    return base


def _js_fill_org_filter(term: str) -> str:
    """Vpiši ime v iskalno/filter polje na strani »Moje organizacije«."""
    val = json.dumps(str(term or "").strip())
    return f"""
(() => {{
  const val = {val};
  if (!val) return 'no_term';
  const inputs = Array.from(document.querySelectorAll('input'));
  const box = inputs.find(i => {{
    if (i.disabled || !i.offsetParent) return false;
    const meta = ((i.placeholder || '') + ' ' + (i.getAttribute('aria-label') || '') + ' ' + (i.id || '') + ' ' + (i.name || '')).toLowerCase();
    return i.type === 'search' || i.type === 'text' || /filter|isk|search|organiz/.test(meta);
  }});
  if (!box) return 'no_input';
  box.focus();
  box.value = val;
  box.dispatchEvent(new Event('input', {{ bubbles: true }}));
  box.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
  box.dispatchEvent(new Event('change', {{ bubbles: true }}));
  box.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: 'Enter' }}));
  box.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
  return 'filled';
}})();
"""


def _js_switch_organisation(org_id: str, org_name: str) -> str:
    """
    »Moje organizacije«: sproži ASP.NET postback za izbrano firmo (po Org_ID ali nazivu).
    Klikljivi element je link/celica z __doPostBack — kliknemo pravega, ne le vrstice.
    """
    oid = json.dumps(str(org_id or "").strip())
    onm = json.dumps(str(org_name or "").strip().lower())
    return f"""
(() => {{
  const oid = {oid};
  const norm = (s) => String(s || '')
    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
    .replace(/đ/g, 'd').replace(/Đ/g, 'd')
    .replace(/\\s+/g, ' ').trim().toLowerCase();
  const onm = norm({onm});

  const clickable = (el) => {{
    if (!el) return null;
    if (el.tagName === 'A') return el;
    const oc = (el.getAttribute && (el.getAttribute('onclick') || '')) || '';
    const href = (el.getAttribute && (el.getAttribute('href') || '')) || '';
    if (/__doPostBack|location|Zacetek/i.test(oc) || /__doPostBack|Zacetek/i.test(href)) return el;
    const a = el.querySelector && (el.querySelector('a[onclick], a[href]') || el.querySelector('a'));
    if (a) return a;
    const pb = el.querySelector && el.querySelector('[onclick*="__doPostBack"], [onclick*="Zacetek"]');
    if (pb) return pb;
    return null;
  }};
  const fromRow = (el) => {{
    let p = el;
    for (let i = 0; i < 5 && p; i++) {{
      const c = clickable(p);
      if (c) return c;
      p = p.parentElement;
    }}
    return null;
  }};
  const fire = (el) => {{
    try {{ el.click(); return true; }} catch (e) {{}}
    try {{
      el.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
      return true;
    }} catch (e) {{}}
    return false;
  }};

  if (oid) {{
    // Najbolj zanesljivo: vrstica firme ima data-organizacijaid ali skrit input z Org_ID.
    const orgLink = (root) => root && (
      root.querySelector('a.organizacija-naziv') ||
      root.querySelector("a[id$='LinkButton1']") ||
      root.querySelector("a[href*='LinkButton1']") ||
      root.querySelector('a')
    );
    const byData = document.querySelector('[data-organizacijaid="' + oid + '"]');
    if (byData) {{ const l = orgLink(byData); if (l && fire(l)) return 'id'; }}
    const hid = document.querySelector('input[value="' + oid + '"]');
    if (hid) {{
      const tr = (hid.closest && hid.closest('tr')) || hid.parentElement;
      const l = orgLink(tr);
      if (l && fire(l)) return 'id';
    }}
    const re = new RegExp('(^|[^0-9])' + oid + '([^0-9]|$)');
    const cand = Array.from(document.querySelectorAll('a, [onclick], [href], [data-organisationid], [data-id], tr, li, td'));
    const byId = cand.find(el => {{
      const h = (el.getAttribute && (el.getAttribute('href') || '')) || '';
      const oc = (el.getAttribute && (el.getAttribute('onclick') || '')) || '';
      const d1 = (el.getAttribute && (el.getAttribute('data-organizacijaid') || '')) || '';
      const d2 = (el.getAttribute && (el.getAttribute('data-organisationid') || '')) || '';
      const d3 = (el.getAttribute && (el.getAttribute('data-id') || '')) || '';
      return d1 === oid || d2 === oid || d3 === oid || re.test(h) || re.test(oc);
    }});
    if (byId) {{ const c = clickable(byId) || fromRow(byId); if (c && fire(c)) return 'id'; }}
  }}

  if (onm && onm.length > 2) {{
    const normTitle = (a) => norm(a.getAttribute('title') || a.textContent || '');
    const headerLinks = Array.from(document.querySelectorAll('#list-of-organizations a.tab-check-link, #list-of-organizations a'));
    const hdrExact = headerLinks.find(a => normTitle(a) === onm);
    if (hdrExact && fire(hdrExact)) return 'name';
    const hdrPart = headerLinks.find(a => normTitle(a).includes(onm));
    if (hdrPart && fire(hdrPart)) return 'name_part';
    const anchors = Array.from(document.querySelectorAll('a'));
    const aExact = anchors.find(a => norm(a.textContent) === onm);
    if (aExact && fire(aExact)) return 'name';
    const rows = Array.from(document.querySelectorAll('tr, li, td, div, span'));
    const rowExact = rows.find(el => norm(el.textContent) === onm) ||
                     rows.find(el => {{ const t = norm(el.textContent); return t.includes(onm) && t.length < onm.length + 40; }});
    if (rowExact) {{ const c = fromRow(rowExact); if (c && fire(c)) return 'name_row'; }}
    const aPart = anchors.find(a => norm(a.textContent).includes(onm));
    if (aPart && fire(aPart)) return 'name_part';
  }}
  return 'not_found';
}})();
"""


def _js_find_org_switch_url(org_id: str, org_name: str) -> str:
    """Absolutni link za preklop firme (pravi notranji href Minimaxa), brez klika."""
    oid = json.dumps(str(org_id or "").strip())
    onm = json.dumps(str(org_name or "").strip().lower())
    return f"""
(() => {{
  const oid = {oid};
  const norm = (s) => String(s || '')
    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
    .replace(/đ/g, 'd').replace(/Đ/g, 'd')
    .replace(/\\s+/g, ' ').trim().toLowerCase();
  const onm = norm({onm});
  const abs = (h) => {{ try {{ return new URL(h, location.href).href; }} catch (e) {{ return ''; }} }};
  const anchors = Array.from(document.querySelectorAll('a[href]'));
  if (oid) {{
    const re = new RegExp('(^|[^0-9])' + oid + '([^0-9]|$)');
    const a = anchors.find(x => re.test(x.getAttribute('href') || ''));
    if (a) return abs(a.getAttribute('href'));
  }}
  if (onm && onm.length > 2) {{
    const els = Array.from(document.querySelectorAll('tr, li, div, td, span'));
    const match = els.find(e => norm(e.textContent) === onm) ||
                  els.find(e => {{ const t = norm(e.textContent); return t.includes(onm) && t.length < onm.length + 40; }});
    if (match) {{
      let a = match.querySelector && match.querySelector('a[href]');
      if (!a) {{ let p = match; for (let i = 0; i < 4 && p; i++) {{ a = p.querySelector && p.querySelector('a[href]'); if (a) break; p = p.parentElement; }} }}
      if (a) return abs(a.getAttribute('href'));
    }}
  }}
  return '';
}})();
"""


def _cdp_switch_org(
    cdp: "CdpSession",
    *,
    org_chooser_url: str,
    org_id: str,
    org_name: str = "",
    wait_sec: float = 3.0,
) -> bool:
    """
    Preklop firme prek »Moje organizacije«: sproži ASP.NET postback (klik na firmo).
    Aktivna firma je v strežniški seji (ni piškotka/URL parametra), zato je klik edina pot.
    """
    cdp.call("Page.navigate", {"url": org_chooser_url})

    # Seznam je lahko paginiran (100+ firm) — najprej filtriraj po imenu, da se firma prikaže.
    term = _org_filter_term(org_name)
    if term:
        deadline = time.time() + max(wait_sec, 2.0)
        while time.time() < deadline:
            time.sleep(0.6)
            if cdp.evaluate(_js_fill_org_filter(term)) == "filled":
                break
        time.sleep(1.2)

    ok_states = ("id", "name", "name_row", "name_part")
    res = ""
    deadline = time.time() + max(wait_sec, 2.5)
    while time.time() < deadline:
        time.sleep(0.6)
        res = cdp.evaluate(_js_switch_organisation(org_id, org_name))
        if res in ok_states:
            break

    if res not in ok_states:
        switch_url = str(cdp.evaluate(_js_find_org_switch_url(org_id, org_name)) or "").strip()
        if switch_url.startswith("http"):
            cdp.call("Page.navigate", {"url": switch_url})
            time.sleep(max(wait_sec, 2.0))
            return cdp.evaluate(_js_has_system_error()) != "error"
        return False

    time.sleep(max(wait_sec, 2.5))
    return cdp.evaluate(_js_has_system_error()) != "error"


def _js_extract_spreadsheet_base_url() -> str:
    """SpreadsheetBaseUrl iz grafa Prejeti računi na Zacetek (isti cache kot chart JS)."""
    return """
(() => {
  try {
    if (typeof GetPrejetiRacuniStanjeChartID === 'function' &&
        typeof CliSrvPageSettingsProviderFactory !== 'undefined' &&
        CliSrvPageSettingsProviderFactory.get) {
      const cache = CliSrvPageSettingsProviderFactory
        .get(GetPrejetiRacuniStanjeChartID()).get();
      const url = cache && cache.Values && cache.Values.SpreadsheetBaseUrl;
      if (url && String(url).length > 10) return String(url);
    }
  } catch (e) {}
  const html = document.documentElement && document.documentElement.innerHTML || '';
  const m = html.match(/SpreadsheetBaseUrl['"]\\s*:\\s*['"]([^'"]+)['"]/i);
  if (m && m[1]) return m[1];
  return '';
})();
"""


def _js_navigate_prejeti_racuni_from_zacetek() -> str:
    """Navigacija na seznam PR prek SpreadsheetBaseUrl ali klika na dashboard."""
    return """
(() => {
  try {
    if (typeof GetPrejetiRacuniStanjeChartID === 'function' &&
        typeof CliSrvPageSettingsProviderFactory !== 'undefined' &&
        CliSrvPageSettingsProviderFactory.get) {
      const cache = CliSrvPageSettingsProviderFactory
        .get(GetPrejetiRacuniStanjeChartID()).get();
      const base = cache && cache.Values && cache.Values.SpreadsheetBaseUrl;
      if (base) {
        window.location.href = String(base);
        return 'spreadsheet';
      }
    }
  } catch (e) {}
  for (const a of document.querySelectorAll('a')) {
    const t = String(a.textContent || '').trim();
    if (/prejet/i.test(t) && /račun/i.test(t) && t.length < 50) {
      try { a.click(); return 'link'; } catch (e) {}
    }
  }
  return 'no';
})();
"""


def _cdp_goto_prejeti_racuni_list(
    cdp: CdpSession,
    *,
    list_url_fallback: str = "",
    wait_sec: float = 3.0,
) -> bool:
    """Po Zacetek: SpreadsheetBaseUrl (Minimax dashboard) ali fallback ListBeta URL."""
    sheet_url = str(cdp.evaluate(_js_extract_spreadsheet_base_url()) or "").strip()
    if sheet_url.startswith("http"):
        cdp.call("Page.navigate", {"url": sheet_url})
        time.sleep(max(wait_sec, 1.0))
        if cdp.evaluate(_js_has_system_error()) != "error":
            return True

    nav = cdp.evaluate(_js_navigate_prejeti_racuni_from_zacetek())
    if nav in ("spreadsheet", "link"):
        time.sleep(max(wait_sec, 1.0))
        if cdp.evaluate(_js_has_system_error()) != "error":
            return True

    fallback = str(list_url_fallback or "").strip()
    if fallback.startswith("http"):
        cdp.call("Page.navigate", {"url": fallback})
        time.sleep(max(wait_sec, 1.0))
        return cdp.evaluate(_js_has_system_error()) != "error"

    return False


def _js_open_prejeti_racuni_menu() -> str:
    return """
(() => {
  for (const a of document.querySelectorAll('a, span, div, button')) {
    const t = String(a.textContent || '').trim();
    if (/prejet/i.test(t) && /račun/i.test(t) && t.length < 40) {
      try { a.click(); return 'menu'; } catch (e) {}
    }
  }
  return 'no_menu';
})();
"""


def _cdp_search_and_open_draft(
    cdp: CdpSession,
    *,
    document_reference: str,
    received_invoice_id: str,
    list_wait_sec: float = 3.0,
) -> bool:
    ref = str(document_reference or "").strip()
    rid = str(received_invoice_id or "").strip()
    deadline = time.time() + max(list_wait_sec, 1.0)
    while time.time() < deadline:
        time.sleep(0.7)
        if cdp.evaluate(_js_fill_search(ref, rid)) == "filled":
            break
    else:
        menu = cdp.evaluate(_js_open_prejeti_racuni_menu())
        if menu == "menu":
            time.sleep(2.0)
            cdp.evaluate(_js_fill_search(ref, rid))
        else:
            return False
    time.sleep(1.0)
    return cdp.evaluate(_js_open_matching_row(ref, rid)) in ("row", "cell")


def cdp_open_received_invoice_view(
    host: str,
    port: int,
    *,
    org_chooser_url: str,
    org_id: str,
    org_name: str = "",
    view_url: str = "",
    list_url: str = "",
    document_reference: str = "",
    received_invoice_id: str = "",
    auto_edit: bool = True,
    auto_expense: bool = True,
    auto_confirm: bool = False,
    expense_account: str = "4190",
    org_wait_sec: float = 4.0,
    view_wait_sec: float = 3.0,
) -> tuple[bool, str]:
    """
    Direkten link: najprej odpre view pr_id v trenutni seji (če si že na pravi firmi —
    brez »Moje organizacije«). Šele ob »Sistemska napaka« (napačna firma) samodejno
    preklopi prek pravega notranjega linka firme in znova odpre view.
    """
    start_url = view_url or org_chooser_url
    ws_url = cdp_new_tab_ws_url(host, port, start_url)
    if not ws_url:
        return False, "CDP zavihek ni bil odprt"

    ref = str(document_reference or "").strip()
    rid = str(received_invoice_id or "").strip()

    try:
        with CdpSession(ws_url) as cdp:
            cdp.call("Page.enable")
            time.sleep(max(org_wait_sec, 2.0))

            opened = False
            switched = False
            if view_url:
                opened = cdp.evaluate(_js_has_system_error()) != "error"

            if not opened:
                switched = _cdp_switch_org(
                    cdp,
                    org_chooser_url=org_chooser_url,
                    org_id=org_id,
                    org_name=org_name,
                    wait_sec=view_wait_sec,
                )
                if not switched:
                    return False, (
                        "Preklop organizacije ni uspel — v Minimaxu Moje organizacije, "
                        "klikni firmo, nato Prejeti računi + referenca."
                    )
                if view_url:
                    cdp.call("Page.navigate", {"url": view_url})
                    time.sleep(max(view_wait_sec, 1.0))
                    opened = cdp.evaluate(_js_has_system_error()) != "error"

            if not opened and (ref or rid):
                if _cdp_goto_prejeti_racuni_list(
                    cdp,
                    list_url_fallback=list_url,
                    wait_sec=view_wait_sec,
                ):
                    opened = _cdp_search_and_open_draft(
                        cdp,
                        document_reference=ref,
                        received_invoice_id=rid,
                    )

            if not opened:
                return False, "Osnutka ni mogoče odpreti — ročno Prejeti računi + referenca."

            way = "preklop firme + direkten link" if switched else "direkten link (že prava firma)"

            if not auto_edit:
                return True, f"Osnutek PR ({way}) — ročno Uredi."

            time.sleep(0.8)
            if cdp.evaluate(_js_click_uredi()) != "uredi":
                return True, f"Osnutek odprt ({way}) — ročno klikni Uredi."

            if auto_expense:
                detail = _cdp_expense_workflow(
                    cdp,
                    expense_account=str(expense_account or "4190"),
                    auto_confirm=auto_confirm,
                )
                return True, f"{detail} [{way}]"

            return True, f"Osnutek + Uredi ({way}) — ročno dodaj odhodek."
    except Exception as exc:
        return False, str(exc)[:120]


def cdp_open_received_draft_search(
    host: str,
    port: int,
    *,
    org_chooser_url: str,
    org_id: str,
    org_name: str = "",
    list_url: str = "",
    document_reference: str = "",
    received_invoice_id: str = "",
    org_wait_sec: float = 2.6,
    list_wait_sec: float = 3.2,
) -> tuple[bool, str]:
    """
    En zavihek: Moje organizacije → klik firme → seznam Prejeti računi → iskanje po referenci/ID.
    """
    ref = str(document_reference or "").strip()
    rid = str(received_invoice_id or "").strip()
    if not ref and not rid:
        return False, "Manjka referenca"

    ws_url = cdp_new_tab_ws_url(host, port, org_chooser_url)
    if not ws_url:
        return False, "CDP zavihek ni bil odprt"

    time.sleep(max(org_wait_sec, 0.0))
    try:
        with CdpSession(ws_url) as cdp:
            cdp.call("Page.enable")
            if not _cdp_switch_org(
                cdp,
                org_chooser_url=org_chooser_url,
                org_id=org_id,
                org_name=org_name,
                wait_sec=list_wait_sec,
            ):
                return False, "Preklop organizacije ni uspel (Moje organizacije → klik firme)."

            if not _cdp_goto_prejeti_racuni_list(
                cdp,
                list_url_fallback=list_url,
                wait_sec=list_wait_sec,
            ):
                return False, "Seznam Prejeti računi ni bil odprt (SpreadsheetBaseUrl / ListBeta)."

            deadline = time.time() + max(list_wait_sec, 1.0)
            fill_result = ""
            while time.time() < deadline:
                time.sleep(0.7)
                fill_result = cdp.evaluate(_js_fill_search(ref, rid))
                if fill_result == "filled":
                    break
            if fill_result != "filled":
                return False, f"Iskalno polje ni najdeno ({fill_result or '?'})"

            time.sleep(1.0)
            open_result = cdp.evaluate(_js_open_matching_row(ref, rid))
            if open_result in ("row", "cell"):
                return True, "Preklop + iskanje + odprt osnutek."
            return True, "Preklop OK — referenca vpisana, odpri vrstico ročno."
    except Exception as exc:
        return False, str(exc)[:120]


def _js_navigate_stranke_sifrant() -> str:
    """Meni Šifrant → Stranke ali neposreden link."""
    return """
(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  for (const a of document.querySelectorAll('a, button, span, div')) {
    const t = norm(a.textContent || '');
    if (t === 'stranke' || (t.includes('strank') && t.length < 24)) {
      try { a.click(); return 'stranke'; } catch (e) {}
    }
  }
  for (const a of document.querySelectorAll('a, button')) {
    const t = norm(a.textContent || '');
    if (t.includes('šifrant') || t.includes('sifrant')) {
      try { a.click(); return 'sifrant_menu'; } catch (e) {}
    }
  }
  return 'no';
})();
"""


def _js_search_customer_tax(tax_number: str) -> str:
    tax = json.dumps(str(tax_number or "").strip())
    return f"""
(() => {{
  const tax = {tax};
  const digits = tax.replace(/\\D/g, '');
  if (!digits) return 'no_tax';
  const setVal = (inp) => {{
    inp.focus();
    inp.value = tax;
    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
    inp.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: 'Enter' }}));
    inp.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
  }};
  const inputs = Array.from(document.querySelectorAll(
    'input[type=search], input[type=text], input:not([type])'
  ));
  for (const inp of inputs) {{
    if (inp.disabled || !inp.offsetParent) continue;
    const ph = String(inp.placeholder || '').toLowerCase();
    const near = String(inp.parentElement && inp.parentElement.textContent || '').toLowerCase();
    if (ph.includes('išči') || ph.includes('isci') || ph.includes('search') ||
        near.includes('išči') || near.includes('davč') || near.includes('naziv')) {{
      setVal(inp);
      return 'filled';
    }}
  }}
  if (inputs.length) {{
    setVal(inputs[0]);
    return 'filled_first';
  }}
  return 'no_field';
}})();
"""


def _js_click_shrani_customer() -> str:
    """Klik «Shrani» na obrazcu stranke (ne «Shrani in nov»)."""
    return """
(() => {
  const clickEl = (n) => {
    try {
      if (typeof WebForm_SimulateClick === 'function') {
        WebForm_SimulateClick(n, { preventDefault() {}, stopPropagation() {} });
        return true;
      }
    } catch (e) {}
    try { n.click(); return true; } catch (e2) {}
    return false;
  };
  for (const n of document.querySelectorAll('a, button, input[type=button], input[type=submit], span')) {
    const t = String(n.textContent || n.value || n.title || '').trim();
    if (/^shrani$/i.test(t) && clickEl(n)) return 'shrani';
  }
  return 'no_shrani';
})();
"""


def _js_open_customer_by_tax(tax_number: str, name_hint: str = "") -> str:
    tax = json.dumps(str(tax_number or "").strip())
    hint = json.dumps(str(name_hint or "").strip().lower())
    return f"""
(() => {{
  const tax = {tax};
  const hint = {hint};
  const digits = tax.replace(/\\D/g, '');
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const match = (txt) => {{
    const t = norm(txt);
    if (digits && t.replace(/\\D/g, '').includes(digits)) return true;
    if (hint && t.includes(hint)) return true;
    if (hint && t.includes('quick')) return true;
    return false;
  }};
  const rows = Array.from(document.querySelectorAll(
    'tr, [role="row"], mat-row, .mat-row, .grid-row, .table-row, a'
  ));
  let best = null;
  let bestScore = -1;
  for (const row of rows) {{
    const txt = norm(row.textContent || '');
    if (!txt) continue;
    let score = 0;
    if (digits && txt.replace(/\\D/g, '').includes(digits)) score += 10;
    if (txt.includes('quick')) score += 8;
    if (hint && txt.includes(hint)) score += 4;
    if (score <= 0) continue;
    if (score > bestScore) {{ bestScore = score; best = row; }}
  }}
  if (best) {{
    try {{ best.click(); }} catch (e) {{}}
    const link = best.querySelector && best.querySelector('a, button, [role="button"]');
    if (link) try {{ link.click(); return 'row_link'; }} catch (e) {{}}
    return 'row';
  }}
  return 'not_found';
}})();
"""


_RECV_FROM_CUSTOMER_PAT = (
    r"prejemanje\s+ra[cč]unov\s+od\s+te\s+strank|"
    r"prejemanje\s+ra[cč]unov\s+od\s+te\s+stranke"
)
_SEND_TO_CUSTOMER_PAT = r"po[šs]iljanje\s+ra[cč]unov\s+tej\s+strank"


def _js_transfer_checkbox_finder() -> str:
    """Skupna logika: najkrajši label / najbližja vrstica, ne celoten blok."""
    return """
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const findBox = (pat, maxLen = 95) => {
    const labels = Array.from(document.querySelectorAll('label'))
      .map((l) => ({ l, t: norm(l.textContent || '') }))
      .filter((x) => pat.test(x.t) && x.t.length <= maxLen)
      .sort((a, b) => a.t.length - b.t.length);
    for (const { l } of labels) {
      let box = l.querySelector('input[type=checkbox]');
      if (!box && l.htmlFor) box = document.getElementById(l.htmlFor);
      if (box) return box;
    }
    for (const box of document.querySelectorAll('input[type=checkbox]')) {
      const row = box.closest('tr, li, label, td') || box.parentElement;
      const t = norm((row && row.textContent) || '');
      if (pat.test(t) && t.length <= maxLen) return box;
    }
    return null;
  };
"""


def _js_recv_invoice_checkbox_state() -> str:
    """checked | unchecked | missing"""
    finder = _js_transfer_checkbox_finder()
    pat = _RECV_FROM_CUSTOMER_PAT
    return f"""
(() => {{
{finder}
  const pat = /{pat}/i;
  const box = findBox(pat);
  if (!box) return 'missing';
  return box.checked ? 'checked' : 'unchecked';
}})();
"""


def _js_set_recv_invoice_checkbox(enable: bool) -> str:
    en = "true" if enable else "false"
    finder = _js_transfer_checkbox_finder()
    pat = _RECV_FROM_CUSTOMER_PAT
    return f"""
(() => {{
  const enable = {en};
{finder}
  const pat = /{pat}/i;
  const clickBox = (box) => {{
    if (!box) return 'missing';
    if (box.checked === enable) return enable ? 'already_on' : 'already_off';
    try {{ box.click(); return enable ? 'turned_on' : 'turned_off'; }} catch (e) {{ return 'click_fail'; }}
  }};
  return clickBox(findBox(pat));
}})();
"""


def _js_enable_recv_from_customer_checkbox() -> str:
    """Okljukaj samo «Prejemanje računov od te stranke»."""
    finder = _js_transfer_checkbox_finder()
    pat = _RECV_FROM_CUSTOMER_PAT
    return f"""
(() => {{
{finder}
  const pat = /{pat}/i;
  const box = findBox(pat);
  if (!box) return 'missing';
  if (box.checked) return 'already_on';
  try {{ box.click(); return 'turned_on'; }} catch (e) {{ return 'click_fail'; }}
}})();
"""


def _js_enable_send_to_customer_checkbox() -> str:
    """Okljukaj samo «Pošiljanje računov tej stranki»."""
    finder = _js_transfer_checkbox_finder()
    pat = _SEND_TO_CUSTOMER_PAT
    return f"""
(() => {{
{finder}
  const pat = /{pat}/i;
  const box = findBox(pat);
  if (!box) return 'missing';
  if (box.checked) return 'already_on';
  try {{ box.click(); return 'turned_on'; }} catch (e) {{ return 'click_fail'; }}
}})();
"""


def _js_checkbox_by_label_regex(label_regex: str, enable: bool) -> str:
    """Najdi checkbox po regexu na labeli/v bližini."""
    pat = json.dumps(str(label_regex or ""))
    en = "true" if enable else "false"
    return f"""
(() => {{
  const pat = new RegExp({pat}, 'i');
  const enable = {en};
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const clickBox = (box) => {{
    if (!box) return 'missing';
    if (box.checked === enable) return enable ? 'already_on' : 'already_off';
    try {{ box.click(); return enable ? 'turned_on' : 'turned_off'; }} catch (e) {{ return 'click_fail'; }}
  }};
  const matchText = (t) => pat.test(norm(t || ''));
  const nodes = Array.from(document.querySelectorAll('label, span, div, td, th, legend, p'));
  for (const n of nodes) {{
    const t = norm(n.textContent || '');
    if (!matchText(t) || t.length > 140) continue;
    const box = n.querySelector('input[type=checkbox]') ||
      (n.parentElement && n.parentElement.querySelector('input[type=checkbox]'));
    const r = clickBox(box);
    if (r !== 'missing') return r;
  }}
  for (const box of document.querySelectorAll('input[type=checkbox]')) {{
    const near = norm((box.parentElement && box.parentElement.textContent) || '');
    if (matchText(near)) return clickBox(box);
  }}
  return 'missing';
}})();
"""


def _js_uncheck_einvoice_blocking_options() -> str:
    """Odkljukaj 2 možnosti, ki blokirajo neposredni prenos (Ponudnik + e-pošta)."""
    return """
(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const offPatterns = [
    /ponudnik\\s+storitev|preko\\s+ponudnika|e-?račun.*ponudnik|e-?racun.*ponudnik/,
    /pošiljanje.*e-?račun.*e-?po[šs]t|e-?po[šs]t.*e-?račun|e-?račun.*e-?po[šs]t/,
  ];
  const clickOff = (box) => {
    if (!box || !box.checked) return 'already_off';
    try { box.click(); return 'turned_off'; } catch (e) { return 'click_fail'; }
  };
  const results = [];
  for (const pat of offPatterns) {
    let hit = 'missing';
    for (const n of document.querySelectorAll('label, span, div, td, th, legend, p')) {
      const t = norm(n.textContent || '');
      if (!pat.test(t) || t.length > 140) continue;
      const box = n.querySelector('input[type=checkbox]') ||
        (n.parentElement && n.parentElement.querySelector('input[type=checkbox]'));
      const r = clickOff(box);
      if (r !== 'missing') { hit = r; break; }
    }
    if (hit === 'missing') {
      for (const box of document.querySelectorAll('input[type=checkbox]')) {
        const near = norm((box.parentElement && box.parentElement.textContent) || '');
        if (pat.test(near)) { hit = clickOff(box); break; }
      }
    }
    results.push(hit);
  }
  return results.join('+');
})();
"""


def _js_enable_direct_transfer_checkboxes() -> str:
    """Okljukaj obe: prejemanje + pošiljanje računov (neposredni prenos)."""
    finder = _js_transfer_checkbox_finder()
    recv_pat = _RECV_FROM_CUSTOMER_PAT
    send_pat = _SEND_TO_CUSTOMER_PAT
    return f"""
(() => {{
{finder}
  const clickOn = (pat) => {{
    const box = findBox(pat);
    if (!box) return 'missing';
    if (box.checked) return 'already_on';
    try {{ box.click(); return 'turned_on'; }} catch (e) {{ return 'click_fail'; }}
  }};
  const recv = clickOn(/{recv_pat}/i);
  const send = clickOn(/{send_pat}/i);
  return recv + '+' + send;
}})();
"""
