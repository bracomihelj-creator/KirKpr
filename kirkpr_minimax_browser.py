"""Povezava KIR/KPR z vgrajeno Minimax Playwright avtomatizacijo.

Enojni osnutek: Chrome URL + razširitev (konto/osnove iz listine).
Serija: ``confirm_pr_drafts_batch`` — Playwright, konto iz vsake listine,
ista firma brez ponovnega preklopa; Potrdi samo po A/Q.

Playwright koda je v paketu ``kirkpr_minimax_pw`` (brez Fakturiranje* map).
"""

from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse


@dataclass(frozen=True)
class BrowserActionResult:
    ok: bool
    message: str
    need_login: bool = False
    output_path: str = ""


@dataclass(frozen=True)
class BrowserSessionStatus:
    ready: bool
    logged_in: bool
    message: str
    profile_path: str = ""


def extract_minimax_record_id(location: str, resource: str = "") -> str:
    """Iz Location glave izlusci numericni ID ustvarjenega API zapisa."""
    text = str(location or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    query_id = (parse_qs(parsed.query).get("id") or [""])[0]
    if str(query_id).isdigit():
        return str(query_id)
    path = parsed.path.rstrip("/")
    if resource:
        match = re.search(
            rf"/{re.escape(resource)}/(\d+)(?=/|$|[?#\s•])",
            path,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
        return ""
    match = re.search(r"/(\d+)(?:/|$)", path)
    return match.group(1) if match else ""


def _plain_money(value: Any) -> str:
    """Znesek za URL (100.00); prazno, če je 0."""
    text = re.sub(r"[^\d,.\-]", "", str(value or "").strip()).replace(",", ".")
    if not text or text in {".", "-", "-."}:
        return ""
    try:
        amount = float(text)
    except ValueError:
        return ""
    if abs(amount) < 0.0000001:
        return ""
    return f"{amount:.2f}"


def received_draft_chrome_url(
    *,
    organisation_id: str,
    received_invoice_id: str,
    organisation_name: str,
    document_reference: str,
    expense_account: str,
    confirm: bool = False,
    base_22: Any = "",
    base_95: Any = "",
    base_5: Any = "",
    vat_22: Any = "",
    vat_95: Any = "",
    vat_5: Any = "",
) -> str:
    """Sestavi URL za prijavljeni Chrome in razširitev Minimax v1.3.6+.

    ``received_invoice_id`` mora biti dejanski ID iz API odgovora/Location.
    Ne računamo ga kot zadnji ID + 1, ker lahko vmes zapis ustvari drug uporabnik.
    """
    received_id = str(received_invoice_id or "").strip()
    account = re.sub(r"\D", "", str(expense_account or "4190")) or "4190"
    if not received_id.isdigit():
        raise ValueError("ReceivedInvoiceId mora biti številka, vrnjena iz Minimax API.")
    # Namerno BREZ Minimaxovih pr_id/pgat na Zacetek.aspx — sicer strežnik
    # včasih odpre PR pred preklopom firme → »Sistemska napaka«.
    params = {
        "kirkpr_pr": received_id,
        "kirkpr_konto": account,
        "kirkpr_org": re.sub(r"\D", "", str(organisation_id or "")),
        "kirkpr_org_name": str(organisation_name or "").strip(),
        "kirkpr_ref": str(document_reference or "").strip(),
        "kirkpr_confirm": "1" if confirm else "0",
    }
    for key, value in (
        ("kirkpr_osnova22", base_22),
        ("kirkpr_osnova95", base_95),
        ("kirkpr_osnova5", base_5),
        ("kirkpr_ddv22", vat_22),
        ("kirkpr_ddv95", vat_95),
        ("kirkpr_ddv5", vat_5),
    ):
        plain = _plain_money(value)
        if plain:
            params[key] = plain
    return (
        "https://moj.minimax.si/SI/VA/WebUI/Zacetek/"
        f"Zacetek.aspx?{urlencode(params)}"
    )


def open_received_draft_in_chrome(
    *,
    organisation_id: str,
    received_invoice_id: str,
    organisation_name: str,
    document_reference: str,
    expense_account: str,
    confirm: bool = False,
    base_22: Any = "",
    base_95: Any = "",
    base_5: Any = "",
    vat_22: Any = "",
    vat_95: Any = "",
    vat_5: Any = "",
) -> BrowserActionResult:
    """Odpre začetno stran v Chromu; razširitev izbere podjetje in nato PR."""
    try:
        url = received_draft_chrome_url(
            organisation_id=organisation_id,
            received_invoice_id=received_invoice_id,
            organisation_name=organisation_name,
            document_reference=document_reference,
            expense_account=expense_account,
            confirm=confirm,
            base_22=base_22,
            base_95=base_95,
            base_5=base_5,
            vat_22=vat_22,
            vat_95=vat_95,
            vat_5=vat_5,
        )
        # new=0: poskusi uporabiti obstoječe okno; razširitev v1.3.5+ nato
        # po možnosti zapre sprožilni zavihek in nadaljuje v že odprtem podjetju.
        if not webbrowser.open(url, new=0, autoraise=True):
            return BrowserActionResult(False, "Privzetega brskalnika ni bilo mogoče odpreti.")
        action = "vnos in potrditev" if confirm else "vnos brez končne potrditve"
        bases = []
        if _plain_money(base_22):
            bases.append("osnova 22%")
        if _plain_money(base_95):
            bases.append("osnova 9,5%")
        if _plain_money(base_5):
            bases.append("osnova 5%")
        bases_txt = (", " + ", ".join(bases)) if bases else ""
        return BrowserActionResult(
            True,
            (
                f"PR {document_reference or received_invoice_id} je poslan v prijavljeni Chrome "
                f"({action}, konto {expense_account or '4190'}{bases_txt}). "
                "Razširitev Minimax v1.3.6+ vnese konto/osnove in prikaže paketek za kopiranje."
            ),
        )
    except Exception as exc:
        return BrowserActionResult(False, str(exc))


def _load_playwright_module() -> Any:
    """Vgrajen paket kirkpr_minimax_pw (brez zunanjih Fakturiranje* map)."""
    from kirkpr_minimax_pw import minimax_playwright as module

    return module


def automation_ready() -> tuple[bool, str]:
    try:
        module = _load_playwright_module()
        if not module.playwright_ready():
            return False, str(module.playwright_setup_hint())
    except Exception as exc:
        return False, str(exc)
    return True, "Playwright in Chromium sta pripravljena."


def shared_profile_path() -> str:
    try:
        return str(_load_playwright_module().playwright_profile_dir())
    except Exception:
        return ""


def check_session() -> BrowserSessionStatus:
    """Preveri skupno prijavo brez branja ali izvažanja piškotkov."""
    try:
        module = _load_playwright_module()
        profile = str(module.playwright_profile_dir())
        if not module.playwright_ready():
            return BrowserSessionStatus(False, False, str(module.playwright_setup_hint()), profile)
        logged_in = bool(module.playwright_logged_in(timeout_sec=20.0, use_cache=False))
        message = (
            "Skupna Playwright seja je prijavljena in uporabna za vsa dostopna podjetja."
            if logged_in
            else "Skupni Playwright profil še ni prijavljen ali pa je seja potekla."
        )
        return BrowserSessionStatus(True, logged_in, message, profile)
    except Exception as exc:
        return BrowserSessionStatus(False, False, str(exc), "")


def ensure_minimax_login(
    progress: Callable[[str], None] | None = None,
) -> BrowserActionResult:
    """Odpre vidno prijavo in sejo shrani v obstojeci Playwright profil."""
    try:
        module = _load_playwright_module()
        result = module.ensure_login(timeout_sec=420.0, progress=progress)
        return BrowserActionResult(
            bool(result.ok),
            str(result.message or ""),
            bool(getattr(result, "need_login", False)),
        )
    except Exception as exc:
        return BrowserActionResult(False, str(exc))


def open_organisation(
    *,
    organisation_id: str,
    organisation_name: str,
) -> BrowserActionResult:
    """V skupnem profilu odpre izbrano podjetje in pusti brskalnik uporabniku."""
    try:
        module = _load_playwright_module()
        result = module.open_organisation_browser(
            str(organisation_id or "").strip(),
            org_name=str(organisation_name or "").strip(),
            hold_until_user_closes=True,
        )
        return BrowserActionResult(
            bool(result.ok),
            str(result.message or ""),
            bool(getattr(result, "need_login", False)),
            str(getattr(result, "export_path", "") or ""),
        )
    except Exception as exc:
        return BrowserActionResult(False, str(exc))


def save_organisation_diagnostic(
    *,
    organisation_id: str,
    organisation_name: str,
    output_path: str | Path,
) -> BrowserActionResult:
    """Shrani očiščen izpis izbirnika; brez cookies, gesel in skritih polj."""
    try:
        module = _load_playwright_module()
        result = module.diagnose_organisation_selector(
            str(organisation_id or "").strip(),
            org_name=str(organisation_name or "").strip(),
            output_path=Path(output_path),
        )
        return BrowserActionResult(
            bool(result.ok),
            str(result.message or ""),
            bool(getattr(result, "need_login", False)),
            str(getattr(result, "export_path", "") or ""),
        )
    except Exception as exc:
        return BrowserActionResult(False, str(exc))


def open_received_draft_with_expense(
    *,
    organisation_id: str,
    received_invoice_id: str,
    organisation_name: str,
    document_reference: str,
    expense_account: str,
    base_22: Any = "",
    base_95: Any = "",
    base_5: Any = "",
    confirm: bool = False,
) -> BrowserActionResult:
    """Odpre PR, klikne Uredi, doda odhodek (konto iz listine) in po želji Potrdi."""
    if not str(received_invoice_id or "").isdigit():
        return BrowserActionResult(False, "Iz odgovora API ni bilo mogoce dolociti ID prejetega racuna.")
    try:
        module = _load_playwright_module()
        if not module.playwright_ready():
            return BrowserActionResult(False, str(module.playwright_setup_hint()))
        result = module.open_confirm_received_draft(
            str(organisation_id or "").strip(),
            str(received_invoice_id),
            org_name=str(organisation_name or "").strip(),
            document_reference=str(document_reference or "").strip(),
            auto_expense=True,
            auto_confirm=bool(confirm),
            expense_account=str(expense_account or "").strip() or "4190",
            base_22=_plain_money(base_22),
            base_95=_plain_money(base_95),
            base_5=_plain_money(base_5),
            headless=bool(confirm),
            hold_until_user_closes=not bool(confirm),
        )
        return BrowserActionResult(
            bool(result.ok),
            str(result.message or ""),
            bool(getattr(result, "need_login", False)),
        )
    except Exception as exc:
        return BrowserActionResult(False, str(exc))


def detect_minimax_firm_cdp() -> dict[str, Any]:
    """Zazna firmo v že odprtem Minimax Chromu (CDP :9222)."""
    try:
        import kirkpr_minimax_cdp_batch as cdp_batch

        return cdp_batch.detect_open_minimax_firm()
    except Exception as exc:
        return {"ok": False, "message": str(exc), "org_name": "", "port": 0}


def open_minimax_chrome_cdp(url: str = "") -> BrowserActionResult:
    """Odpre Minimax v Chrome s CDP (ločeni profil) — za serijo na že prijavljeni seji."""
    try:
        import kirkpr_minimax_cdp_batch as cdp_batch

        target = (url or "").strip() or cdp_batch.MINIMAX_PREJET_LIST
        ok, msg = cdp_batch.launch_chrome_cdp_minimax(target)
        return BrowserActionResult(ok, msg)
    except Exception as exc:
        return BrowserActionResult(False, str(exc))


def confirm_pr_drafts_batch_extension(
    items: list[dict[str, Any]],
    *,
    auto_confirm: bool = True,
    progress: Callable[[str], None] | None = None,
    pause_sec: float = 2.2,
) -> list[dict[str, Any]]:
    """Serija v ŽE ODPRTEM Chromu (razširitev Minimax) — brez nove prijave / profila.

    Odpre ``Zacetek.aspx?kirkpr_*`` z new=0 (isti brskalnik). Razširitev v1.3.7+
    preklopi firmo le po potrebi, nato Uredi → Nov odhodek → konto/osnove → Potrdi.
    """
    import time

    out: list[dict[str, Any]] = []
    total = len(items or [])
    for idx, it in enumerate(items or [], 1):
        ref = str(it.get("document_reference") or "")
        acct = str(it.get("expense_account") or "").strip() or "4190"
        rid = str(it.get("received_invoice_id") or "").strip()
        if progress:
            progress(f"[Chrome {idx}/{total}] {ref} konto {acct}…")
        if not rid.isdigit():
            out.append(
                {
                    "ok": False,
                    "confirmed": False,
                    "message": "Manjka ReceivedInvoiceId",
                    "ref": ref,
                    "expense_account": acct,
                    "method": "extension",
                    "ref_key": it.get("ref_key"),
                }
            )
            continue
        result = open_received_draft_in_chrome(
            organisation_id=str(it.get("org_id") or ""),
            received_invoice_id=rid,
            organisation_name=str(it.get("org_name") or ""),
            document_reference=ref,
            expense_account=acct,
            confirm=bool(auto_confirm),
            base_22=it.get("base_22"),
            base_95=it.get("base_95"),
            base_5=it.get("base_5"),
        )
        out.append(
            {
                "ok": bool(result.ok),
                "confirmed": bool(auto_confirm and result.ok),
                "need_login": bool(result.need_login),
                "message": str(result.message or ""),
                "ref": ref,
                "received_invoice_id": rid,
                "expense_account": acct,
                "ref_key": it.get("ref_key"),
                "method": "extension",
            }
        )
        if idx < total:
            time.sleep(max(0.8, float(pause_sec or 2.2)))
    return out


def confirm_pr_drafts_batch(
    items: list[dict[str, Any]],
    *,
    auto_confirm: bool = True,
    headless: bool = True,
    progress: Callable[[str], None] | None = None,
    prefer_cdp: bool = True,
    prefer_extension: bool = True,
    expected_org_name: str = "",
    expected_org_id: str = "",
) -> list[dict[str, Any]]:
    """Serija PR: 1) CDP če :9222 že teče  2) sicer razširitev v obstoječem Chromu.

    Nikoli ne odpira novega CDP profila / nove prijave.
    """
    _ = headless  # PW ni primarni motor za serijo
    if prefer_cdp:
        try:
            import kirkpr_minimax_cdp_batch as cdp_batch

            if cdp_batch.find_open_debug_port():
                if progress:
                    progress("CDP: uporabljam že odprt Chrome / Minimax…")
                return cdp_batch.confirm_pr_drafts_batch_cdp(
                    items,
                    auto_confirm=auto_confirm,
                    progress=progress,
                    expected_org_name=expected_org_name,
                    expected_org_id=expected_org_id,
                )
        except Exception as exc:
            if progress:
                progress(f"CDP ni na voljo ({exc}) — razširitev v obstoječem Chromu…")

    if prefer_extension:
        if progress:
            progress("Chrome razširitev: obstoječi zavihek (brez nove prijave)…")
        return confirm_pr_drafts_batch_extension(
            items,
            auto_confirm=auto_confirm,
            progress=progress,
        )

    return [
        {
            "ok": False,
            "confirmed": False,
            "message": "Ni CDP in razširitev je izklopljena.",
            "ref": str(it.get("document_reference") or ""),
            "method": "none",
        }
        for it in items
    ]
