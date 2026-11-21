"""IBAN plačnika iz Evidence firm / AJPES (eRTR)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

EVIDENCA_FIRM_ROOT = Path(r"D:\PISARNA\Python\EvidencaFirm")


@dataclass(frozen=True)
class PayerIbanLookup:
    ibans: list[str]
    selected: str
    source: str
    detail: str = ""
    ajpes_id: str = ""


def _ensure_evidenca_path() -> Path:
    root = EVIDENCA_FIRM_ROOT
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def company_ajpes_id(record: Mapping[str, Any] | None) -> str:
    if not record:
        return ""
    for key in ("AJPES sifra", "AjpesSifra", "AJPES", "ajpes_id", "entity_id"):
        digits = re.sub(r"\D", "", str(record.get(key) or ""))
        if digits:
            return digits
    return ""


def _normalize_si_iban(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).upper()
    if re.fullmatch(r"SI\d{17}", text):
        return text
    return ""


def _convert_trr_to_iban(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    direct = _normalize_si_iban(text)
    if direct:
        return direct
    try:
        _ensure_evidenca_path()
        from trr_store import try_convert_durs_trr_to_iban

        return _normalize_si_iban(try_convert_durs_trr_to_iban(text)) or ""
    except Exception:
        return ""


def _ibans_from_evidence_field(record: Mapping[str, Any] | None) -> list[str]:
    if not record:
        return []
    raw = ""
    for key, value in record.items():
        key_l = str(key).casefold()
        if "ransakcijski" in key_l or key_l in {"iban", "trr", "bančni račun", "bancni racun"}:
            raw = str(value or "").strip()
            if raw:
                break
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    try:
        _ensure_evidenca_path()
        from trr_store import split_iban_list

        parts = split_iban_list(raw)
    except Exception:
        parts = re.split(r"[;,|\n]+", raw)
    for part in parts:
        iban = _normalize_si_iban(part) or _convert_trr_to_iban(part)
        if iban and iban not in seen:
            seen.add(iban)
            out.append(iban)
    if not out:
        iban = _convert_trr_to_iban(raw)
        if iban:
            out.append(iban)
    return out


def _ibans_from_trr_store(tax_number: str) -> tuple[list[str], str]:
    tax = re.sub(r"\D", "", tax_number or "")
    if len(tax) < 8:
        return [], ""
    try:
        _ensure_evidenca_path()
        from trr_store import iban_list_for_davcna, selected_iban_for_davcna

        ibans = [_normalize_si_iban(x) for x in iban_list_for_davcna(tax)]
        ibans = [x for x in ibans if x]
        selected = _normalize_si_iban(selected_iban_for_davcna(tax)) or (ibans[0] if ibans else "")
        return ibans, selected
    except Exception:
        return [], ""


def resolve_payer_ibans(
    company: Mapping[str, Any] | None,
    *,
    tax_number: str = "",
    saved_iban: str = "",
) -> PayerIbanLookup:
    """IBAN plačnika: Evidenca firm (Transakcijski račun) je glavni vir.

    Vrstni red: 1) polje v Evidenci  2) trr_evidenca (isti sistem)  3) shranjeno.
    """
    tax = re.sub(r"\D", "", tax_number or "")
    if not tax and company:
        tax = re.sub(r"\D", "", str(company.get("DAVČNA") or company.get("DAVCNA") or ""))
    if len(tax) > 8:
        tax = tax[-8:]
    ajpes_id = company_ajpes_id(company)

    evidence = _ibans_from_evidence_field(company)
    store_ibans, store_sel = _ibans_from_trr_store(tax)

    merged: list[str] = []
    seen: set[str] = set()
    for iban in [*evidence, *store_ibans]:
        if iban and iban not in seen:
            seen.add(iban)
            merged.append(iban)

    if merged:
        # Izbrani = prvi iz Evidence; sicer izbrani v trr_evidenca.
        if evidence:
            selected = evidence[0]
            source = "Evidenca firm"
            detail = "Transakcijski račun"
        else:
            selected = store_sel if store_sel in merged else merged[0]
            source = "Evidenca firm"
            detail = "trr_evidenca"
        if selected not in merged:
            selected = merged[0]
        return PayerIbanLookup(
            ibans=merged,
            selected=selected,
            source=source,
            detail=detail,
            ajpes_id=ajpes_id,
        )

    saved = _normalize_si_iban(saved_iban) or _convert_trr_to_iban(saved_iban)
    if saved:
        return PayerIbanLookup(
            ibans=[saved],
            selected=saved,
            source="shranjeno",
            detail="ddvo_payer_iban",
            ajpes_id=ajpes_id,
        )
    return PayerIbanLookup(ibans=[], selected="", source="ni podatka", ajpes_id=ajpes_id)


def fetch_payer_ibans_from_ajpes(
    company: Mapping[str, Any] | None,
    *,
    tax_number: str = "",
) -> PayerIbanLookup:
    """Živo branje IBAN z AJPES (eRTR) po AJPES šifri / davčni / imenu."""
    _ensure_evidenca_path()
    from ajpes_company_service import company_record_from_candidate
    from ajpes_prs_lookup import lookup_ajpes
    from trr_store import normalize_iban, upsert_trr_accounts

    company = dict(company or {})
    tax = re.sub(r"\D", "", tax_number or str(company.get("DAVČNA") or ""))
    if len(tax) > 8:
        tax = tax[-8:]
    name = str(company.get("Kratko ime") or company.get("Dolgo") or "").strip()
    ajpes_id = company_ajpes_id(company)
    zst_raw = re.sub(r"\D", "", str(company.get("Zšt") or company.get("ZST") or "0"))
    zst = int(zst_raw) if zst_raw else 0

    lookup = lookup_ajpes(tax, name, entity_id=ajpes_id)
    candidates = list(getattr(lookup, "candidates", None) or [])
    if not candidates:
        message = str(getattr(lookup, "message", "") or "AJPES ni vrnil podjetja.")
        raise RuntimeError(message)

    # Če je več zadetkov in imamo davčno, izberi ujemajočega.
    chosen = candidates[0]
    if tax and len(candidates) > 1:
        for cand in candidates:
            cand_tax = re.sub(r"\D", "", str(getattr(cand, "davcna", "") or ""))
            if cand_tax.endswith(tax):
                chosen = cand
                break

    _record, ibans, note, _status = company_record_from_candidate(chosen, zst)
    clean = [normalize_iban(x) for x in ibans if _normalize_si_iban(x) or normalize_iban(x)]
    clean = [x for x in clean if _normalize_si_iban(x)]
    if not clean:
        raise RuntimeError(
            "AJPES ni vrnil nobenega odprtega IBAN (eRTR).\n"
            + (str(note or "").strip()[:240] if note else "")
        )

    entity = company_ajpes_id(_record) or ajpes_id
    if tax:
        try:
            upsert_trr_accounts(tax, clean, selected=clean[0], source="AJPES")
        except Exception:
            pass

    return PayerIbanLookup(
        ibans=clean,
        selected=clean[0],
        source="AJPES eRTR",
        detail=(str(note or "").strip()[:160] or f"{len(clean)} računov"),
        ajpes_id=entity,
    )


def prefer_open_ibans(ibans: Sequence[str], selected: str = "") -> tuple[list[str], str]:
    values = [_normalize_si_iban(x) for x in ibans]
    values = [x for x in values if x]
    sel = _normalize_si_iban(selected)
    if sel and sel in values:
        return values, sel
    return values, (values[0] if values else "")


__all__ = [
    "PayerIbanLookup",
    "company_ajpes_id",
    "fetch_payer_ibans_from_ajpes",
    "prefer_open_ibans",
    "resolve_payer_ibans",
]
