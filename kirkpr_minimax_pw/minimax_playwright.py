"""Lasten brskalnik (Playwright/Chromium) za polno avtomatizacijo Minimax WebUI.

Namen: e-računi (osnutki PR), ki jih Minimax API ne zna poknjižiti, se v celoti
obdelajo v lastnem, vgrajenem brskalniku:
  preklop firme → odpri osnutek → + Nov odhodek (konto 4190) → Potrdi.

Prednosti pred CDP na tvojem Chromu:
  • lasten Chromium (ne dotika se tvojega Chroma, brez debug portov),
  • enkratna prijava (headed), potem vse teče v ozadju (headless),
  • robustno (Playwright auto-wait) in ponovljivo.

JS koraki so isti kot pri CDP poti (domain.minimax_cdp) — tu jih poganjamo prek
Playwright page.evaluate.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple

from kirkpr_minimax_pw.minimax_cdp import (
    _js_click_by_label,
    _js_click_shrani_customer,
    _js_click_uredi,
    _js_enable_recv_from_customer_checkbox,
    _js_enable_send_to_customer_checkbox,
    _js_expense_state,
    _js_extract_spreadsheet_base_url,
    _js_fill_konto,
    _js_fill_konto_grid,
    _js_fill_org_filter,
    _js_fill_search,
    _js_fill_vat_bases,
    _js_find_org_switch_url,
    _js_has_system_error,
    _js_is_pr_already_confirmed,
    _js_navigate_prejeti_racuni_from_zacetek,
    _js_navigate_stranke_sifrant,
    _js_open_customer_by_tax,
    _js_open_matching_row,
    _js_open_prejeti_racuni_menu,
    _js_probe_row_status,
    _js_recv_invoice_checkbox_state,
    _js_search_customer_tax,
    _js_set_recv_invoice_checkbox,
    _js_switch_organisation,
    _js_uncheck_einvoice_blocking_options,
    _org_filter_term,
)
from kirkpr_minimax_pw.minimax_web_links import (
    MINIMAX_ORG_LIST_URL,
    MINIMAX_ZACETEK_URL,
    MINIMAX_ORG_SELECT_URL,
    minimax_client_zacetek_url,
    minimax_org_list_urls,
    minimax_customers_spa_url,
    minimax_payment_order_from_received_url,
    minimax_payment_order_mass_export_url,
    minimax_received_invoice_list_url,
    minimax_received_invoice_view_url,
    minimax_stranka_edit_url,
)
from kirkpr_minimax_pw.virman_export import virman_export_path

DEFAULT_EXPENSE_ACCOUNT = "4190"
PROFILE_ROOT = "MinimaxBlagajna"
PROFILE_FOLDER = "PlaywrightProfile"

# Playwright profil je skupen — serializiraj probe/potrditev ob vzporednem API pollu.
_PW_LOCK = threading.Lock()
_LOGIN_CACHE: tuple[float, bool] | None = None
_LOGIN_CACHE_TTL = 90.0
_PREWARM_THREAD: threading.Thread | None = None


@dataclass
class PwResult:
    ok: bool
    message: str
    need_login: bool = False
    method: str = "playwright"
    confirmed: bool = False  # True = osnutek dejansko POTRJEN (klik Potrdi uspel)
    export_path: str = ""  # pot izvoženega virmana (če ustvarjen)
    recv_checked: bool = False  # True = kljukica prejema ob zaprtju brskalnika


@dataclass
class PwBatchItem:
    """En element paketne obdelave (ena firma / en prejeti osnutek)."""
    org_id: str
    received_invoice_id: str = ""
    org_name: str = ""
    document_reference: str = ""
    ref_key: object = None  # poljuben ključ klicatelja (npr. client_id) za povezavo rezultata
    wants_virman: bool = False
    popa_id: int = 0
    supplier_name: str = "QuickMB"
    invoice_number: str = ""
    skip_draft: bool = False  # True = osnutek že potrjen (API), samo virman
    expense_account: str = ""  # prazen = batch privzeti / 4190
    base_22: str = ""  # osnova 22% (npr. "32.64")
    base_95: str = ""
    base_5: str = ""


@dataclass
class PwProbeResult:
    phase: str = "cakanje"  # cakanje | poslano | potrjen
    detail: str = ""
    received_id: str = ""
    ok: bool = False
    message: str = ""


def _parse_probe_status(raw: str) -> tuple[str, str]:
    """JS rezultat → (faza, opis)."""
    val = str(raw or "").strip().lower()
    if not val or val in ("no_ref", "not_found", "not_view", "unknown"):
        return "cakanje", ""
    if val.startswith("potrjen"):
        return "potrjen", "Potrjen (Minimax UI)"
    if val.startswith("osnutek"):
        return "poslano", "Osnutek PR (Minimax UI)"
    if val.startswith("confirmed"):
        return "potrjen", "Potrjen (Minimax pogled)"
    if val.startswith("draft"):
        return "poslano", "Osnutek PR (Minimax pogled)"
    if val.startswith("found:"):
        return "poslano", "PR najden (status neznan)"
    return "cakanje", ""


# ── razpoložljivost ─────────────────────────────────────────────────────────
def playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def _browsers_root() -> Path:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"


def playwright_browser_installed() -> bool:
    root = _browsers_root()
    try:
        if not root.is_dir():
            return False
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("chromium"):
                return True
    except Exception:
        return False
    return False


def playwright_ready() -> bool:
    return playwright_installed() and playwright_browser_installed()


def playwright_profile_dir() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA", "")) / PROFILE_ROOT / PROFILE_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def playwright_setup_hint() -> str:
    return (
        "Za lasten brskalnik (Playwright) namesti:\n"
        "  py -3.10 -m pip install playwright\n"
        "  py -3.10 -m playwright install chromium\n\n"
        f"Profil (enkratna prijava): {playwright_profile_dir()}"
    )


def _launch_args(*, headless: bool) -> list[str]:
    args = ["--no-first-run", "--no-default-browser-check"]
    if not headless:
        args.append("--start-maximized")
    return args


def _safe_close_playwright_context(ctx) -> None:
    """Zapri vse zavihke in kontekst — Minimax ne sme videti več sej."""
    if ctx is None:
        return
    try:
        for pg in list(ctx.pages):
            try:
                pg.close()
            except Exception:
                pass
    except Exception:
        pass
    try:
        ctx.close()
    except Exception:
        pass


@contextmanager
def _minimax_pw_session(
    *,
    headless: bool = True,
    accept_downloads: bool = False,
    no_viewport: bool | None = None,
    downloads_path: str | None = None,
    hold_until_user_closes: bool = False,
    wait_close_emit: Optional[Callable[[str], None]] = None,
) -> Iterator[Tuple[object, object]]:
    """En Playwright zagon z garantiranim zaprtjem ob izhodu (profil ostane na disku)."""
    if not playwright_ready():
        raise RuntimeError("Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())

    from playwright.sync_api import sync_playwright

    profile = str(playwright_profile_dir())
    kwargs: dict = {
        "headless": headless,
        "args": _launch_args(headless=headless),
        "accept_downloads": accept_downloads,
        "no_viewport": (not headless) if no_viewport is None else no_viewport,
    }
    if downloads_path:
        kwargs["downloads_path"] = downloads_path

    with _PW_LOCK:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(profile, **kwargs)
            try:
                ctx.set_default_timeout(20000)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                yield page, ctx
            finally:
                if hold_until_user_closes and not headless:
                    _wait_browser_user_close(ctx, emit=wait_close_emit)
                _safe_close_playwright_context(ctx)


# ── pomožno ─────────────────────────────────────────────────────────────────
def _eval(page, js: str) -> str:
    expr = js.strip()
    while expr.endswith(";"):
        expr = expr[:-1].rstrip()
    try:
        val = page.evaluate(expr)
    except Exception:
        return ""
    return "" if val is None else str(val)


def _eval_frames(page, js: str, *, ok_prefixes: tuple[str, ...] = ()) -> str:
    """Evaluate JS v glavnem oknu in vseh iframe-ih; vrne prvi 'uspešen' rezultat."""
    expr = js.strip()
    while expr.endswith(";"):
        expr = expr[:-1].rstrip()
    ok = set(ok_prefixes)

    def _ok(val: object) -> bool:
        s = "" if val is None else str(val)
        if not s or s in ("no_field", "not_found", "no_uredi"):
            return False
        if ok:
            return any(s.startswith(p) for p in ok)
        return True

    for frame in page.frames:
        try:
            val = frame.evaluate(expr)
            if _ok(val):
                return str(val)
        except Exception:
            continue
    try:
        val = page.evaluate(expr)
    except Exception:
        return ""
    return "" if val is None else str(val)


def _try_fill_konto(page, acct: str) -> bool:
    """Poskusi vpis konta: polje z oznako → mreža (Beta) → tipkovnica."""
    if _eval_frames(page, _js_fill_konto(acct), ok_prefixes=("filled",)) in (
        "filled_konto",
    ):
        return True
    if _eval_frames(page, _js_fill_konto_grid(acct), ok_prefixes=("filled",)) in (
        "filled_grid",
        "filled_grid_active",
    ):
        return True
    try:
        page.keyboard.type(acct, delay=70)
        page.keyboard.press("Enter")
        time.sleep(0.6)
    except Exception:
        pass
    state = _eval(page, _js_expense_state(acct))
    return state in ("has_account", "ready_confirm")


def _settle(page, sec: float = 1.0) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    if sec > 0:
        time.sleep(sec)


def _page_state(page) -> str:
    """'app' = prijavljen (Minimax odprt), 'login' = prijavna stran, 'unknown' = nalaganje."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    try:
        body = (page.inner_text("body", timeout=2500) or "").lower()
    except Exception:
        body = ""

    if "login.minimax" in url or "wsignin" in url:
        return "login"

    app_hints = ("odjava", "moje organizacije", "prejeti računi", "poslovanje")
    if any(h in body for h in app_hints):
        return "app"

    login_hints = ("digitalno potrdilo", "uporabniško ime", "pozabljeno geslo", "prijava v minimax")
    if any(h in body for h in login_hints):
        return "app" if "odjava" in body else "login"
    if "login" in url:
        return "login"
    return "unknown"


