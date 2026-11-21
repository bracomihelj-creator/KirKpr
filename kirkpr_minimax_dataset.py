"""Pretvorba Minimax API (računi ali temeljnice IR/PR) → KirkprDataset."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

import kirkpr_minimax_core as core
import minimax_api_client as minimax_api

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO
    try:
        return Decimal(str(value).replace(",", ".")).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return ZERO


def _iso(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback[:10] if fallback else ""
    return text[:10]


def _country_from_tax(tax_id: str) -> str:
    text = re.sub(r"\s+", "", str(tax_id or "")).upper()
    if len(text) >= 2 and text[:2].isalpha():
        return text[:2]
    return "SI"


def _tax_digits(tax_id: str) -> str:
    text = re.sub(r"\s+", "", str(tax_id or "")).upper()
    if text.startswith("SI") and len(text) > 2:
        text = text[2:]
    return re.sub(r"\D", "", text)


def _obdobje_code(day: str) -> str:
    try:
        d = date.fromisoformat(day[:10])
    except ValueError:
        d = date.today()
    return f"{d.month:02d}{d.month:02d}"


def _party_name(node: Any) -> str:
    if isinstance(node, Mapping):
        for key in ("Name", "name", "Title", "Code"):
            value = str(node.get(key) or "").strip()
            if value:
                return value
    return ""


def _account_code(node: Any) -> str:
    if not isinstance(node, Mapping):
        return ""
    name = str(node.get("Name") or node.get("Code") or "").strip()
    match = re.match(r"^(\d+)\b", name)
    return match.group(1) if match else ""


def _vat_rate_code(row: Mapping[str, Any]) -> str:
    """Minimax SI: S=22%, Z=9,5%, 0=5%, O=oproščeno, N=neobdavčeno."""
    rate = row.get("VatRate") if isinstance(row.get("VatRate"), Mapping) else {}
    name = str(rate.get("Name") or rate.get("Code") or "S").strip().upper()
    if name == "O" or name.startswith("OP"):
        return "O"
    head = name[:1]
    if head in {"S", "Z", "N"}:
        return head
    if head == "0" or name.startswith("5"):
        return "5"
    return "S"


def _vat_row_totals(rows: Sequence[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Seštevek osnov/DDV po stopnji; loči odbitni / neodbitni del."""
    codes = ("S", "Z", "5", "O", "N")
    ded_base = {c: ZERO for c in codes}
    ded_vat = {c: ZERO for c in codes}
    nd_base = {c: ZERO for c in codes}
    nd_vat = {c: ZERO for c in codes}
    services_base = ZERO
    goods_base = ZERO
    services_vat = ZERO
    goods_vat = ZERO
    for row in rows:
        code = _vat_rate_code(row)
        db = _money(row.get("VatBase")) + _money(row.get("ServicesVatBase"))
        dv = _money(row.get("Vat")) + _money(row.get("ServicesVat"))
        nb = _money(row.get("NonDeductibleVatBase")) + _money(
            row.get("ServicesNonDeductibleVatBase")
        )
        nv = _money(row.get("NonDeductibleVat")) + _money(row.get("ServicesNonDeductibleVat"))
        ded_base[code] += db
        ded_vat[code] += dv
        nd_base[code] += nb
        nd_vat[code] += nv
        services_base += _money(row.get("ServicesVatBase")) + _money(
            row.get("ServicesNonDeductibleVatBase")
        )
        goods_base += _money(row.get("VatBase")) + _money(row.get("NonDeductibleVatBase"))
        services_vat += _money(row.get("ServicesVat")) + _money(
            row.get("ServicesNonDeductibleVat")
        )
        goods_vat += _money(row.get("Vat")) + _money(row.get("NonDeductibleVat"))

    base_s = ded_base["S"] + nd_base["S"]
    base_z = ded_base["Z"] + nd_base["Z"]
    base_5 = ded_base["5"] + nd_base["5"]
    base_o = ded_base["O"] + nd_base["O"]
    base_n = ded_base["N"] + nd_base["N"]
    vat_s = ded_vat["S"] + nd_vat["S"]
    vat_z = ded_vat["Z"] + nd_vat["Z"]
    vat_5 = ded_vat["5"] + nd_vat["5"]
    return {
        "base_s": base_s,
        "base_z": base_z,
        "base_5": base_5,
        "base_o": base_o,
        "base_n": base_n,
        # Združljivost: base_0 / vat_0 = 5% (ne oproščeno!).
        "base_0": base_5,
        "vat_s": vat_s,
        "vat_z": vat_z,
        "vat_5": vat_5,
        "vat_0": vat_5,
        "ded_base_s": ded_base["S"],
        "ded_base_z": ded_base["Z"],
        "ded_base_5": ded_base["5"],
        "ded_vat_s": ded_vat["S"],
        "ded_vat_z": ded_vat["Z"],
        "ded_vat_5": ded_vat["5"],
        "nd_base_s": nd_base["S"],
        "nd_base_z": nd_base["Z"],
        "nd_base_5": nd_base["5"],
        "nd_vat_s": nd_vat["S"],
        "nd_vat_z": nd_vat["Z"],
        "nd_vat_5": nd_vat["5"],
        "base": base_s + base_z + base_5 + base_o + base_n,
        "vat": vat_s + vat_z + vat_5,
        "taxable_base": base_s + base_z + base_5,
        "services_base": services_base,
        "goods_base": goods_base,
        "services_vat": services_vat,
        "goods_vat": goods_vat,
    }