def _is_login_page(page) -> bool:
    return _page_state(page) == "login"


def _webui_credentials() -> tuple:
    """E-pošta + geslo za Minimax WebUI iz configa (rezerva; primarno je potrdilo)."""
    try:
        from db.connection import load_config

        mm = load_config().get("minimax") or {}
    except Exception:
        return "", ""
    email = str(mm.get("webui_email") or "").strip()
    pw = str(mm.get("webui_password") or "")
    return email, pw


def _try_webui_login(page) -> bool:
    """
    Best-effort samodejna prijava e-pošta + geslo (če je v configu).
    Halcom PIN / digitalno potrdilo se NE shranjuje — to ureja brskalnik/uporabnik.
    """
    email, pw = _webui_credentials()
    if not email:
        return False

    def _click_submit():
        for sel in ("button[type=submit]", "input[type=submit]", "button"):
            try:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    return True
            except Exception:
                continue
        return False

    try:
        em = page.query_selector('#Email, input[name="Email"], input[type=email]')
        if em:
            em.fill(email)
            _click_submit()
            _settle(page, 2.0)
    except Exception:
        pass

    if pw:
        try:
            pel = page.query_selector('input[type=password]')
            if pel:
                pel.fill(pw)
                _click_submit()
                _settle(page, 2.5)
        except Exception:
            pass

    return _page_state(page) == "app"


# ── preklop firme ───────────────────────────────────────────────────────────
_ORG_LIST_COUNT_JS = """
(() => {
  const n1 = document.querySelectorAll("a[href*='RepeaterMojeOrganizacije']").length;
  if (n1) return n1;
  const n2 = document.querySelectorAll('[data-organizacijaid]').length;
  if (n2) return n2;
  return document.querySelectorAll('a.organizacija-naziv').length;
})()
"""

_JS_CLICK_MOJE_ORG = """
(() => {
  const anchors = Array.from(document.querySelectorAll('a'));
  const a = anchors.find(x => /moje organizacije/i.test(String(x.textContent || '')));
  if (a) { try { a.click(); return 'ok'; } catch (e) {} }
  return 'no';
})()
"""


def _org_list_count(page) -> int:
    try:
        val = page.evaluate(_ORG_LIST_COUNT_JS)
        return int(val or 0)
    except Exception:
        return 0


def _goto_org_list(page, *, wait_sec: float = 5.0) -> int:
    """Odpri seznam firm — Minimax ga kaže na Zacetek.aspx?login=1, ne vedno na ZacetekOrganizacije."""
    if _is_login_page(page):
        return 0
    cnt = _org_list_count(page)
    if cnt > 0:
        return cnt
    deadline = time.time() + max(wait_sec, 4.0)
    for url in minimax_org_list_urls():
        if time.time() > deadline:
            break
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        _settle(page, 0.7)
        while time.time() < deadline and _org_list_count(page) == 0:
            time.sleep(0.35)
        cnt = _org_list_count(page)
        if cnt > 0:
            return cnt
    if _eval(page, _JS_CLICK_MOJE_ORG) == "ok":
        _settle(page, 1.0)
        while time.time() < deadline and _org_list_count(page) == 0:
            time.sleep(0.35)
    return _org_list_count(page)


def _view_opened(page) -> bool:
    """
    Osnutek je RES odprt le, če smo na strani PrejetRacunView in NE na seznamu firm.
    Napačna aktivna firma -> Minimax tiho preusmeri na Zacetek.aspx?login=1 (seznam
    firm), BREZ 'Sistemska napaka' -> tega ne smemo šteti za odprt osnutek.
    """
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    if "prejetracun" not in url:
        return False
    if _org_list_count(page) > 0:
        return False
    return _eval(page, _js_has_system_error()) != "error"


_JS_ORG_DASHBOARD_JS = """
(() => !!(
  document.querySelector('#P_MuuriGrid, .muuri-grid-item, [data-type="IRStanje"]')
  || document.querySelector('#content h1[title]')
))()
"""


def _on_org_chooser_page(page) -> bool:
    """Stran z izbirnikom firm (ne dashboard po uspešnem preklopu)."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    if "login=1" in url:
        return True
    if "zacetekorganizacije" in url:
        try:
            if page.evaluate(_JS_ORG_DASHBOARD_JS):
                return False
        except Exception:
            pass
        return True
    # OrganisationId v URL = seja že nastavljena na firmi (direktna pot / postback).
    if "organisationid=" in url:
        return False
    if "zacetek.aspx" in url and _org_list_count(page) >= 15:
        return True
    return False


def _org_session_ok(page) -> bool:
    """Aktivna firma v seji (ni prijave, ni izbirnika firm, ni sistemske napake)."""
    if _is_login_page(page):
        return False
    if _eval(page, _js_has_system_error()) == "error":
        return False
    if _on_org_chooser_page(page):
        return False
    return _page_state(page) == "app"


def _go_minimax_dashboard(page, *, wait_sec: float = 2.0) -> None:
    """Dashboard po postbacku (seja je že nastavljena — brez login=1 / OrganisationId)."""
    try:
        page.goto(MINIMAX_ZACETEK_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    _settle(page, max(wait_sec, 1.5))


def _try_org_click_on_page(page, org_id: str, org_name: str, *, wait_sec: float = 2.5) -> str:
    """Klik na firmo na trenutni strani (login=1 ali ZacetekOrganizacije)."""
    _fill_org_list_filter(page, org_name, org_id=org_id, wait_sec=wait_sec)
    ok_states = ("id", "name", "name_row", "name_part")
    res = ""
    deadline = time.time() + max(wait_sec, 2.5)
    while time.time() < deadline:
        res = _eval(page, _js_switch_organisation(org_id, org_name))
        if res in ok_states:
            break
        time.sleep(0.6)
    return res


def _try_org_direct(page, org_id: str, *, wait_sec: float = 2.0) -> bool:
    """Direktno Zacetek.aspx?OrganisationId= — hitra pot ob znanem Org_ID (npr. TEST 101469)."""
    org = str(org_id or "").strip()
    if not org.isdigit():
        return False
    try:
        page.goto(minimax_client_zacetek_url(org), wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    _settle(page, max(wait_sec, 1.5))
    if _on_org_chooser_page(page):
        res = _try_org_click_on_page(page, org, "", wait_sec=wait_sec)
        if res in ("id", "name", "name_row", "name_part"):
            _settle(page, 2.0)
            _go_minimax_dashboard(page, wait_sec=wait_sec)
        else:
            print(
                f"[minimax] _try_org_direct: chooser org_id={org} url={getattr(page, 'url', '?')}"
            )
            return False
    elif not _org_session_ok(page):
        _go_minimax_dashboard(page, wait_sec=wait_sec)
    ok = _org_session_ok(page)
    print(f"[minimax] _try_org_direct: ok={ok} org_id={org} url={getattr(page, 'url', '?')}")
    return ok


def _fill_org_list_filter(
    page,
    org_name: str,
    *,
    org_id: str = "",
    wait_sec: float = 2.0,
) -> None:
    """Filter na strani Moje organizacije (paginiran seznam 100+ firm)."""
    term = _org_filter_term(org_name) or str(org_id or "").strip()
    if not term:
        return
    deadline = time.time() + max(wait_sec, 2.0)
    while time.time() < deadline:
        time.sleep(0.6)
        if _eval(page, _js_fill_org_filter(term)) == "filled":
            break
    time.sleep(1.2)


def _switch_org_via_list(
    page,
    org: str,
    name: str,
    *,
    wait_sec: float = 4.0,
) -> bool:
    """Preklop prek seznama Moje organizacije (postback klik)."""
    # Minimax izbiro aktivne firme hrani v seji. ZacetekOrganizacije.aspx je zato
    # zanesljivejsa prva pot kot neposredni ?OrganisationId= na Zacetek.aspx.
    for url in (MINIMAX_ORG_SELECT_URL, MINIMAX_ORG_LIST_URL, MINIMAX_ZACETEK_URL):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        _settle(page, 0.8)
        if _org_list_count(page) > 0 or "zacetekorganizacije" in (page.url or "").lower():
            break

    cnt = _org_list_count(page)
    if cnt == 0:
        cnt = _goto_org_list(page, wait_sec=max(wait_sec, 5.0))
    print(f"[minimax] _switch_org: org_list_count={cnt} url={getattr(page, 'url', '?')}")
    if cnt == 0:
        return False

    ok_states = ("id", "name", "name_row", "name_part")
    res = "not_found"
    for term_name, term_id in ((name, ""), ("", org)):
        if not term_name and not term_id:
            continue
        _fill_org_list_filter(page, term_name, org_id=term_id, wait_sec=wait_sec)
        res = _try_org_click_on_page(page, org, name, wait_sec=wait_sec)
        print(f"[minimax] _switch_org: click result={res!r} (org_id={org})")
        if res in ok_states:
            break

    if res not in ok_states:
        switch_url = _eval(page, _js_find_org_switch_url(org, name)).strip()
        if switch_url.startswith("http"):
            try:
                page.goto(switch_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            _settle(page, 1.5)
            _go_minimax_dashboard(page, wait_sec=wait_sec)
            return _org_session_ok(page)
        return False

    deadline = time.time() + max(wait_sec, 6.0)
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        if _org_session_ok(page):
            print(f"[minimax] _switch_org: ok org_id={org} url={getattr(page, 'url', '?')}")
            return True

    _go_minimax_dashboard(page, wait_sec=wait_sec)
    if _org_session_ok(page):
        print(f"[minimax] _switch_org: ok org_id={org} url={getattr(page, 'url', '?')}")
        return True

    if _on_org_chooser_page(page):
        res2 = _try_org_click_on_page(page, org, name, wait_sec=wait_sec)
        print(f"[minimax] _switch_org: retry click result={res2!r} (org_id={org})")
        if res2 in ok_states:
            _settle(page, 2.0)
            _go_minimax_dashboard(page, wait_sec=wait_sec)
            if _org_session_ok(page):
                print(f"[minimax] _switch_org: ok org_id={org} url={getattr(page, 'url', '?')}")
                return True

    return False


def _switch_org(page, org_id: str, org_name: str, *, wait_sec: float = 4.0) -> bool:
    """
    Preklop firme: (1) seznam Moje organizacije + klik, (2) direktna rezervna
    pot po Org_ID. Ujemanje imena je neodvisno od šumnikov (č/ć/š/ž).

    Seznam je primaren, ker URL po izbiri lahko ostane ZacetekOrganizacije.aspx;
    aktivno firmo Minimax hrani v seji in je ni mogoce potrditi samo iz URL-ja.
    """
    if _is_login_page(page):
        return False

    org = str(org_id or "").strip()
    name = str(org_name or "").strip()
    if not org.isdigit():
        return False

    if _switch_org_via_list(page, org, name, wait_sec=wait_sec):
        return True

    if _try_org_direct(page, org, wait_sec=wait_sec):
        return True

    print(f"[minimax] _switch_org: FAILED org_id={org} url={getattr(page, 'url', '?')}")
    return False


# ── seznam Prejeti računi + iskanje ─────────────────────────────────────────
def _goto_list(page, list_url: str, *, wait_sec: float = 3.0) -> bool:
    sheet = _eval(page, _js_extract_spreadsheet_base_url()).strip()
    if sheet.startswith("http"):
        try:
            page.goto(sheet, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        _settle(page, 1.0)
        if _eval(page, _js_has_system_error()) != "error":
            return True

    nav = _eval(page, _js_navigate_prejeti_racuni_from_zacetek())
    if nav in ("spreadsheet", "link"):
        _settle(page, 1.0)
        if _eval(page, _js_has_system_error()) != "error":
            return True

    fallback = (list_url or "").strip()
    if fallback.startswith("http"):
        try:
            page.goto(fallback, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        _settle(page, 1.0)
        return _eval(page, _js_has_system_error()) != "error"
    return False


def _search_open(page, ref: str, rid: str, *, wait_sec: float = 3.0) -> bool:
    deadline = time.time() + max(wait_sec, 1.0)
    filled = False
    while time.time() < deadline:
        time.sleep(0.6)
        if _eval(page, _js_fill_search(ref, rid)) == "filled":
            filled = True
            break
    if not filled:
        if _eval(page, _js_open_prejeti_racuni_menu()) == "menu":
            _settle(page, 1.5)
            filled = _eval(page, _js_fill_search(ref, rid)) == "filled"
    if not filled:
        return False
    time.sleep(1.0)
    return _eval(page, _js_open_matching_row(ref, rid)) in ("row", "cell")


def _ref_variants(ref: str) -> list[str]:
    """Različni zapisi št. knjižbe za iskanje v Minimax seznamu."""
    raw = str(ref or "").strip()
    if not raw:
        return []
    out: list[str] = [raw]
    seen = {raw.casefold()}
    norm = raw.replace("_", "-")
    parts = norm.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[-1].isdigit():
        y, n = parts[0], parts[-1]
        for v in (f"{y}-{n}", f"{n}-{y}", f"{n}/{y}", f"{y}/{n}", n, y):
            if v and v.casefold() not in seen:
                seen.add(v.casefold())
                out.append(v)
    return out


def _collect_search_refs(
    ref: str,
    rid: str,
    extra: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in list(extra or []) + _ref_variants(ref):
        s = str(r or "").strip()
        if not s or s.casefold() in seen:
            continue
        seen.add(s.casefold())
        out.append(s)
    if rid.isdigit() and rid.casefold() not in seen:
        out.append(rid)
    return out


def _draft_not_found_message(ref: str, refs: list[str]) -> str:
    tried = ", ".join(refs[:4]) if refs else (ref or "—")
    return (
        "Ni najdenega PR osnutka/prejetega računa pri stranki "
        f"(iskano: {tried}).\n\n"
        "Verjetno IR ni bil prenesen v PR (prejemanje od Quick ni bilo vključeno ob Izstavi).\n"
        "Koraki: «Prejem od Quick…» → «Prenos PR v Minimax» — ali ročno v Minimaxu (Prejeti računi)."
    )


def _probe_list_status(page, ref: str, rid: str, *, wait_sec: float = 2.0) -> PwProbeResult:
    """Preberi status PR v seznamu (brez odpiranja pogleda)."""
    deadline = time.time() + max(wait_sec, 1.0)
    filled = False
    while time.time() < deadline:
        time.sleep(0.6)
        if _eval(page, _js_fill_search(ref, rid)) == "filled":
            filled = True
            break
    if not filled:
        return PwProbeResult(message="Iskalno polje ni najdeno")
    time.sleep(1.2)
    raw = _eval(page, _js_probe_row_status(ref, rid))
    phase, detail = _parse_probe_status(raw)
    if phase != "cakanje":
        return PwProbeResult(phase=phase, detail=detail, ok=True, message=detail)
    return PwProbeResult(message=str(raw or "not_found"))


def _probe_phase_on_page(
    page,
    *,
    org: str,
    org_name: str,
    rid: str,
    ref: str,
) -> PwProbeResult:
    """Preklop firme → seznam ali pogled → preberi P/O status (brez potrditve)."""
    list_url = minimax_received_invoice_list_url(org)
    view_url = minimax_received_invoice_view_url(rid, org) if rid.isdigit() else ""

    if not _switch_org(page, org, org_name):
        state = _page_state(page)
        if state == "login":
            return PwProbeResult(message="Potrebna prijava v Minimax (lasten brskalnik).")
        return PwProbeResult(message="Preklop firme ni uspel.")

    if view_url:
        try:
            page.goto(view_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        _settle(page, 1.0)
        if _view_opened(page):
            raw = _eval(page, _js_is_pr_already_confirmed())
            phase, detail = _parse_probe_status(raw)
            if phase != "cakanje":
                return PwProbeResult(
                    phase=phase,
                    detail=detail,
                    received_id=rid,
                    ok=True,
                    message=detail,
                )

    if ref or rid:
        if _goto_list(page, list_url):
            listed = _probe_list_status(page, ref, rid)
            if listed.ok and listed.phase == "potrjen":
                return listed
            if ref or rid:
                if _search_open(page, ref, rid):
                    _settle(page, 1.0)
                    if "prejetracun" in str(getattr(page, "url", "") or "").lower():
                        raw = _eval(page, _js_is_pr_already_confirmed())
                        phase, detail = _parse_probe_status(raw)
                        if phase != "cakanje":
                            return PwProbeResult(
                                phase=phase,
                                detail=detail,
                                received_id=rid,
                                ok=True,
                                message=detail,
                            )
            if listed.ok:
                return listed
            if listed.message and listed.message not in ("not_found", "no_ref"):
                return listed

    return PwProbeResult(message="PR ni najden v Minimaxu")


def probe_received_invoice_phase(
    org_id: str,
    *,
    org_name: str = "",
    document_reference: str = "",
    received_invoice_id: str = "",
    headless: bool = True,
) -> PwProbeResult:
    """Preberi status PR pri stranki prek WebUI (za org brez API dostopa)."""
    batch = probe_received_invoice_phases_batch(
        [
            {
                "org_id": org_id,
                "org_name": org_name,
                "document_reference": document_reference,
                "received_invoice_id": received_invoice_id,
            }
        ],
        headless=headless,
    )
    return batch[0] if batch else PwProbeResult(message="Ni podatkov za preverjanje.")


def probe_received_invoice_phases_batch(
    items: list,
    *,
    headless: bool = True,
) -> list[PwProbeResult]:
    """Več strank v enem brskalniku — ob koncu vedno zaprt (ena Minimax seja)."""
    if not items:
        return []
    org = str(items[0].get("org_id") or "").strip()
    if not org.isdigit() and len(items) == 1:
        return [PwProbeResult(message="Manjka Org_ID stranke.")]
    if not playwright_ready():
        return [PwProbeResult(message="Playwright ni nameščen.")] * len(items)

    try:
        with _minimax_pw_session(headless=headless) as (page, _ctx):
            out: list[PwProbeResult] = []
            for it in items:
                oid = str(it.get("org_id") or "").strip()
                if not oid.isdigit():
                    out.append(PwProbeResult(message="Manjka Org_ID stranke."))
                    continue
                out.append(
                    _probe_phase_on_page(
                        page,
                        org=oid,
                        org_name=str(it.get("org_name") or "").strip(),
                        rid=str(it.get("received_invoice_id") or "").strip(),
                        ref=str(it.get("document_reference") or "").strip(),
                    )
                )
            return out
    except Exception as exc:
        msg = str(exc)
        if "ProcessSingleton" in msg or "SingletonLock" in msg:
            msg = "Profil brskalnika je zaseden — zapri druga okna."
        return [PwProbeResult(message=msg[:200])] * len(items)


# ── odhodek + potrditev ─────────────────────────────────────────────────────
def _expense_workflow(
    page,
    *,
    expense_account: str,
    auto_confirm: bool,
    base_22: str = "",
    base_95: str = "",
    base_5: str = "",
):
    """
    Vrne (opis, potrjeno: bool). potrjeno=True le, če je klik 'Potrdi' uspel.

    Ključno: »Nov odhodek« kliknemo NAJVEČ ENKRAT (sicer se doda kup praznih vrstic),
    nato konto + osnove DDV iz KPR, nato Potrdi po želji.
    """
    acct = str(expense_account or "4190").strip() or "4190"
    time.sleep(0.5)
    added_row = False
    konto_filled = False
    vat_filled = False
    b22 = str(base_22 or "").strip()
    b95 = str(base_95 or "").strip()
    b5 = str(base_5 or "").strip()

    def _try_confirm(prefix: str):
        if auto_confirm and _eval(page, _js_click_by_label("^potrdi$")) == "clicked":
            return (f"{prefix} — Potrdi (avtomatsko).", True)
        return (f"{prefix} — ročno klikni Potrdi.", False)

    for _ in range(12):
        if not vat_filled and (b22 or b95 or b5):
            vat_res = str(_eval(page, _js_fill_vat_bases(b22, b95, b5)) or "")
            if vat_res.startswith("filled:"):
                vat_filled = True
                time.sleep(0.35)

        state = _eval(page, _js_expense_state(acct))
        if state == "ready_confirm":
            return _try_confirm(f"Odhodek {acct}, razlika 0")
        if state == "has_account":
            return _try_confirm(f"Odhodek {acct} vnesen")

        # state == needs_expense (ali neznano): vrstico dodamo SAMO enkrat.
        if not added_row:
            if _eval(page, _js_click_by_label("nov odhodek")) == "clicked":
                added_row = True
                time.sleep(0.7)
        if _try_fill_konto(page, acct):
            konto_filled = True
        time.sleep(0.4)

    if konto_filled:
        return (f"Odhodek {acct} vpisan, a ni samodejno potrjen — ročno preveri konto in Potrdi.", False)
    if added_row:
        return (f"Vrstica odhodka dodana — ročno vpiši konto {acct} in Potrdi.", False)
    return (f"Ročno: Uredi → + Nov odhodek → konto {acct} → Potrdi.", False)


# ── jedro toka za eno firmo/osnutek (deljeno med posamični in paketni tok) ────
def _process_draft(
    page,
    *,
    org: str,
    org_name: str,
    rid: str,
    ref: str,
    acct: str,
    auto_expense: bool,
    auto_confirm: bool,
    headless: bool,
    document_references: list[str] | None = None,
    skip_org_switch: bool = False,
    base_22: str = "",
    base_95: str = "",
    base_5: str = "",
) -> PwResult:
    """En osnutek na že odprti strani: preklop firme → osnutek → odhodek → (Potrdi)."""
    view_url = minimax_received_invoice_view_url(rid, org) if rid.isdigit() else ""
    list_url = minimax_received_invoice_list_url(org)
    refs = _collect_search_refs(ref, rid, document_references)

    if not headless:
        try:
            page.bring_to_front()
        except Exception:
            pass

    # 1) Preklop firme (preskoči, če smo že na isti org — batch same-org).
    if skip_org_switch:
        switched = True
        way_prefix = "ista firma"
    else:
        switched = _switch_org(page, org, org_name)
        way_prefix = "preklop firme + osnutek"
    if not switched:
        url = str(getattr(page, "url", "") or "").lower()
        state = _page_state(page)
        if state == "login" or "login.minimax" in url or "wsignin" in url:
            if _try_webui_login(page) and _page_state(page) == "app":
                switched = _switch_org(page, org, org_name)
            if not switched:
                return PwResult(
                    False,
                    "Potrebna je enkratna prijava v Minimax (lasten brskalnik).",
                    need_login=True,
                )
        else:
            return PwResult(False, "Preklop firme ni uspel (Moje organizacije).")

    # 2) Zdaj smo na pravi firmi in prijavljeni -> odpri osnutek.
    opened = False
    if view_url:
        try:
            page.goto(view_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        _settle(page, 0.6)
        print(f"[minimax] po odprtju view: url={getattr(page, 'url', '?')}")
        opened = _view_opened(page)

    if not opened and refs:
        if _goto_list(page, list_url):
            for r in refs:
                if _search_open(page, r, rid, wait_sec=4.0):
                    _settle(page, 0.8)
                    url_l = str(getattr(page, "url", "") or "").lower()
                    if _view_opened(page) or "prejetracun" in url_l:
                        opened = True
                        break
            if not opened:
                for r in refs:
                    listed = _probe_list_status(page, r, rid, wait_sec=3.0)
                    if listed.ok and listed.phase == "potrjen":
                        detail = listed.detail or "Potrjen (Minimax seznam)"
                        return PwResult(True, detail, confirmed=True)
                    if listed.ok and listed.phase == "poslano" and _search_open(
                        page, r, rid, wait_sec=5.0
                    ):
                        _settle(page, 0.8)
                        url_l = str(getattr(page, "url", "") or "").lower()
                        if _view_opened(page) or "prejetracun" in url_l:
                            opened = True
                            break

    if not opened:
        msg = _draft_not_found_message(ref, refs)
        if not headless:
            _goto_list(page, list_url)
            msg += "\n\nSeznam Prejeti računi je odprt — poišči ročno ali preveri «Prenos PR»."
        return PwResult(False, msg)

    confirmed_state = _eval(page, _js_is_pr_already_confirmed())
    if confirmed_state == "confirmed":
        return PwResult(True, "že potrjen v Minimaxu", confirmed=True)

    way = way_prefix

    # Klik »Uredi« je občasno počasen (postback); poskusi večkrat.
    uredi_ok = False
    for _ in range(6):
        time.sleep(0.35)
        if _eval(page, _js_click_uredi()) == "uredi":
            uredi_ok = True
            break
    if not uredi_ok:
        return PwResult(True, f"Osnutek odprt ({way}) — ročno Uredi.")

    if auto_expense:
        detail, confirmed = _expense_workflow(
            page,
            expense_account=acct,
            auto_confirm=auto_confirm,
            base_22=base_22,
            base_95=base_95,
            base_5=base_5,
        )
        return PwResult(True, f"{detail} [{way}]", confirmed=confirmed)

    return PwResult(True, f"Osnutek + Uredi ({way}) — ročno dodaj odhodek.")


def _js_save_payment_order() -> str:
    """Poskusi shraniti / potrditi plačilni nalog na odprti strani."""
    return r"""(() => {
      const labels = ['shrani', 'potrdi', 'ustvari', 'v redu', 'ok', 'izvozi'];
      const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const nodes = Array.from(document.querySelectorAll(
        'a, button, input[type=button], input[type=submit], span[onclick], div[onclick]'
      ));
      for (const want of labels) {
        const el = nodes.find(n => {
          const t = norm(n.textContent || n.value || n.title || '');
          const vis = !!(n.offsetParent);
          return vis && (t === want || t.startsWith(want + ' '));
        });
        if (el) {
          try { el.click(); return 'clicked:' + want; } catch (e) {}
        }
      }
      return 'no_button';
    })()"""


def _mass_export_sepa(page, out_path) -> tuple[bool, str]:
    """Množični izvoz neplačanih — čarovnik MasovneObdelave (Naprej → … → prenos)."""
    export_url = minimax_payment_order_mass_export_url()
    try:
        page.goto(export_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    _settle(page, 1.5)
    last = ""
    for step in range(8):
        for label in ("izvozi", "izvoz", "potrdi", "zaključi", "končaj"):
            try:
                with page.expect_download(timeout=10000) as dl_info:
                    hit = _eval(page, _js_click_by_label(label))
                    if hit != "clicked":
                        raise RuntimeError("no click")
                    last = f"clicked:{label}"
                download = dl_info.value
                out_path.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(str(out_path))
                return True, f"izvoz ({label}) → {out_path.name}"
            except Exception:
                last = f"no_dl:{label}"
        if _eval(page, _js_click_by_label("naprej")) == "clicked":
            last = "naprej"
            _settle(page, 1.0)
            continue
        time.sleep(0.6)
    return False, f"čarovnik izvoza — zadnji korak: {last or '?'}"


def create_and_export_payment_order(
    page,
    *,
    org: str,
    org_name: str,
    received_invoice_id: str,
    popa_id: int,
    firm_name: str,
    supplier_name: str = "QuickMB",
    invoice_ref: str = "",
    already_on_org: bool = True,
) -> PwResult:
    """
    Kreira plačilni nalog iz prejetega računa (prkn) in izvozi SEPA XML v TROPS mapo.
    """
    rid = str(received_invoice_id or "").strip()
    if not rid.isdigit():
        return PwResult(False, "Manjka ID prejetega računa (prkn).")
    if not popa_id:
        return PwResult(False, "Manjka ZŠT stranke (mapa TROPS).")

    if not already_on_org:
        if not _switch_org(page, org, org_name):
            return PwResult(False, "Preklop firme ni uspel (virman).")

    create_url = minimax_payment_order_from_received_url(rid)
    try:
        page.goto(create_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    _settle(page, 1.5)
    print(f"[minimax] virman create url={getattr(page, 'url', '?')}")

    save_res = ""
    for _ in range(4):
        save_res = _eval(page, _js_save_payment_order())
        if save_res.startswith("clicked:"):
            _settle(page, 1.2)
            break
        time.sleep(0.6)
    print(f"[minimax] virman save: {save_res}")

    out_path = virman_export_path(
        popa_id,
        firm_name,
        supplier_name,
        invoice_ref or rid,
    )
    ok, detail = _mass_export_sepa(page, out_path)
    if ok:
        print(f"[minimax] virman exported -> {out_path}")
        return PwResult(True, f"Virman izvožen → {out_path}", export_path=str(out_path))
    return PwResult(
        False,
        f"Virman: {detail} (shrani: {save_res or '?'})",
    )


def _wait_browser_user_close(
    ctx,
    *,
    emit: Optional[Callable[[str], None]] = None,
    page: object | None = None,
    poll_recv_checkbox: bool = False,
) -> str:
    """Po ročnem koraku počakaj, da uporabnik zapre okno. Vrne zadnje stanje prejema."""
    last_recv = ""
    if emit:
        try:
            emit("Shrani v Minimaxu, nato zapri okno brskalnika …")
        except Exception:
            pass
    while True:
        try:
            if not ctx.pages:
                break
            if poll_recv_checkbox and page is not None:
                try:
                    chk = _eval_frames(
                        page,
                        _js_recv_invoice_checkbox_state(),
                        ok_prefixes=("checked", "unchecked", "missing"),
                    )
                    if chk:
                        last_recv = chk
                except Exception:
                    pass
        except Exception:
            break
        time.sleep(1.0)
    return last_recv


# ── glavni tok ──────────────────────────────────────────────────────────────
def open_confirm_received_draft(
    org_id: str,
    received_invoice_id: str = "",
    *,
    org_name: str = "",
    document_reference: str = "",
    document_references: list[str] | None = None,
    auto_expense: bool = True,
    auto_confirm: bool = False,
    expense_account: str = DEFAULT_EXPENSE_ACCOUNT,
    base_22: str = "",
    base_95: str = "",
    base_5: str = "",
    headless: bool = True,
    hold_open_sec: float = 0.0,
    hold_until_user_closes: bool = False,
) -> PwResult:
    """
    Poln tok: preklop firme → osnutek → odhodek (konto iz listine) + osnove → (opcijsko) Potrdi.
    hold_until_user_closes (samo headless=False): ne zapiraj okna — počakaj, da ga
    uporabnik sam zapre po ročnem Potrdi.
    hold_open_sec > 0: po koncu pusti okno odprto določen čas (legacy).
    """
    org = str(org_id or "").strip()
    if not org.isdigit():
        return PwResult(False, "Manjka Org_ID stranke.")
    if not playwright_ready():
        return PwResult(False, "Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())

    rid = str(received_invoice_id or "").strip()
    ref = str(document_reference or "").strip()
    acct = str(expense_account or DEFAULT_EXPENSE_ACCOUNT).strip() or DEFAULT_EXPENSE_ACCOUNT

    def _flow(page) -> PwResult:
        return _process_draft(
            page,
            org=org,
            org_name=org_name,
            rid=rid,
            ref=ref,
            acct=acct,
            auto_expense=auto_expense,
            auto_confirm=auto_confirm,
            headless=headless,
            document_references=document_references,
            base_22=base_22,
            base_95=base_95,
            base_5=base_5,
        )

    profile = str(playwright_profile_dir())
    print(f"[minimax] launch headless={headless} profile={profile}")
    try:
        with _minimax_pw_session(
            headless=headless,
            hold_until_user_closes=False,
        ) as (page, ctx):
            res = _flow(page)
            print(f"[minimax] flow done ok={res.ok} msg={res.message}")
            if hold_until_user_closes and not headless and not res.confirmed:
                _wait_browser_user_close(ctx)
            elif hold_open_sec > 0 and not headless:
                deadline = time.time() + hold_open_sec
                while time.time() < deadline and ctx.pages:
                    time.sleep(1.0)
            return res
    except Exception as exc:
        import traceback

        traceback.print_exc()
        msg = str(exc)
        if "ProcessSingleton" in msg or "SingletonLock" in msg or "in use" in msg.lower():
            msg = (
                "Profil lastnega brskalnika je zaseden (že teče drug proces). "
                "Zapri odprta okna lastnega brskalnika in poskusi znova."
            )
        return PwResult(False, msg[:300])


# ── paketni tok (en brskalnik, več firm) ────────────────────────────────────
def confirm_received_drafts_batch(
    items,
    *,
    auto_expense: bool = True,
    auto_confirm: bool | None = None,
    expense_account: str = DEFAULT_EXPENSE_ACCOUNT,
    headless: bool = True,
    hold_until_user_closes: bool | None = None,
    progress: Optional[Callable[[str], None]] = None,
) -> list:
    """
    En sam lasten brskalnik obdela SEZNAM osnutkov (po firmah) zaporedoma —
    veliko hitreje kot zagon/zaustavitev brskalnika za vsako firmo posebej.

    Vidno okno (headless=False): brez avto Potrdi; okno ostane odprto, dokler ga
    uporabnik ne zapre. V tem načinu se obdela največ en osnutek na zagon.
    """
    items = list(items or [])
    acct = str(expense_account or DEFAULT_EXPENSE_ACCOUNT).strip() or DEFAULT_EXPENSE_ACCOUNT
    if hold_until_user_closes is None:
        hold_until_user_closes = not headless
    if auto_confirm is None:
        auto_confirm = headless

    def _emit(text: str) -> None:
        if progress:
            try:
                progress(text)
            except Exception:
                pass

    if not items:
        return []
    if not playwright_ready():
        r = PwResult(False, "Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())
        return [(it, r) for it in items]

    needs_download = any(getattr(it, "wants_virman", False) for it in items)

    from playwright.sync_api import sync_playwright

    results: list = []
    total = len(items)
    profile = str(playwright_profile_dir())
    launch_args = ["--no-first-run", "--no-default-browser-check"]
    if not headless:
        launch_args.append("--start-maximized")
    print(f"[minimax] BATCH launch headless={headless} n={total} profile={profile}")
    try:
        with _PW_LOCK:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    profile,
                    headless=headless,
                    args=_launch_args(headless=headless),
                    accept_downloads=needs_download,
                    no_viewport=(not headless),
                )
                try:
                    ctx.set_default_timeout(20000)
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    stop_login = False
                    last_org = ""
                    for idx, it in enumerate(items, 1):
                        org = str(getattr(it, "org_id", "") or "").strip()
                        org_name = str(getattr(it, "org_name", "") or "").strip()
                        rid = str(getattr(it, "received_invoice_id", "") or "").strip()
                        ref = str(getattr(it, "document_reference", "") or "").strip()
                        wants_vm = bool(getattr(it, "wants_virman", False))
                        skip_draft = bool(getattr(it, "skip_draft", False))
                        popa_id = int(getattr(it, "popa_id", 0) or 0)
                        supplier = str(getattr(it, "supplier_name", "") or "QuickMB").strip() or "QuickMB"
                        inv_no = str(getattr(it, "invoice_number", "") or ref or "").strip()
                        # Konto VEDNO iz listine (PwBatchItem.expense_account);
                        # batch privzeti 4190 samo, če listina nima konta.
                        item_acct = (
                            str(getattr(it, "expense_account", "") or "").strip()
                            or acct
                        )
                        b22 = str(getattr(it, "base_22", "") or "").strip()
                        b95 = str(getattr(it, "base_95", "") or "").strip()
                        b5 = str(getattr(it, "base_5", "") or "").strip()
                        label = ref or inv_no or org_name or org or "?"
                        same_org = bool(last_org and last_org == org)
                        if stop_login:
                            results.append((it, PwResult(False, "Preskočeno (potrebna prijava).", need_login=True)))
                            continue
                        if not org.isdigit():
                            res = PwResult(False, "Manjka Org_ID stranke.")
                            results.append((it, res))
                            _emit(f"[{idx}/{total}] {label}: {res.message}")
                            continue
                        if skip_draft:
                            _emit(f"[{idx}/{total}] {label}: virman (že potrjeno API)…")
                        else:
                            sw = "ista firma" if same_org else "preklop firme"
                            _emit(
                                f"[{idx}/{total}] {label}: {sw} → osnutek → "
                                f"konto {item_acct}…"
                            )
                        try:
                            if skip_draft:
                                if same_org or _switch_org(page, org, org_name):
                                    if not same_org:
                                        last_org = org
                                    res = PwResult(True, "že potrjeno (API)", confirmed=True)
                                else:
                                    res = PwResult(False, "Preklop firme ni uspel (virman).")
                            else:
                                res = _process_draft(
                                    page,
                                    org=org,
                                    org_name=org_name,
                                    rid=rid,
                                    ref=ref,
                                    acct=item_acct,
                                    auto_expense=auto_expense,
                                    auto_confirm=auto_confirm,
                                    headless=headless,
                                    skip_org_switch=same_org,
                                    base_22=b22,
                                    base_95=b95,
                                    base_5=b5,
                                )
                                if res.ok and not res.need_login:
                                    last_org = org
                            if wants_vm and res.confirmed and rid.isdigit():
                                _emit(f"[{idx}/{total}] {label}: kreiram virman…")
                                vm = create_and_export_payment_order(
                                    page,
                                    org=org,
                                    org_name=org_name,
                                    received_invoice_id=rid,
                                    popa_id=popa_id,
                                    firm_name=org_name or label,
                                    supplier_name=supplier,
                                    invoice_ref=inv_no or ref,
                                    already_on_org=True,
                                )
                                if vm.ok:
                                    res = PwResult(
                                        res.ok,
                                        f"{res.message} | {vm.message}",
                                        confirmed=res.confirmed,
                                        export_path=vm.export_path,
                                    )
                                else:
                                    res = PwResult(
                                        False,
                                        f"{res.message} | {vm.message}",
                                        confirmed=res.confirmed,
                                    )
                        except Exception as exc:
                            import traceback

                            traceback.print_exc()
                            res = PwResult(False, str(exc)[:200])
                        results.append((it, res))
                        _emit(f"[{idx}/{total}] {label}: {res.message}")
                        print(f"[minimax] BATCH [{idx}/{total}] {label} ok={res.ok} msg={res.message}")
                        if res.need_login:
                            stop_login = True
                        if (
                            hold_until_user_closes
                            and not headless
                            and not skip_draft
                            and not res.confirmed
                            and res.ok
                        ):
                            _emit("Ročni način: po Potrdi zapri brskalnik; nato ponovi za naslednjo stranko.")
                            break
                finally:
                    if hold_until_user_closes and not headless:
                        _wait_browser_user_close(ctx, emit=_emit)
                    _safe_close_playwright_context(ctx)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        msg = str(exc)
        if "ProcessSingleton" in msg or "SingletonLock" in msg or "in use" in msg.lower():
            msg = (
                "Profil lastnega brskalnika je zaseden (že teče drug proces). "
                "Zapri odprta okna lastnega brskalnika in poskusi znova."
            )
        done = {id(it) for it, _ in results}
        for it in items:
            if id(it) not in done:
                results.append((it, PwResult(False, msg[:300])))
    return results


# ── enkratna prijava (headed) ───────────────────────────────────────────────
def invalidate_login_cache() -> None:
    global _LOGIN_CACHE
    _LOGIN_CACHE = None


def prewarm_playwright_profile() -> None:
    """V ozadju segreje Chromium profil — manj čakanja ob paketnem odpiranju."""
    global _PREWARM_THREAD
    if not playwright_ready():
        return
    if _PREWARM_THREAD is not None and _PREWARM_THREAD.is_alive():
        return

    def _run() -> None:
        try:
            with _minimax_pw_session(headless=True) as (page, _ctx):
                page.goto(
                    MINIMAX_ORG_LIST_URL,
                    wait_until="domcontentloaded",
                    timeout=12000,
                )
        except Exception:
            pass

    _PREWARM_THREAD = threading.Thread(target=_run, daemon=True)
    _PREWARM_THREAD.start()


def playwright_logged_in(*, timeout_sec: float = 12.0, use_cache: bool = True) -> bool:
    """Hitro (headless) preveri, ali je lasten profil prijavljen v Minimax."""
    global _LOGIN_CACHE
    if use_cache and _LOGIN_CACHE is not None:
        ts, ok = _LOGIN_CACHE
        if time.monotonic() - ts < _LOGIN_CACHE_TTL:
            return ok
    if not playwright_ready():
        return False
    ok = False
    try:
        with _minimax_pw_session(headless=True) as (page, _ctx):
            try:
                page.goto(
                    MINIMAX_ORG_LIST_URL,
                    wait_until="domcontentloaded",
                    timeout=int(timeout_sec * 1000),
                )
            except Exception:
                pass
            _settle(page, 0.6)
            state = _page_state(page)
            if state == "unknown":
                time.sleep(0.6)
                state = _page_state(page)
            ok = state == "app"
    except Exception:
        ok = False
    _LOGIN_CACHE = (time.monotonic(), ok)
    return ok


def ensure_login(
    *,
    timeout_sec: float = 420.0,
    progress: Optional[Callable[[str], None]] = None,
) -> PwResult:
    """
    Odpre vidno okno lastnega brskalnika za enkratno prijavo v Minimax.
    Čaka, da se uporabnik prijavi (potrdilo + geslo), nato shrani sejo v profil.
    """
    global _LOGIN_CACHE
    if not playwright_ready():
        return PwResult(False, "Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())

    try:
        with _minimax_pw_session(headless=False) as (page, ctx):
            try:
                page.goto(MINIMAX_ORG_LIST_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            _settle(page, 1.5)
            if _page_state(page) == "login" and _webui_credentials()[0]:
                if progress:
                    progress("Poskušam samodejno prijavo (e-pošta iz configa)…")
                if _try_webui_login(page):
                    invalidate_login_cache()
                    _LOGIN_CACHE = (time.monotonic(), True)
                    return PwResult(True, "Prijava (e-pošta) uspešna in shranjena.")

            if progress:
                progress("Prijavi se v Minimax (potrdilo + geslo) — okno je odprto…")

            deadline = time.time() + max(timeout_sec, 30.0)
            closed_by_user = False
            while time.time() < deadline:
                time.sleep(1.5)
                if not ctx.pages:
                    closed_by_user = True
                    break
                try:
                    page = ctx.pages[-1]
                except Exception:
                    closed_by_user = True
                    break
                if _page_state(page) == "app":
                    time.sleep(1.0)
                    if _page_state(page) == "app":
                        invalidate_login_cache()
                        _LOGIN_CACHE = (time.monotonic(), True)
                        return PwResult(
                            True, "Prijava shranjena. Naslednjič teče vse v ozadju."
                        )
            if closed_by_user:
                return PwResult(
                    True,
                    "Okno zaprto — če si se prijavil, je seja shranjena.",
                )
            return PwResult(
                False,
                "Prijava ni bila zaznana (časovna omejitev). Poskusi znova.",
                need_login=True,
            )
    except Exception as exc:
        return PwResult(False, str(exc)[:160], need_login=True)


def open_organisation_browser(
    org_id: str,
    *,
    org_name: str = "",
    hold_until_user_closes: bool = True,
) -> PwResult:
    """Odpre vidni skupni Playwright profil in izbere poljubno Minimax organizacijo."""
    org = str(org_id or "").strip()
    name = str(org_name or "").strip()
    if not org.isdigit():
        return PwResult(False, "Manjka veljaven Org_ID podjetja.")
    if not playwright_ready():
        return PwResult(False, "Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())

    try:
        with _minimax_pw_session(headless=False) as (page, ctx):
            _goto_webui(page, MINIMAX_ORG_SELECT_URL, wait_sec=1.2)
            if _is_login_page(page):
                return PwResult(
                    False,
                    "Skupni Playwright profil še ni prijavljen v Minimax.",
                    need_login=True,
                )
            if not _switch_org_via_list(page, org, name, wait_sec=4.0):
                return PwResult(
                    False,
                    f"Podjetja {name or org} (Org_ID {org}) ni bilo mogoče izbrati na strani Moje organizacije.",
                )
            _go_minimax_dashboard(page, wait_sec=2.0)
            if not _org_session_ok(page):
                return PwResult(False, f"Minimax seje ni bilo mogoče potrditi za Org_ID {org}.")
            result = PwResult(True, f"Odprto podjetje: {name or org} (Org_ID {org}).")
            if hold_until_user_closes:
                _wait_browser_user_close(ctx)
            return result
    except Exception as exc:
        return PwResult(False, str(exc)[:300])


def diagnose_organisation_selector(
    org_id: str,
    *,
    org_name: str = "",
    output_path: str | Path,
) -> PwResult:
    """Shrani varen JSON pregled izbirnika organizacij brez piškotkov in žetonov."""
    org = str(org_id or "").strip()
    name = str(org_name or "").strip()
    target = Path(output_path)
    if not org.isdigit():
        return PwResult(False, "Manjka veljaven Org_ID podjetja.")
    if not playwright_ready():
        return PwResult(False, "Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())

    diagnostic_js = """