def journal_vat_date(journal: Mapping[str, Any], book: str) -> str:
    """Datum DDV (VatDate) — merodajen za obdobje knjige / DDV-O."""
    vat_entry = _pick_vat_entry(journal, book)
    return _iso(
        (vat_entry or {}).get("VatDate")
        or (vat_entry or {}).get("ReceivedDate")
        or (vat_entry or {}).get("DocumentDate")
        or journal.get("JournalDate")
    )


def filter_journals_by_vat_period(
    journals: Sequence[Mapping[str, Any]],
    book: str,
    date_from: str,
    date_to: str,
) -> list[Mapping[str, Any]]:
    start = str(date_from or "")[:10]
    end = str(date_to or "")[:10]
    if not start or not end:
        return list(journals)
    return [
        row
        for row in journals
        if start <= journal_vat_date(row, book) <= end
    ]


EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
    "RO", "SE", "SI", "SK",
}


def _party_country(node: Any) -> str:
    if not isinstance(node, Mapping):
        return ""
    country = node.get("Country")
    if isinstance(country, Mapping):
        code = str(country.get("Name") or country.get("Code") or "").strip().upper()
        if code:
            return code[:2]
    for key in ("CountryCode", "CountryName"):
        text = str(node.get(key) or "").strip().upper()
        if len(text) == 2 and text.isalpha():
            return text
    tax = str(node.get("VATIdentificationNumber") or node.get("VatNumber") or "").strip().upper()
    if len(tax) >= 2 and tax[:2].isalpha():
        return tax[:2]
    return ""