() => {
  const clean = (value, limit = 240) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, limit);
  const selectors = [
    '[data-organizacijaid]', '[data-organisationid]', '[data-id]',
    'a.organizacija-naziv', 'table tr', 'ul li'
  ];
  const seen = new Set();
  const rows = [];
  for (const el of document.querySelectorAll(selectors.join(','))) {
    if (!el.offsetParent) continue;
    const text = clean(el.innerText || el.textContent || '');
    if (!text || text.length < 2) continue;
    const orgId = clean(
      el.getAttribute('data-organizacijaid') ||
      el.getAttribute('data-organisationid') ||
      el.getAttribute('data-id') || '',
      40
    );
    const key = `${el.tagName}|${orgId}|${text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({
      tag: clean(el.tagName, 20),
      organisation_id: orgId,
      text,
      class_name: clean(el.className, 120)
    });
    if (rows.length >= 200) break;
  }
  return rows;
}
"""
    try:
        with _minimax_pw_session(headless=True) as (page, _ctx):
            _goto_webui(page, MINIMAX_ORG_SELECT_URL, wait_sec=1.2)
            if _is_login_page(page):
                return PwResult(
                    False,
                    "Skupni Playwright profil še ni prijavljen v Minimax.",
                    need_login=True,
                )
            if _org_list_count(page) == 0:
                _goto_org_list(page, wait_sec=5.0)
            _fill_org_list_filter(page, name, org_id=org, wait_sec=2.0)
            rows = page.evaluate(diagnostic_js) or []
            payload = {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "target": {"name": name, "organisation_id": org},
                "page": "ZacetekOrganizacije.aspx",
                "profile": str(playwright_profile_dir()),
                "contains_cookies": False,
                "contains_passwords": False,
                "visible_candidates": rows,
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return PwResult(
                True,
                f"Varen diagnostični zapis je shranjen: {target}",
                export_path=str(target),
            )
    except Exception as exc:
        return PwResult(False, str(exc)[:300])


def _recv_checkbox_on_page(page) -> str:
    return _eval_frames(
        page,
        _js_recv_invoice_checkbox_state(),
        ok_prefixes=("checked", "unchecked", "missing"),
    )


def _set_recv_checkbox_on_page(page, enable: bool) -> str:
    return _eval_frames(
        page,
        _js_set_recv_invoice_checkbox(enable),
        ok_prefixes=("turned_on", "already_on", "turned_off", "already_off", "missing", "click_fail"),
    )


def _enable_recv_checkbox_on_page(page) -> str:
    """Vklopi kljukico «Prejemanje računov od te stranke» (z več poskusi)."""
    ok_prefixes = ("turned_on", "already_on", "missing", "click_fail")
    res = _eval_frames(page, _js_enable_recv_from_customer_checkbox(), ok_prefixes=ok_prefixes)
    if res in ("turned_on", "already_on"):
        return res
    _settle(page, 0.4)
    res = _set_recv_checkbox_on_page(page, True)
    if res in ("turned_on", "already_on"):
        return res
    _settle(page, 0.4)
    return _eval_frames(page, _js_enable_recv_from_customer_checkbox(), ok_prefixes=ok_prefixes) or res


def _parse_transfer_enable_result(enable_res: str) -> tuple[bool, bool]:
    """Vrne (prejem_ok, pošiljanje_ok) iz rezultata _js_enable_direct_transfer_checkboxes."""
    parts = str(enable_res or "").split("+")
    ok_vals = {"turned_on", "already_on"}

    def _part_ok(idx: int) -> bool:
        if idx >= len(parts):
            return False
        return parts[idx].strip() in ok_vals

    return _part_ok(0), _part_ok(1)


def _click_uredi_on_page(page, *, tries: int = 5) -> bool:
    for _ in range(max(1, tries)):
        _settle(page, 0.7)
        if _eval_frames(page, _js_click_uredi(), ok_prefixes=("uredi",)) == "uredi":
            return True
        time.sleep(0.5)
    return False


def _goto_webui(page, url: str, *, wait_sec: float = 1.0) -> None:
    """En sam page.goto (WebUI klasično)."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    _settle(page, wait_sec)


def _quick_recv_three_steps(
    page,
    *,
    org_id: str,
    org_name: str,
    st_id: str,
) -> tuple[bool, str]:
    """
    Natanko 3 odprtja strani (ročni postopek):
      1. Zacetek.aspx
      2. ZacetekOrganizacije.aspx (+ postback klik firme)
      3. StrankaEdit.aspx?st_id=…&pgat=pgate
    """
    org = str(org_id or "").strip()
    name = str(org_name or "").strip()
    sid = str(st_id or "").strip()
    if not org.isdigit():
        return False, "manjka Org_ID"
    if not sid.isdigit():
        return False, "manjka st_id"

    _goto_webui(page, MINIMAX_ZACETEK_URL, wait_sec=1.0)
    if _is_login_page(page):
        return False, "login"

    _goto_webui(page, MINIMAX_ORG_SELECT_URL, wait_sec=1.2)
    if _is_login_page(page):
        return False, "login"

    ok_states = ("id", "name", "name_row", "name_part")
    res = "not_found"
    for term_name, term_id in ((name, ""), ("", org)):
        if not term_name and not term_id:
            continue
        _fill_org_list_filter(page, term_name, org_id=term_id, wait_sec=2.0)
        res = _try_org_click_on_page(page, org, name, wait_sec=3.0)
        if res in ok_states:
            break
    if res not in ok_states:
        return False, f"firma ni najdena ({res})"

    _settle(page, 1.5)
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if _eval(page, _js_has_system_error()) == "error":
            return False, "sistemska napaka po preklopu"
        if _org_session_ok(page):
            break
        time.sleep(0.4)
    if not _org_session_ok(page):
        return False, "seja ni na firmi po preklopu"

    _goto_webui(page, minimax_stranka_edit_url(sid), wait_sec=1.2)
    if _eval(page, _js_has_system_error()) == "error":
        return False, "sistemska napaka StrankaEdit"
    if _recv_checkbox_on_page(page) == "missing":
        return False, "checkbox prejema ni najden"
    return True, f"Zacetek → Organizacije → StrankaEdit st_id={sid}"


def _try_open_stranka_edit_direct(page, st_id: str) -> tuple[bool, str]:
    """Odpri StrankaEdit.aspx?st_id=… — hitreje kot SPA šifrant."""
    sid = str(st_id or "").strip()
    if not sid.isdigit():
        return False, "manjka st_id"
    edit_url = minimax_stranka_edit_url(sid)
    try:
        page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        return False, f"goto: {exc}"
    _settle(page, 1.2)
    if _eval(page, _js_has_system_error()) == "error":
        return False, "sistemska napaka"
    chk = _recv_checkbox_on_page(page)
    if chk == "missing":
        return False, "checkbox prejema ni najden"
    return True, f"StrankaEdit st_id={sid}"


def _open_quick_recv_via_spa(
    page,
    *,
    org: str,
    name: str,
    tax: str,
) -> str:
    """Šifrant strank (SPA) → Quick (davčna) → Uredi. Vrne detail prefix."""
    cust_url = minimax_customers_spa_url(org)
    try:
        page.goto(cust_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    _settle(page, 1.5)
    if _eval(page, _js_has_system_error()) == "error":
        _eval(page, _js_navigate_stranke_sifrant())
        _settle(page, 1.2)

    search_res = _eval(page, _js_search_customer_tax(tax))
    if search_res.startswith("filled"):
        time.sleep(2.0)
    open_res = _eval(page, _js_open_customer_by_tax(tax, "quick"))
    if open_res == "not_found":
        open_res = _eval(page, _js_open_customer_by_tax(tax, "quick m.b."))
    if open_res == "not_found":
        open_res = _eval(page, _js_open_customer_by_tax(tax, name[:20]))
    _settle(page, 1.5)

    detail = f"Org {org} · šifrant → Quick ({tax})"
    if open_res == "not_found":
        detail += " — vrstica ni najdena"
    else:
        detail += f" — odprto ({open_res})"

    uredi_ok = _click_uredi_on_page(page)
    _settle(page, 1.0)
    if uredi_ok:
        detail += " · Uredi ✓"
    else:
        detail += " · Uredi — ročno"
    return detail


def _process_quick_recv_on_page(
    page,
    *,
    client_org: str,
    client_name: str,
    quick_tax: str,
    auto_toggle: bool,
    auto_save: bool = True,
    quick_supplier_st_id: int | str | None = None,
) -> PwResult:
    """3 koraki: Zacetek → ZacetekOrganizacije → StrankaEdit (st_id) → prejem → Shrani."""
    org = str(client_org or "").strip()
    name = str(client_name or "").strip()
    tax = str(quick_tax or "").strip()
    if not org.isdigit():
        return PwResult(False, "Manjka Org_ID stranke.")
    if not tax:
        return PwResult(False, "Manjka davčna Quick MB.")

    try:
        page.bring_to_front()
    except Exception:
        pass

    st_id = str(quick_supplier_st_id or "").strip()
    if not st_id.isdigit():
        try:
            from kirkpr_minimax_pw.pr_einvoice_setup import resolve_quick_supplier_st_id  # type: ignore

            resolved = resolve_quick_supplier_st_id(org, tax)
            if resolved:
                st_id = str(resolved)
        except Exception:
            resolved = None
    if not st_id.isdigit():
        return PwResult(
            False,
            f"Manjka st_id (Quick v šifrantu org {org}). "
            "Dodaj v SQL / ročni seznam ali preveri API.",
        )

    opened, open_msg = _quick_recv_three_steps(
        page,
        org_id=org,
        org_name=name,
        st_id=st_id,
    )
    if not opened:
        if open_msg == "login":
            return PwResult(False, "Potrebna prijava v lasten brskalnik.", need_login=True)
        return PwResult(False, f"3 koraki niso uspeli: {open_msg}")
    detail = f"Org {org} · {open_msg}"

    if auto_toggle:
        _settle(page, 0.5)
        uncheck_res = _eval_frames(page, _js_uncheck_einvoice_blocking_options())
        detail += f"; odkljukaj blok: {uncheck_res or '?'}"
        _settle(page, 0.4)
        recv_res = _enable_recv_checkbox_on_page(page)
        detail += f"; prejem: {recv_res}"
        recv_ok = recv_res in ("turned_on", "already_on")
        send_res = _eval_frames(
            page,
            _js_enable_send_to_customer_checkbox(),
            ok_prefixes=("turned_on", "already_on", "missing", "click_fail"),
        )
        detail += f"; pošiljanje: {send_res or '?'}"
        send_ok = send_res in ("turned_on", "already_on")
        chk = _recv_checkbox_on_page(page)
        if not recv_ok:
            if chk == "checked":
                recv_ok = True
                detail += "; prejem preverjen"
            else:
                detail += f"; prejem stanje: {chk}"
        changed = (
            "turned_off" in str(uncheck_res or "")
            or recv_res == "turned_on"
            or send_res == "turned_on"
            or chk == "unchecked"
        )
        if auto_save and (changed or not recv_ok):
            _settle(page, 0.6)
            save_res = _eval_frames(page, _js_click_shrani_customer(), ok_prefixes=("shrani",))
            detail += f"; Shrani: {save_res}"
            saved = save_res == "shrani"
            if saved:
                _settle(page, 1.0)
                chk = _recv_checkbox_on_page(page)
                if chk == "checked":
                    recv_ok = True
                elif chk == "unchecked":
                    recv_ok = False
        elif recv_ok and send_ok:
            detail += "; prenos že vključen"
        recv_ok = recv_ok or _recv_checkbox_on_page(page) == "checked"
        return PwResult(True, detail, recv_checked=recv_ok)

    chk = _recv_checkbox_on_page(page)
    if chk == "checked":
        detail += "; prejem že vključen"
    elif chk == "unchecked":
        detail += "; označi «Prejemanje računov od te stranke»"
    else:
        detail += "; checkbox prejema ni najden"
    recv_ok = chk == "checked"
    return PwResult(True, detail, recv_checked=recv_ok)


def _sync_quick_recv_api(
    client_id: int | None,
    *,
    org_id: str,
    playwright_detail: str,
    recv_checked: bool,
) -> tuple[bool, str]:
    """Po Shrani: Minimax API → SQL evidence."""
    if not client_id or not recv_checked:
        return recv_checked, playwright_detail
    try:
        from kirkpr_minimax_pw.pr_einvoice_setup import sync_quick_recv_after_playwright  # type: ignore

        _, _, sync_msg = sync_quick_recv_after_playwright(
            [int(client_id)],
            org_id=org_id,
            playwright_detail=playwright_detail,
        )
        return True, f"{playwright_detail}; {sync_msg}"
    except Exception as exc:
        return recv_checked, f"{playwright_detail}; API sync napaka: {exc}"[:300]


def open_client_quick_recv_browser(
    *,
    client_org: str,
    client_name: str = "",
    quick_tax: str,
    auto_toggle: bool = False,
    auto_save: bool = True,
    hold_until_user_closes: bool = True,
    headless: bool = False,
    quick_supplier_st_id: int | str | None = None,
    client_id: int | None = None,
    org_id: str = "",
    sync_api_after_save: bool = True,
) -> PwResult:
    """
    V lastnem brskalniku: org stranke → StrankaEdit (st_id) → prenos → Shrani → API sync.
    """
    if not playwright_ready():
        return PwResult(False, "Playwright/Chromium ni nameščen.\n\n" + playwright_setup_hint())

    try:
        with _minimax_pw_session(
            headless=headless,
            hold_until_user_closes=False,
        ) as (page, ctx):
            res = _process_quick_recv_on_page(
                page,
                client_org=client_org,
                client_name=client_name,
                quick_tax=quick_tax,
                auto_toggle=auto_toggle,
                auto_save=auto_save,
                quick_supplier_st_id=quick_supplier_st_id,
            )
            if sync_api_after_save and auto_toggle and res.ok and res.recv_checked:
                recv_ok, msg = _sync_quick_recv_api(
                    client_id,
                    org_id=org_id,
                    playwright_detail=res.message,
                    recv_checked=res.recv_checked,
                )
                res = PwResult(
                    res.ok,
                    msg,
                    need_login=res.need_login,
                    method=res.method,
                    confirmed=res.confirmed,
                    export_path=res.export_path,
                    recv_checked=recv_ok,
                )
            if hold_until_user_closes and not headless:
                final_chk = _wait_browser_user_close(
                    ctx,
                    page=page,
                    poll_recv_checkbox=True,
                )
                recv_ok = final_chk == "checked" or res.recv_checked
                if recv_ok and not res.recv_checked:
                    res = PwResult(
                        res.ok,
                        f"{res.message}; prejem ✓ (ob zaprtju brskalnika)",
                        need_login=res.need_login,
                        method=res.method,
                        confirmed=res.confirmed,
                        export_path=res.export_path,
                        recv_checked=True,
                    )
                elif recv_ok:
                    res = PwResult(
                        res.ok,
                        res.message,
                        need_login=res.need_login,
                        method=res.method,
                        confirmed=res.confirmed,
                        export_path=res.export_path,
                        recv_checked=True,
                    )
            return res
    except Exception as exc:
        msg = str(exc)
        if "ProcessSingleton" in msg or "SingletonLock" in msg:
            msg = "Profil brskalnika je zaseden — zapri druga okna."
        return PwResult(False, msg[:300])


def open_client_quick_recv_batch(
    items: list,
    *,
    auto_toggle: bool = False,
    auto_save: bool = True,
    hold_until_user_closes: bool = True,
    headless: bool = False,
    org_id: str = "",
    sync_api_after_save: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> list:
    """items: dict z client_org, client_name, quick_tax."""
    out: list = []
    if not items:
        return out
    if not playwright_ready():
        r = PwResult(False, playwright_setup_hint())
        return [(it, r) for it in items]

    def _emit(t: str) -> None:
        if progress:
            try:
                progress(t)
            except Exception:
                pass

    from playwright.sync_api import sync_playwright

    profile = str(playwright_profile_dir())
    total = len(items)
    try:
        with _PW_LOCK:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    profile,
                    headless=headless,
                    args=_launch_args(headless=headless),
                    accept_downloads=False,
                    no_viewport=(not headless),
                )
                try:
                    ctx.set_default_timeout(20000)
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    for idx, it in enumerate(items, 1):
                        org = str(it.get("client_org") or "").strip()
                        name = str(it.get("client_name") or "").strip()
                        tax = str(it.get("quick_tax") or "").strip()
                        st_id = it.get("quick_supplier_st_id") or 0
                        label = name or org or "?"
                        _emit(f"[{idx}/{total}] {label}: Quick prejem …")
                        try:
                            res = _process_quick_recv_on_page(
                                page,
                                client_org=org,
                                client_name=name,
                                quick_tax=tax,
                                auto_toggle=auto_toggle,
                                auto_save=auto_save,
                                quick_supplier_st_id=st_id,
                            )
                            cid = int(it.get("client_id") or 0)
                            if (
                                sync_api_after_save
                                and auto_toggle
                                and res.ok
                                and res.recv_checked
                                and cid
                            ):
                                recv_ok, msg = _sync_quick_recv_api(
                                    cid,
                                    org_id=org_id,
                                    playwright_detail=res.message,
                                    recv_checked=res.recv_checked,
                                )
                                res = PwResult(
                                    res.ok,
                                    msg,
                                    need_login=res.need_login,
                                    method=res.method,
                                    confirmed=res.confirmed,
                                    export_path=res.export_path,
                                    recv_checked=recv_ok,
                                )
                        except Exception as exc:
                            res = PwResult(False, str(exc)[:200])
                        out.append((it, res))
                        _emit(f"[{idx}/{total}] {label}: {res.message}")
                        if hold_until_user_closes and not headless:
                            _emit("Zapri brskalnik po Shrani — nadaljujem z naslednjo stranko …")
                            _wait_browser_user_close(ctx, page=page, poll_recv_checkbox=True)
                            page = ctx.pages[0] if ctx.pages else ctx.new_page()
                finally:
                    if hold_until_user_closes and not headless:
                        _wait_browser_user_close(ctx, emit=_emit)
                    _safe_close_playwright_context(ctx)
    except Exception as exc:
        msg = str(exc)[:300]
        done = {id(it) for it, _ in out}
        for it in items:
            if id(it) not in done:
                out.append((it, PwResult(False, msg)))
    return out