def _party_tax_id(node: Any) -> str:
    if not isinstance(node, Mapping):
        return ""
    for key in ("VATIdentificationNumber", "VatNumber", "TaxNumber"):
        value = str(node.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_eu_foreign(country: str) -> bool:
    code = str(country or "").strip().upper()[:2]
    return bool(code) and code in EU_COUNTRY_CODES and code != "SI"


def _is_non_eu_foreign(country: str) -> bool:
    code = str(country or "").strip().upper()[:2]
    return bool(code) and code != "SI" and code not in EU_COUNTRY_CODES


def _looks_like_eu_vat_id(tax_id: str, country: str = "") -> bool:
    """VIES-KP: samo ID za DDV s predpono EU (DE…, AT…, DK…) — brez SI, brez FO/OSS.

    Fizične osebe / OSS kupci nimajo (pravega) ID za DDV → ne spadajo v polje 12 / P10+P11.
    """
    raw = re.sub(r"\s+", "", str(tax_id or "")).upper()
    cc = str(country or "").strip().upper()[:2]
    if len(raw) < 4:
        return False
    if len(raw) >= 2 and raw[:2].isalpha():
        prefix = raw[:2]
        # GR → EL (VIES predpona za Grčijo)
        if prefix == "GR":
            prefix = "EL"
        digits = re.sub(r"\D", "", raw[2:])
        return prefix in EU_COUNTRY_CODES and prefix != "SI" and len(digits) >= 2
    # Brez predpone: samo če poznamo državo EU ≠ SI in dovolj številk — potem sestavi ID.
    digits = re.sub(r"\D", "", raw)
    if cc == "GR":
        cc = "EL"
    return bool(cc and cc != "SI" and cc in EU_COUNTRY_CODES and len(digits) >= 5)


def _normalize_eu_vat_id(tax_id: str, country: str = "") -> str:
    """Vrni ID z EU predpono (npr. DE123…) ali prazen, če ni VIES-upravičen."""
    raw = re.sub(r"\s+", "", str(tax_id or "")).upper()
    cc = str(country or "").strip().upper()[:2]
    if cc == "GR":
        cc = "EL"
    if not _looks_like_eu_vat_id(raw, cc):
        return ""
    if len(raw) >= 2 and raw[:2].isalpha():
        prefix = raw[:2]
        if prefix == "GR":
            return "EL" + raw[2:]
        return raw
    digits = re.sub(r"\D", "", raw)
    if cc and cc != "SI" and cc in EU_COUNTRY_CODES and digits:
        return f"{cc}{digits}"
    return ""


def _empty_kir(*, zapst: int, day: str, invoice: str, party: str, country: str, tax: str) -> dict[str, Any]:
    return {
        "ZAPST": zapst,
        "OBDOBJE": _obdobje_code(day),
        "P2": day,
        "P3": invoice,
        "P4": day,
        "P5": party,
        "P6": country or "SI",
        "P6DS": tax,
        "P7": ZERO,
        "P8": ZERO,
        "P9": ZERO,
        "P10": ZERO,
        "P11": ZERO,
        "P12": ZERO,
        "P13": ZERO,
        "P14": ZERO,
        "P15": ZERO,
        "P16": ZERO,
        "P17": ZERO,
        "P18": ZERO,
        "P19": ZERO,
        "P20": ZERO,
        "P21": ZERO,
        "P22": ZERO,
        "P23": ZERO,
        "P24": ZERO,
        "P25": ZERO,
        "P26": ZERO,
        "P27": ZERO,
        "OBRAVNAVA": "1",
        "__source__": "minimax-journal",
    }


def _invoice_from_description(description: str, kind: str) -> str:
    text = str(description or "").strip()
    prefix = f"{kind}:"
    if text.upper().startswith(prefix):
        return text[len(prefix) :].strip() or text
    return text


def _pick_vat_entry(journal: Mapping[str, Any], book: str) -> Mapping[str, Any] | None:
    entries = [
        row for row in (journal.get("VatEntries") or []) if isinstance(row, Mapping)
    ]
    if not entries:
        return None
    book = book.upper()
    for row in entries:
        if str(row.get("VatBook") or "").strip().upper() == book:
            return row
    return entries[0]


def _customer_from_journal(journal: Mapping[str, Any], vat_entry: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if isinstance(vat_entry, Mapping) and isinstance(vat_entry.get("Customer"), Mapping):
        return vat_entry["Customer"]  # type: ignore[return-value]
    for entry in journal.get("JournalEntries") or []:
        if isinstance(entry, Mapping) and isinstance(entry.get("Customer"), Mapping):
            return entry["Customer"]  # type: ignore[return-value]
    return {}


def _revenue_account(journal: Mapping[str, Any]) -> str:
    for entry in journal.get("JournalEntries") or []:
        if not isinstance(entry, Mapping):
            continue
        credit = _money(entry.get("Credit") or entry.get("CreditInDomesticCurrency"))
        code = _account_code(entry.get("Account"))
        if credit > ZERO and code.startswith("76"):
            return code
    return ""


def _expense_account(journal: Mapping[str, Any]) -> str:
    for entry in journal.get("JournalEntries") or []:
        if not isinstance(entry, Mapping):
            continue
        debit = _money(entry.get("Debit") or entry.get("DebitInDomesticCurrency"))
        code = _account_code(entry.get("Account"))
        if debit > ZERO and code and not code.startswith(("16", "26", "12", "22")):
            return code
    return ""


def journal_to_kir(journal: Mapping[str, Any], *, zapst: int) -> dict[str, Any]:
    vat_entry = _pick_vat_entry(journal, "IR")
    totals = _vat_row_totals(
        [row for row in ((vat_entry or {}).get("VatEntryRows") or []) if isinstance(row, Mapping)]
    )
    # P2/P4 = datum listine; OBDOBJE = davčno obdobje (VatDate), kot eDavki.
    day = _iso(
        (vat_entry or {}).get("DocumentDate")
        or (vat_entry or {}).get("VatDate")
        or journal.get("JournalDate"),
        date.today().isoformat(),
    )
    vat_day = _iso(
        (vat_entry or {}).get("VatDate") or day,
        day,
    )
    invoice = str((vat_entry or {}).get("Document") or "").strip() or _invoice_from_description(
        str(journal.get("Description") or ""), "IR"
    )
    customer = _customer_from_journal(journal, vat_entry)
    party = _party_name(customer) or _party_name((vat_entry or {}).get("Customer"))
    country = _party_country(customer) or "SI"
    tax = _party_tax_id(customer)
    if tax and not re.match(r"^[A-Za-z]{2}", tax) and country and country != "SI":
        tax = f"{country}{tax}"
    account = _revenue_account(journal)
    jid = journal.get("JournalId") or journal.get("ID")
    base_s = totals["base_s"]
    base_z = totals["base_z"]
    base_5 = totals["base_5"]
    taxable = base_s + base_z + base_5
    row = _empty_kir(zapst=zapst, day=day, invoice=invoice, party=party, country=country, tax=tax)
    row["OBDOBJE"] = _obdobje_code(vat_day)
    row["__vat_date__"] = vat_day
    # VIES-KP / polje 12 = samo EU PO z ID za DDV (predpona ≠ SI).
    # OSS / fizične osebe brez ID → NE v P10/P11 (ostanejo P7 ali izven VIES).
    eu_vat = _normalize_eu_vat_id(tax, country)
    if eu_vat:
        row["P6DS"] = eu_vat
        if len(eu_vat) >= 2:
            row["P6"] = eu_vat[:2]
    if (
        eu_vat
        and _is_eu_foreign(country)
        and totals["vat"] == ZERO
        and taxable > ZERO
    ):
        goods = totals["goods_base"]
        services = totals["services_base"]
        if goods > ZERO:
            row["P10"] = goods
        if services > ZERO:
            row["P11"] = services
        if goods == ZERO and services == ZERO:
            row["P11"] = taxable
    else:
        # Polje 11 = vse obdavčljive osnove (22/9,5/5); oproščeno → P9; N izven DDV-O.
        row["P7"] = taxable
        row["P8"] = ZERO
        row["P9"] = totals["base_o"]
        row["P14"] = totals["vat_s"]
        row["P15"] = totals["vat_z"]
        row["P16"] = totals["vat_5"]
    row["__minimax_id__"] = str(jid or "")
    row["__minimax_status__"] = str(journal.get("Status") or "")
    row["__konto__"] = account
    row["MINIMAX_KONTO"] = account
    row["__gross__"] = totals["taxable_base"] + totals["vat"]
    return row


def journal_to_kpr(journal: Mapping[str, Any], *, zapst: int) -> dict[str, Any]:
    vat_entry = _pick_vat_entry(journal, "PR")
    totals = _vat_row_totals(
        [row for row in ((vat_entry or {}).get("VatEntryRows") or []) if isinstance(row, Mapping)]
    )
    # P2/P4 = datum prejema; OBDOBJE pa po VatDate (davčno obdobje / eDavki).
    # Sicer aprilski prejem z VatDate 31.3. pade v 0404 in izpade iz Q1.
    received = _iso(
        (vat_entry or {}).get("ReceivedDate")
        or (vat_entry or {}).get("VatDate")
        or journal.get("JournalDate"),
        date.today().isoformat(),
    )
    issued = _iso(
        (vat_entry or {}).get("DocumentDate") or journal.get("JournalDate"),
        received,
    )
    vat_day = _iso(
        (vat_entry or {}).get("VatDate") or received,
        received,
    )
    invoice = str((vat_entry or {}).get("Document") or "").strip() or _invoice_from_description(
        str(journal.get("Description") or ""), "PR"
    )
    customer = _customer_from_journal(journal, vat_entry)
    party = _party_name(customer)
    country = _party_country(customer)
    tax = _party_tax_id(customer)
    country, tax = core.ensure_party_ds(country, tax, party)
    self_tax = str((vat_entry or {}).get("SelfTaxing") or "").strip().upper() in {"D", "DA", "TRUE", "1"}
    # Pri samoobdavčitvi: osnova lahko iz IR, odbitek pa SAMO iz PR (ded vs nd).
    # Minimax na PR strani pogosto zapiše ServicesNonDeductible* → polje 41 = 0, 51 = 23a.
    ir_tot: dict[str, Decimal] | None = None
    if self_tax:
        ir_entry = _pick_vat_entry(journal, "IR")
        if ir_entry is not None:
            ir_tot = _vat_row_totals(
                [row for row in (ir_entry.get("VatEntryRows") or []) if isinstance(row, Mapping)]
            )
    account = _expense_account(journal)
    jid = journal.get("JournalId") or journal.get("ID")
    taxable = totals["taxable_base"]
    p8 = p9 = p10 = p11 = p14 = p17 = ZERO
    p18 = totals["ded_vat_s"]
    p19 = totals["ded_vat_z"]
    p20 = totals["ded_vat_5"]
    # Neodbitni DDV → P17 (ne P18/P19), sicer Σ »→41/42« napihne čipe.
    nd_vat = totals["nd_vat_s"] + totals["nd_vat_z"] + totals["nd_vat_5"]
    vat_deductible = True
    if self_tax:
        goods = totals["goods_base"]
        services = totals["services_base"]
        if ir_tot is not None:
            if goods == ZERO and services == ZERO:
                goods = ir_tot["goods_base"]
                services = ir_tot["services_base"]
            if taxable == ZERO:
                taxable = ir_tot["taxable_base"]
        services = services or (taxable if goods == ZERO else ZERO)
        if _is_eu_foreign(country):
            if goods > ZERO:
                p10 = goods
            if services > ZERO:
                p11 = services
            if goods == ZERO and services == ZERO:
                p11 = services or taxable or totals["base"]
        else:
            p9 = taxable or totals["base"]
        # Odbitek 41/42 = samo odbitni del na PR; neodbitni → P17 (Minimax nd).
        p17 = nd_vat
        vat_deductible = nd_vat == ZERO or (p18 + p19 + p20 > ZERO)
    else:
        # 31 = obdavčljive nabave S+Z+5 (z neodbitnim delom osnove); O → 33; N izven.
        p8 = taxable
        p14 = totals["base_o"]
        p17 = nd_vat
        # P18–P20 samo odbitni del (kot DDV-O 41/42/42a).
        # Samo neodbitni (npr. reprezentanca): označi za UI, P18…P20 = 0.
        vat_deductible = nd_vat == ZERO or (p18 + p19 + p20 > ZERO)

    return {
        "ZAPST": zapst,
        "OBDOBJE": _obdobje_code(vat_day),
        "P2": received,
        "P3": invoice,
        "P4": received,
        "P5": issued,
        "P6": party,
        "P7": country or "SI",
        "P7DS": tax,
        "P8": p8,
        "P9": p9,
        "P10": p10,
        "P11": p11,
        "P12": ZERO,
        "P13": ZERO,
        "P14": p14,
        "P15": ZERO,
        "P16": ZERO,
        "P17": p17,
        "P18": p18,
        "P19": p19,
        "P20": p20,
        "P21": ZERO,
        "OBRAVNAVA": "1",
        "__source__": "minimax-journal",
        "__minimax_id__": str(jid or ""),
        "__minimax_status__": str(journal.get("Status") or ""),
        "__konto__": account,
        "MINIMAX_KONTO": account,
        "__samoobdavcitev__": self_tax,
        "__ddv_se_odbija__": vat_deductible,
        "__gross__": taxable + totals["vat"],
        "__country__": country,
        "__vat_date__": vat_day,
    }


def self_assessment_kir_from_pr_journal(journal: Mapping[str, Any], *, zapst: int) -> dict[str, Any] | None:
    """KIR vrstica samoobdavčitve (polja 23/23a/25) iz PR temeljnice."""
    pr_entry = _pick_vat_entry(journal, "PR")
    self_tax = str((pr_entry or {}).get("SelfTaxing") or "").strip().upper() in {"D", "DA", "TRUE", "1"}
    if not self_tax:
        return None
    vat_entry = _pick_vat_entry(journal, "IR") or pr_entry
    totals = _vat_row_totals(
        [row for row in ((vat_entry or {}).get("VatEntryRows") or []) if isinstance(row, Mapping)]
    )
    if totals["vat"] == ZERO:
        return None
    day = _iso(
        (vat_entry or {}).get("VatDate")
        or (vat_entry or {}).get("DocumentDate")
        or journal.get("JournalDate"),
        date.today().isoformat(),
    )
    invoice = str((vat_entry or {}).get("Document") or "").strip() or _invoice_from_description(
        str(journal.get("Description") or ""), "PR"
    )
    customer = _customer_from_journal(journal, vat_entry)
    party = _party_name(customer)
    country = _party_country(customer) or "SI"
    tax = _party_tax_id(customer)
    if tax and not re.match(r"^[A-Za-z]{2}", tax) and country and country != "SI":
        tax = f"{country}{tax}"
    row = _empty_kir(zapst=zapst, day=day, invoice=invoice, party=party, country=country, tax=tax)
    goods = totals["goods_base"]
    services = totals["services_base"]
    if _is_eu_foreign(country):
        if goods > ZERO and services == ZERO:
            row["P17"] = totals["vat_s"]  # polje 23
            row["P19"] = totals["vat_z"]
        else:
            row["P18"] = totals["vat_s"]  # polje 23a
            row["P20"] = totals["vat_z"]
    else:
        row["P23"] = totals["vat_s"]  # polje 25
        row["P24"] = totals["vat_z"]
    jid = journal.get("JournalId") or journal.get("ID")
    row["__minimax_id__"] = str(jid or "")
    row["__minimax_status__"] = str(journal.get("Status") or "")
    row["__source__"] = "minimax-journal-selftax"
    row["__gross__"] = totals["vat"]
    return row


def journal_as_book_row(journal: Mapping[str, Any], book: str) -> dict[str, Any]:
    """Poenostavljen zapis za predogled Knjig (stolpci kot pri API računih)."""
    vat_entry = _pick_vat_entry(journal, book)
    totals = _vat_row_totals(
        [row for row in ((vat_entry or {}).get("VatEntryRows") or []) if isinstance(row, Mapping)]
    )
    day = _iso(
        (vat_entry or {}).get("DocumentDate")
        or (vat_entry or {}).get("ReceivedDate")
        or journal.get("JournalDate")
    )
    invoice = str((vat_entry or {}).get("Document") or "").strip() or _invoice_from_description(
        str(journal.get("Description") or ""), book
    )
    jid = journal.get("JournalId") or journal.get("ID")
    amount = totals["base"] + totals["vat"]
    return {
        "JournalId": jid,
        "IssuedInvoiceId": jid if book == "IR" else None,
        "ReceivedInvoiceId": jid if book == "PR" else None,
        "DocumentReference": invoice,
        "DateIssued": day,
        "InvoiceAmount": float(amount),
        "Status": journal.get("Status") or "P",
        "Customer": (vat_entry or {}).get("Customer"),
        "Supplier": (vat_entry or {}).get("Customer"),
        "_journal": True,
    }


def dataset_from_minimax_journals(
    *,
    ir_journals: Sequence[Mapping[str, Any]],
    pr_journals: Sequence[Mapping[str, Any]],
    date_from: str,
    date_to: str,
    company_name: str = "",
    tax_number: str = "",
    org_id: str = "",
) -> core.KirkprDataset:
    # Knjiga / DDV-O gre po VatDate, ne po datumu temeljnice.
    ir_in = filter_journals_by_vat_period(ir_journals, "IR", date_from, date_to)
    pr_in = filter_journals_by_vat_period(pr_journals, "PR", date_from, date_to)
    kir: list[dict[str, Any]] = []
    kpr: list[dict[str, Any]] = []
    for row in ir_in:
        kir.append(journal_to_kir(row, zapst=len(kir) + 1))
    for row in pr_in:
        kpr.append(journal_to_kpr(row, zapst=len(kpr) + 1))
        tax_kir = self_assessment_kir_from_pr_journal(row, zapst=len(kir) + 1)
        if tax_kir is not None:
            kir.append(tax_kir)
    label = company_name or "Minimax"
    source = Path(f"minimax_journals_{org_id or 'org'}_{date_from}_{date_to}.virtual")
    header = {
        "TaxPayerID": re.sub(r"\D", "", tax_number) or tax_number,
        "TaxPayerName": label,
        "OBDOBJE_OD": date_from[:10],
        "OBDOBJE_DO": date_to[:10],
        "DocumentType": "MINIMAX_API_JOURNALS",
    }
    warnings = [
        "Vir: Minimax temeljnice knjige IR/PR (filter = VatDate).",
        "Stopnje: S=22%, Z=9,5%, 0=5%, O=oproščeno, N=neobdavčeno (izven 31/33).",
    ]
    if not kir and not kpr:
        warnings.append("V obdobju ni temeljnic IR/PR (po datumu DDV).")
    return core.KirkprDataset(
        header=header,
        kir=kir,
        kpr=kpr,
        source_path=source,
        source_format="minimax-api",
        source_members=[
            f"IR journals {len(ir_in)}/{len(ir_journals)}",
            f"PR journals {len(pr_in)}/{len(pr_journals)}",
            f"KIR vrstice {len(kir)} (z samoobd.)",
            f"Org {org_id}",
        ],
        warnings=warnings,
    )


# --- legacy: mapiranje iz issuedinvoices/receivedinvoices (če obstajajo) ---

def _merged(record: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(record)
    for key in ("IssuedInvoice", "issuedInvoice", "ReceivedInvoice", "receivedInvoice"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            merged.update(nested)
    return merged


def _record_id(record: Mapping[str, Any]) -> int | None:
    merged = _merged(record)
    for key in (
        "IssuedInvoiceId", "ReceivedInvoiceId", "JournalId", "ID", "Id", "id",
    ):
        value = merged.get(key)
        if value is None:
            continue
        try:
            result = int(value)
            if result > 0:
                return result
        except (TypeError, ValueError):
            pass
    return None


def _record_money(record: Mapping[str, Any], *keys: str) -> Decimal:
    merged = _merged(record)
    for key in keys:
        if key in merged and merged.get(key) not in (None, ""):
            return _money(merged.get(key))
    return ZERO


def issued_to_kir(record: Mapping[str, Any], *, zapst: int) -> dict[str, Any]:
    merged = _merged(record)
    day = minimax_api.invoice_record_date(merged) or date.today().isoformat()
    invoice = minimax_api.invoice_record_reference(merged)
    party = minimax_api.invoice_record_party(merged)
    tax = minimax_api.invoice_record_tax_id(merged)
    country = minimax_api.invoice_record_country(merged) or _country_from_tax(tax) or "SI"
    gross = minimax_api.invoice_record_amount(merged)
    vat = _record_money(
        merged, "VatAmount", "VATAmount", "TaxAmount", "VatValue", "InvoiceVatAmount"
    )
    net = _record_money(
        merged,
        "NetAmount",
        "InvoiceNetAmount",
        "BaseAmount",
        "TaxableAmount",
        "AmountWithoutVAT",
        "InvoiceAmountWithoutVAT",
        "ValueWithoutVAT",
    )
    if net == ZERO and gross != ZERO and vat != ZERO:
        net = gross - vat
    if vat == ZERO and gross != ZERO and net != ZERO and gross > net:
        vat = gross - net
    # Brez znanega neto/DDV ne vpisuj bruto v P7 (sicer polje 11 = neto+DDV).
    rid = _record_id(merged)
    status = minimax_api.invoice_record_status(merged)
    # VIES-KP / polje 12: samo EU ID za DDV s predpono (brez SI / FO / OSS).
    eu_vat = _normalize_eu_vat_id(tax, country)
    p7 = net
    p10 = ZERO
    p11 = ZERO
    p14 = vat
    if eu_vat and _is_eu_foreign(country) and vat == ZERO and net > ZERO:
        p7 = ZERO
        p14 = ZERO
        p11 = net  # storitve/blago: pri IR modulu ločitev goods/services ni zanesljiva
    return {
        "ZAPST": zapst,
        "OBDOBJE": _obdobje_code(day),
        "P2": day,
        "P3": invoice,
        "P4": day,
        "P5": party,
        "P6": (eu_vat[:2] if eu_vat else country),
        "P6DS": eu_vat or (tax or ""),
        "P7": p7,
        "P8": ZERO,
        "P9": ZERO,
        "P10": p10,
        "P11": p11,
        "P12": ZERO,
        "P13": ZERO,
        "P14": p14,
        "P15": ZERO,
        "P16": ZERO,
        "P17": ZERO,
        "P18": ZERO,
        "P19": ZERO,
        "P20": ZERO,
        "P21": ZERO,
        "P22": ZERO,
        "P23": ZERO,
        "P24": ZERO,
        "P25": ZERO,
        "P26": ZERO,
        "P27": ZERO,
        "OBRAVNAVA": "1",
        "__source__": "minimax-api",
        "__minimax_id__": str(rid or ""),
        "__minimax_status__": status,
        "__gross__": gross,
        "__country__": country,
    }


def received_to_kpr(record: Mapping[str, Any], *, zapst: int) -> dict[str, Any]:
    merged = _merged(record)
    issued = _iso(merged.get("DateIssued") or merged.get("InvoiceDate") or merged.get("DocumentDate"))
    received = _iso(
        merged.get("ReceiptDate") or merged.get("DateReceived") or merged.get("DateTransaction") or issued
    )
    day = received or issued or date.today().isoformat()
    invoice = minimax_api.invoice_record_reference(merged) or minimax_api.supplier_invoice_number(merged)
    party = minimax_api.invoice_record_party(merged)
    tax = minimax_api.invoice_record_tax_id(merged)
    hint = minimax_api.invoice_record_address_hint(merged)
    country = minimax_api.invoice_record_country(merged) or _country_from_tax(tax)
    country, tax = core.ensure_party_ds(country, tax, f"{party} {hint}")
    gross = minimax_api.invoice_record_amount(merged)
    vat = _record_money(merged, "VatAmount", "VATAmount", "TaxAmount", "DeductibleVatAmount")
    net = _record_money(
        merged,
        "NetAmount",
        "InvoiceNetAmount",
        "BaseAmount",
        "TaxableAmount",
        "AmountWithoutVAT",
        "InvoiceAmountWithoutVAT",
        "ValueWithoutVAT",
    )
    if net == ZERO and gross != ZERO and vat != ZERO:
        net = gross - vat
    if vat == ZERO and gross != ZERO and net != ZERO and gross > net:
        vat = gross - net
    rid = _record_id(merged)
    status = minimax_api.invoice_record_status(merged)
    return {
        "ZAPST": zapst,
        "OBDOBJE": _obdobje_code(day),
        "P2": day,
        "P3": invoice,
        "P4": received or day,
        "P5": issued or day,
        "P6": party,
        "P7": country,
        "P7DS": tax or "",
        "P8": net,
        "P9": ZERO,
        "P10": ZERO,
        "P11": ZERO,
        "P12": ZERO,
        "P13": ZERO,
        "P14": ZERO,
        "P15": ZERO,
        "P16": ZERO,
        "P17": ZERO,
        "P18": vat,
        "P19": ZERO,
        "P20": ZERO,
        "P21": ZERO,
        "OBRAVNAVA": "1",
        "__source__": "minimax-api",
        "__minimax_id__": str(rid or ""),
        "__minimax_status__": status,
        "__gross__": gross,
    }


def dataset_from_minimax_books(
    *,
    ir_records: Sequence[Mapping[str, Any]],
    pr_records: Sequence[Mapping[str, Any]],
    date_from: str,
    date_to: str,
    company_name: str = "",
    tax_number: str = "",
    org_id: str = "",
) -> core.KirkprDataset:
    kir = [issued_to_kir(row, zapst=i + 1) for i, row in enumerate(ir_records)]
    kpr = [received_to_kpr(row, zapst=i + 1) for i, row in enumerate(pr_records)]
    label = company_name or "Minimax"
    source = Path(f"minimax_api_{org_id or 'org'}_{date_from}_{date_to}.virtual")
    header = {
        "TaxPayerID": re.sub(r"\D", "", tax_number) or tax_number,
        "TaxPayerName": label,
        "OBDOBJE_OD": date_from[:10],
        "OBDOBJE_DO": date_to[:10],
        "DocumentType": "MINIMAX_API_IR_PR",
    }
    warnings = ["Vir: Minimax API izdani/prejeti računi (knjiga IR/PR)."]
    if not kir and not kpr:
        warnings.append("Minimax API v obdobju ni vrnil IR/PR zapisov.")
    return core.KirkprDataset(
        header=header,
        kir=kir,
        kpr=kpr,
        source_path=source,
        source_format="minimax-api",
        source_members=[f"IR {len(kir)}", f"PR {len(kpr)}", f"Org {org_id}"],
        warnings=warnings,
    )


def dataset_from_minimax_hybrid(
    *,
    ir_invoice_records: Sequence[Mapping[str, Any]] | None = None,
    pr_invoice_records: Sequence[Mapping[str, Any]] | None = None,
    ir_journals: Sequence[Mapping[str, Any]] | None = None,
    pr_journals: Sequence[Mapping[str, Any]] | None = None,
    date_from: str,
    date_to: str,
    company_name: str = "",
    tax_number: str = "",
    org_id: str = "",
    prefer: str = "journals",
) -> tuple[core.KirkprDataset, dict[str, str]]:
    """Sestavi KIR/KPR po knjigi: temeljnice in/ali moduli IR/PR.

    prefer='journals' (privzeto, zanesljivo): najprej temeljnice knjige,
    moduli samo če je knjiga prazna (PROJEST/Aeon; Dišport IR).
    prefer='invoices': najprej moduli, potem temeljnice.
    """
    ir_inv = list(ir_invoice_records or [])
    pr_inv = list(pr_invoice_records or [])
    ir_j_all = list(ir_journals or [])
    pr_j_all = list(pr_journals or [])
    ir_j = filter_journals_by_vat_period(ir_j_all, "IR", date_from, date_to)
    pr_j = filter_journals_by_vat_period(pr_j_all, "PR", date_from, date_to)

    prefer = str(prefer or "journals").strip().lower()
    if prefer == "invoices":
        ir_source = "invoices" if ir_inv else ("journals" if ir_j else "empty")
        pr_source = "invoices" if pr_inv else ("journals" if pr_j else "empty")
    else:
        ir_source = "journals" if ir_j else ("invoices" if ir_inv else "empty")
        pr_source = "journals" if pr_j else ("invoices" if pr_inv else "empty")

    kir: list[dict[str, Any]] = []
    kpr: list[dict[str, Any]] = []

    if ir_source == "invoices":
        kir.extend(issued_to_kir(row, zapst=len(kir) + 1) for row in ir_inv)
    elif ir_source == "journals":
        kir.extend(journal_to_kir(row, zapst=len(kir) + 1) for row in ir_j)

    if pr_source == "invoices":
        kpr.extend(received_to_kpr(row, zapst=len(kpr) + 1) for row in pr_inv)
    elif pr_source == "journals":
        for row in pr_j:
            kpr.append(journal_to_kpr(row, zapst=len(kpr) + 1))
            tax_kir = self_assessment_kir_from_pr_journal(row, zapst=len(kir) + 1)
            if tax_kir is not None:
                kir.append(tax_kir)

    # Če je PR iz modula, samoobdavčitev (23/23a) še vedno iz PR temeljnic (brez dvojnih KPR).
    if pr_source == "invoices" and pr_j:
        for row in pr_j:
            tax_kir = self_assessment_kir_from_pr_journal(row, zapst=len(kir) + 1)
            if tax_kir is not None:
                kir.append(tax_kir)

    label = company_name or "Minimax"
    parts = []
    if ir_source == "invoices" or pr_source == "invoices":
        parts.append("api")
    if ir_source == "journals" or pr_source == "journals" or (
        pr_source == "invoices" and pr_j
    ):
        parts.append("journals")
    tag = "_".join(parts) or "empty"
    source = Path(f"minimax_{tag}_{org_id or 'org'}_{date_from}_{date_to}.virtual")
    header = {
        "TaxPayerID": re.sub(r"\D", "", tax_number) or tax_number,
        "TaxPayerName": label,
        "OBDOBJE_OD": date_from[:10],
        "OBDOBJE_DO": date_to[:10],
        "DocumentType": "MINIMAX_API_HYBRID",
    }
    warnings = [
        f"IR vir: {'knjiga (izdani računi)' if ir_source == 'invoices' else 'temeljnice' if ir_source == 'journals' else '—'}.",
        f"PR vir: {'knjiga (prejeti računi)' if pr_source == 'invoices' else 'temeljnice' if pr_source == 'journals' else '—'}.",
    ]
    if ir_source == "journals" or pr_source == "journals":
        warnings.append(
            "Temeljnice: stopnje S/Z/0(=5%)/O/N, filter VatDate (npr. PROJEST/Aeon/Dišport IR)."
        )
    dataset = core.KirkprDataset(
        header=header,
        kir=kir,
        kpr=kpr,
        source_path=source,
        source_format="minimax-api",
        source_members=[
            f"IR {ir_source} {len(ir_inv) if ir_source == 'invoices' else len(ir_j)}",
            f"PR {pr_source} {len(pr_inv) if pr_source == 'invoices' else len(pr_j)}",
            f"KIR vrstice {len(kir)}",
            f"Org {org_id}",
        ],
        warnings=warnings,
    )
    return dataset, {"IR": ir_source, "PR": pr_source}
