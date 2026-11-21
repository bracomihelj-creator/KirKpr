"""Grafični pretvornik KIR/KPR v Minimax XML.

Program prebere FURS KIR/KPR iz ZIP, JSON, XML ali CSV, prikaže izdane in
prejete račune, omogoča popravek kontov, izračuna kontrolni DDV-O ter izvozi
dve XSD-preverjeni Minimax XML datoteki in ZIP za arhiv/uvoz.
"""

from __future__ import annotations

import argparse
import calendar
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

import kirkpr_minimax_core as core
import kirkpr_company_registry as company_registry
import kirkpr_gui_style as gui_style
import kirkpr_minimax_browser as minimax_browser
import kirkpr_minimax_dataset as minimax_dataset
import kirkpr_logging
import minimax_api_client as minimax_api


APP_VERSION = "4.0.2"
CHROME_EXTENSION_VERSION = "1.4.19"
APP_TITLE = "KIR/KPR → Minimax Studio"
APP_DISPLAY_TITLE = f"{APP_TITLE} v{APP_VERSION}"
APP_EDITION = "Cursor"
SLO_MONTHS = (
    "januar", "februar", "marec", "april", "maj", "junij",
    "julij", "avgust", "september", "oktober", "november", "december",
)
# Enako kot Fakturiranje / Evidenca: meseci + razponi.
PERIOD_RANGES: dict[str, tuple[int, int]] = {
    name: (index, index) for index, name in enumerate(SLO_MONTHS, start=1)
}
PERIOD_RANGES.update(
    {
        "jan-mar": (1, 3),
        "apr-jun": (4, 6),
        "jul-sep": (7, 9),
        "okt-dec": (10, 12),
        "jan-jun": (1, 6),
        "jul-dec": (7, 12),
        "jan-dec": (1, 12),
    }
)
PERIOD_CHOICES = SLO_MONTHS + (
    "jan-mar",
    "apr-jun",
    "jul-sep",
    "okt-dec",
    "jan-jun",
    "jul-dec",
    "jan-dec",
)
NAVIGATION_DEFAULT_WIDTH = 360
NAVIGATION_MIN_WIDTH = 300
COMMON_PR_ACCOUNTS = ("4190", "4000", "4040", "0400", "6500", "6600")
COMMON_IR_ACCOUNTS = ("7601", "7600", "7610", "7620", "7680")
ACTION_LABELS = {
    "open": "odprti podatki",
    "minimax_load": "podatki iz Minimaxa",
    "account_change": "spremenjen konto",
    "vat_settings": "spremenjeni nastavitvi DDV",
    "company_select": "izbrano podjetje",
    "data_edit": "spremenjeni podatki delovne kopije",
    "working_copy": "shranjena delovna kopija",
    "document_edit": "popravljen prejeti račun",
    "issued_edit": "popravljen izdani račun",
    "save": "shranjeni konti",
    "export": "izvožen Minimax XML/ZIP",
    "ddvo": "preračunan DDV-O",
    "ddvo_copy": "kopiran kontrolni podatek DDV-O",
    "ddvo_report": "shranjen kontrolni pregled DDV-O",
    "ddvo_pdf": "shranjen DDV-O PDF (e-DDV_O_11.7)",
    "ddvo_xml": "shranjen DDV-O XML (DDV_O_11)",
    "ddvo_preview": "predogled DDV-O PDF",
    "ddvo_export": "izvoz DDV-O PDF+XML",
    "ddvo_print": "tisk DDV-O PDF",
    "ddvo_minimax": "Minimax tisk DDV-O + virman",
    "api_connect": "preverjena Minimax API povezava",
    "api_statuses": "osveženi statusi računov Minimax",
    "api_validate": "preverjeni podatki za Minimax API",
    "api_send": "oddani dokumenti v Minimax API",
    "browser_open": "odprt Minimax osnutek v brskalniku",
    "browser_session": "preverjena skupna Playwright seja",
    "browser_company": "odprto podjetje v Playwrightu",
    "browser_diagnostic": "shranjena varna diagnostika organizacij",
}

IR_FIELD_LABELS = {
    "ZAPST": "Zaporedna številka", "P2": "Datum knjiženja", "P3": "Listina",
    "P4": "Datum listine", "P5": "Kupec", "P6": "Država", "P6DS": "ID za DDV",
    "P7": "Obdavčljive dobave", "P8": "Dobave – obrnjena obveznost", "P9": "Oproščene dobave",
    "P10": "Dobave blaga v EU", "P11": "Dobave storitev v EU", "P12": "Prodaja na daljavo",
    "P13": "Montaža v drugi državi", "P14": "DDV 22 %", "P15": "DDV 9,5 %",
    "P16": "DDV 5 %", "P17": "Pridobitve EU – DDV 22 %", "P18": "Storitve EU – DDV 22 %",
    "P19": "Pridobitve EU – DDV 9,5 %", "P20": "Storitve EU – DDV 9,5 %",
    "P21": "Pridobitve EU – DDV 5 %", "P22": "Storitve EU – DDV 5 %",
    "P23": "Samoobdavčitev – DDV 22 %", "P24": "Samoobdavčitev – DDV 9,5 %",
    "P25": "Samoobdavčitev – DDV 5 %", "P26": "Uvoz – DDV", "P27": "Neobdavčene dobave",
    "OBRAVNAVA": "Vrsta obravnave",
}
PR_FIELD_LABELS = {
    "ZAPST": "Zaporedna številka", "P2": "Datum knjiženja", "P3": "Listina",
    "P4": "Datum prejema", "P5": "Datum računa", "P6": "Dobavitelj", "P7": "Država",
    "P7DS": "ID za DDV", "P8": "Nabave v Sloveniji", "P9": "Nabave – obrnjena obveznost",
    "P10": "Pridobitve blaga iz EU", "P11": "Prejete storitve iz EU",
    "P12": "Nepremičnine", "P13": "Druga osnovna sredstva", "P14": "Oproščene nabave",
    "P15": "Oproščene nepremičnine", "P16": "Oproščena osnovna sredstva",
    "P17": "Neodbitni DDV", "P18": "Odbitni DDV 22 %", "P19": "Odbitni DDV 9,5 %",
    "P20": "Odbitni DDV 5 %", "P21": "Pavšalno nadomestilo", "OBRAVNAVA": "Vrsta obravnave",
}


# Polja zneska DDV → stopnja za povratni izračun osnove (DDV / stopnja).
VAT_BASE_RATE_FIELDS: dict[str, tuple[Decimal, str]] = {
    "P14": (Decimal("0.22"), "22%"),   # KIR / tudi splošno
    "P15": (Decimal("0.095"), "9,5%"),
    "P16": (Decimal("0.05"), "5%"),
    "P18": (Decimal("0.22"), "22%"),   # KPR odbitni 22%
    "P19": (Decimal("0.095"), "9,5%"),
    "P20": (Decimal("0.05"), "5%"),
}


def format_money(value: Decimal | Any) -> str:
    """Slovenski prikaz zneska, npr. 1.234,56."""
    try:
        amount = core.decimal_value(value)
    except core.KirkprError:
        return str(value or "")
    text = f"{amount:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_virman_formula(obligation: Any, saldo: Any, payment: Any) -> str:
    """»5.000,00 − 1.261,61 (stanje 62 v dobro) = 3.738,39 EUR« — predznak razložen."""
    obl = core.decimal_value(obligation)
    bal = core.decimal_value(saldo)
    pay = core.decimal_value(payment)
    if bal == 0:
        return f"{format_money(obl)} + 0,00 (stanje 62) = {format_money(pay)} EUR"
    sign = "−" if bal < 0 else "+"
    label = "v dobro" if bal < 0 else "manjko"
    return (
        f"{format_money(obl)} {sign} {format_money(abs(bal))} (stanje 62 {label}) "
        f"= {format_money(pay)} EUR"
    )


def listina_sort_key(value: Any) -> tuple[Any, ...]:
    """Naravni vrstni red listine, npr. 26-120-000022 pred 26-120-000030."""
    text = str(value or "").strip()
    parts: list[Any] = []
    for chunk in re.findall(r"\d+|\D+", text):
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        else:
            parts.append((1, chunk.casefold()))
    return tuple(parts) if parts else ((1, ""),)


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", text)
    if not match:
        return None
    day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_si_date(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def previous_month_bounds(ref: date | None = None) -> tuple[date, date]:
    """Privzeto obdobje: prejšnji koledarski mesec."""
    today = ref or date.today()
    if today.month == 1:
        return month_bounds(today.year - 1, 12)
    return month_bounds(today.year, today.month - 1)


def previous_quarter_bounds(ref: date | None = None) -> tuple[date, date]:
    """Prejšnji zaključeni koledarski kvartal (1.1–31.3, 1.4–30.6, …)."""
    today = ref or date.today()
    current_q = (today.month - 1) // 3  # 0=Q1 … 3=Q4
    if current_q == 0:
        year = today.year - 1
        start_month = 10
    else:
        year = today.year
        start_month = (current_q - 1) * 3 + 1
    end_month = start_month + 2
    return date(year, start_month, 1), month_bounds(year, end_month)[1]


def period_bounds_for_oddaja_ddv(
    oddaja_ddv: str,
    ref: date | None = None,
) -> tuple[date, date] | None:
    """Iz »oddaja DDV«: Mesečni → prejšnji mesec, Tromesečni → prejšnji kvartal."""
    kind = company_registry.normalize_oddaja_ddv(oddaja_ddv)
    if kind == "Mesečni":
        return previous_month_bounds(ref)
    if kind == "Tromesečni":
        return previous_quarter_bounds(ref)
    return None


_PATH_PERIOD_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})[_\s-](20\d{2}-\d{2}-\d{2})")
_PATH_YEAR_MONTH_RE = re.compile(r"(?:^|[^\d])(20\d{2})[-_/ ](0?[1-9]|1[0-2])(?:[^\d]|$)")


def period_from_source_path(path: Path | str | None) -> tuple[date, date] | None:
    """Iz poti/imena razbere obdobje: 2026-06-01_2026-06-30 ali …-2026-6 / 2026-06."""
    if not path:
        return None
    text = str(path).replace("\\", "/")
    match = _PATH_PERIOD_RE.search(text)
    if match:
        try:
            start = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            end = datetime.strptime(match.group(2), "%Y-%m-%d").date()
        except ValueError:
            pass
        else:
            if end < start:
                start, end = end, start
            return start, end
    # Ime datoteke npr. 002-KIRKPR-2026-6.zip ali KIRKPR_2026-06.json
    stem = Path(text).stem
    stem_match = _PATH_YEAR_MONTH_RE.search(f"{stem}/") or _PATH_YEAR_MONTH_RE.search(text)
    if stem_match:
        return month_bounds(int(stem_match.group(1)), int(stem_match.group(2)))
    return None


def is_last_month_of_span(start: date, end: date, span_from: date, span_to: date) -> bool:
    """True, če je [start,end] samo zadnji mesec večmesečnega razpona (napačen auto-filter)."""
    if span_from.year == span_to.year and span_from.month == span_to.month:
        return False
    last_start, last_end = month_bounds(span_to.year, span_to.month)
    return start == last_start and end == last_end


def period_bounds(year: int, label: str) -> tuple[date, date] | None:
    """Vrne (prvi, zadnji) dan za mesec ali razpon (jan-mar … jan-dec)."""
    key = str(label or "").strip().casefold()
    months = PERIOD_RANGES.get(key)
    if months is None:
        return None
    start_month, end_month = months
    return date(year, start_month, 1), month_bounds(year, end_month)[1]


def period_label_for_range(start: date, end: date) -> str:
    """Oznaka v spustnem seznamu (kot Fakturiranje): junij, jan-mar, jan-dec …"""
    if start.year == end.year and start.day == 1:
        # Najprej večmesečni razponi, nato posamezni mesec.
        for label in PERIOD_CHOICES:
            m1, m2 = PERIOD_RANGES[label]
            if start.month == m1 and end == month_bounds(start.year, m2)[1]:
                if m1 != m2 or label in SLO_MONTHS:
                    # Pri enomesečnem razponu je label mesec; pri večmesečnem razpon.
                    if m1 == m2 or "-" in label:
                        return label
    return SLO_MONTHS[start.month - 1]


def row_filter_date(_book: str, row: Mapping[str, Any]) -> date | None:
    """Datum za filter obdobja v IR/PR tabelah: P4 (listina / prejem)."""
    return parse_iso_date(row.get("P4"))


def parse_obdobje_mmyy(value: Any) -> tuple[int, int] | None:
    """FURS OBDOBJE MMYY → (leto, mesec), npr. 0626 → (2026, 6)."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}", text):
        return None
    month = int(text[:2])
    year = 2000 + int(text[2:])
    if month < 1 or month > 12:
        return None
    return year, month


def parse_obdobje_span(value: Any, header_year: int) -> tuple[date, date] | None:
    """FURS OBDOBJE kot MM+MM znotraj leta glave: 0606=junij, 0406=apr–jun."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}", text):
        return None
    month_from = int(text[:2])
    month_to = int(text[2:])
    if not (1 <= month_from <= 12 and 1 <= month_to <= 12):
        return None
    year = int(header_year)
    if month_to >= month_from:
        return month_bounds(year, month_from)[0], month_bounds(year, month_to)[1]
    # Prehod čez novo leto (npr. 1102).
    return month_bounds(year, month_from)[0], month_bounds(year + 1, month_to)[1]


def row_in_ddvo_period(
    row: Mapping[str, Any],
    start: date,
    end: date,
    *,
    header_year: int | None = None,
) -> bool:
    """Vrstica sodi v DDV-O obdobje: OBDOBJE (MM+MM), sicer P2, sicer P4.

    Uradni DDV-O vključuje vse postavke davčnega obdobja, tudi če je P4 zunaj
    koledarskega meseca (npr. OBDOBJE=0606, P4=2026-07-02).
    """
    year = header_year if header_year is not None else start.year
    span = parse_obdobje_span(row.get("OBDOBJE"), year)
    if span is not None:
        span_from, span_to = span
        return not (span_to < start or span_from > end)
    # Starejši zapis MMYY (npr. 0626).
    parsed = parse_obdobje_mmyy(row.get("OBDOBJE"))
    if parsed is not None:
        y, m = parsed
        month_start, month_end = month_bounds(y, m)
        return not (month_end < start or month_start > end)
    for field_name in ("P2", "P4", "P5"):
        day = parse_iso_date(row.get(field_name))
        if day is not None:
            return start <= day <= end
    return True


def row_booking_date(book: str, row: Mapping[str, Any]) -> date | None:
    """Datum vrstice: P4, sicer P2 (za razpone / prikaze)."""
    _ = book
    return parse_iso_date(row.get("P4")) or parse_iso_date(row.get("P2"))


def is_money_field(book: str, field_name: str) -> bool:
    """Vrne True za zneskovna polja KIR/KPR, ki se v GUI prikažejo slovensko."""
    match = re.fullmatch(r"P(\d+)", str(field_name or "").upper())
    if not match:
        return False
    number = int(match.group(1))
    return 7 <= number <= 27 if book.upper() == "IR" else 8 <= number <= 21


def open_in_file_manager(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


class ToolTip:
    """Lebdeča rumena pasica (1–3 stavki); pri dnu okna se odpre NAVZGOR."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event: tk.Event | None = None) -> None:
        if self.window or not self.text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        label = tk.Label(
            self.window,
            text=self.text,
            bg="#ffffe0",
            fg="#1a1a1a",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=6,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=380,
        )
        label.pack()
        self.window.update_idletasks()
        tip_w = max(self.window.winfo_reqwidth(), 120)
        tip_h = max(self.window.winfo_reqheight(), 28)
        screen_h = int(self.widget.winfo_screenheight() or 900)
        screen_w = int(self.widget.winfo_screenwidth() or 1400)
        wx = int(self.widget.winfo_rootx())
        wy = int(self.widget.winfo_rooty())
        wh = int(self.widget.winfo_height() or 24)
        x = min(max(8, wx + 12), max(8, screen_w - tip_w - 8))
        # Če je gumb pri dnu zaslona → pasica NAVZGOR, sicer pod gumbom.
        below = wy + wh + 8
        if below + tip_h > screen_h - 12:
            y = max(8, wy - tip_h - 8)
        else:
            y = below
        self.window.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self.window:
            self.window.destroy()
            self.window = None


class ConverterApp:
    def __init__(self, root: tk.Tk, initial_source: Path | None = None) -> None:
        self.root = root
        self.dataset: core.KirkprDataset | None = None
        self.source_dataset: core.KirkprDataset | None = None
        self.working_dirty = False
        self.pending_working_changes: list[str] = []
        self.pr_editor: tk.Toplevel | None = None
        self.ir_editor: tk.Toplevel | None = None
        self.config_file = core.config_path()
        self.config = core.load_config(self.config_file)
        self.log = kirkpr_logging.setup_logging(
            level=str(self.config.get("log_level") or "INFO"),
            console=False,
        )
        self.log.info("Zagon %s (izdaja %s)", APP_DISPLAY_TITLE, APP_EDITION)
        version_history = self.config.setdefault("version_history", [])
        if str(self.config.get("app_version") or "") != APP_VERSION:
            version_history.append(
                {"version": APP_VERSION, "registered_at": datetime.now().astimezone().isoformat(timespec="seconds")}
            )
            self.config["version_history"] = version_history[-50:]
            self.config["app_version"] = APP_VERSION
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
        registry_preferred = str(self.config.get("company_registry_path") or "")
        self.company_registry_path, self.companies = company_registry.load_companies(registry_preferred or None)
        if self.company_registry_path:
            self.config["company_registry_path"] = str(self.company_registry_path)
        self.active_company = company_registry.find_company(
            self.companies,
            str(self.config.get("selected_company_key") or ""),
        )
        profile = self._profile_config()
        self.account_catalog: dict[str, str] = {
            str(code): str(name) for code, name in dict(profile.get("account_catalog") or {}).items()
        }
        self.minimax_client: minimax_api.MinimaxClient | None = None
        self.minimax_organisations: dict[str, int] = {}
        self.minimax_invoice_status_catalog: dict[str, dict[str, dict[str, str]]] = {
            "IR": {"by_reference": {}, "by_id": {}, "by_reference_id": {}},
            "PR": {"by_reference": {}, "by_id": {}, "by_reference_id": {}},
        }
        self.minimax_invoice_status_org = ""
        self.minimax_invoice_status_checked = False
        self.api_view_mode = "json"  # json = lokalni podatki; minimax = usklajeno z API
        self.api_diff_summary: dict[str, Any] = {}
        self._cleared_listinas: set[str] = set()
        self.api_busy = False
        self._period_filter_updating = False
        # Privzeto vedno prejšnji mesec (npr. julij → junij 2026).
        self.filter_from_date, self.filter_to_date = previous_month_bounds()
        self.data_span_from: date | None = None
        self.data_span_to: date | None = None
        self.company_sort_column = "zst"
        self.company_sort_reverse = False
        saved_export_dir = str(profile.get("last_export_dir") or self.config.get("last_export_dir") or "")
        self.last_export_dir = Path(saved_export_dir) if saved_export_dir else None
        self.colors = self._configure_gui_style()

        self.source_var = tk.StringVar(value="Izberite ZIP/JSON/XML/CSV ali »Podatki iz Minimaxa«.")
        self.company_var = tk.StringVar(value=self._active_company_text())
        self.company_search_var = tk.StringVar(value="")
        self.format_var = tk.StringVar(value="Format: —")
        self.period_var = tk.StringVar(value="Obdobje: —")
        self.filter_month_var = tk.StringVar(value=SLO_MONTHS[self.filter_from_date.month - 1])
        self.filter_year_var = tk.StringVar(value=str(self.filter_from_date.year))
        self.filter_from_var = tk.StringVar(value=format_si_date(self.filter_from_date))
        self.filter_to_var = tk.StringVar(value=format_si_date(self.filter_to_date))
        self.filter_info_var = tk.StringVar(value="Filter obdobja še ni uporabljen.")
        self.recent_session_var = tk.StringVar(value="")
        self._recent_session_by_label: dict[str, dict[str, Any]] = {}
        self._recent_session_updating = False
        self._selected_session_id: int | None = None
        self._suppress_session_remember_keys: set[tuple[str, str, str]] = set()
        import kirkpr_sessions_db as sessions_db

        self.sessions_db = sessions_db.SessionsDb()
        self.member_var = tk.StringVar(value="Vsebina: —")
        self.status_var = tk.StringVar(value=self._last_action_text() or "Pripravljeno za uvoz podatkov.")
        self.selection_var = tk.StringVar(value="Izbranih PR: 0")
        self.account_var = tk.StringVar(value=str(profile.get("last_account") or self.config.get("last_account") or self.config.get("pr_default_account") or "4190"))
        self.account_name_var = tk.StringVar(value="")
        self.remember_supplier_var = tk.BooleanVar(value=True)
        self.ir_selection_var = tk.StringVar(value="Izbranih IR: 0")
        self.ir_account_var = tk.StringVar(value=str(profile.get("last_ir_account") or self.config.get("last_ir_account") or self.config.get("ir_revenue_account") or "7601"))
        self.ir_account_name_var = tk.StringVar(value="")
        self.remember_customer_var = tk.BooleanVar(value=True)
        self.auto_reopen_var = tk.BooleanVar(value=bool(self.config.get("auto_reopen_last_source", True)))
        self.summary_vars = {
            "ir_count": tk.StringVar(value="0"),
            "ir_value": tk.StringVar(value="0,00 EUR"),
            "pr_count": tk.StringVar(value="0"),
            "pr_value": tk.StringVar(value="0,00 EUR"),
            "tax_only": tk.StringVar(value="0"),
            "tax_only_detail": tk.StringVar(value="Prenese se v PR, ne v IR"),
        }
        self.ddvo_taxpayer_var = tk.StringVar(value="Davčna številka: —")
        self.ddvo_period_var = tk.StringVar(value="Obdobje: —")
        self.ddvo_flags_var = tk.StringVar(value="Vračilo: —  •  Odbitni delež: —")
        self.ddvo_output_var = tk.StringVar(value="0,00 EUR")
        self.ddvo_output_detail_var = tk.StringVar(value="vsota polj 21–26")
        self.ddvo_input_var = tk.StringVar(value="0,00 EUR")
        self.ddvo_input_detail_var = tk.StringVar(value="vsota polj 41–43")
        self.ddvo_result_var = tk.StringVar(value="0,00 EUR")
        self.ddvo_result_detail_var = tk.StringVar(value="polje 51 / 52")
        self.ddvo_control_var = tk.StringVar(value="Kontrolni podatek bo izračunan po odprtju KIR/KPR.")
        api_settings_path = minimax_api.resolve_settings_path(str(self.config.get("minimax_settings_path") or ""))
        self.api_settings_path_var = tk.StringVar(value=str(api_settings_path))
        self.api_status_var = tk.StringVar(value="Povezava še ni preverjena.")
        self.api_org_var = tk.StringVar(value="")
        journal_status = str(self.config.get("minimax_journal_status") or "O").upper()
        self.api_journal_status_var = tk.StringVar(value="O — osnutek" if journal_status != "P" else "P — potrjeno")
        transfer_mode = str(profile.get("minimax_api_transfer_mode") or self.config.get("minimax_api_transfer_mode") or "journal")
        self.api_transfer_mode_var = tk.StringVar(
            value="Izdani/Prejeti račun — osnutek" if transfer_mode == "invoice" else "Temeljnica + DDV"
        )
        self.api_ir_numbering_var = tk.StringVar(value=str(profile.get("minimax_ir_numbering_id") or ""))
        self.api_pr_numbering_var = tk.StringVar(value=str(profile.get("minimax_pr_numbering_id") or ""))
        self.api_ir_item_var = tk.StringVar(value=str(profile.get("minimax_ir_item_id") or ""))
        self.api_due_days_var = tk.StringVar(value=str(profile.get("minimax_due_days") or "8"))
        self.api_vat_type_ir_var = tk.StringVar(value=str(profile.get("minimax_vat_type_ir") or "OD — Obračuna se DDV"))
        self.api_vat_type_pr_var = tk.StringVar(value=str(profile.get("minimax_vat_type_pr") or "— običajni PR (brez posebne vrste)"))
        self.api_pr_companion_var = tk.BooleanVar(value=bool(profile.get("minimax_pr_companion_journal", False)))
        self.api_ir_numbering_values: list[str] = []
        self.api_pr_numbering_values: list[str] = []
        self.api_ir_item_values: list[str] = []
        self.api_vat_type_ir_values: list[str] = ["OD — Obračuna se DDV"]
        self.api_vat_type_pr_values: list[str] = ["— običajni PR (brez posebne vrste)"]
        self.api_help_var = tk.StringVar(value="Oddaja ustvari temeljnico in nato ločeno preverjeno DDV-vrstico.")
        self.api_selection_var = tk.StringVar(value="Izbranih za oddajo: 0")
        saved_api_filter = str(profile.get("minimax_api_view_filter") or "ALL").upper()
        self.api_view_filter = saved_api_filter if saved_api_filter in {"ALL", "IR", "PR"} else "ALL"
        self.api_view_filter_var = tk.StringVar(value="Prikaz: vsi računi")
        self.ir_search_var = tk.StringVar(value="")
        self.pr_search_var = tk.StringVar(value="")
        self.ddvo_search_var = tk.StringVar(value="")
        self.ddvo_view_mode = "json"  # json | compare (JSON + Minimax)
        self.api_search_var = tk.StringVar(value="")
        self.knjiga_ir_search_var = tk.StringVar(value="")
        self.knjiga_pr_search_var = tk.StringVar(value="")
        self.knjiga_view_mode = "json"  # json | api
        self.knjiga_summary_var = tk.StringVar(
            value="Knjige: predogled JSON (KIR/KPR) ali Minimax API — izberi vir."
        )
        self.knjiga_records: dict[str, list[dict[str, Any]]] = {"IR": [], "PR": []}
        self.knjiga_period: tuple[str, str] | None = None
        self.knjiga_view_var = tk.StringVar(value="Predogled: JSON")
        # Stolpci: chk (prikaz) + sumarni zneski po knjigi.
        self.knjiga_column_vars: dict[str, dict[str, tk.BooleanVar]] = {"IR": {}, "PR": {}}
        self.knjiga_totals_labels: dict[str, dict[str, tk.Label]] = {"IR": {}, "PR": {}}
        self.knjiga_totals_frames: dict[str, tk.Misc | None] = {"IR": None, "PR": None}
        self.knjiga_totals_inner: dict[str, tk.Misc | None] = {"IR": None, "PR": None}
        self.knjiga_totals_amounts: dict[str, dict[str, Decimal]] = {"IR": {}, "PR": {}}
        self.knjiga_totals_headings: dict[str, dict[str, str]] = {"IR": {}, "PR": {}}
        self.api_item_sent_info: dict[str, dict[str, Any]] = {}
        self.playwright_session_var = tk.StringVar(value="Seja: še ni preverjena")
        self.playwright_profile_var = tk.StringVar(value="Skupni profil se uporablja za vsa podjetja istega Minimax uporabnika.")
        try:
            saved_navigation_width = int(self.config.get("navigation_width") or NAVIGATION_DEFAULT_WIDTH)
        except (TypeError, ValueError):
            saved_navigation_width = NAVIGATION_DEFAULT_WIDTH
        self.navigation_width = max(NAVIGATION_MIN_WIDTH, min(600, saved_navigation_width))
        self._navigation_guard_job: str | None = None

        self.root.title(APP_DISPLAY_TITLE)
        try:
            self.root.geometry(str(self.config.get("window_geometry") or "1480x900"))
        except tk.TclError:
            self.root.geometry("1480x900")
        self.root.minsize(1120, 700)
        self.root.configure(bg=self.colors["bg"])
        self._build_menu()
        self._build_layout()
        self._seed_and_refresh_recent_sessions()
        self._on_api_mode_changed(save=False)
        self._set_account_catalog(self.account_catalog)
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            import kirkpr_force_exit as force_exit

            force_exit.start_all()
        except Exception:
            pass
        try:
            self.notebook.select(max(0, min(4, int(self.config.get("active_tab", 0)))))
        except (tk.TclError, TypeError, ValueError):
            pass
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._on_tab_changed()
        saved_window_state = str(self.config.get("window_state") or "normal")
        if saved_window_state in {"normal", "zoomed"}:
            self.root.after(0, lambda: self.root.state(saved_window_state))

        last_source_value = str(self._profile_config().get("last_source_file") or self.config.get("last_source_file") or "")
        if initial_source:
            self.root.after(120, lambda: self.load_source(initial_source))
        elif self.auto_reopen_var.get() and last_source_value:
            if self._is_projest_vasco_source(Path(last_source_value)):
                self._forget_projest_vasco_last_source()
                self.status_var.set(
                    "Zadnji vir je bil Vasco/SQLite — uvoz je v ProJest Studio. Odpri FURS ZIP/JSON."
                )
            else:
                self.root.after(180, lambda: self.open_last_source(silent=True))

    def _profile_config(self) -> dict[str, Any]:
        if not self.active_company:
            return self.config
        return core.company_profile(self.config, company_registry.company_key(self.active_company))

    def _active_company_text(self) -> str:
        if not self.active_company:
            return "Podjetje: ni izbrano"
        name = company_registry.company_name(self.active_company)
        zst = company_registry.company_zst(self.active_company) or "—"
        org_id = company_registry.company_org_id(self.active_company) or "brez Org_ID"
        return f"Podjetje: {zst} • {name} • Minimax {org_id}"

    def _trops_root(self) -> Path:
        return company_registry.resolve_trops_root(str(self.config.get("trops_root") or "") or None)

    def _company_paths(self) -> company_registry.CompanyPaths | None:
        if not self.active_company:
            return None
        if self.dataset:
            start, end = self._filter_iso_bounds()
        else:
            start = end = ""
        try:
            return company_registry.company_paths(
                self.active_company,
                start,
                end,
                trops_root=self._trops_root(),
            )
        except ValueError:
            return None

    def _account_name(self, account: Any) -> str:
        return self.account_catalog.get(str(account or "").strip(), "")

    def _account_label(self, account: Any) -> str:
        code = str(account or "").strip()
        name = self._account_name(code)
        return f"{code} — {name}" if code and name else code

    @staticmethod
    def _account_code(value: Any) -> str:
        return core.normalize_account_code(value)

    def _validated_account_code(self, value: Any) -> str:
        """Polna Minimax šifra; zavrne prekratke (417 → uporabi 4170)."""
        catalog = self.account_catalog or None
        return core.validate_minimax_account_code(value, catalog=catalog)

    def _account_choices(self) -> tuple[str, ...]:
        if self.account_catalog:
            def key(code: str) -> tuple[int, int, str]:
                return (0, int(code), code) if code.isdigit() else (1, 0, code.casefold())
            return tuple(self._account_label(code) for code in sorted(self.account_catalog, key=key))
        return tuple(dict.fromkeys((*COMMON_PR_ACCOUNTS, *COMMON_IR_ACCOUNTS)))

    @staticmethod
    def _account_search_value(value: Any) -> str:
        """Normalizira iskanje, da »stroski« najde tudi »Stroški«."""
        normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(character for character in normalized if not unicodedata.combining(character))

    def _filtered_account_choices(self, query: Any) -> tuple[str, ...]:
        """Filtrira šifrant po poljubnem delu šifre ali naziva konta."""
        choices = self._account_choices()
        terms = self._account_search_value(query).split()
        if not terms:
            return choices
        return tuple(
            label
            for label in choices
            if all(term in self._account_search_value(label) for term in terms)
        )

    def _configure_account_filter(
        self,
        combo: ttk.Combobox,
        value_var: tk.StringVar,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        """Editable Combobox sproti omeji na konte, ki ustrezajo vpisanemu filtru."""
        def apply_filter(_event: tk.Event | None = None) -> None:
            current = value_var.get().strip()
            all_choices = self._account_choices()
            # Puščica na že izbranem polnem kontu ponovno pokaže ves šifrant;
            # vpisan del šifre ali besedila pa ostane dejanski filter.
            choices = all_choices if _event is None and current in all_choices else self._filtered_account_choices(current)
            combo.configure(values=choices)
            if on_change:
                on_change()

        combo.configure(postcommand=apply_filter)
        combo.bind("<KeyRelease>", apply_filter, add="+")

    def _set_account_catalog(self, entries: list[dict[str, Any]] | Mapping[str, Any]) -> None:
        if isinstance(entries, Mapping):
            catalog = {str(code): str(name) for code, name in entries.items() if str(code).strip()}
        else:
            catalog = {
                str(entry.get("code") or "").strip(): str(entry.get("name") or "").strip()
                for entry in entries
                if str(entry.get("code") or "").strip()
            }
        self.account_catalog = catalog
        profile = self._profile_config()
        profile["account_catalog"] = dict(catalog)
        choices = self._account_choices()
        if hasattr(self, "account_combo"):
            self.account_combo.configure(values=choices)
        if hasattr(self, "ir_account_combo"):
            self.ir_account_combo.configure(values=choices)
        if hasattr(self, "account_var"):
            self.account_name_var.set(self._account_name(self._account_code(self.account_var.get())))
            self.ir_account_name_var.set(self._account_name(self._account_code(self.ir_account_var.get())))

    def _refresh_account_name_labels(self) -> None:
        self.account_name_var.set(self._account_name(self._account_code(self.account_var.get())))
        self.ir_account_name_var.set(self._account_name(self._account_code(self.ir_account_var.get())))

    def _mark_working_dirty(self, detail: str = "") -> None:
        self.working_dirty = True
        detail = str(detail or "").strip()
        if detail:
            self.pending_working_changes.append(detail)
        self.format_var.set(f"Format: {self.dataset.source_format if self.dataset else '—'} • delovna kopija spremenjena")

    def _configure_gui_style(self) -> dict[str, str]:
        theme = str(self.config.get("gui_theme") or gui_style.DEFAULT_THEME)
        return gui_style.configure_app_style(self.root, theme=theme)

    def _on_gui_theme_chosen(self) -> None:
        theme = gui_style.normalize_theme(self.gui_theme_var.get())
        self.gui_theme_var.set(theme)
        self.config["gui_theme"] = theme
        try:
            self._save_session_state()
        except OSError:
            pass
        messagebox.showinfo(
            "Videz",
            "Izbrani videz se v celoti uveljavi ob naslednjem zagonu programa.\n"
            "Trops je svetla preobleka; klasični videz je prejšnji temni slog.",
        )

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Odpri podatke…\tCtrl+O", command=self.choose_source)
        file_menu.add_command(label="Podatki iz Minimaxa…\tCtrl+Shift+M", command=self.load_data_from_minimax)
        file_menu.add_command(label="Odpri zadnjo datoteko\tCtrl+L", command=self.open_last_source)
        file_menu.add_command(
            label="Pridobivanje in prenos (ZIP → API/XML)…",
            command=self.open_source_acquisition_settings,
        )
        file_menu.add_command(label="Shrani konta\tCtrl+S", command=self.save_accounts)
        file_menu.add_command(label="Shrani delovno kopijo pod novim imenom\tCtrl+Shift+S", command=self.save_working_copy)
        file_menu.add_checkbutton(
            label="Ob zagonu ponovno odpri zadnjo datoteko",
            variable=self.auto_reopen_var,
            command=self._save_auto_reopen_preference,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Izvozi Minimax XML/ZIP…\tCtrl+E", command=self.export_files)
        file_menu.add_command(label="Minimax API povezava", command=lambda: self.notebook.select(3))
        file_menu.add_command(label="Knjige IR/PR (Minimax)…", command=lambda: self.notebook.select(4))
        file_menu.add_command(label="Prikaži levi panel\tCtrl+B", command=self.show_navigation_panel)
        file_menu.add_command(label="Odpri zadnjo izhodno mapo", command=self.open_last_export)
        file_menu.add_separator()
        file_menu.add_command(label="Nastavitve poti…", command=self.open_path_settings)
        file_menu.add_command(
            label="Uredi predlogo e-pošte DDV + virman…",
            command=self.open_ddvo_email_template_editor,
        )
        file_menu.add_command(label="Odpri dnevnik…", command=self.open_log_file)
        file_menu.add_separator()
        file_menu.add_command(
            label="FORCE EXIT (kill)\tCtrl+Shift+F12",
            command=lambda: __import__("kirkpr_force_exit").confirm_force_kill(parent=self.root),
        )
        file_menu.add_command(
            label="Odpri kill okno (če UI visi)…",
            command=lambda: __import__("kirkpr_force_exit").start_guardian_window(),
        )
        file_menu.add_command(label="Izhod", command=self.on_close)
        menu.add_cascade(label="Datoteka", menu=file_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        self.gui_theme_var = tk.StringVar(value=gui_style.current_theme())
        view_menu.add_radiobutton(
            label="Videz Trops",
            variable=self.gui_theme_var,
            value="trops",
            command=self._on_gui_theme_chosen,
        )
        view_menu.add_radiobutton(
            label="Klasični videz",
            variable=self.gui_theme_var,
            value="classic",
            command=self._on_gui_theme_chosen,
        )
        menu.add_cascade(label="Videz", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Podprti formati", command=self.show_format_help)
        help_menu.add_command(label="Kaj je novega (Cursor)", command=self.show_cursor_changelog)
        help_menu.add_command(label="O programu", command=self.show_about)
        menu.add_cascade(label="Pomoč", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=(18, 16, 18, 0))
        container.pack(fill="both", expand=True)

        _header, actions, source_meta = gui_style.pack_purple_header(
            container,
            APP_DISPLAY_TITLE,
            subtitle=(
                "Uvoz FURS / Minimax API • DDV-O • knjige IR/PR • Cursor izdaja"
                f" • Chrome dodatek v{CHROME_EXTENSION_VERSION}"
            ),
            pad=(22, 16),
        )
        open_button = gui_style.PillButton(
            actions,
            "Odpri podatke",
            command=self.choose_source,
            bg=gui_style.BTN_GREY,
            hover=gui_style.BTN_GREY_HOVER,
        )
        open_button.pack(side="left", padx=(0, 4))
        minimax_data_btn = gui_style.PillButton(
            actions,
            "Podatki iz Minimaxa",
            command=self.load_data_from_minimax,
            bg=gui_style.BTN_PURPLE,
            hover=gui_style.HEADER_PURPLE_SOFT,
            padx=10,
        )
        minimax_data_btn.pack(side="left", padx=(0, 4))
        self.minimax_data_button = minimax_data_btn
        source_cfg_btn = gui_style.PillButton(
            actions,
            "⚙ Vir",
            command=self.open_source_acquisition_settings,
            bg=gui_style.BTN_BLUE,
            hover=gui_style.BTN_BLUE_HOVER,
            padx=10,
        )
        source_cfg_btn.pack(side="left", padx=(0, 8))
        save_button = gui_style.PillButton(
            actions,
            "Shrani delovno kopijo",
            command=self.save_working_copy,
            bg=gui_style.BTN_GREY,
            hover=gui_style.BTN_GREY_HOVER,
        )
        save_button.pack(side="left", padx=(0, 8))
        api_button = gui_style.PillButton(
            actions,
            "Minimax API",
            command=lambda: self.notebook.select(3),
            bg=gui_style.BTN_BLUE,
            hover=gui_style.BTN_BLUE_HOVER,
        )
        api_button.pack(side="left", padx=(0, 8))
        self.export_button = gui_style.PillButton(
            actions,
            "Izvozi XML + ZIP",
            command=self.export_files,
            bg=gui_style.BTN_GREEN,
            hover=gui_style.BTN_GREEN_HOVER,
            state="disabled",
        )
        self.export_button.pack(side="left")
        import kirkpr_force_exit as force_exit

        force_exit.attach_force_exit_button(actions, pack_side="right", padx=(16, 0))
        ToolTip(open_button, "Odpre ZIP, JSON, XML ali CSV in samodejno zazna vsebino.")
        ToolTip(
            minimax_data_btn,
            "Najprej temeljnice knjige IR/PR (polni stolpci FURS / DDV-O). "
            "Če knjige ni (npr. Dišport PR samo v modulu), dopolni iz "
            "izdanih/prejetih računov.",
        )
        ToolTip(
            source_cfg_btn,
            "Pridobi KIR/KPR iz ZIP/JSON/XML/CSV, nato prenos: Minimax API ali XML za uvoz.",
        )
        ToolTip(save_button, "Pokaže začasne popravke, zahteva potrditev in jih shrani v novo delovno JSON kopijo.")
        ToolTip(api_button, "Odpre povezavo, predpreverjanje in neposredno oddajo temeljnic v Minimax API.")

        # Vir / podjetje / obdobje — združeno v isti glavi (2. vrstica).
        meta_bg = gui_style.HEADER_PURPLE_SOFT
        source_icon = tk.Label(
            source_meta,
            text="KIR\nKPR",
            bg=gui_style.HEADER_PURPLE,
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=5,
        )
        source_icon.pack(side="left", padx=(0, 10))
        source_info = tk.Frame(source_meta, bg=meta_bg)
        source_info.pack(side="left", fill="x", expand=True)
        tk.Label(
            source_info,
            textvariable=self.company_var,
            bg=meta_bg,
            fg=gui_style.COLORS["header_muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            source_info,
            textvariable=self.source_var,
            bg=meta_bg,
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w")
        metadata = tk.Frame(source_info, bg=meta_bg)
        metadata.pack(fill="x", pady=(2, 0))
        for var in (self.format_var, self.period_var, self.member_var):
            tk.Label(
                metadata,
                textvariable=var,
                bg=meta_bg,
                fg=gui_style.COLORS["header_muted"],
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(0, 14))
        xsd = core.find_xsd()
        badge_text = "XSD VKLOPLJEN" if xsd else "BREZ XSD"
        badge_color = self.colors["success"] if xsd else self.colors["warning"]
        badge_fg = self.colors["on_success"] if xsd else self.colors["on_warning"]
        tk.Label(
            source_meta,
            text=badge_text,
            bg=badge_color,
            fg=badge_fg,
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=5,
        ).pack(side="right")

        self._build_period_filter_bar(container)

        summary_sec = gui_style.CollapsibleSection(
            container,
            "Povzetek IR / PR",
            bg=self.colors["bg"],
            muted=self.colors["muted"],
            initially_open=bool(self.config.get("ui_summary_open", True)),
            padx=4,
            pady=4,
            on_toggle=lambda _open: self._persist_ui_section_state(),
        )
        summary_sec.pack(fill="x", pady=(10, 0))
        self.ui_summary_section = summary_sec
        summary = ttk.Frame(summary_sec.body)
        summary.pack(fill="x")
        summary.columnconfigure((0, 1, 2), weight=1, uniform="summary")
        self._summary_card(summary, 0, "IZDANI RAČUNI (IR)", self.summary_vars["ir_count"], self.summary_vars["ir_value"], self.colors["accent"])
        self._summary_card(summary, 1, "PREJETI RAČUNI (PR)", self.summary_vars["pr_count"], self.summary_vars["pr_value"], self.colors["purple"])
        self._summary_card(summary, 2, "KIR SAMOOBDAVČITEV", self.summary_vars["tax_only"], self.summary_vars["tax_only_detail"], self.colors["warning"])

        self.workspace_paned = ttk.Panedwindow(container, orient="horizontal")
        self.workspace_paned.pack(fill="both", expand=True, pady=(10, 8))
        navigation = ttk.Frame(
            self.workspace_paned,
            style="Sidebar.TFrame",
            padding=(10, 10),
            width=self.navigation_width,
        )
        self.navigation_panel = navigation
        content = ttk.Frame(self.workspace_paned, style="Panel.TFrame")
        self.workspace_paned.add(navigation, weight=0)
        self.workspace_paned.add(content, weight=1)
        self._build_navigation(navigation)

        self.notebook = ttk.Notebook(content)
        self.notebook.pack(fill="both", expand=True)
        ir_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        pr_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        ddvo_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        api_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        knjige_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(6, 6))
        self.notebook.add(ir_tab, text="  Izdani računi (IR)  ")
        self.notebook.add(pr_tab, text="  Prejeti računi (PR)  ")
        self.notebook.add(ddvo_tab, text="  DDV-O  ")
        self.notebook.add(api_tab, text="  Minimax API  ")
        self.notebook.add(knjige_tab, text="  Knjige  ")
        self.ir_tree = self._build_ir_tree(ir_tab)
        self._build_ir_account_bar(ir_tab)
        self.pr_tree = self._build_pr_tree(pr_tab)
        self._build_pr_account_bar(pr_tab)
        self._build_ddvo_tab(ddvo_tab)
        self._build_api_tab(api_tab)
        self._build_knjige_tab(knjige_tab)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_main_notebook_tab_changed, add="+")
        self.workspace_paned.bind("<Configure>", self._schedule_navigation_width_guard, add="+")
        self.workspace_paned.bind("<ButtonRelease-1>", self._on_navigation_sash_released, add="+")
        self.root.after(150, self._set_initial_navigation_width)

        status = ttk.Frame(self.root, style="Panel.TFrame")
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(side="left", fill="x", expand=True)
        import kirkpr_force_exit as force_exit

        force_exit.attach_force_exit_button(status, pack_side="right", padx=(8, 10))
        ttk.Label(
            status,
            text="Ctrl+Shift+F12 kill  •  Ctrl+O odpri  •  Ctrl+S shrani",
            style="Status.TLabel",
        ).pack(side="right")

    def _build_period_filter_bar(self, parent: ttk.Frame) -> None:
        period_sec = gui_style.CollapsibleSection(
            parent,
            "Obdobje",
            bg=gui_style.COLORS["card"],
            muted=self.colors["muted"],
            initially_open=bool(self.config.get("ui_period_open", True)),
            padx=8,
            pady=6,
            on_toggle=lambda _open: self._persist_ui_section_state(),
        )
        period_sec.pack(fill="x", pady=(10, 0))
        self.ui_period_section = period_sec
        bar = period_sec.body
        tk.Label(bar, text="Mesec", bg=gui_style.COLORS["card"], fg=self.colors["muted"]).pack(side="left", padx=(0, 8))

        gui_style.pill(bar, "‹", lambda: self.shift_period_filter(-1), kind="grey", padx=8, pady=3).pack(side="left")
        self.filter_month_combo = ttk.Combobox(
            bar,
            textvariable=self.filter_month_var,
            values=PERIOD_CHOICES,
            state="readonly",
            width=14,
        )
        self.filter_month_combo.pack(side="left", padx=(6, 4))
        self.filter_month_combo.bind("<<ComboboxSelected>>", self._on_period_month_year_changed)
        self.filter_year_spin = tk.Spinbox(
            bar,
            from_=2000,
            to=2100,
            textvariable=self.filter_year_var,
            width=6,
            command=self._on_period_month_year_changed,
            bg=self.colors["input"],
            fg=self.colors["text"],
            buttonbackground=gui_style.BTN_GREY,
            relief="flat",
            insertbackground=self.colors["text"],
        )
        self.filter_year_spin.pack(side="left", padx=(0, 4))
        self.filter_year_spin.bind("<Return>", self._on_period_month_year_changed)
        self.filter_year_spin.bind("<FocusOut>", self._on_period_month_year_changed)
        next_month = gui_style.pill(bar, "›", lambda: self.shift_period_filter(1), kind="grey", padx=8, pady=3)
        next_month.pack(side="left", padx=(0, 14))
        ToolTip(next_month, "Naslednji mesec / razpon (ni skrči — klikni naslov »Obdobje« za skrči/razširi).")

        tk.Label(bar, text="Datum od", bg=gui_style.COLORS["card"], fg=self.colors["muted"]).pack(side="left", padx=(0, 6))
        from_entry = ttk.Entry(bar, textvariable=self.filter_from_var, width=12)
        from_entry.pack(side="left")
        from_entry.bind("<Return>", self._on_period_dates_changed)
        from_entry.bind("<FocusOut>", self._on_period_dates_changed)
        tk.Label(bar, text="Datum do", bg=gui_style.COLORS["card"], fg=self.colors["muted"]).pack(side="left", padx=(12, 6))
        to_entry = ttk.Entry(bar, textvariable=self.filter_to_var, width=12)
        to_entry.pack(side="left")
        to_entry.bind("<Return>", self._on_period_dates_changed)
        to_entry.bind("<FocusOut>", self._on_period_dates_changed)

        gui_style.pill(bar, "Uporabi", self.apply_period_filter, kind="blue").pack(side="left", padx=(14, 6))
        gui_style.pill(bar, "Vsa obdobja", self.reset_period_filter_to_data, kind="grey").pack(side="left", padx=(0, 10))
        tk.Label(
            bar,
            textvariable=self.filter_info_var,
            bg=gui_style.COLORS["card"],
            fg=self.colors["muted"],
        ).pack(side="left", fill="x", expand=True)

        ToolTip(
            self.filter_month_combo,
            "Mesec ali razpon (jan-mar … jan-dec), kot v Fakturiranju. Filter po P4.",
        )
        ToolTip(from_entry, "Začetek obdobja (DD.MM.LLLL). Filter po datumu P4 v vrstici.")
        ToolTip(to_entry, "Konec obdobja. Velja za tabele, DDV-O, JSON pogled in Minimax API.")

        self._build_sessions_bar(parent)

    def _build_sessions_bar(self, parent: ttk.Frame) -> None:
        """Vrstica sej: combobox + Odpri / Shrani / Uredi / Briši (SQLite)."""
        seje_sec = gui_style.CollapsibleSection(
            parent,
            "Seje",
            bg=gui_style.COLORS["card"],
            muted=self.colors["muted"],
            initially_open=bool(self.config.get("ui_sessions_open", True)),
            padx=8,
            pady=6,
            on_toggle=lambda _open: self._persist_ui_section_state(),
        )
        seje_sec.pack(fill="x", pady=(8, 0))
        self.ui_sessions_section = seje_sec
        bar = seje_sec.body
        self.recent_session_combo = ttk.Combobox(
            bar,
            textvariable=self.recent_session_var,
            state="readonly",
            width=52,
        )
        self.recent_session_combo.pack(side="left", fill="x", expand=True)
        self.recent_session_combo.bind("<<ComboboxSelected>>", self._on_recent_session_combo_pick)
        self.recent_session_combo.bind("<Double-Button-1>", lambda _e: self.open_selected_session())

        btn_open = gui_style.pill(bar, "Odpri sejo", self.open_selected_session, kind="grey")
        btn_open.pack(side="left", padx=(10, 0))
        btn_save = gui_style.pill(bar, "Shrani sejo", self.save_current_session, kind="blue")
        btn_save.pack(side="left", padx=(6, 0))
        btn_edit = gui_style.pill(bar, "Uredi", self.edit_selected_session, kind="grey")
        btn_edit.pack(side="left", padx=(6, 0))
        btn_del = gui_style.pill(bar, "Briši", self.delete_selected_session, kind="red")
        btn_del.pack(side="left", padx=(6, 0))

        ToolTip(
            self.recent_session_combo,
            "Shranjene seje (SQLite): ob izbiri nastavi firmo + obdobje. "
            "»Odpri sejo«: vpraša SQL/datoteka ali svež Minimax API. "
            "Briši odstrani sejo s seznama.",
        )
        ToolTip(
            btn_open,
            "Odpre sejo: najprej vpraša — shranjena datoteka (hitro) ali Minimax API (počasi).",
        )
        ToolTip(
            btn_save,
            "Shrani trenutno stanje kot sejo (delovna kopija + meta v kirkpr_sessions.sqlite3).",
        )
        ToolTip(btn_edit, "Preimenuj sejo / uredi opombo.")
        ToolTip(btn_del, "Odstrani sejo s seznama (datoteke ostanejo).")

    def _on_main_notebook_tab_changed(self, _event: tk.Event | None = None) -> None:
        """Na zavihku Knjige skrči zgornje panele → več prostora za tabelo."""
        try:
            tab = self.notebook.select()
            text = self.notebook.tab(tab, "text")
        except tk.TclError:
            return
        is_knjige = "Knjige" in str(text)
        sections = {
            "period": getattr(self, "ui_period_section", None),
            "sessions": getattr(self, "ui_sessions_section", None),
            "summary": getattr(self, "ui_summary_section", None),
        }
        if is_knjige:
            if getattr(self, "_ui_sections_before_knjige", None) is None:
                self._ui_sections_before_knjige = {
                    key: bool(getattr(sec, "_open", True)) if sec is not None else True
                    for key, sec in sections.items()
                }
            for sec in sections.values():
                if sec is not None:
                    sec.set_open(False)
        else:
            saved = getattr(self, "_ui_sections_before_knjige", None)
            if saved:
                for key, sec in sections.items():
                    if sec is not None:
                        sec.set_open(bool(saved.get(key, True)))
                self._ui_sections_before_knjige = None
        self._persist_ui_section_state()

    def _persist_ui_section_state(self) -> None:
        """Shrani želeno odprtost panelov (med Knjigami: stanje pred skrčenjem)."""
        saved = getattr(self, "_ui_sections_before_knjige", None)
        if saved is not None:
            self.config["ui_period_open"] = bool(saved.get("period", True))
            self.config["ui_sessions_open"] = bool(saved.get("sessions", True))
            self.config["ui_summary_open"] = bool(saved.get("summary", True))
            return
        for key, attr in (
            ("ui_period_open", "ui_period_section"),
            ("ui_sessions_open", "ui_sessions_section"),
            ("ui_summary_open", "ui_summary_section"),
        ):
            sec = getattr(self, attr, None)
            if sec is not None:
                self.config[key] = bool(getattr(sec, "_open", True))

    def _filter_iso_bounds(self) -> tuple[str, str]:
        return self.filter_from_date.isoformat(), self.filter_to_date.isoformat()

    def _sync_period_filter_vars(self) -> None:
        self._period_filter_updating = True
        try:
            self.filter_month_var.set(period_label_for_range(self.filter_from_date, self.filter_to_date))
            self.filter_year_var.set(str(self.filter_from_date.year))
            self.filter_from_var.set(format_si_date(self.filter_from_date))
            self.filter_to_var.set(format_si_date(self.filter_to_date))
        finally:
            self._period_filter_updating = False

    def _set_period_filter(self, start: date, end: date, *, refresh: bool = True) -> None:
        if end < start:
            start, end = end, start
        self.filter_from_date = start
        self.filter_to_date = end
        self._sync_period_filter_vars()
        if refresh:
            self.apply_period_filter()

    def shift_period_filter(self, delta: int) -> None:
        # Enako kot Fakturiranje: kroži po seznamu (meseci + razponi).
        label = period_label_for_range(self.filter_from_date, self.filter_to_date)
        try:
            index = PERIOD_CHOICES.index(label)
        except ValueError:
            index = max(0, self.filter_from_date.month - 1)
        index = (index + int(delta)) % len(PERIOD_CHOICES)
        year = self.filter_from_date.year
        bounds = period_bounds(year, PERIOD_CHOICES[index])
        if bounds is None:
            bounds = month_bounds(year, self.filter_from_date.month)
        self._set_period_filter(bounds[0], bounds[1], refresh=True)

    def _on_period_month_year_changed(self, _event: Any = None) -> None:
        if self._period_filter_updating:
            return
        try:
            year = int(str(self.filter_year_var.get()).strip())
        except ValueError:
            year = self.filter_from_date.year
        bounds = period_bounds(year, self.filter_month_var.get())
        if bounds is None:
            bounds = month_bounds(year, self.filter_from_date.month)
        self._set_period_filter(bounds[0], bounds[1], refresh=True)

    def _on_period_dates_changed(self, _event: Any = None) -> None:
        if self._period_filter_updating:
            return
        start = parse_iso_date(self.filter_from_var.get())
        end = parse_iso_date(self.filter_to_var.get())
        if start is None or end is None:
            return
        self.filter_from_date = start
        self.filter_to_date = end if end >= start else start
        self._sync_period_filter_vars()
        self.apply_period_filter()

    def reset_period_filter_to_data(self) -> None:
        if self.data_span_from and self.data_span_to:
            self._set_period_filter(self.data_span_from, self.data_span_to, refresh=True)
            return
        if self.dataset:
            start = parse_iso_date(self.dataset.period_from) or self.filter_from_date
            end = parse_iso_date(self.dataset.period_to) or self.filter_to_date
            self._set_period_filter(start, end, refresh=True)
            return
        self.apply_period_filter()

    def apply_period_filter(self) -> None:
        start = parse_iso_date(self.filter_from_var.get()) or self.filter_from_date
        end = parse_iso_date(self.filter_to_var.get()) or self.filter_to_date
        if end < start:
            start, end = end, start
        self.filter_from_date = start
        self.filter_to_date = end
        self._sync_period_filter_vars()
        if not self.dataset:
            self.filter_info_var.set("Najprej odprite podatke — filter bo veljal za JSON in Minimax.")
            return
        visible_ir = sum(1 for row in self.dataset.kir if self._row_in_period("IR", row))
        visible_pr = sum(1 for row in self.dataset.kpr if self._row_in_period("PR", row))
        total = len(self.dataset.kir) + len(self.dataset.kpr)
        self.filter_info_var.set(
            f"Filter {format_si_date(start)} – {format_si_date(end)} · P4: "
            f"IR {visible_ir}/{len(self.dataset.kir)}, PR {visible_pr}/{len(self.dataset.kpr)} "
            f"(skupaj {visible_ir + visible_pr}/{total})"
        )
        self._populate_trees()
        self._update_header_and_summary()
        self._invalidate_knjige_for_period_change()
        self.status_var.set(
            f"Obdobje filtrirano: {format_si_date(start)} – {format_si_date(end)} "
            f"(JSON + Minimax: {visible_ir + visible_pr} računov)."
        )

    def _row_in_period(self, book: str, row: Mapping[str, Any]) -> bool:
        """Vključi vrstico v IR/PR/API, če je datum P4 znotraj Datum od–do."""
        parsed = row_filter_date(book, row)
        if parsed is None:
            return True
        return self.filter_from_date <= parsed <= self.filter_to_date

    def _row_in_knjiga_period(self, row: Mapping[str, Any]) -> bool:
        """FURS knjiga / eDavki: davčno obdobje (OBDOBJE), enako kot DDV-O — ne samo P4."""
        return self._row_in_ddvo_period(row)

    def _row_in_ddvo_period(self, row: Mapping[str, Any]) -> bool:
        """Vključi vrstico v DDV-O po davčnem obdobju (OBDOBJE/P2), ne samo P4."""
        header_year = self.filter_from_date.year
        if self.dataset:
            header_from = parse_iso_date(self.dataset.period_from)
            if header_from is not None:
                header_year = header_from.year
        return row_in_ddvo_period(
            row,
            self.filter_from_date,
            self.filter_to_date,
            header_year=header_year,
        )

    def _ddvo_view_dataset(self) -> core.KirkprDataset | None:
        """Podatki za kontrolni DDV-O (davčno obdobje, usklajeno z eDavki)."""
        if not self.dataset:
            return None
        header = dict(self.dataset.header)
        header_from = parse_iso_date(self.dataset.period_from)
        header_to = parse_iso_date(self.dataset.period_to)
        # Če filter pokriva celotno obdobje datoteke, vzemi vse vrstice (kot eDavki).
        if (
            header_from
            and header_to
            and self.filter_from_date <= header_from
            and self.filter_to_date >= header_to
        ):
            kir_rows = list(self.dataset.kir)
            kpr_rows = list(self.dataset.kpr)
        else:
            kir_rows = [row for row in self.dataset.kir if self._row_in_ddvo_period(row)]
            kpr_rows = [row for row in self.dataset.kpr if self._row_in_ddvo_period(row)]
        header["OBDOBJE_OD"] = self.filter_from_date.isoformat()
        header["OBDOBJE_DO"] = self.filter_to_date.isoformat()
        return core.KirkprDataset(
            header=header,
            kir=kir_rows,
            kpr=kpr_rows,
            source_path=self.dataset.source_path,
            source_format=self.dataset.source_format,
            source_members=list(self.dataset.source_members),
            warnings=list(self.dataset.warnings),
        )

    def _init_period_filter_from_dataset(
        self,
        *,
        prefer: tuple[date, date] | None = None,
    ) -> None:
        assert self.dataset is not None
        dates: list[date] = []
        for row in self.dataset.kir:
            parsed = row_booking_date("IR", row)
            if parsed is not None:
                dates.append(parsed)
        for row in self.dataset.kpr:
            parsed = row_booking_date("PR", row)
            if parsed is not None:
                dates.append(parsed)
        header_from = parse_iso_date(self.dataset.period_from)
        header_to = parse_iso_date(self.dataset.period_to)
        # Placeholder 2000-01-01 iz prazne/pokvarjene glave = ni obdobja.
        if header_from == date(2000, 1, 1) and header_to == date(2000, 1, 1):
            header_from = None
            header_to = None
        if dates:
            self.data_span_from = min(dates)
            self.data_span_to = max(dates)
        else:
            self.data_span_from = header_from
            self.data_span_to = header_to
        path_span = period_from_source_path(self.dataset.source_path)
        # Celotno obdobje datoteke (header / ime ZIP / podatki) — NE samo zadnji mesec.
        start = (
            header_from
            or (path_span[0] if path_span else None)
            or self.data_span_from
            or previous_month_bounds()[0]
        )
        end = (
            header_to
            or (path_span[1] if path_span else None)
            or self.data_span_to
            or previous_month_bounds()[1]
        )
        if prefer is not None:
            start, end = prefer
            # Popravi stare seje, shranjene kot »samo junij« znotraj tromesečja 4–6.
            span_from = header_from or (path_span[0] if path_span else None) or self.data_span_from
            span_to = header_to or (path_span[1] if path_span else None) or self.data_span_to
            if span_from and span_to and is_last_month_of_span(start, end, span_from, span_to):
                start, end = span_from, span_to
        self._set_period_filter(start, end, refresh=False)
        visible_ir = sum(1 for row in self.dataset.kir if self._row_in_period("IR", row))
        visible_pr = sum(1 for row in self.dataset.kpr if self._row_in_period("PR", row))
        self.filter_info_var.set(
            f"Filter {format_si_date(self.filter_from_date)} – {format_si_date(self.filter_to_date)} · P4: "
            f"IR {visible_ir}/{len(self.dataset.kir)}, PR {visible_pr}/{len(self.dataset.kpr)}"
        )

    def _view_dataset(self) -> core.KirkprDataset | None:
        """Delovni podatki, omejeni na izbrano obdobje (JSON + Minimax + DDV-O)."""
        if not self.dataset:
            return None
        header = dict(self.dataset.header)
        header["OBDOBJE_OD"] = self.filter_from_date.isoformat()
        header["OBDOBJE_DO"] = self.filter_to_date.isoformat()
        return core.KirkprDataset(
            header=header,
            kir=[row for row in self.dataset.kir if self._row_in_period("IR", row)],
            kpr=[row for row in self.dataset.kpr if self._row_in_period("PR", row)],
            source_path=self.dataset.source_path,
            source_format=self.dataset.source_format,
            source_members=list(self.dataset.source_members),
            warnings=list(self.dataset.warnings),
        )

    def _build_navigation(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="PODJETJA", style="SidebarMuted.TLabel").pack(anchor="w", padx=4, pady=(2, 5))
        company_search = ttk.Entry(parent, textvariable=self.company_search_var)
        company_search.pack(fill="x", padx=4, pady=(0, 6))
        company_search.bind("<KeyRelease>", lambda _event: self._populate_company_tree())
        company_frame = ttk.Frame(parent, style="Sidebar.TFrame")
        company_frame.pack(fill="x", padx=4, pady=(0, 9))
        self.company_tree = ttk.Treeview(
            company_frame,
            columns=("zst", "name", "org"),
            show="headings",
            height=8,
            selectmode="browse",
            style="Sidebar.Treeview",
        )
        company_scroll = ttk.Scrollbar(company_frame, orient="vertical", command=self.company_tree.yview)
        self.company_tree.configure(yscrollcommand=company_scroll.set)
        self.company_tree.grid(row=0, column=0, sticky="nsew")
        company_scroll.grid(row=0, column=1, sticky="ns")
        company_frame.columnconfigure(0, weight=1)
        self.company_tree.heading("zst", text="Zšt ▲", command=lambda: self.sort_company_tree("zst"))
        self.company_tree.heading("name", text="Podjetje", command=lambda: self.sort_company_tree("name"))
        self.company_tree.heading("org", text="Org_ID", command=lambda: self.sort_company_tree("org"))
        self.company_tree.column("zst", width=42, minwidth=38, anchor="center", stretch=False)
        self.company_tree.column("name", width=170, minwidth=110, stretch=True)
        self.company_tree.column("org", width=70, minwidth=64, anchor="center", stretch=False)
        self.company_tree.bind("<<TreeviewSelect>>", self._on_company_select)
        self._populate_company_tree()

        ttk.Label(parent, text="VSEBINA", style="SidebarMuted.TLabel").pack(anchor="w", padx=4, pady=(2, 8))
        self.nav_tree = ttk.Treeview(parent, show="tree", selectmode="browse", style="Sidebar.Treeview")
        self.nav_tree.pack(fill="both", expand=True)
        data = self.nav_tree.insert("", "end", iid="nav:data", text="  KIR/KPR podatki", open=True)
        self.nav_tree.insert(data, "end", iid="nav:ir", text="  Izdani računi")
        self.nav_tree.insert(data, "end", iid="nav:pr", text="  Prejeti računi")
        self.nav_tree.insert(data, "end", iid="nav:ddvo", text="  Obrazec DDV-O")
        minimax = self.nav_tree.insert("", "end", iid="nav:minimax", text="  Minimax", open=True)
        self.nav_tree.insert(minimax, "end", iid="nav:api", text="  API povezava in oddaja")
        self.nav_tree.insert(minimax, "end", iid="nav:knjige", text="  Knjige IR/PR")
        self.nav_tree.insert(minimax, "end", iid="nav:knjiga_ir", text="  Knjiga IR")
        self.nav_tree.insert(minimax, "end", iid="nav:knjiga_pr", text="  Knjiga PR")
        output = self.nav_tree.insert("", "end", iid="nav:output", text="  Izvoz", open=True)
        self.nav_tree.insert(output, "end", iid="nav:export", text="  Minimax XML + ZIP")
        self.nav_tree.tag_configure("root", foreground=self.colors["muted"])
        for item in (data, minimax, output):
            self.nav_tree.item(item, tags=("root",))
        self.nav_tree.selection_set("nav:ir")
        self.nav_tree.bind("<<TreeviewSelect>>", self._on_navigation_select)
        ttk.Label(
            parent,
            text="Izberite sklop. Drevo sledi aktivnemu zavihku.",
            style="SidebarMuted.TLabel",
            wraplength=280,
            justify="left",
        ).pack(fill="x", padx=4, pady=(9, 2))

    def _set_initial_navigation_width(self) -> None:
        self._apply_navigation_width(self.navigation_width)
        self.root.after(500, self._guard_navigation_width)

    def _apply_navigation_width(self, requested: int | None = None) -> None:
        """Razpre levi panel in uposteva najmanjso uporabno sirino."""
        try:
            total_width = max(0, int(self.workspace_paned.winfo_width()))
            desired = max(NAVIGATION_MIN_WIDTH, int(requested or self.navigation_width))
            if total_width > NAVIGATION_MIN_WIDTH + 620:
                desired = min(desired, total_width - 620)
            self.navigation_width = max(NAVIGATION_MIN_WIDTH, min(600, desired))
            self.navigation_panel.configure(width=self.navigation_width)
            self.workspace_paned.sashpos(0, self.navigation_width)
        except tk.TclError:
            pass

    def _schedule_navigation_width_guard(self, _event: tk.Event | None = None) -> None:
        if self._navigation_guard_job:
            try:
                self.root.after_cancel(self._navigation_guard_job)
            except tk.TclError:
                pass
        self._navigation_guard_job = self.root.after(80, self._guard_navigation_width)

    def _guard_navigation_width(self) -> None:
        self._navigation_guard_job = None
        try:
            current = int(self.workspace_paned.sashpos(0))
        except tk.TclError:
            return
        if current < NAVIGATION_MIN_WIDTH:
            self._apply_navigation_width(self.navigation_width)

    def _on_navigation_sash_released(self, _event: tk.Event | None = None) -> None:
        try:
            current = int(self.workspace_paned.sashpos(0))
        except tk.TclError:
            return
        if current < NAVIGATION_MIN_WIDTH:
            self.show_navigation_panel()
            return
        self.navigation_width = min(600, current)
        self.config["navigation_width"] = self.navigation_width

    def show_navigation_panel(self) -> None:
        """Rocno povrne levi seznam podjetij in navigacijsko drevo."""
        self.navigation_width = max(NAVIGATION_DEFAULT_WIDTH, self.navigation_width)
        self._apply_navigation_width(self.navigation_width)
        self.config["navigation_width"] = self.navigation_width
        self.status_var.set("Levi panel s podjetji in navigacijo je razširjen.")

    def _populate_company_tree(self) -> None:
        if not hasattr(self, "company_tree"):
            return
        self._updating_company_tree = True
        try:
            self.company_tree.delete(*self.company_tree.get_children())
            query = re.sub(r"\s+", " ", self.company_search_var.get().strip().casefold())
            visible: list[Mapping[str, Any]] = []
            for company in self.companies:
                haystack = " ".join(
                    (
                        company_registry.company_zst(company),
                        company_registry.company_name(company),
                        company_registry.company_tax_number(company),
                        company_registry.company_org_id(company),
                    )
                ).casefold()
                if query and any(term not in haystack for term in query.split()):
                    continue
                visible.append(company)

            column = self.company_sort_column

            def sort_key(company: Mapping[str, Any]) -> tuple[int, Any, str]:
                values = {
                    "zst": company_registry.company_zst(company),
                    "name": company_registry.company_name(company),
                    "org": company_registry.company_org_id(company),
                }
                text = str(values.get(column) or "").strip()
                if column in {"zst", "org"} and text.isdigit():
                    return (0, int(text), text)
                return (1, text.casefold(), text)

            visible.sort(key=sort_key, reverse=self.company_sort_reverse)
            for company in visible:
                key = company_registry.company_key(company)
                self.company_tree.insert(
                    "",
                    "end",
                    iid=key,
                    values=(
                        company_registry.company_zst(company),
                        company_registry.company_name(company),
                        company_registry.company_org_id(company),
                    ),
                )
            if self.active_company:
                key = company_registry.company_key(self.active_company)
                if self.company_tree.exists(key):
                    self.company_tree.selection_set(key)
                    self.company_tree.see(key)
        finally:
            self._updating_company_tree = False

    def sort_company_tree(self, column: str) -> None:
        """Sortira podjetja po Zšt, nazivu ali Org_ID; številčna stolpca sta številčna."""
        if column == self.company_sort_column:
            self.company_sort_reverse = not self.company_sort_reverse
        else:
            self.company_sort_column = column
            self.company_sort_reverse = False
        labels = {"zst": "Zšt", "name": "Podjetje", "org": "Org_ID"}
        for name, label in labels.items():
            marker = " ▼" if self.company_sort_reverse else " ▲"
            self.company_tree.heading(name, text=label + (marker if name == column else ""))
        self._populate_company_tree()

    def _clear_minimax_invoice_statuses(self) -> None:
        self.minimax_invoice_status_catalog = {
            "IR": {"by_reference": {}, "by_id": {}, "by_reference_id": {}},
            "PR": {"by_reference": {}, "by_id": {}, "by_reference_id": {}},
        }
        self.minimax_invoice_status_org = ""
        self.minimax_invoice_status_checked = False
        self.api_diff_summary = {}
        self._cleared_listinas = set()

    def _reload_active_company_from_registry(self) -> Mapping[str, Any] | None:
        """Osveži firmo iz Evidence (JSON na disku) — IBAN/AJPES po shrambi v Evidenci."""
        preferred = str(self.config.get("company_registry_path") or "") or None
        path, companies = company_registry.load_companies(preferred)
        if path:
            self.company_registry_path = path
            self.config["company_registry_path"] = str(path)
        self.companies = companies
        key = ""
        if self.active_company:
            key = company_registry.company_key(self.active_company)
        elif self.config.get("selected_company_key"):
            key = str(self.config.get("selected_company_key") or "")
        found = company_registry.find_company(self.companies, key) if key else None
        if found:
            self.active_company = dict(found)
            self.company_var.set(self._active_company_text())
            try:
                self._populate_company_tree()
            except Exception:
                pass
            return self.active_company
        return self.active_company

    def _apply_company_period_from_evidenca(self, company: Mapping[str, Any]) -> bool:
        """Ob izbiri firme: Mesečni → prejšnji mesec, Tromesečni → prejšnji kvartal."""
        oddaja = company_registry.company_oddaja_ddv(company)
        bounds = period_bounds_for_oddaja_ddv(oddaja)
        if bounds is None:
            return False
        start, end = bounds
        # Ob izbiri firme nastavi filter; osveži tabele šele če so podatki že naloženi.
        self._set_period_filter(start, end, refresh=bool(self.dataset))
        return True

    def _activate_company(self, company: Mapping[str, Any], *, user_action: bool = False) -> None:
        self.active_company = dict(company)
        self._clear_minimax_invoice_statuses()
        key = company_registry.company_key(company)
        self.config["selected_company_key"] = key
        profile = self._profile_config()
        org_id = company_registry.company_org_id(company)
        if org_id:
            profile["minimax_selected_org_id"] = org_id
            self.config["minimax_selected_org_id"] = org_id
        self.company_var.set(self._active_company_text())
        self._set_account_catalog(dict(profile.get("account_catalog") or {}))
        self.account_var.set(self._account_label(profile.get("last_account") or "4190"))
        self.ir_account_var.set(self._account_label(profile.get("last_ir_account") or "7601"))
        self._load_api_profile_options(profile)
        self._refresh_account_name_labels()
        saved_export = str(profile.get("last_export_dir") or "")
        self.last_export_dir = Path(saved_export) if saved_export else None
        if self.minimax_organisations and org_id:
            label = next(
                (label for label, value in self.minimax_organisations.items() if str(value) == org_id),
                "",
            )
            if label:
                self.api_org_var.set(label)
                if self.minimax_client:
                    self.root.after(0, self._on_api_org_selected)
        self._populate_company_tree()
        if user_action:
            applied = self._apply_company_period_from_evidenca(company)
            oddaja = company_registry.company_oddaja_ddv(company) or "—"
            period_note = ""
            if applied:
                period_note = (
                    f"; obdobje {format_si_date(self.filter_from_date)}–"
                    f"{format_si_date(self.filter_to_date)} ({oddaja})"
                )
            self._record_action(
                "company_select",
                f"Zšt {company_registry.company_zst(company)}; {company_registry.company_name(company)}; "
                f"Org_ID {org_id or '—'}; oddaja DDV {oddaja}{period_note}",
            )

    def _on_company_select(self, _event: tk.Event | None = None) -> None:
        if getattr(self, "_updating_company_tree", False):
            return
        selected = self.company_tree.selection()
        if not selected:
            return
        company = company_registry.find_company(self.companies, selected[0])
        if not company:
            return
        if self.active_company and company_registry.company_key(self.active_company) == selected[0]:
            return
        if self.working_dirty and self.dataset:
            self.save_working_copy(quiet=True)
        self._activate_company(company, user_action=True)
        profile = self._profile_config()
        last_source = Path(str(profile.get("last_source_file") or ""))
        if last_source.is_file():
            self.load_source(last_source, match_company=False)
        else:
            self._clear_dataset_for_company()
            self.status_var.set(
                f"Izbrano podjetje {company_registry.company_name(company)}. Odprite njegove KIR/KPR podatke."
            )
        # Obdobje iz »oddaja DDV« ima prednost pred filterjem iz zadnje datoteke.
        self._apply_company_period_from_evidenca(company)

    def _clear_dataset_for_company(self) -> None:
        self.dataset = None
        self.source_dataset = None
        self.working_dirty = False
        self.pending_working_changes.clear()
        if hasattr(self, "ir_tree"):
            self.ir_tree.delete(*self.ir_tree.get_children())
            self.pr_tree.delete(*self.pr_tree.get_children())
            self._populate_api_tree()
        self.source_var.set("Izberite ZIP/JSON/XML/CSV ali »Podatki iz Minimaxa«.")
        self.format_var.set("Format: —")
        self.period_var.set("Obdobje: —")
        self.member_var.set("Vsebina: —")
        for name in ("ir_count", "pr_count", "tax_only"):
            self.summary_vars[name].set("0")
        self.summary_vars["ir_value"].set("0,00 EUR")
        self.summary_vars["pr_value"].set("0,00 EUR")
        self.export_button.configure(state="disabled")

    def _on_navigation_select(self, _event: tk.Event | None = None) -> None:
        selected = self.nav_tree.selection()
        if not selected:
            return
        item = selected[0]
        tab_by_item = {
            "nav:ir": 0,
            "nav:pr": 1,
            "nav:ddvo": 2,
            "nav:api": 3,
            "nav:knjige": 4,
            "nav:knjiga_ir": 4,
            "nav:knjiga_pr": 4,
        }
        if item in tab_by_item:
            self.notebook.select(tab_by_item[item])
            if item == "nav:knjiga_ir" and hasattr(self, "knjige_notebook"):
                self.knjige_notebook.select(0)
            elif item == "nav:knjiga_pr" and hasattr(self, "knjige_notebook"):
                self.knjige_notebook.select(1)
        elif item == "nav:export":
            self.export_files()

    def _summary_card(
        self,
        parent: ttk.Frame,
        column: int,
        title: str,
        value_var: tk.StringVar,
        detail_var: tk.StringVar,
        accent: str,
    ) -> None:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(0, 0, 0, 0))
        outer.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
        tk.Frame(outer, bg=accent, height=4).pack(fill="x")
        content = ttk.Frame(outer, style="Card.TFrame", padding=(16, 11))
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=title, style="CardMuted.TLabel").pack(anchor="w")
        line = ttk.Frame(content, style="Card.TFrame")
        line.pack(fill="x", pady=(3, 0))
        ttk.Label(line, textvariable=value_var, style="SummaryValue.TLabel").pack(side="left")
        ttk.Label(line, textvariable=detail_var, style="CardMuted.TLabel").pack(side="right", anchor="s", pady=(7, 0))

    def _make_tree(
        self,
        parent: ttk.Frame,
        columns: tuple[str, ...],
        headings: dict[str, str],
        widths: dict[str, int],
        *,
        selectmode: str = "extended",
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", style="Studio.Treeview", selectmode=selectmode)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for column in columns:
            money_cols = {
                "net", "vat", "vat_22", "vat_95", "vat_5", "gross", "amount",
                *[f"p{i}" for i in range(7, 28)],
            }
            center_cols = {
                "zapst", "date", "country", "account", "self_tax",
                "vat_deductible", "minimax_status", "status", "match", "api_id",
                "obdobje", "p2", "p4", "p5", "p6", "p7",
            }
            anchor = "e" if column in money_cols else "center" if column in center_cols else "w"
            tree.heading(column, text=headings[column], command=lambda col=column, item=tree: self._sort_tree(item, col, False))
            stretch = column in {
                "invoice", "party", "account_name",
            }
            tree.column(column, width=widths.get(column, 100), minwidth=48, anchor=anchor, stretch=stretch)
        gui_style.apply_tree_tags(tree, "odd", "tax_only", "self_assessment", "vat_not_deducted")
        return tree

    def _pack_tab_search(
        self,
        parent: ttk.Frame,
        variable: tk.StringVar,
        *,
        on_change: Callable[[], None],
        clear_command: Callable[[], None],
        tip: str = "",
        entry_width: int = 28,
    ) -> None:
        """Skupni iskalnik na zavihku (desno)."""
        box = ttk.Frame(parent, style="Panel.TFrame")
        box.pack(side="right")
        ttk.Label(box, text="Išči", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(box, textvariable=variable, width=int(entry_width))
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _event: on_change())
        entry.bind("<Return>", lambda _event: on_change())
        ttk.Button(box, text="×", width=3, command=clear_command).pack(side="left", padx=(4, 0))
        ToolTip(
            entry,
            tip
            or "Iskalnik po vseh podatkih: listina, partner, znesek, DDV, datum, konto …",
        )

    def _build_ir_tree(self, parent: ttk.Frame) -> ttk.Treeview:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Pregled izdanih računov", style="SectionTitle.TLabel").pack(side="left")
        self._pack_tab_search(
            top,
            self.ir_search_var,
            on_change=self._populate_trees,
            clear_command=self.clear_ir_search,
            tip="Išči IR: listina, kupec, znesek, DDV, datum, konto, status …",
        )
        columns = (
            "zapst", "date", "invoice", "party", "tax_id", "net",
            "vat_22", "vat_95", "vat", "gross",
            "account", "account_name", "minimax_status", "status",
        )
        headings = {
            "zapst": "Zap. št.", "date": "Datum", "invoice": "Listina", "party": "Kupec",
            "tax_id": "ID za DDV", "net": "Neto",
            "vat_22": "DDV 22%", "vat_95": "DDV 9,5%", "vat": "DDV", "gross": "Skupaj",
            "account": "Konto", "account_name": "Naziv konta",
            "minimax_status": "Status", "status": "Obravnava",
        }
        widths = {
            "zapst": 65, "date": 95, "invoice": 145, "party": 220, "tax_id": 110,
            "net": 95, "vat_22": 85, "vat_95": 85, "vat": 85, "gross": 100,
            "account": 75, "account_name": 170, "minimax_status": 95, "status": 140,
        }
        tree = self._make_tree(parent, columns, headings, widths)
        tree.bind("<<TreeviewSelect>>", self._on_ir_selection)
        tree.bind("<Double-1>", self._on_ir_double_click)
        tree.bind("<Return>", lambda _event: self.open_ir_editor())
        tree.bind("<Control-a>", self._select_all_ir)
        return tree

    def _build_pr_tree(self, parent: ttk.Frame) -> ttk.Treeview:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Pregled in kontiranje prejetih računov", style="SectionTitle.TLabel").pack(side="left")
        self._pack_tab_search(
            top,
            self.pr_search_var,
            on_change=self._populate_trees,
            clear_command=self.clear_pr_search,
            tip="Išči PR: listina, dobavitelj, znesek, DDV, datum, konto, samoobdavčitev …",
        )
        columns = (
            "zapst", "date", "invoice", "party", "tax_id", "net",
            "vat_22", "vat_95", "vat", "gross",
            "account", "account_name", "self_tax", "vat_deductible", "minimax_status", "status",
        )
        headings = {
            "zapst": "Zap. št.", "date": "Datum", "invoice": "Listina", "party": "Dobavitelj",
            "tax_id": "ID za DDV", "net": "Osnova",
            "vat_22": "DDV 22%", "vat_95": "DDV 9,5%", "vat": "Odbitni DDV", "gross": "Obveznost",
            "account": "Konto", "account_name": "Naziv konta",
            "self_tax": "Samoobd.", "vat_deductible": "DDV se odbija",
            "minimax_status": "Status", "status": "Vrsta",
        }
        widths = {
            "zapst": 65, "date": 95, "invoice": 135, "party": 200, "tax_id": 105,
            "net": 90, "vat_22": 80, "vat_95": 80, "vat": 90, "gross": 95,
            "account": 70, "account_name": 155, "self_tax": 80, "vat_deductible": 95,
            "minimax_status": 90, "status": 125,
        }
        tree = self._make_tree(parent, columns, headings, widths)
        tree.bind("<<TreeviewSelect>>", self._on_pr_selection)
        tree.bind("<Double-1>", self._on_pr_double_click)
        tree.bind("<Return>", lambda _event: self.open_pr_editor())
        tree.bind("<Control-a>", self._select_all_pr)
        return tree

    def _build_ir_account_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 10, 2, 1))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.ir_selection_var, style="Muted.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(bar, text="Konto prihodka:", style="TLabel").pack(side="left", padx=(0, 6))
        self.ir_account_combo = ttk.Combobox(bar, textvariable=self.ir_account_var, values=self._account_choices(), width=38)
        self.ir_account_combo.pack(side="left", padx=(0, 8))
        self._configure_account_filter(self.ir_account_combo, self.ir_account_var, self._refresh_account_name_labels)
        self.ir_account_combo.bind("<Return>", lambda _event: self.apply_ir_account())
        self.ir_account_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_account_name_labels())
        ttk.Label(bar, textvariable=self.ir_account_name_var, style="Muted.TLabel").pack(side="left", padx=(0, 8))
        apply_button = gui_style.pill(bar, "Uporabi za izbrane", self.apply_ir_account, kind="blue")
        apply_button.pack(side="left", padx=(0, 9))
        reset_button = gui_style.pill(bar, "Nastavi 7601", lambda: self.set_selected_ir_account("7601"), kind="grey")
        reset_button.pack(side="left", padx=(0, 14))
        ttk.Checkbutton(bar, text="Zapomni si za kupca", variable=self.remember_customer_var).pack(side="left")
        gui_style.pill(bar, "Shrani vse konte", self.save_accounts, kind="green").pack(side="right")
        edit_button = gui_style.pill(bar, "Odpri račun / popravi", self.open_ir_editor, kind="purple")
        edit_button.pack(side="right", padx=(0, 8))
        data_button = gui_style.pill(bar, "Uredi podatke", lambda: self.open_data_editor("IR"), kind="grey")
        data_button.pack(side="right", padx=(0, 8))
        ToolTip(apply_button, "Spremeni prihodkovni konto pri vseh izbranih IR in po želji ustvari pravilo za kupca.")
        ToolTip(
            self.ir_account_combo,
            "Polna Minimax šifra (npr. 7601, ne 760). Iskanje po delu šifre/naziva — shrani se samo polna šifra.",
        )
        ToolTip(reset_button, "Izbrane izdane račune vrne na privzeti prihodkovni konto 7601.")
        ToolTip(edit_button, "Odpre podrobno formo za konto in opis izbranega izdanega računa.")
        ToolTip(data_button, "Odpre izvorne in delovne vrednosti računa. Spremeni se samo delovna kopija.")

    def _build_pr_account_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 10, 2, 1))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.selection_var, style="Muted.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(bar, text="Konto:", style="TLabel").pack(side="left", padx=(0, 6))
        self.account_combo = ttk.Combobox(bar, textvariable=self.account_var, values=self._account_choices(), width=38)
        self.account_combo.pack(side="left", padx=(0, 8))
        self._configure_account_filter(self.account_combo, self.account_var, self._refresh_account_name_labels)
        self.account_combo.bind("<Return>", lambda _event: self.apply_account())
        self.account_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_account_name_labels())
        ttk.Label(bar, textvariable=self.account_name_var, style="Muted.TLabel").pack(side="left", padx=(0, 8))
        apply_button = gui_style.pill(bar, "Uporabi za izbrane", self.apply_account, kind="blue")
        apply_button.pack(side="left", padx=(0, 9))
        reset_button = gui_style.pill(bar, "Nastavi 4190", lambda: self.set_selected_account("4190"), kind="grey")
        reset_button.pack(side="left", padx=(0, 8))
        deduct_button = gui_style.pill(bar, "DDV se odbija", lambda: self.set_selected_vat_deductible(True), kind="green")
        deduct_button.pack(side="left", padx=(0, 4))
        no_deduct_button = gui_style.pill(
            bar, "DDV brez odbitka", lambda: self.set_selected_vat_deductible(False), kind="yellow"
        )
        no_deduct_button.pack(side="left", padx=(0, 12))
        ttk.Checkbutton(bar, text="Zapomni si za dobavitelja", variable=self.remember_supplier_var).pack(side="left")
        gui_style.pill(bar, "Shrani vse konte", self.save_accounts, kind="green").pack(side="right")
        edit_button = gui_style.pill(bar, "Odpri račun / popravi", self.open_pr_editor, kind="purple")
        edit_button.pack(side="right", padx=(0, 8))
        data_button = gui_style.pill(bar, "Uredi podatke", lambda: self.open_data_editor("PR"), kind="grey")
        data_button.pack(side="right", padx=(0, 8))
        ToolTip(apply_button, "Spremeni konto pri vseh izbranih PR. Po želji ustvari tudi pravilo za dobavitelja.")
        ToolTip(
            self.account_combo,
            "Polna Minimax šifra (npr. 4170, ne 417). Iskanje po 417 pokaže 4170 — shrani se samo polna šifra.",
        )
        ToolTip(reset_button, "Izbrane prejete račune vrne na privzeti konto storitev 4190.")
        ToolTip(deduct_button, "Pri izbranih računih vključi Minimaxovo nastavitev »DDV se odbija«.")
        ToolTip(no_deduct_button, "Pri izbranih računih izključi odbitek; DDV se pri knjiženju prišteje strošku.")
        ToolTip(edit_button, "Odpre podrobno formo za konto in opis izbranega prejetega računa.")
        ToolTip(data_button, "Primerja izvorne in delovne vrednosti ter spremembe shrani v novo kopijo.")

    def _build_ddvo_tab(self, parent: ttk.Frame) -> None:
        # Vrstica 1: naslov + iskalnik (brez gneče gumbov)
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 4))
        title_box = ttk.Frame(top, style="Panel.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="Kontrolni obrazec DDV-O (e-DDV_O_11.7)", style="SectionTitle.TLabel").pack(anchor="w")
        metadata = ttk.Frame(title_box, style="Panel.TFrame")
        metadata.pack(fill="x", pady=(3, 0))
        ttk.Label(metadata, textvariable=self.ddvo_taxpayer_var, style="Muted.TLabel").pack(side="left", padx=(0, 18))
        ttk.Label(metadata, textvariable=self.ddvo_period_var, style="Muted.TLabel").pack(side="left", padx=(0, 18))
        ttk.Label(metadata, textvariable=self.ddvo_flags_var, style="Muted.TLabel").pack(side="left")
        self._pack_tab_search(
            top,
            self.ddvo_search_var,
            on_change=self._populate_ddvo,
            clear_command=self.clear_ddvo_search,
            tip="Išči DDV-O: polje, opis, vir, znesek, razdelek …",
            entry_width=18,
        )

        # Vrstica 2: vsi gumbi vedno vidni (Minimax = glavni tisk)
        actions = tk.Frame(parent, bg=self.colors["panel"], padx=2, pady=4)
        actions.pack(fill="x", pady=(0, 8))
        btn_minimax = gui_style.pill(actions, "Minimax", self.print_ddvo_minimax, kind="green")
        btn_minimax.pack(side="left")
        btn_preview = gui_style.pill(actions, "Predogled", self.preview_ddvo_pdf, kind="blue")
        btn_preview.pack(side="left", padx=(8, 0))
        btn_export = gui_style.pill(actions, "Izvozi PDF…", self.export_ddvo_pdf_xml, kind="grey")
        btn_export.pack(side="left", padx=(8, 0))
        btn_pkg = gui_style.pill(actions, "PDF + virman…", self.create_ddvo_pdf_virman, kind="green")
        btn_pkg.pack(side="left", padx=(8, 0))
        gui_style.pill(actions, "Preračunaj", self.recalculate_ddvo, kind="grey").pack(side="left", padx=(8, 0))
        btn_email = gui_style.pill(actions, "E-pošta virman…", self.open_ddvo_email_template_editor, kind="purple")
        btn_email.pack(side="left", padx=(8, 0))
        self.ddvo_json_view_button = gui_style.pill(actions, "JSON", self.show_ddvo_json_view, kind="grey")
        self.ddvo_json_view_button.pack(side="right")
        self.ddvo_compare_view_button = gui_style.pill(
            actions, "JSON + Minimax", self.show_ddvo_compare_view, kind="yellow"
        )
        self.ddvo_compare_view_button.pack(side="right", padx=(0, 8))
        ToolTip(
            btn_minimax,
            "Minimax uskladitev + DDV PDF/virman (zahteva API). Za samo lokalni virman uporabi »PDF + virman…«.",
        )
        ToolTip(btn_preview, "Odpre DDV-O PDF (eDavki) v pregledovalniku.")
        ToolTip(
            btn_pkg,
            "Lokalno: DDV-O PDF + SEPA virman iz odprtih podatkov (brez Minimax prijave). "
            "Konto 62: stanje (s predznakom) se prišteje virmanu (51 + stanje).",
        )
        ToolTip(
            btn_email,
            "Odpre HTML predlogo z DEJANSKIMI zneski iz DDV-O (51 + stanje 62). "
            "Shrani + Outlook nastavi Od: in razmike.",
        )
        ToolTip(
            btn_export,
            "Tisk v PDF / izvoz v TROPS\\{Zšt}\\DDV\\ — prikaz z uradnim eDavki XSLT.",
        )
        ToolTip(self.ddvo_json_view_button, "DDV-O samo iz lokalnega KIR/KPR JSON.")
        ToolTip(
            self.ddvo_compare_view_button,
            "Primerjava: JSON (vse vrstice obdobja) vs Minimax (samo listine, ki obstajajo v API).",
        )

        cards = ttk.Frame(parent, style="Panel.TFrame")
        cards.pack(fill="x", pady=(0, 8))
        cards.columnconfigure((0, 1, 2), weight=1, uniform="ddvo")
        self._summary_card(cards, 0, "OBRAČUNANI DDV", self.ddvo_output_var, self.ddvo_output_detail_var, self.colors["accent"])
        self._summary_card(cards, 1, "ODBITNI DDV", self.ddvo_input_var, self.ddvo_input_detail_var, self.colors["purple"])
        self._summary_card(cards, 2, "OBVEZNOST / PRESEŽEK", self.ddvo_result_var, self.ddvo_result_detail_var, self.colors["warning"])

        self.ddvo_control_label = tk.Label(
            parent,
            textvariable=self.ddvo_control_var,
            bg=gui_style.HEADER_PURPLE,
            fg="#ffffff",
            anchor="w",
            padx=13,
            pady=8,
            font=("Segoe UI", 9, "bold"),
        )
        self.ddvo_control_label.pack(fill="x", pady=(0, 8))

        columns = ("section", "code", "description", "source", "json_amt", "minimax_amt", "diff", "status")
        headings = {
            "section": "Razdelek",
            "code": "Polje",
            "description": "Opis polja DDV-O",
            "source": "Vir",
            "json_amt": "JSON (KIR/KPR)",
            "minimax_amt": "Minimax",
            "diff": "Razlika",
            "status": "Kontrola",
        }
        widths = {
            "section": 160, "code": 55, "description": 320, "source": 100,
            "json_amt": 115, "minimax_amt": 115, "diff": 95, "status": 80,
        }
        self.ddvo_tree = self._make_tree(parent, columns, headings, widths, selectmode="browse")
        self.ddvo_tree.column("json_amt", anchor="e", stretch=False)
        self.ddvo_tree.column("minimax_amt", anchor="e", stretch=False)
        self.ddvo_tree.column("diff", anchor="e", stretch=False)
        self.ddvo_tree.column("code", anchor="center", stretch=False)
        self.ddvo_tree.column("status", anchor="center", stretch=False)
        gui_style.apply_tree_tags(self.ddvo_tree, "section_start", "result", "diff_row")

        bottom = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 9, 2, 1))
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text="Minimax = glavni tisk (API uskladitev + PDF/XML + virman) · obdobje zgoraj.",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(bottom, text="Shrani PDF drugam…", command=self.save_ddvo_pdf).pack(side="right")
        ttk.Button(bottom, text="Shrani XML drugam…", command=self.save_ddvo_xml).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="Shrani kontrolni pregled…", command=self.save_ddvo_report).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="Kopiraj kontrolni podatek", command=self.copy_ddvo_control).pack(side="right", padx=(0, 8))

    def _build_api_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 8))
        title_box = ttk.Frame(top, style="Panel.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="Neposredna oddaja v Minimax API", style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Ciljno organizacijo določa izbrano podjetje; program pred oddajo sam preveri povezavo in šifrante.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        self.api_connect_button = ttk.Button(top, text="Poveži z izbranim podjetjem", style="Accent.TButton", command=self.connect_minimax_api)
        self.api_connect_button.pack(side="right")
        self.api_connection_toggle_button = ttk.Button(top, text="▸ Povezava / nastavitve", command=self.toggle_api_connection_panel)
        self.api_connection_toggle_button.pack(side="right", padx=(0, 7))

        connection = ttk.Frame(parent, style="Card.TFrame", padding=(14, 11))
        self.api_connection_panel = connection
        connection.pack(fill="x", pady=(0, 8))
        options_row = ttk.Frame(connection, style="Card.TFrame")
        options_row.pack(fill="x")
        ttk.Label(options_row, text="Cilj:", style="CardMuted.TLabel", width=8).pack(side="left")
        ttk.Label(options_row, textvariable=self.company_var, style="Card.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(options_row, text="Stanje temeljnic:", style="CardMuted.TLabel").pack(side="left", padx=(0, 6))
        self.api_status_combo = ttk.Combobox(
            options_row,
            textvariable=self.api_journal_status_var,
            state="readonly",
            values=("O — osnutek", "P — potrjeno"),
            width=17,
        )
        self.api_status_combo.pack(side="left")
        self.api_status_combo.bind("<<ComboboxSelected>>", self._save_api_options)

        mode_row = ttk.Frame(connection, style="Card.TFrame")
        mode_row.pack(fill="x", pady=(9, 0))
        ttk.Label(mode_row, text="Način:", style="CardMuted.TLabel", width=8).pack(side="left")
        self.api_mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.api_transfer_mode_var,
            state="readonly",
            values=("Temeljnica + DDV", "Izdani/Prejeti račun — osnutek"),
            width=37,
        )
        self.api_mode_combo.pack(side="left")
        self.api_mode_combo.bind("<<ComboboxSelected>>", self._on_api_mode_changed)
        ttk.Button(
            mode_row,
            text="Nastavitve DDV in računov…",
            command=self.open_api_transfer_settings,
        ).pack(side="left", padx=(9, 0))
        ttk.Label(
            mode_row,
            text="Računi se zaradi kontrole vedno ustvarijo kot osnutki.",
            style="CardMuted.TLabel",
        ).pack(side="right")

        browser_row = ttk.Frame(connection, style="Card.TFrame")
        browser_row.pack(fill="x", pady=(9, 0))
        browser_text = ttk.Frame(browser_row, style="Card.TFrame")
        browser_text.pack(fill="x")
        ttk.Label(browser_text, text="Playwright:", style="CardMuted.TLabel").pack(side="left", padx=(0, 8))
        ttk.Label(browser_text, textvariable=self.playwright_session_var, style="Card.TLabel").pack(side="left")
        ttk.Label(
            browser_text,
            textvariable=self.playwright_profile_var,
            style="CardMuted.TLabel",
        ).pack(side="left", padx=(12, 0))
        browser_actions = ttk.Frame(browser_row, style="Card.TFrame")
        browser_actions.pack(fill="x", pady=(7, 0))
        self.api_latest_received_button = ttk.Button(
            browser_actions,
            text="Zadnji potrjeni PR (API)",
            command=self.show_latest_confirmed_received_invoice,
            state="disabled",
        )
        self.api_latest_received_button.pack(side="left")
        self.api_browser_diagnostic_button = ttk.Button(
            browser_actions,
            text="Varna diagnostika…",
            command=self.save_minimax_browser_diagnostic,
        )
        self.api_browser_diagnostic_button.pack(side="right")
        self.api_open_company_button = ttk.Button(
            browser_actions,
            text="Odpri izbrano podjetje",
            style="Accent.TButton",
            command=self.open_selected_company_browser,
        )
        self.api_open_company_button.pack(side="right", padx=(0, 6))
        self.api_browser_login_button = ttk.Button(
            browser_actions,
            text="Prijava / obnovi sejo…",
            command=self.login_minimax_browser,
        )
        self.api_browser_login_button.pack(side="right", padx=(0, 6))
        self.api_browser_check_button = ttk.Button(
            browser_actions,
            text="Preveri sejo",
            command=self.check_minimax_browser_session,
        )
        self.api_browser_check_button.pack(side="right", padx=(0, 6))
        self.api_browser_buttons = (
            self.api_browser_check_button,
            self.api_browser_login_button,
            self.api_open_company_button,
            self.api_browser_diagnostic_button,
        )

        self.api_connection_label = tk.Label(
            connection,
            textvariable=self.api_status_var,
            bg=self.colors.get("status_idle", self.colors["panel"]),
            fg=self.colors["text"],
            anchor="w",
            padx=10,
            pady=6,
            font=("Segoe UI Semibold", 9),
        )
        self.api_connection_label.pack(fill="x", pady=(9, 0))

        status_actions = ttk.Frame(parent, style="Card.TFrame", padding=(8, 5))
        self.api_status_actions = status_actions
        status_actions.pack(fill="x", pady=(0, 8))
        ttk.Label(
            status_actions,
            text="Statusi in priponke:",
            style="Card.TLabel",
            font=("Segoe UI Semibold", 10),
        ).pack(side="left")
        self.api_refresh_status_button = ttk.Button(
            status_actions,
            text="↻ Osveži statuse IR/PR",
            style="Accent.TButton",
            command=self.refresh_minimax_invoice_statuses,
            state="disabled",
        )
        self.api_refresh_status_button.pack(side="left", padx=(14, 7))
        ttk.Button(
            status_actions,
            text="Podatki iz Minimaxa",
            command=self.load_data_from_minimax,
        ).pack(side="left", padx=(0, 7))
        self.api_download_attachment_button = ttk.Button(
            status_actions,
            text="KLUG PR priponka (API)",
            style="Success.TButton",
            command=self.download_selected_invoice_attachments,
            state="disabled",
        )
        self.api_download_attachment_button.pack(side="left", padx=7)
        self.api_local_attachment_button = ttk.Button(
            status_actions, text="Dodaj lokalno datoteko…", command=self.import_attachment_from_folder, state="disabled",
        )
        self.api_local_attachment_button.pack(side="left", padx=7)
        self.api_supplier_attachment_button = ttk.Button(
            status_actions, text="Shrani QUICK PDF…", command=self.download_supplier_issued_attachment, state="disabled",
        )
        self.api_supplier_attachment_button.pack(side="left", padx=7)
        self.api_attach_supplier_pdf_button = ttk.Button(
            status_actions,
            text="QUICK PDF → izbrani PR",
            style="Success.TButton",
            command=self.attach_supplier_pdf_to_selected_received_invoice,
            state="disabled",
        )
        self.api_attach_supplier_pdf_button.pack(side="left", padx=7)

        search_box = ttk.Frame(status_actions, style="Card.TFrame")
        search_box.pack(side="right")
        ttk.Label(search_box, text="Išči", style="CardMuted.TLabel").pack(side="left", padx=(0, 6))
        self.api_search_entry = ttk.Entry(search_box, textvariable=self.api_search_var, width=32)
        self.api_search_entry.pack(side="left")
        self.api_search_entry.bind("<KeyRelease>", lambda _event: self._populate_api_tree())
        self.api_search_entry.bind("<Return>", lambda _event: self._populate_api_tree())
        ttk.Button(search_box, text="×", width=3, command=self.clear_api_search).pack(side="left", padx=(4, 0))
        ToolTip(
            self.api_search_entry,
            "Iskalnik po vseh podatkih vrstice: listina, partner, znesek, DDV, "
            "datum, konto, ID za DDV, status, napaka …",
        )
        self.api_connection_expanded = False
        connection.pack_forget()

        action_bar = ttk.Frame(parent, style="Panel.TFrame")
        action_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(action_bar, text="Prikaz:", style="Muted.TLabel").pack(side="left")
        ttk.Button(action_bar, text="Vsi", command=lambda: self.set_api_view_filter("ALL")).pack(side="left", padx=(8, 4))
        ttk.Button(action_bar, text="Samo IR", command=lambda: self.set_api_view_filter("IR")).pack(side="left", padx=4)
        ttk.Button(action_bar, text="Samo PR", command=lambda: self.set_api_view_filter("PR")).pack(side="left", padx=4)
        ttk.Label(action_bar, textvariable=self.api_view_filter_var, style="Muted.TLabel").pack(side="left", padx=(14, 8))
        ttk.Label(action_bar, textvariable=self.api_selection_var, style="Muted.TLabel").pack(side="left")
        self.api_json_view_button = ttk.Button(action_bar, text="JSON pogled", command=self.show_json_api_view)
        self.api_json_view_button.pack(side="right", padx=(0, 6))
        ToolTip(self.api_json_view_button, "Lokalni KIR/KPR podatki (samo za branje). Nič se ne spremeni.")
        self.api_minimax_view_button = ttk.Button(
            action_bar, text="Minimax pogled", style="Accent.TButton", command=self.show_minimax_api_view,
        )
        self.api_minimax_view_button.pack(side="right", padx=(0, 6))
        ToolTip(
            self.api_minimax_view_button,
            "Prebere Minimax, uskladi Status/API stanje in pokaže razliko glede na program.",
        )
        self.api_validate_button = ttk.Button(action_bar, text="Predpreveri izbrane", command=self.validate_api_selection, state="disabled")
        self.api_validate_button.pack(side="right", padx=(0, 6))

        transfer_bar = ttk.Frame(parent, style="Card.TFrame", padding=(12, 9))
        transfer_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(transfer_bar, text="Prenos v Minimax API:", style="Card.TLabel", font=("Segoe UI Semibold", 10)).pack(side="left")
        self.api_transfer_ir_button = ttk.Button(
            transfer_bar, text="Prenesi vse IR", style="Accent.TButton",
            command=lambda: self.transfer_api_group("IR"), state="disabled",
        )
        self.api_transfer_ir_button.pack(side="left", padx=(14, 6))
        self.api_transfer_pr_button = ttk.Button(
            transfer_bar, text="Prenesi vse PR", style="Accent.TButton",
            command=lambda: self.transfer_api_group("PR"), state="disabled",
        )
        self.api_transfer_pr_button.pack(side="left", padx=6)
        self.api_transfer_all_button = ttk.Button(
            transfer_bar, text="Prenesi IR + PR", style="Success.TButton",
            command=lambda: self.transfer_api_group("ALL"), state="disabled",
        )
        self.api_transfer_all_button.pack(side="left", padx=6)
        self.api_retry_failed_button = ttk.Button(
            transfer_bar,
            text="Ponovi NAPAKA",
            command=self.retry_failed_api_rows,
            state="disabled",
        )
        self.api_retry_failed_button.pack(side="left", padx=6)
        ToolTip(
            self.api_retry_failed_button,
            "Označi vse vrstice s stanjem NAPAKA, jih predpreveri in ponovno ponudi oddajo.",
        )
        self.api_transfer_buttons = (
            self.api_transfer_ir_button,
            self.api_transfer_pr_button,
            self.api_transfer_all_button,
        )
        ttk.Label(
            transfer_bar,
            text="Najprej uskladi z Minimaxom, nato ustvari samo manjkajoče listine (brez podvajanja).",
            style="CardMuted.TLabel",
        ).pack(side="right")

        columns = ("book", "invoice", "party", "tax_id", "total", "account", "invoice_status", "api_status", "detail")
        headings = {
            "book": "Knjiga",
            "invoice": "Listina",
            "party": "Partner",
            "tax_id": "ID za DDV",
            "total": "Znesek",
            "account": "Konto",
            "invoice_status": "Status računa",
            "api_status": "API stanje",
            "detail": "Rezultat / napaka",
        }
        widths = {"book": 65, "invoice": 145, "party": 230, "tax_id": 115, "total": 105, "account": 210, "invoice_status": 115, "api_status": 105, "detail": 340}
        self.api_tree = self._make_tree(parent, columns, headings, widths, selectmode="extended")
        self.api_tree.column("total", anchor="e", stretch=False)
        self.api_tree.column("book", anchor="center", stretch=False)
        self.api_tree.column("account", anchor="center", stretch=False)
        self.api_tree.column("invoice_status", anchor="center", stretch=False)
        self.api_tree.column("api_status", anchor="center", stretch=False)
        gui_style.apply_tree_tags(
            self.api_tree,
            "api_ready",
            "api_ok",
            "api_error",
            "api_sent",
            "api_missing",
            "api_exists",
        )
        self.api_tree.bind("<<TreeviewSelect>>", self._on_api_tree_selection)
        self.api_tree.bind("<Double-1>", self.open_api_row_from_double_click)
        self.api_tree.bind("<Control-a>", lambda _event: self.select_api_rows("ALL"))

        # Namig + Serija NAD spodnjimi gumbi (sicer se na dnu okna odreže).
        help_bar = ttk.Frame(parent, style="Card.TFrame", padding=(10, 8))
        help_bar.pack(fill="x", pady=(6, 4))
        self.api_cdp_hint_var = tk.StringVar(
            value=(
                "Serija PR: v ŽE ODPRTEM Minimax zavihku (brez nove prijave) — "
                "razširitev / CDP. Uredi → Nov odhodek → konto iz listine → Potrdi."
            )
        )
        ttk.Label(
            help_bar,
            textvariable=self.api_help_var,
            style="Card.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", fill="x")
        ttk.Label(
            help_bar,
            textvariable=self.api_cdp_hint_var,
            style="CardMuted.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(4, 0))

        series_bar = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 4, 2, 2))
        series_bar.pack(fill="x")
        self.api_batch_pr_button = ttk.Button(
            series_bar,
            text="Serija: odhodek + Potrdi (CDP)",
            style="Success.TButton",
            command=self.batch_confirm_pr_drafts_playwright,
            state="disabled",
        )
        self.api_batch_pr_button.pack(side="left")
        ToolTip(
            self.api_batch_pr_button,
            "Serija oddanih PR-osnutkov v že odprti firmi. "
            "Konto in osnove iz listine. Da = tudi Potrdi, Ne = samo odhodek.",
        )
        self.api_open_draft_button = ttk.Button(
            series_bar,
            text="Odpri PR-osnutek + vnesi odhodek",
            style="Accent.TButton",
            command=self.open_selected_api_draft,
            state="disabled",
        )
        self.api_open_draft_button.pack(side="left", padx=(8, 0))
        ToolTip(
            self.api_open_draft_button,
            "Odpre en oddani PR-osnutek: Uredi → Nov odhodek s kontom iz listine. Potrdi po A/Q.",
        )

        bottom = ttk.Frame(parent, style="Panel.TFrame", padding=(2, 6, 2, 2))
        bottom.pack(fill="x")
        ttk.Button(
            bottom,
            text="Prikaži cel rezultat",
            command=self.show_api_result_details,
        ).pack(side="left")
        self.api_send_button = ttk.Button(
            bottom,
            text="Oddaj izbrane v Minimax",
            style="Success.TButton",
            command=self.send_api_selection,
            state="disabled",
        )
        self.api_send_button.pack(side="right")

    def _build_knjige_tab(self, parent: ttk.Frame) -> None:
        """Knjige IR/PR: predogled JSON (KIR/KPR) ali že kreirane knjige iz Minimax API."""
        tools_sec = gui_style.CollapsibleSection(
            parent,
            "Knjige — vir / povzetek",
            bg=self.colors.get("panel", "#101a2f"),
            muted=self.colors["muted"],
            initially_open=bool(self.config.get("ui_knjige_tools_open", True)),
            padx=8,
            pady=6,
            on_toggle=lambda open_: self._on_knjige_tools_toggled(open_),
        )
        tools_sec.pack(fill="x", pady=(0, 6))
        self.ui_knjige_tools_section = tools_sec
        body = tools_sec.body

        top = tk.Frame(body, bg=body.cget("bg"))
        top.pack(fill="x")
        title_box = tk.Frame(top, bg=body.cget("bg"))
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_box,
            text="Knjige IR / PR",
            bg=body.cget("bg"),
            fg=self.colors["text"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_box,
            textvariable=self.knjiga_view_var,
            bg=body.cget("bg"),
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(top, bg=body.cget("bg"))
        actions.pack(side="right")
        self.knjiga_json_button = gui_style.pill(
            actions, "JSON", self.show_knjiga_json_view, kind="grey"
        )
        self.knjiga_json_button.pack(side="left")
        self.knjiga_api_button = gui_style.pill(
            actions, "Minimax API", self.show_knjiga_api_view, kind="yellow"
        )
        self.knjiga_api_button.pack(side="left", padx=(8, 0))
        self.knjiga_refresh_button = gui_style.pill(
            actions, "Osveži API", self.refresh_knjige_from_api, kind="blue"
        )
        self.knjiga_refresh_button.pack(side="left", padx=(8, 0))
        ToolTip(self.knjiga_json_button, "Predogled knjig iz odprtega KIR/KPR JSON (originalni stolpci).")
        ToolTip(
            self.knjiga_api_button,
            "Predogled že kreiranih IR/PR v Minimaxu (API) za izbrano obdobje.",
        )
        ToolTip(self.knjiga_refresh_button, "Ponovno preberi knjige iz Minimax API.")

        tk.Label(
            body,
            textvariable=self.knjiga_summary_var,
            bg=body.cget("bg"),
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            wraplength=980,
            justify="left",
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(6, 0))

        self.knjige_notebook = ttk.Notebook(parent)
        self.knjige_notebook.pack(fill="both", expand=True)
        self.knjiga_ir_frame = ttk.Frame(self.knjige_notebook, style="Panel.TFrame", padding=(6, 6))
        self.knjiga_pr_frame = ttk.Frame(self.knjige_notebook, style="Panel.TFrame", padding=(6, 6))
        self.knjige_notebook.add(self.knjiga_ir_frame, text="  Knjiga IR  ")
        self.knjige_notebook.add(self.knjiga_pr_frame, text="  Knjiga PR  ")
        self.knjiga_ir_tree: ttk.Treeview | None = None
        self.knjiga_pr_tree: ttk.Treeview | None = None
        self._rebuild_knjiga_trees()
        self._populate_knjiga_tree("IR")
        self._populate_knjiga_tree("PR")

    def _on_knjige_tools_toggled(self, open_: bool) -> None:
        self.config["ui_knjige_tools_open"] = bool(open_)

    def _knjiga_column_spec(self, book: str) -> tuple[tuple[str, ...], dict[str, str], dict[str, int]]:
        """Stolpci kot Minimax/FURS knjiga IR (P2–P27) oziroma PR (P2–P21)."""
        if self.knjiga_view_mode == "api":
            columns = (
                "zapst", "api_id", "date", "invoice", "party", "tax_id",
                "amount", "status", "match",
            )
            headings = {
                "zapst": "1 ZŠT",
                "api_id": "API ID",
                "date": "Datum",
                "invoice": "4 Listina",
                "party": "Kupec" if book == "IR" else "Dobavitelj",
                "tax_id": "ID za DDV",
                "amount": "7 Znesek",
                "status": "Status",
                "match": "KIR/KPR",
            }
            widths = {
                "zapst": 55, "api_id": 80, "date": 95, "invoice": 150, "party": 220,
                "tax_id": 110, "amount": 100, "status": 90, "match": 120,
            }
            return columns, headings, widths
        if book == "IR":
            # Uradna knjiga izdanih računov (FURS KIR / Minimax tisk).
            columns = (
                "zapst", "obdobje", "p2", "p3", "p4", "p5", "p6ds", "p6",
                "p7", "p8", "p9", "p10", "p11", "p12", "p13",
                "p14", "p15", "p16",
                "p17", "p18", "p19", "p20", "p21", "p22",
                "p23", "p24", "p25", "p26", "p27",
            )
            headings = {
                "zapst": "1 ZŠT",
                "obdobje": "2 Obdobje",
                "p2": "3 Dat knj",
                "p3": "4 Listina",
                "p4": "Dat list",
                "p5": "Kupec",
                "p6ds": "ID za DDV",
                "p6": "Drž",
                "p7": "7 Vred brez DDV",
                "p8": "8 Samoobd",
                "p9": "9 Oprošč",
                "p10": "10 EU blago",
                "p11": "11 EU stor",
                "p12": "12 Prod dalj",
                "p13": "13 Montaža",
                "p14": "14 DDV 22%",
                "p15": "15 DDV 9,5%",
                "p16": "16 DDV 5%",
                "p17": "17 EU DDV 22%",
                "p18": "18 EU stor 22%",
                "p19": "19 EU DDV 9,5%",
                "p20": "20 EU stor 9,5%",
                "p21": "21 EU DDV 5%",
                "p22": "22 EU stor 5%",
                "p23": "23 Samoobd 22%",
                "p24": "24 Samoobd 9,5%",
                "p25": "25 Samoobd 5%",
                "p26": "26 Uvoz DDV",
                "p27": "27 Neobdavč",
            }
            widths = {
                "zapst": 55, "obdobje": 70, "p2": 90, "p3": 150, "p4": 90,
                "p5": 200, "p6ds": 110, "p6": 45,
                "p7": 110, "p8": 95, "p9": 95, "p10": 100, "p11": 100, "p12": 100, "p13": 95,
                "p14": 100, "p15": 100, "p16": 95,
                "p17": 105, "p18": 110, "p19": 105, "p20": 110, "p21": 100, "p22": 100,
                "p23": 110, "p24": 110, "p25": 100, "p26": 100, "p27": 90,
            }
            return columns, self._knjiga_apply_ddvo_headings(book, headings), widths
        # Uradna knjiga prejetih računov (FURS KPR / Minimax tisk).
        columns = (
            "zapst", "obdobje", "p2", "p4", "p3", "p5", "p6", "p7ds", "p7",
            "p8", "p9", "p10", "p11", "p12", "p13", "p14", "p15", "p16",
            "p17", "p18", "p19", "p20", "p21",
        )
        headings = {
            "zapst": "1 ZŠT",
            "obdobje": "2 Obdobje",
            "p2": "3 Dat knj",
            "p4": "4 Dat pr",
            "p3": "5 Listina",
            "p5": "6 Dat list",
            "p6": "7 Dobavitelj",
            "p7ds": "ID za DDV",
            "p7": "Drž",
            "p8": "8 Vred brez DDV",
            "p9": "9 Samoobd",
            "p10": "10 Prid BL",
            "p11": "11 Prej ST",
            "p12": "12 Neprem",
            "p13": "13 OS",
            "p14": "14 Oprošč",
            "p15": "15 Opr nepr",
            "p16": "16 Opr OS",
            "p17": "17 Neodb DDV",
            "p18": "18 VST 22%",
            "p19": "19 VST 9,5%",
            "p20": "20 VST 5%",
            "p21": "21 Pavšal",
        }
        widths = {
            "zapst": 55, "obdobje": 70, "p2": 90, "p4": 90, "p3": 150, "p5": 90,
            "p6": 200, "p7ds": 110, "p7": 45,
            "p8": 110, "p9": 95, "p10": 100, "p11": 100, "p12": 95, "p13": 90,
            "p14": 95, "p15": 100, "p16": 95,
            "p17": 100, "p18": 100, "p19": 100, "p20": 95, "p21": 95,
        }
        return columns, self._knjiga_apply_ddvo_headings(book, headings), widths

    def _knjiga_cell_date(self, row: Mapping[str, Any], field: str) -> str:
        parsed = parse_iso_date(row.get(field))
        if parsed is not None:
            return format_si_date(parsed)
        return str(row.get(field) or "").strip()

    def _knjiga_cell_obdobje(self, row: Mapping[str, Any]) -> str:
        """Prikaz obdobja kot Minimax (npr. 01-03.26 za tromesečje, sicer 06.26)."""
        # Pri filtru jan–mar (davčno 0103) prikaži obdobje filtra — enako Minimax 1-Obd.
        if self.filter_from_date and self.filter_to_date:
            f0, f1 = self.filter_from_date, self.filter_to_date
            if (
                f0.year == f1.year
                and f0.month != f1.month
                and f0.day == 1
                and f1 == month_bounds(f1.year, f1.month)[1]
            ):
                return f"{f0.month:02d}-{f1.month:02d}.{str(f0.year)[-2:]}"
        raw = str(row.get("OBDOBJE") or "").strip()
        if not re.fullmatch(r"\d{4}", raw):
            return raw
        m1 = int(raw[:2])
        m2 = int(raw[2:])
        year = self.filter_from_date.year if self.filter_from_date else date.today().year
        # FURS span MM+MM (0406 = apr–jun istega leta).
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            yy = str(year)[-2:]
            if m1 == m2:
                return f"{m1:02d}.{yy}"
            return f"{m1:02d}-{m2:02d}.{yy}"
        parsed = parse_obdobje_mmyy(raw)
        if parsed is not None:
            y, m = parsed
            return f"{m:02d}.{str(y)[-2:]}"
        return raw

    def _knjiga_cell_money(self, row: Mapping[str, Any], field: str) -> str:
        raw = row.get(field)
        if raw in (None, ""):
            return "0,00"
        return format_money(raw)

    def _knjiga_money_columns(self, book: str) -> tuple[str, ...]:
        if self.knjiga_view_mode == "api":
            return ("amount",)
        if book == "IR":
            return tuple(f"p{i}" for i in range(7, 28))
        return tuple(f"p{i}" for i in range(8, 22))

    def _knjiga_column_field(self, column: str) -> str:
        """Tree stolpec → FURS polje (p7 → P7)."""
        if column.startswith("p") and column[1:].isdigit():
            return column.upper()
        return column

    def _knjiga_ddvo_codes(self, book: str, column: str) -> tuple[str, ...]:
        """Polja DDV-O obrazca za stolpec knjige (npr. p7 → ('11',))."""
        field = self._knjiga_column_field(column)
        if not str(field).upper().startswith("P"):
            return ()
        return core.ddvo_codes_for_field(book, field)

    def _knjiga_heading_with_ddvo(self, book: str, column: str, base: str) -> str:
        """Naslov stolpca + kam gre v DDV-O (npr. »7 Vred →11«)."""
        codes = self._knjiga_ddvo_codes(book, column)
        if not codes:
            return base
        return f"{base} →{'+'.join(codes)}"

    def _knjiga_apply_ddvo_headings(
        self,
        book: str,
        headings: dict[str, str],
    ) -> dict[str, str]:
        return {
            col: self._knjiga_heading_with_ddvo(book, col, text)
            for col, text in headings.items()
        }

    def _build_knjiga_column_checks(
        self,
        parent: ttk.Frame,
        book: str,
        columns: tuple[str, ...],
        headings: dict[str, str],
    ) -> None:
        """Chk za vsak stolpec (vklop/izklop prikaza)."""
        wrap = ttk.Frame(parent, style="Panel.TFrame")
        wrap.pack(fill="x", pady=(0, 4))
        tools = ttk.Frame(wrap, style="Panel.TFrame")
        tools.pack(fill="x")
        ttk.Label(tools, text="Stolpci:", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        btn_all = gui_style.pill(
            tools, "Vse označi", lambda b=book: self._knjiga_set_all_columns(b, True), kind="grey"
        )
        btn_all.pack(side="left", padx=(0, 4))
        btn_none = gui_style.pill(
            tools, "Vse odznači", lambda b=book: self._knjiga_set_all_columns(b, False), kind="grey"
        )
        btn_none.pack(side="left", padx=(0, 4))
        gui_style.pill(
            tools, "Neničelni", lambda b=book: self._knjiga_hide_zero_columns(b), kind="blue"
        ).pack(side="left", padx=(0, 4))
        gui_style.pill(
            tools, "Zneski", lambda b=book: self._knjiga_set_money_columns_only(b), kind="grey"
        ).pack(side="left", padx=(0, 8))
        ToolTip(btn_all, "Označi vse stolpce (prikaži vse).")
        ToolTip(btn_none, "Odznači vse stolpce (skrij vse).")
        ToolTip(
            tools,
            "Vse označi / odznači = chk. Neničelni = skrij stolpce z 0,00. "
            "Zneski = identiteta + vsi zneskovni.",
        )

        scroll_row = ttk.Frame(wrap, style="Panel.TFrame")
        scroll_row.pack(fill="x", pady=(2, 0))
        canvas = tk.Canvas(scroll_row, height=30, highlightthickness=0, bg=self.colors["panel"])
        hbar = ttk.Scrollbar(scroll_row, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hbar.set)
        canvas.pack(side="top", fill="x", expand=True)
        hbar.pack(side="bottom", fill="x")
        inner = ttk.Frame(canvas, style="Panel.TFrame")
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scroll(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, height=inner.winfo_reqheight())

        inner.bind("<Configure>", _sync_scroll)

        prev = self.knjiga_column_vars.get(book) or {}
        vars_map: dict[str, tk.BooleanVar] = {}
        for column in columns:
            old = prev.get(column)
            var = tk.BooleanVar(value=bool(old.get()) if old is not None else True)
            vars_map[column] = var
            full = headings.get(column, column)
            if " →" in full:
                base, _, ddvo = full.partition(" →")
                if len(base) > 14:
                    base = base[:13] + "…"
                short = f"{base} →{ddvo}"
            else:
                short = full if len(full) <= 18 else full[:16] + "…"
            tip = f"Stolpec: {full}"
            codes = self._knjiga_ddvo_codes(book, column)
            if codes:
                tip += f"\nDDV-O obrazec: polje {'+'.join(codes)}"
            chk = ttk.Checkbutton(
                inner,
                text=short,
                variable=var,
                command=lambda b=book: self._apply_knjiga_displaycolumns(b),
            )
            chk.pack(side="left", padx=(0, 8))
            ToolTip(chk, tip)
        self.knjiga_column_vars[book] = vars_map

    def _knjiga_set_all_columns(self, book: str, value: bool) -> None:
        for var in (self.knjiga_column_vars.get(book) or {}).values():
            var.set(value)
        self._apply_knjiga_displaycolumns(book)

    def _knjiga_set_money_columns_only(self, book: str) -> None:
        money = set(self._knjiga_money_columns(book))
        identity = {
            "zapst", "obdobje", "p2", "p3", "p4", "p5", "p6", "p6ds", "p7", "p7ds",
            "date", "invoice", "party", "tax_id", "api_id",
        }
        for col, var in (self.knjiga_column_vars.get(book) or {}).items():
            var.set(col in identity or col in money)
        self._apply_knjiga_displaycolumns(book)

    def _knjiga_hide_zero_columns(self, book: str) -> None:
        """Skrij zneskovne stolpce s Σ 0,00 — ostanejo vidni samo podatki."""
        money = set(self._knjiga_money_columns(book))
        amounts = self.knjiga_totals_amounts.get(book) or {}
        identity = {
            "zapst", "obdobje", "p2", "p3", "p4", "p5", "p6", "p6ds", "p7", "p7ds",
            "date", "invoice", "party", "tax_id", "api_id", "status", "match",
        }
        for col, var in (self.knjiga_column_vars.get(book) or {}).items():
            if col in identity:
                var.set(True)
            elif col in money:
                try:
                    amount = Decimal(str(amounts.get(col, 0) or 0))
                except Exception:
                    amount = Decimal("0")
                var.set(amount != 0)
            else:
                var.set(True)
        self._apply_knjiga_displaycolumns(book)

    def _apply_knjiga_displaycolumns(self, book: str) -> None:
        tree = self.knjiga_ir_tree if book == "IR" else self.knjiga_pr_tree
        if tree is None:
            return
        vars_map = self.knjiga_column_vars.get(book) or {}
        all_cols = list(tree["columns"])
        visible = [c for c in all_cols if vars_map.get(c) is None or bool(vars_map[c].get())]
        if not visible:
            # Vedno vsaj zap. št., da drevo ne pade.
            visible = [all_cols[0]] if all_cols else []
            if visible and visible[0] in vars_map:
                vars_map[visible[0]].set(True)
        tree.configure(displaycolumns=visible)
        self._refresh_knjiga_totals_bar(book)

    def _build_knjiga_totals_bar(
        self,
        parent: ttk.Frame,
        book: str,
        columns: tuple[str, ...],
        headings: dict[str, str],
    ) -> None:
        """Sumarni zneski pod chk — svetel trak, samo neničelni stolpci."""
        card_bg = self.colors["card"]
        bar = tk.Frame(
            parent,
            bg=card_bg,
            highlightbackground=self.colors["accent"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(
            bar,
            text="Skupaj",
            bg=card_bg,
            fg=self.colors["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        inner = tk.Frame(bar, bg=card_bg)
        inner.pack(fill="x", pady=(4, 0))
        self.knjiga_totals_labels[book] = {}
        self.knjiga_totals_frames[book] = bar
        self.knjiga_totals_inner[book] = inner
        self.knjiga_totals_amounts[book] = {}
        self.knjiga_totals_headings[book] = {
            col: headings.get(col, col) for col in columns if col in set(self._knjiga_money_columns(book))
        }
        tk.Label(
            inner,
            text="(ni zneskov — odpri podatke / osveži knjigo)",
            bg=card_bg,
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left")

    def _set_knjiga_totals(
        self,
        book: str,
        totals: Mapping[str, Decimal],
        *,
        visible_rows: int,
        auto_hide_zeros: bool = True,
    ) -> None:
        """Nastavi Σ; privzeto Neničelni (skrij stolpce z 0,00) + sumarni čipi."""
        self.knjiga_totals_amounts[book] = {
            col: Decimal(str(val or 0)) for col, val in totals.items()
        }
        if auto_hide_zeros:
            self._knjiga_hide_zero_columns(book)
        else:
            self._render_knjiga_totals_chips(book)
            self._apply_knjiga_displaycolumns(book)
        vars_map = self.knjiga_column_vars.get(book) or {}
        nonzero = [
            f"{col.upper()}={format_money(val)}"
            for col, val in totals.items()
            if val and (vars_map.get(col) is None or bool(vars_map[col].get()))
        ]
        tip = ", ".join(nonzero[:12])
        if len(nonzero) > 12:
            tip += " …"
        if self.knjiga_view_mode == "json" and self.dataset and self.filter_from_date and self.filter_to_date:
            ir_n = sum(1 for r in self.dataset.kir if self._row_in_knjiga_period(r))
            pr_n = sum(1 for r in self.dataset.kpr if self._row_in_knjiga_period(r))
            base = (
                f"JSON knjiga FURS {self.filter_from_date.isoformat()} – {self.filter_to_date.isoformat()}: "
                f"IR {ir_n}, PR {pr_n} (prikaz Knjiga {book}: {visible_rows}). "
                "Filter = davčno obdobje (kot DDV-O); po naložitvi so neničelni stolpci "
                "(Vse označi / Neničelni)."
            )
        elif self.knjiga_view_mode == "api":
            ir_n = len(self.knjiga_records.get("IR") or [])
            pr_n = len(self.knjiga_records.get("PR") or [])
            period = self.knjiga_period or self._filter_iso_bounds()
            base = (
                f"Minimax API {period[0]} – {period[1]}: IR {ir_n}, PR {pr_n} "
                f"(prikaz Knjiga {book}: {visible_rows})."
            )
        else:
            base = self.knjiga_summary_var.get().split(" | Σ")[0] or "Knjige"
        if tip:
            self.knjiga_summary_var.set(f"{base} | Σ {book}: {tip}")
        else:
            self.knjiga_summary_var.set(base)

    def _render_knjiga_totals_chips(self, book: str) -> None:
        """Osveži vidne sumarne »čipe« (neničelni + vklopljeni stolpci), v več vrsticah."""
        inner = self.knjiga_totals_inner.get(book)
        if inner is None:
            return
        card_bg = self.colors["card"]
        chip_bg = self.colors["chip_bg"]
        for child in inner.winfo_children():
            child.destroy()
        self.knjiga_totals_labels[book] = {}
        vars_map = self.knjiga_column_vars.get(book) or {}
        amounts = self.knjiga_totals_amounts.get(book) or {}
        headings = self.knjiga_totals_headings.get(book) or {}
        money_cols = list(self._knjiga_money_columns(book))
        chips: list[tuple[str, Decimal, str]] = []
        for column in money_cols:
            if vars_map.get(column) is not None and not bool(vars_map[column].get()):
                continue
            amount = amounts.get(column, Decimal("0"))
            if not amount:
                continue
            chips.append((column, amount, headings.get(column, column.upper())))
        if not chips:
            tk.Label(
                inner,
                text="Skupaj: 0,00 (ni neničelnih zneskov v vklopljenih stolpcih)",
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(side="left")
            return
        # Več vrstic — da so vidni vsi Σ (7…20), ne samo prvi čip.
        per_row = 6
        for start in range(0, len(chips), per_row):
            row_frame = tk.Frame(inner, bg=card_bg)
            row_frame.pack(fill="x", anchor="w", pady=(0, 2))
            for column, amount, title in chips[start : start + per_row]:
                chip = tk.Frame(row_frame, bg=chip_bg, padx=8, pady=4)
                chip.pack(side="left", padx=(0, 8), pady=2)
                tk.Label(
                    chip,
                    text=title,
                    bg=chip_bg,
                    fg=self.colors["chip_fg"],
                    font=("Segoe UI", 8),
                ).pack(anchor="w")
                lab = tk.Label(
                    chip,
                    text=format_money(amount),
                    bg=chip_bg,
                    fg=self.colors["chip_value"],
                    font=("Segoe UI", 11, "bold"),
                )
                lab.pack(anchor="e")
                self.knjiga_totals_labels[book][column] = lab

    def _refresh_knjiga_totals_bar(self, book: str) -> None:
        """Po chk osveži sumarne čipe."""
        self._render_knjiga_totals_chips(book)

    def _rebuild_knjiga_trees(self) -> None:
        for frame, book, attr in (
            (self.knjiga_ir_frame, "IR", "knjiga_ir_tree"),
            (self.knjiga_pr_frame, "PR", "knjiga_pr_tree"),
        ):
            for child in frame.winfo_children():
                child.destroy()
            self.knjiga_totals_labels[book] = {}
            self.knjiga_totals_frames[book] = None
            self.knjiga_totals_inner[book] = None
            self.knjiga_totals_amounts[book] = {}
            top = ttk.Frame(frame, style="Panel.TFrame")
            top.pack(fill="x", pady=(0, 6))
            if self.knjiga_view_mode == "api":
                label = (
                    "Minimax knjiga izdanih računov (API)"
                    if book == "IR"
                    else "Minimax knjiga prejetih računov (API)"
                )
            else:
                label = (
                    "Knjiga izdanih računov (FURS KIR / JSON)"
                    if book == "IR"
                    else "Knjiga prejetih računov (FURS KPR / JSON)"
                )
            ttk.Label(top, text=label, style="SectionTitle.TLabel").pack(side="left")
            search_var = self.knjiga_ir_search_var if book == "IR" else self.knjiga_pr_search_var
            self._pack_tab_search(
                top,
                search_var,
                on_change=lambda b=book: self._populate_knjiga_tree(b),
                clear_command=lambda b=book: self._clear_knjiga_search(b),
                tip=f"Išči v knjigi {book}: listina, partner, znesek, datum …",
            )
            columns, headings, widths = self._knjiga_column_spec(book)
            self._build_knjiga_column_checks(frame, book, columns, headings)
            self._build_knjiga_totals_bar(frame, book, columns, headings)
            tree = self._make_tree(frame, columns, headings, widths, selectmode="browse")
            gui_style.apply_tree_tags(tree, "match_ok", "match_api_only", "match_local_only", "totals")
            setattr(self, attr, tree)
            self._apply_knjiga_displaycolumns(book)

    def show_knjiga_json_view(self) -> None:
        self.knjiga_view_mode = "json"
        self.knjiga_view_var.set("Predogled: JSON (KIR/KPR)")
        self._rebuild_knjiga_trees()
        self._populate_knjiga_tree("IR")
        self._populate_knjiga_tree("PR")
        self.status_var.set("Knjige: predogled JSON.")

    def show_knjiga_api_view(self) -> None:
        self.knjiga_view_mode = "api"
        self.knjiga_view_var.set("Predogled: Minimax API")
        self._rebuild_knjiga_trees()
        bounds = self._filter_iso_bounds()
        if self.knjiga_period == bounds and (
            self.knjiga_records.get("IR") or self.knjiga_records.get("PR")
        ):
            self._populate_knjiga_tree("IR")
            self._populate_knjiga_tree("PR")
            self.status_var.set("Knjige: predogled Minimax API (predhodno naloženo).")
            return
        self.refresh_knjige_from_api()

    def _clear_knjiga_search(self, book: str) -> None:
        if book == "IR":
            self.knjiga_ir_search_var.set("")
        else:
            self.knjiga_pr_search_var.set("")
        self._populate_knjiga_tree(book)

    def _invalidate_knjige_for_period_change(self) -> None:
        bounds = self._filter_iso_bounds()
        if self.knjiga_period and self.knjiga_period != bounds:
            self.knjiga_records = {"IR": [], "PR": []}
            self.knjiga_period = None
        if hasattr(self, "knjiga_ir_tree") and self.knjiga_ir_tree is not None:
            if self.knjiga_view_mode == "json":
                self._populate_knjiga_tree("IR")
                self._populate_knjiga_tree("PR")
            else:
                self.knjiga_summary_var.set(
                    "Obdobje spremenjeno — klikni »Osveži API« ali »Minimax API«."
                )
                self._populate_knjiga_tree("IR")
                self._populate_knjiga_tree("PR")

    def _local_book_refs(self, book: str) -> dict[str, Mapping[str, Any]]:
        refs: dict[str, Mapping[str, Any]] = {}
        if not self.dataset:
            return refs
        rows = self.dataset.kir if book == "IR" else self.dataset.kpr
        for row in rows:
            if not self._row_in_period(book, row):
                continue
            if book == "IR":
                metrics = core.ir_metrics(row, self.dataset.kpr)
                if metrics.get("tax_only"):
                    continue
            key = minimax_api.normal_invoice_reference(row.get("P3"))
            if key:
                refs[key] = row
        return refs

    def refresh_knjige_from_api(self) -> None:
        if not self.active_company:
            messagebox.showinfo("Knjige", "Najprej izberi podjetje.", parent=self.root)
            return
        self.knjiga_view_mode = "api"
        self.knjiga_view_var.set("Predogled: Minimax API")
        if not self.minimax_client or not self.minimax_client.organisation_id:
            self.connect_minimax_api(after_connect=self.refresh_knjige_from_api)
            return
        if self.knjiga_ir_tree is None or list(self.knjiga_ir_tree["columns"]) != list(
            self._knjiga_column_spec("IR")[0]
        ):
            self._rebuild_knjiga_trees()
        date_from, date_to = self._filter_iso_bounds()
        client = self.minimax_client

        def task() -> dict[str, Any]:
            assert client is not None
            return {
                "IR": client.invoice_book("IR", date_from=date_from, date_to=date_to),
                "PR": client.invoice_book("PR", date_from=date_from, date_to=date_to),
                "period": (date_from, date_to),
            }

        def success(result: Any) -> None:
            self.knjiga_records = {
                "IR": list(result.get("IR") or []),
                "PR": list(result.get("PR") or []),
            }
            self.knjiga_period = tuple(result.get("period") or (date_from, date_to))
            self._populate_knjiga_tree("IR")
            self._populate_knjiga_tree("PR")
            ir_n = len(self.knjiga_records["IR"])
            pr_n = len(self.knjiga_records["PR"])
            self.knjiga_summary_var.set(
                f"Minimax API {date_from} – {date_to}: IR {ir_n}, PR {pr_n}. "
                "Stolpec KIR/KPR = ujemanje z lokalnim JSON."
            )
            self.status_var.set(f"Knjige API: IR {ir_n}, PR {pr_n}.")
            try:
                self.notebook.tab(4, text=f"  Knjige  IR {ir_n} / PR {pr_n}  ")
            except tk.TclError:
                pass

        self._run_api_worker(
            task,
            success,
            busy_text=f"Berem Minimax knjige {date_from} – {date_to} …",
        )

    def _populate_knjiga_tree(self, book: str) -> None:
        tree = self.knjiga_ir_tree if book == "IR" else self.knjiga_pr_tree
        if tree is None:
            return
        tree.delete(*tree.get_children())
        if self.knjiga_view_mode == "json":
            self._populate_knjiga_tree_json(book, tree)
        else:
            self._populate_knjiga_tree_api(book, tree)

    def _populate_knjiga_tree_json(self, book: str, tree: ttk.Treeview) -> None:
        if not self.dataset:
            self.knjiga_summary_var.set("JSON: najprej odpri KIR/KPR podatke.")
            self._set_knjiga_totals(book, {}, visible_rows=0)
            try:
                idx = 0 if book == "IR" else 1
                self.knjige_notebook.tab(idx, text=f"  Knjiga {book}  0  ")
            except tk.TclError:
                pass
            return
        search_var = self.knjiga_ir_search_var if book == "IR" else self.knjiga_pr_search_var
        tokens = self._search_tokens(search_var.get())
        columns = list(tree["columns"])
        money_cols = self._knjiga_money_columns(book)
        totals: dict[str, Decimal] = {col: Decimal("0") for col in money_cols}
        visible = 0
        rows = self.dataset.kir if book == "IR" else self.dataset.kpr

        for index, row in enumerate(rows):
            if not self._row_in_knjiga_period(row):
                continue
            # Celotna FURS knjiga: vključno samoobdavčitev (kot Minimax/eDavki).
            if book == "IR":
                metrics = core.ir_metrics(row, self.dataset.kpr)
                tax_only = bool(metrics.get("tax_only"))
                values_map = {
                    "zapst": str(row.get("ZAPST") or ""),
                    "obdobje": self._knjiga_cell_obdobje(row),
                    "p2": self._knjiga_cell_date(row, "P2"),
                    "p3": str(row.get("P3") or ""),
                    "p4": self._knjiga_cell_date(row, "P4"),
                    "p5": str(row.get("P5") or ""),
                    "p6ds": str(row.get("P6DS") or ""),
                    "p6": str(row.get("P6") or ""),
                    **{f"p{i}": self._knjiga_cell_money(row, f"P{i}") for i in range(7, 28)},
                }
                tags = ("tax_only",) if tax_only else (("odd",) if visible % 2 else ())
                search_extra = (
                    values_map["p3"],
                    values_map["p5"],
                    values_map["p6ds"],
                    "samoobdavčitev" if tax_only else "izdani",
                )
            else:
                metrics = core.pr_metrics(row)
                self_assessment = bool(metrics.get("self_assessment"))
                vat_deductible = bool(metrics.get("vat_deductible"))
                values_map = {
                    "zapst": str(row.get("ZAPST") or ""),
                    "obdobje": self._knjiga_cell_obdobje(row),
                    "p2": self._knjiga_cell_date(row, "P2"),
                    "p4": self._knjiga_cell_date(row, "P4"),
                    "p3": str(row.get("P3") or ""),
                    "p5": self._knjiga_cell_date(row, "P5"),
                    "p6": str(row.get("P6") or ""),
                    "p7ds": str(row.get("P7DS") or ""),
                    "p7": str(row.get("P7") or ""),
                    **{f"p{i}": self._knjiga_cell_money(row, f"P{i}") for i in range(8, 22)},
                }
                tags = (
                    ("vat_not_deducted",)
                    if not vat_deductible
                    else (
                        ("self_assessment",)
                        if self_assessment
                        else (("odd",) if visible % 2 else ())
                    )
                )
                search_extra = (
                    values_map["p3"],
                    values_map["p6"],
                    values_map["p7ds"],
                    "samoobdavčitev" if self_assessment else "prejeti",
                )
            values = tuple(values_map.get(col, "") for col in columns)
            if not self._haystack_matches(
                tokens,
                self._evidence_row_search_chunks(book, row, metrics, extra=search_extra),
            ):
                continue
            for col in money_cols:
                field = self._knjiga_column_field(col)
                try:
                    totals[col] += core.decimal_value(row.get(field))
                except core.KirkprError:
                    pass
            tree.insert("", "end", iid=f"k{book.lower()}:json:{index}", tags=tags, values=values)
            visible += 1

        # Vrstica Σ v tabeli (ostane na dnu pri sortiranju).
        total_values = []
        for col in columns:
            if col == "zapst":
                total_values.append("Σ")
            elif col in money_cols:
                total_values.append(format_money(totals[col]))
            elif col == "obdobje":
                total_values.append("SKUPAJ")
            else:
                total_values.append("")
        tree.insert(
            "",
            "end",
            iid=f"k{book.lower()}:totals",
            tags=("totals",),
            values=tuple(total_values),
        )
        self._set_knjiga_totals(book, totals, visible_rows=visible)
        ir_n = sum(1 for r in self.dataset.kir if self._row_in_knjiga_period(r))
        pr_n = sum(1 for r in self.dataset.kpr if self._row_in_knjiga_period(r))
        try:
            idx = 0 if book == "IR" else 1
            self.knjige_notebook.tab(idx, text=f"  Knjiga {book}  {visible}  ")
            self.notebook.tab(4, text=f"  Knjige  IR {ir_n} / PR {pr_n}  ")
        except tk.TclError:
            pass

    def _populate_knjiga_tree_api(self, book: str, tree: ttk.Treeview) -> None:
        search_var = self.knjiga_ir_search_var if book == "IR" else self.knjiga_pr_search_var
        tokens = self._search_tokens(search_var.get())
        local_refs = self._local_book_refs(book)
        api_refs: set[str] = set()
        visible = 0
        columns = list(tree["columns"])
        money_cols = self._knjiga_money_columns(book)
        totals: dict[str, Decimal] = {col: Decimal("0") for col in money_cols}

        for record in self.knjiga_records.get(book) or []:
            ref = minimax_api.invoice_record_reference(record)
            ref_key = minimax_api.normal_invoice_reference(ref)
            if ref_key:
                api_refs.add(ref_key)
            match = "V KIR/KPR" if ref_key and ref_key in local_refs else "Samo v Minimax"
            tag = "match_ok" if match == "V KIR/KPR" else "match_api_only"
            rid = record.get("IssuedInvoiceId") if book == "IR" else record.get("ReceivedInvoiceId")
            if rid is None:
                for key in ("ID", "Id", "id"):
                    if record.get(key) is not None:
                        rid = record.get(key)
                        break
            amount = minimax_api.invoice_record_amount(record)
            values_map = {
                "zapst": str(visible + 1),
                "api_id": str(rid or ""),
                "date": minimax_api.invoice_record_date(record),
                "invoice": ref,
                "party": minimax_api.invoice_record_party(record),
                "tax_id": minimax_api.invoice_record_tax_id(record),
                "amount": format_money(amount),
                "status": minimax_api.invoice_record_status(record),
                "match": match,
            }
            values = tuple(values_map.get(col, "") for col in columns)
            if not self._haystack_matches(tokens, values):
                continue
            try:
                totals["amount"] += core.decimal_value(amount)
            except (core.KirkprError, KeyError):
                pass
            tags = (tag,) if visible % 2 == 0 else (tag, "odd")
            tree.insert("", "end", iid=f"k{book.lower()}:api:{visible}", tags=tags, values=values)
            visible += 1

        for ref_key, row in local_refs.items():
            if ref_key in api_refs:
                continue
            values_map = {
                "zapst": str(visible + 1),
                "api_id": "",
                "date": str(row.get("P2") or row.get("P4") or ""),
                "invoice": str(row.get("P3") or ""),
                "party": str(row.get("P5") or "") if book == "IR" else str(row.get("P6") or ""),
                "tax_id": str(row.get("P6DS") or "") if book == "IR" else str(row.get("P7DS") or ""),
                "amount": "",
                "status": "",
                "match": "Manjka v Minimax",
            }
            values = tuple(values_map.get(col, "") for col in columns)
            if not self._haystack_matches(tokens, values):
                continue
            tree.insert(
                "",
                "end",
                iid=f"k{book.lower()}:local:{visible}",
                tags=("match_local_only",),
                values=values,
            )
            visible += 1

        total_values = []
        for col in columns:
            if col == "zapst":
                total_values.append("Σ")
            elif col in money_cols:
                total_values.append(format_money(totals[col]))
            elif col == "match":
                total_values.append("SKUPAJ")
            else:
                total_values.append("")
        tree.insert(
            "",
            "end",
            iid=f"k{book.lower()}:totals",
            tags=("totals",),
            values=tuple(total_values),
        )
        self._set_knjiga_totals(book, totals, visible_rows=visible)

        if not (self.knjiga_records.get("IR") or self.knjiga_records.get("PR")):
            self.knjiga_summary_var.set(
                "Minimax API: ni naloženih knjig — klikni »Osveži API« / »Minimax API«."
            )
        try:
            idx = 0 if book == "IR" else 1
            self.knjige_notebook.tab(idx, text=f"  Knjiga {book}  {visible}  ")
        except tk.TclError:
            pass

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.choose_source())
        self.root.bind("<Control-Shift-M>", lambda _event: self.load_data_from_minimax())
        self.root.bind("<Control-l>", lambda _event: self.open_last_source())
        self.root.bind("<Control-s>", lambda _event: self.save_accounts())
        self.root.bind("<Control-Shift-S>", lambda _event: self.save_working_copy())
        self.root.bind("<Control-e>", lambda _event: self.export_files())
        self.root.bind("<Control-b>", lambda _event: self.show_navigation_panel())
        self.root.bind("<F5>", lambda _event: self.reload_source())

    def _last_action_text(self) -> str:
        action = str(self.config.get("last_action") or "")
        if not action:
            return ""
        label = ACTION_LABELS.get(action, action)
        detail = str(self.config.get("last_action_detail") or "")
        timestamp = str(self.config.get("last_action_at") or "").replace("T", " ")[:19]
        suffix = f" — {detail}" if detail else ""
        when = f" ({timestamp})" if timestamp else ""
        return f"Zadnje dejanje: {label}{suffix}{when}"

    def _save_session_state(self) -> None:
        pr_account = self._account_code(self.account_var.get()) or "4190"
        ir_account = self._account_code(self.ir_account_var.get()) or "7601"
        self.config["last_account"] = pr_account
        self.config["last_ir_account"] = ir_account
        profile = self._profile_config()
        profile["last_account"] = pr_account
        profile["last_ir_account"] = ir_account
        try:
            self.config["active_tab"] = int(self.notebook.index(self.notebook.select()))
        except (tk.TclError, ValueError):
            pass
        state = self.root.state()
        if state in {"normal", "zoomed"}:
            self.config["window_state"] = state
        if state == "normal":
            geometry = self.root.geometry()
            if "x" in geometry:
                self.config["window_geometry"] = geometry
        if hasattr(self, "workspace_paned"):
            try:
                navigation_width = int(self.workspace_paned.sashpos(0))
                if navigation_width >= NAVIGATION_MIN_WIDTH:
                    self.navigation_width = min(600, navigation_width)
            except tk.TclError:
                pass
        self.config["navigation_width"] = self.navigation_width
        core.save_config(self.config, self.config_file)

    def _record_action(self, action: str, detail: str = "") -> None:
        self.config["last_action"] = action
        self.config["last_action_detail"] = detail
        self.config["last_action_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self._save_session_state()

    def _save_auto_reopen_preference(self) -> None:
        self.config["auto_reopen_last_source"] = self.auto_reopen_var.get()
        self._save_session_state()
        state = "vključeno" if self.auto_reopen_var.get() else "izključeno"
        self.status_var.set(f"Samodejno odpiranje zadnje datoteke je {state}.")

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        try:
            active = int(self.notebook.index(self.notebook.select()))
            self.config["active_tab"] = active
            core.save_config(self.config, self.config_file)
            nav_item = {
                0: "nav:ir",
                1: "nav:pr",
                2: "nav:ddvo",
                3: "nav:api",
                4: "nav:knjige",
            }.get(active)
            if nav_item and hasattr(self, "nav_tree") and self.nav_tree.exists(nav_item):
                self.nav_tree.selection_set(nav_item)
                self.nav_tree.see(nav_item)
        except (OSError, tk.TclError, ValueError):
            pass

    def on_close(self) -> None:
        if self.working_dirty and self.dataset:
            answer = messagebox.askyesnocancel(
                "Neshranjeni popravki",
                "Delovna kopija vsebuje začasne popravke.\n\n"
                "Da = potrdi in shrani delovno kopijo\n"
                "Ne = zapri brez zapisa začasnih popravkov\n"
                "Prekliči = vrni se v program",
                parent=self.root,
            )
            if answer is None:
                return
            if answer and self.save_working_copy(quiet=True) is None:
                return
        try:
            self._save_session_state()
        except OSError:
            pass
        try:
            import kirkpr_force_exit as force_exit

            force_exit.stop_guardian()
        except Exception:
            pass
        self.root.destroy()

    def _is_projest_vasco_source(self, source: Path | str | None) -> bool:
        """Vasco Excel/SQLite gre v ProJest — KIR/KPR ga ne bere več."""
        path = Path(source or "")
        suffix = path.suffix.casefold()
        name = path.name.casefold()
        if suffix in {".xls", ".xlsx", ".xlsm", ".sqlite3", ".sqlite", ".db"}:
            return True
        if "kirkpr_excel" in name or name.startswith("if ") or name.startswith("kp"):
            return True
        return False

    def _forget_projest_vasco_last_source(self) -> None:
        profile = self._profile_config()
        for store in (self.config, profile):
            for key in ("last_source_file", "last_excel_sqlite"):
                value = str(store.get(key) or "")
                if value and self._is_projest_vasco_source(Path(value)):
                    store[key] = ""
        try:
            core.save_config(self.config, self.config_file)
        except OSError:
            pass

    def open_last_source(self, silent: bool = False) -> None:
        value = str(self._profile_config().get("last_source_file") or self.config.get("last_source_file") or "")
        source = Path(value) if value else None
        if source and source.is_file():
            if self._is_projest_vasco_source(source):
                self._forget_projest_vasco_last_source()
                msg = (
                    "Zadnji vir je Vasco/Excel SQLite — uvoz je v ProJest Studio.\n"
                    "Tu odpri FURS ZIP/JSON/XML/CSV."
                )
                self.status_var.set("Vasco vir → ProJest Studio.")
                if not silent:
                    messagebox.showinfo("Vasco → ProJest", msg, parent=self.root)
                return
            self.load_source(source)
            return
        if not silent:
            messagebox.showinfo(
                "Ni zadnje datoteke",
                "Zadnja vhodna datoteka še ni shranjena ali pa ne obstaja več.",
                parent=self.root,
            )

    def _seed_and_refresh_recent_sessions(self) -> None:
        # Najprej uvozi morebitne JSON seje iz configa (enkrat).
        try:
            migrated = self.sessions_db.migrate_from_config(self.config)
            if migrated:
                core.seed_recent_sessions_from_profiles(self.config)
                core.save_config(self.config, self.config_file)
        except OSError:
            pass
        if not self.sessions_db.list_sessions():
            core.seed_recent_sessions_from_profiles(self.config)
            for row in self.config.get("recent_sessions") or []:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("company_key") or "")
                company = company_registry.find_company(self.companies, key) if key else None
                if company:
                    zst = company_registry.company_zst(company) or "—"
                    name = company_registry.company_name(company)
                    row["company_label"] = f"{zst} {name}"
                try:
                    self.sessions_db.upsert(
                        company_key=str(row.get("company_key") or ""),
                        company_label=str(row.get("company_label") or ""),
                        source=str(row.get("source") or ""),
                        working_copy=str(row.get("working_copy") or "") or None,
                        period_from=str(row.get("period_from") or ""),
                        period_to=str(row.get("period_to") or ""),
                        title=str(row.get("title") or ""),
                    )
                except ValueError:
                    continue
        self._refresh_recent_sessions_combo()

    def _refresh_recent_sessions_combo(self, select_path: Path | str | None = None) -> None:
        if not hasattr(self, "recent_session_combo"):
            return
        rows = self.sessions_db.list_sessions()
        labels: list[str] = []
        mapping: dict[str, dict[str, Any]] = {}
        for row in rows:
            path = self.sessions_db.open_path(row)
            if path is None:
                # Ostane na seznamu (manjkajoča datoteka) — uporabnik lahko briše.
                pass
            label = str(row.get("label") or core.format_recent_session_label(row))
            base = label
            n = 2
            while label in mapping:
                label = f"{base} ({n})"
                n += 1
            row = dict(row)
            row["label"] = label
            mapping[label] = row
            labels.append(label)
        self._recent_session_by_label = mapping
        active_key = (
            company_registry.company_key(self.active_company) if self.active_company else ""
        )
        self._recent_session_updating = True
        try:
            self.recent_session_combo.configure(values=labels)
            selected = ""
            if self._selected_session_id:
                for label, row in mapping.items():
                    if int(row.get("id") or 0) == int(self._selected_session_id):
                        # Ne ohrani izbora seje druge firme.
                        if (
                            not active_key
                            or str(row.get("company_key") or "") == active_key
                        ):
                            selected = label
                        break
            if not selected and select_path:
                want = str(Path(select_path))
                for label, row in mapping.items():
                    candidates = {
                        str(row.get("source") or ""),
                        str(row.get("working_copy") or ""),
                    }
                    if want in candidates:
                        selected = label
                        break
            # Privzeto: prva seja aktivne firme (ne Co.Next, če je odprt Projest).
            if not selected and active_key:
                for label, row in mapping.items():
                    if str(row.get("company_key") or "") == active_key:
                        selected = label
                        break
            if not selected and labels and not active_key:
                selected = labels[0]
            self.recent_session_var.set(selected)
            entry = mapping.get(selected) if selected else None
            self._selected_session_id = int(entry["id"]) if entry and entry.get("id") else None
        finally:
            self._recent_session_updating = False

    def _current_session_entry(self) -> dict[str, Any] | None:
        label = self.recent_session_var.get().strip()
        return self._recent_session_by_label.get(label)

    def _remember_current_session(
        self,
        *,
        working_copy: Path | str | None = None,
        title: str = "",
        notes: str = "",
        use_selected_id: bool = False,
    ) -> dict[str, Any] | None:
        if not self.active_company or not self.dataset:
            return None
        key = company_registry.company_key(self.active_company)
        zst = company_registry.company_zst(self.active_company) or "—"
        name = company_registry.company_name(self.active_company)
        period_from, period_to = self._filter_iso_bounds()
        suppress_key = (key, period_from, period_to)
        if suppress_key in self._suppress_session_remember_keys:
            return None
        wc = working_copy
        if wc is None:
            wc = str(self._profile_config().get("last_working_copy") or "") or None
        # Ne pripni delovne kopije iz drugega obdobja (npr. maj k junij seji).
        if wc:
            prefer_bounds = None
            if period_from and period_to:
                start = parse_iso_date(period_from)
                end = parse_iso_date(period_to)
                if start and end:
                    prefer_bounds = (start, end)
            usable, _reason = self._session_file_usable(Path(str(wc)), prefer_bounds)
            if not usable:
                wc = None
        # Vzporedno še v config (združljivost), glavno pa SQLite.
        core.remember_recent_session(
            self.config,
            company_key=key,
            company_label=f"{zst} {name}",
            source=self.dataset.source_path,
            working_copy=wc,
            period_from=period_from,
            period_to=period_to,
        )
        sid = self._selected_session_id if use_selected_id else None
        source_s = str(self.dataset.source_path or "")
        # Minimax virtual: ista firma+obdobje → ena seja (brez duplikatov api/journals).
        if sid is None and (".virtual" in source_s.casefold() or "minimax" in source_s.casefold()):
            existing = self.sessions_db.find_virtual_for_company_period(
                key, period_from, period_to
            )
            if existing and existing.get("id"):
                sid = int(existing["id"])
        entry = self.sessions_db.upsert(
            company_key=key,
            company_label=f"{zst} {name}",
            source=self.dataset.source_path,
            working_copy=wc,
            period_from=period_from,
            period_to=period_to,
            title=title,
            notes=notes,
            session_id=sid,
        )
        if ".virtual" in source_s.casefold() or "minimax" in source_s.casefold():
            try:
                self.sessions_db.delete_virtual_for_company_period(
                    key,
                    period_from,
                    period_to,
                    keep_id=int(entry.get("id") or 0) or None,
                )
            except Exception:
                pass
        self._selected_session_id = int(entry.get("id") or 0) or None
        open_path = Path(str(wc)) if wc and Path(str(wc)).is_file() else self.dataset.source_path
        self._refresh_recent_sessions_combo(select_path=open_path)
        return entry

    def _on_recent_session_combo_pick(self, _event: tk.Event | None = None) -> None:
        """Izbira seje → firmo + obdobje (brez samodejnega prenosa — sicer Briši ne deluje)."""
        if self._recent_session_updating:
            return
        entry = self._current_session_entry()
        self._selected_session_id = int(entry["id"]) if entry and entry.get("id") else None
        if not entry:
            return
        # Samo kontekst (firma/mesec). Podatke naloži »Odpri sejo« / dvojni klik.
        self._apply_session_company_and_period(entry)
        company_name = company_registry.company_name(self.active_company or {}) or "—"
        prefer = self._session_period_bounds(entry)
        if prefer is not None:
            self.status_var.set(
                f"Seja izbrana: {company_name}, "
                f"{format_si_date(prefer[0])} – {format_si_date(prefer[1])} "
                "— klikni »Odpri sejo« za podatke."
            )
        else:
            self.status_var.set(
                f"Seja izbrana: {company_name} — klikni »Odpri sejo« za podatke."
            )

    def _session_period_bounds(self, entry: Mapping[str, Any]) -> tuple[date, date] | None:
        """Obdobje iz seje (period_from/to ali YYYY-MM v naslovu)."""
        period_from = str(entry.get("period_from") or "")[:10]
        period_to = str(entry.get("period_to") or "")[:10]
        if period_from and period_to:
            start = parse_iso_date(period_from)
            end = parse_iso_date(period_to)
            if start and end:
                return start, end
        text = " ".join(
            str(entry.get(key) or "")
            for key in ("title", "label", "source", "source_path", "working_copy")
        )
        match = re.search(r"(20\d{2})[-/](\d{2})", text)
        if not match:
            return None
        year = int(match.group(1))
        month = int(match.group(2))
        if month < 1 or month > 12:
            return None
        return month_bounds(year, month)

    def _apply_session_company_and_period(self, entry: Mapping[str, Any]) -> bool:
        """Nastavi firmo in mesec iz seje. Vrne True, če je obdobje nastavljeno."""
        company_key = str(entry.get("company_key") or "")
        company = company_registry.find_company(self.companies, company_key) if company_key else None
        if company:
            current_key = (
                company_registry.company_key(self.active_company) if self.active_company else ""
            )
            if company_key != current_key:
                if self.working_dirty and self.dataset:
                    self.save_working_copy(quiet=True)
                self._activate_company(company, user_action=False)
                self._record_action(
                    "session_company",
                    f"Zšt {company_registry.company_zst(company)}; "
                    f"{company_registry.company_name(company)}",
                )
        prefer = self._session_period_bounds(entry)
        if prefer is None:
            return False
        self._set_period_filter(prefer[0], prefer[1], refresh=bool(self.dataset))
        return True

    @staticmethod
    def _session_is_minimax(entry: Mapping[str, Any]) -> bool:
        text = " ".join(
            str(entry.get(key) or "")
            for key in ("title", "label", "source", "source_path", "working_copy")
        ).casefold()
        return "minimax" in text or ".virtual" in text

    def _session_file_usable(
        self,
        path: Path | None,
        prefer: tuple[date, date] | None,
    ) -> tuple[bool, str]:
        """Ali je shranjena datoteka uporabna za izbrano obdobje seje."""
        if path is None or not path.is_file():
            return False, "ni shranjene datoteke"
        text = str(path).replace("\\", "/")
        if prefer is not None:
            start, end = prefer
            start_s, end_s = start.isoformat(), end.isoformat()
            ym = f"{start.year}-{start.month:02d}"
            periods_in_path = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
            if periods_in_path and start_s not in text and end_s not in text and ym not in text:
                return (
                    False,
                    f"datoteka je za drugo obdobje ({periods_in_path[0]}…), seja je {start_s}–{end_s}",
                )
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return True, path.name  # naj load_source pove napako
        if isinstance(raw, Mapping):
            payload = raw.get("DDV_KIR_KPR") if isinstance(raw.get("DDV_KIR_KPR"), Mapping) else raw
            if isinstance(payload, Mapping):
                kir = payload.get("Lista_KIR") or {}
                kpr = payload.get("Lista_KPR") or {}
                kir_rows = kir.get("KIR", []) if isinstance(kir, Mapping) else kir
                kpr_rows = kpr.get("KPR", []) if isinstance(kpr, Mapping) else kpr
                n_kir = len(kir_rows or []) if isinstance(kir_rows, list) else 0
                n_kpr = len(kpr_rows or []) if isinstance(kpr_rows, list) else 0
                if n_kir == 0 and n_kpr == 0 and (
                    "MINIMAX_DELOVNA_KOPIJA" in raw or "DDV_KIR_KPR" in raw
                ):
                    return False, "delovna kopija je prazna (0 IR/PR)"
        return True, path.name

    def _ask_session_data_source(
        self,
        entry: Mapping[str, Any],
        path: Path | None,
    ) -> str | None:
        """Vpraša pred odpiranjem: 'sql' | 'minimax' | None (prekliči)."""
        company = str(entry.get("company_label") or entry.get("label") or "seja")
        prefer = self._session_period_bounds(entry)
        period_txt = (
            f"{format_si_date(prefer[0])} – {format_si_date(prefer[1])}"
            if prefer
            else "—"
        )
        usable, file_hint = self._session_file_usable(path, prefer)
        has_file = usable
        if not has_file:
            file_hint = (
                f"{file_hint} — gumb SQL je onemogočen.\n"
                "Najprej odpri prek Minimax API (program shrani delovno kopijo), "
                "nato bo »Shranjena seja« spet na voljo."
            )

        result: dict[str, str | None] = {"value": None}
        win = tk.Toplevel(self.root)
        win.title("Odpri sejo — vir podatkov")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors.get("bg", "#0b1220"))
        win.minsize(520, 300)
        outer = ttk.Frame(win, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=f"{company}\nObdobje: {period_txt}",
            style="Panel.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            outer,
            text="Od kod naložiti podatke?",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            outer,
            text=f"Shranjena datoteka: {file_hint}",
            style="Muted.TLabel",
            wraplength=480,
        ).pack(anchor="w", pady=(0, 14))

        def _pick(value: str) -> None:
            result["value"] = value
            win.destroy()

        def _cancel(_event: tk.Event | None = None) -> None:
            result["value"] = None
            win.destroy()

        sql_btn = ttk.Button(
            outer,
            text="1) Shranjena seja (SQL / datoteka) — hitro",
            style="Accent.TButton",
            command=lambda: _pick("sql"),
        )
        sql_btn.pack(fill="x", pady=(0, 8))
        if not has_file:
            sql_btn.state(["disabled"])

        ttk.Button(
            outer,
            text="2) Minimax API — sveže (počasneje)",
            command=lambda: _pick("minimax"),
        ).pack(fill="x", pady=(0, 12))

        ttk.Button(outer, text="Prekliči", command=_cancel).pack(anchor="e")
        win.bind("<Escape>", _cancel)
        win.bind("<Return>", lambda _e: _pick("sql" if has_file else "minimax"))
        win.update_idletasks()
        w, h = max(520, win.winfo_reqwidth()), max(300, win.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2)
        y = self.root.winfo_rooty() + max(40, (self.root.winfo_height() - h) // 3)
        win.geometry(f"{w}x{h}+{x}+{y}")
        self.root.wait_window(win)
        return result["value"]

    def _open_session_from_saved_file(
        self,
        entry: Mapping[str, Any],
        path: Path,
        prefer: tuple[date, date] | None,
    ) -> None:
        if self.working_dirty and self.dataset:
            self.save_working_copy(quiet=True)
        self.load_source(path, match_company=False, remember=False, prefer_period=prefer)
        if self.dataset:
            self._remember_current_session(title="", use_selected_id=True)
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
        self.status_var.set(
            f"Odprta seja (SQL/datoteka): "
            f"{self.recent_session_var.get() or entry.get('label') or path.name}"
        )

    def _open_session_from_minimax(
        self,
        entry: Mapping[str, Any],
        prefer: tuple[date, date] | None,
    ) -> None:
        company_name = company_registry.company_name(self.active_company or {}) or "—"
        period_txt = (
            f"{prefer[0].isoformat()} – {prefer[1].isoformat()}"
            if prefer
            else "—"
        )
        company_key = str(entry.get("company_key") or "")
        if company_key and prefer is not None:
            self._suppress_session_remember_keys.discard(
                (company_key, prefer[0].isoformat(), prefer[1].isoformat())
            )
        self.status_var.set(
            f"Seja Minimax: {company_name}, {period_txt} — prenašam podatke …"
        )
        self.load_data_from_minimax()

    def open_selected_session(self) -> None:
        entry = self._current_session_entry()
        if not entry:
            messagebox.showinfo("Seje", "Ni izbrane seje.", parent=self.root)
            return
        self._selected_session_id = int(entry.get("id") or 0) or None
        applied_period = self._apply_session_company_and_period(entry)
        path = self.sessions_db.open_path(entry)
        prefer = self._session_period_bounds(entry)

        # Minimax seje: vedno vprašaj SQL/datoteka ali svež API.
        if self._session_is_minimax(entry):
            choice = self._ask_session_data_source(entry, path)
            if choice is None:
                self.status_var.set("Odpiranje seje preklicano.")
                return
            if choice == "sql":
                usable, reason = self._session_file_usable(path, prefer)
                if usable and path is not None:
                    self._open_session_from_saved_file(entry, path, prefer)
                    return
                messagebox.showinfo(
                    "Seja",
                    "Shranjena datoteka ni uporabna za to sejo.\n"
                    f"({reason})\n\n"
                    "Izberi Minimax API za svež prenos obdobja.",
                    parent=self.root,
                )
                return
            self._open_session_from_minimax(entry, prefer)
            return

        if path is not None and path.is_file():
            self._open_session_from_saved_file(entry, path, prefer)
            return

        if not applied_period and path is None:
            messagebox.showinfo(
                "Seja ni na voljo",
                "Datoteka za to sejo ne obstaja več (premik/brisanje).\n"
                "Lahko jo zbrišeš s seznama (Briši).",
                parent=self.root,
            )
            self._refresh_recent_sessions_combo()
            return

        company_name = company_registry.company_name(self.active_company or {}) or "—"
        if prefer is not None:
            self.status_var.set(
                f"Seja: {company_name}, "
                f"{format_si_date(prefer[0])} – {format_si_date(prefer[1])} "
                "(datoteka ni na voljo — obdobje in firma sta nastavljena)."
            )
        else:
            self.status_var.set(f"Seja: firma {company_name} (obdobje v seji ni zapisano).")

    def _ask_wide_string(
        self,
        title: str,
        prompt: str,
        *,
        initialvalue: str = "",
        multiline: bool = False,
    ) -> str | None:
        """Širok dialog z Entry/Text — autosize glede na dolžino besedila."""
        result: dict[str, str | None] = {"value": None}
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors.get("bg", "#0b1220"))
        text0 = str(initialvalue or "")
        # Autosize: ~8 px/znak, omejitev 420–980.
        width_px = max(420, min(980, 80 + max(28, len(text0)) * 8))
        win.minsize(420, 140 if not multiline else 200)
        outer = ttk.Frame(win, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=prompt, style="Muted.TLabel", wraplength=width_px - 40).pack(
            anchor="w", pady=(0, 8)
        )
        if multiline:
            box = tk.Text(
                outer,
                height=4,
                width=max(40, min(100, len(text0) + 8)),
                wrap="word",
                font=("Segoe UI", 10),
                bg=self.colors.get("input", "#0f1724"),
                fg=self.colors.get("text", "#e8eef8"),
                insertbackground=self.colors.get("text", "#e8eef8"),
                relief="solid",
                borderwidth=1,
                padx=6,
                pady=4,
            )
            box.pack(fill="both", expand=True)
            if text0:
                box.insert("1.0", text0)
            box.focus_set()

            def _get() -> str:
                return box.get("1.0", "end-1c")

        else:
            var = tk.StringVar(value=text0)
            entry = ttk.Entry(outer, textvariable=var, font=("Segoe UI", 10))
            entry.pack(fill="x")
            entry.focus_set()
            entry.selection_range(0, "end")
            # Širina Entry v znakih.
            entry.configure(width=max(40, min(110, len(text0) + 6)))

            def _get() -> str:
                return var.get()

        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(12, 0))

        def _ok(_event: tk.Event | None = None) -> None:
            result["value"] = _get()
            win.destroy()

        def _cancel(_event: tk.Event | None = None) -> None:
            result["value"] = None
            win.destroy()

        ttk.Button(btns, text="Prekliči", command=_cancel).pack(side="right")
        ttk.Button(btns, text="V redu", style="Accent.TButton", command=_ok).pack(
            side="right", padx=(0, 8)
        )
        win.bind("<Return>", _ok)
        win.bind("<Escape>", _cancel)
        win.update_idletasks()
        # Centriraj in nastavi širino.
        h = max(win.winfo_reqheight(), 150 if not multiline else 220)
        w = max(width_px, win.winfo_reqwidth())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2)
        y = self.root.winfo_rooty() + max(40, (self.root.winfo_height() - h) // 3)
        win.geometry(f"{w}x{h}+{x}+{y}")
        self.root.wait_window(win)
        return result["value"]

    def save_current_session(self) -> None:
        """Eksplicitno shrani trenutno sejo (podatki + SQLite meta)."""
        if not self.dataset:
            messagebox.showinfo("Seje", "Najprej odpri KIR/KPR podatke.", parent=self.root)
            return
        if self.working_dirty:
            saved = self.save_working_copy(quiet=False)
            if saved is None:
                return
        else:
            # Posodobi delovno kopijo tiho, če še ni.
            self.save_working_copy(quiet=True)
        active_key = (
            company_registry.company_key(self.active_company) if self.active_company else ""
        )
        current = self._current_session_entry()
        # Ne prepiši seje druge firme (npr. combo še kaže Co.Next, aktivna je Projest).
        use_selected = bool(
            current
            and active_key
            and str(current.get("company_key") or "") == active_key
        )
        if not use_selected:
            self._selected_session_id = None
        default_title = ""
        if use_selected and current:
            default_title = str(current.get("title") or current.get("label") or "")
        if not default_title and self.active_company:
            zst = company_registry.company_zst(self.active_company) or "—"
            name = company_registry.company_name(self.active_company)
            period_from, period_to = self._filter_iso_bounds()
            default_title = core.format_recent_session_label(
                {
                    "company_label": f"{zst} {name}",
                    "period_from": period_from,
                    "period_to": period_to,
                    "source": str(self.dataset.source_path),
                    "working_copy": str(self._profile_config().get("last_working_copy") or ""),
                }
            )
        title = self._ask_wide_string(
            "Shrani sejo",
            "Ime seje (predlagano — lahko spremeniš ali pustiš):",
            initialvalue=default_title,
        )
        if title is None:
            self.status_var.set("Shranjevanje seje preklicano.")
            return
        entry = self._remember_current_session(title=title.strip(), use_selected_id=use_selected)
        if entry:
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
            self.status_var.set(f"Seja shranjena: {entry.get('label')}")
            messagebox.showinfo(
                "Seja shranjena",
                f"Seja je v SQLite:\n{self.sessions_db.path}\n\n{entry.get('label')}",
                parent=self.root,
            )

    def edit_selected_session(self) -> None:
        entry = self._current_session_entry()
        if not entry or not entry.get("id"):
            messagebox.showinfo("Seje", "Ni izbrane seje za urejanje.", parent=self.root)
            return
        suggested = str(entry.get("title") or "").strip()
        if not suggested:
            suggested = str(entry.get("label") or "")
        title = self._ask_wide_string(
            "Uredi sejo",
            "Ime seje (predlagano — lahko spremeniš):",
            initialvalue=suggested,
        )
        if title is None:
            return
        notes = self._ask_wide_string(
            "Uredi sejo",
            "Opomba (neobvezno):",
            initialvalue=str(entry.get("notes") or ""),
            multiline=True,
        )
        if notes is None:
            notes = str(entry.get("notes") or "")
        updated = self.sessions_db.update_meta(
            int(entry["id"]),
            title=title.strip(),
            notes=str(notes or "").strip(),
        )
        if updated:
            self._selected_session_id = int(updated["id"])
            self._refresh_recent_sessions_combo()
            self.status_var.set(f"Seja posodobljena: {updated.get('label')}")

    def delete_selected_session(self) -> None:
        entry = self._current_session_entry()
        if not entry or not entry.get("id"):
            messagebox.showinfo("Seje", "Ni izbrane seje za brisanje.", parent=self.root)
            return
        label = str(entry.get("label") or entry.get("id"))
        if not messagebox.askyesno(
            "Briši sejo",
            f"Odstraniti sejo s seznama?\n\n{label}\n\n"
            "Datoteke (ZIP / delovna kopija) ostanejo na disku.",
            parent=self.root,
        ):
            return
        sid = int(entry["id"])
        company_key = str(entry.get("company_key") or "")
        period_from = str(entry.get("period_from") or "")[:10]
        period_to = str(entry.get("period_to") or "")[:10]
        # Prepreči, da bi tekoči Minimax prenos takoj znova ustvaril isto sejo.
        if company_key and period_from and period_to:
            self._suppress_session_remember_keys.add((company_key, period_from, period_to))
        deleted = self.sessions_db.delete(sid)
        if self._session_is_minimax(entry) and company_key and period_from and period_to:
            try:
                self.sessions_db.delete_virtual_for_company_period(
                    company_key, period_from, period_to
                )
            except Exception:
                pass
        # Odstrani tudi iz config recent_sessions (stari seznam).
        try:
            src = str(entry.get("source") or entry.get("source_path") or "")
            wc = str(entry.get("working_copy") or "")
            rows_out: list[dict[str, Any]] = []
            for row in self.config.get("recent_sessions") or []:
                if not isinstance(row, dict):
                    continue
                same_company_period = (
                    str(row.get("company_key") or "") == company_key
                    and str(row.get("period_from") or "")[:10] == period_from
                    and str(row.get("period_to") or "")[:10] == period_to
                )
                same_file = (
                    (src and str(row.get("source") or "") == src)
                    or (wc and str(row.get("working_copy") or "") == wc)
                )
                if self._session_is_minimax(entry) and same_company_period:
                    continue
                if same_file:
                    continue
                rows_out.append(row)
            self.config["recent_sessions"] = rows_out
            core.save_config(self.config, self.config_file)
        except OSError:
            pass
        if self._selected_session_id == sid:
            self._selected_session_id = None
        self._refresh_recent_sessions_combo()
        if deleted:
            self.status_var.set(f"Seja odstranjena: {label}")
        else:
            messagebox.showwarning(
                "Seje",
                f"Seje ni bilo mogoče izbrisati (id={sid}).",
                parent=self.root,
            )

    def _on_recent_session_selected(self, _event: tk.Event | None = None) -> None:
        # Združljivost: stari klici → Odpri.
        self.open_selected_session()

    def _source_picker_initial_dir(self) -> str:
        """Privzeta mapa za odpiranje KIR/KPR (nastavitev → podjetje → zadnja)."""
        profile = self._profile_config()
        paths = self._company_paths()
        candidates = [
            str(self.config.get("source_input_dir") or "").strip(),
            str(profile.get("last_input_dir") or "").strip(),
            str(paths.ddv_root) if paths else "",
            str(self.config.get("last_input_dir") or "").strip(),
            str(Path.cwd()),
        ]
        for raw in candidates:
            if raw and Path(raw).is_dir():
                return raw
        return str(Path.cwd())

    def _source_filetypes(self, preferred: str | None = None) -> list[tuple[str, str]]:
        """Vrstni red filtrov glede na prednostni format (CSV/XML/JSON/ZIP)."""
        choice = str(
            preferred if preferred is not None else self.config.get("source_preferred_format") or "all"
        ).strip().casefold()
        all_types = [
            ("KIR/KPR podatki", "*.zip *.json *.xml *.csv"),
            ("ZIP arhiv", "*.zip"),
            ("JSON", "*.json"),
            ("XML", "*.xml"),
            ("CSV", "*.csv"),
            ("Vse datoteke", "*.*"),
        ]
        if choice in {"zip", "json", "xml", "csv"}:
            head = [row for row in all_types if choice in row[1].casefold() and "kir/kpr" not in row[0].casefold()]
            rest = [row for row in all_types if row not in head]
            return head + rest
        return all_types

    def choose_source(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Izberite KIR/KPR podatke (CSV / XML / JSON / ZIP)",
            initialdir=self._source_picker_initial_dir(),
            filetypes=self._source_filetypes(),
        )
        if selected:
            self.load_source(Path(selected))

    def reload_source(self) -> None:
        if self.dataset:
            if str(self.dataset.source_format or "") == "minimax-api":
                self.load_data_from_minimax()
                return
            self.load_source(self.dataset.source_path)

    def _clear_dataset_for_minimax_reload(self) -> None:
        """Počisti stare IR/PR / Knjige pred novim prenosom iz Minimaxa."""
        self.dataset = None
        self.source_dataset = None
        self.working_dirty = False
        self.pending_working_changes.clear()
        self.knjiga_records = {"IR": [], "PR": []}
        self.knjiga_period = None
        try:
            self.member_var.set("Vsebina: prenašam …")
            self.source_var.set("Minimax — prenos v teku …")
            self.format_var.set("Format: —")
            self.status_var.set("Čistim stare podatke, prenašam iz Minimaxa …")
            self.summary_vars["ir_count"].set("0")
            self.summary_vars["pr_count"].set("0")
            self.summary_vars["ir_value"].set("—")
            self.summary_vars["pr_value"].set("—")
            self.notebook.tab(0, text="  Izdani računi (IR)  0  ")
            self.notebook.tab(1, text="  Prejeti računi (PR)  0  ")
            self.nav_tree.item("nav:ir", text="  Izdani računi (0)")
            self.nav_tree.item("nav:pr", text="  Prejeti računi (0)")
        except Exception:
            pass
        for book in ("IR", "PR"):
            tree = self.knjiga_ir_tree if book == "IR" else self.knjiga_pr_tree
            if tree is None:
                continue
            try:
                tree.delete(*tree.get_children())
            except tk.TclError:
                pass
        try:
            self._populate_trees()
        except Exception:
            pass
        # Počisti tudi IR/PR/API tabele glavnega notebooka.
        for attr in ("ir_tree", "pr_tree", "api_tree"):
            tree = getattr(self, attr, None)
            if tree is None:
                continue
            try:
                tree.delete(*tree.get_children())
            except tk.TclError:
                pass

    def load_data_from_minimax(self) -> None:
        """Naloži IR/PR iz Minimax API za izbrano firmo in obdobje v program."""
        if self.api_busy:
            messagebox.showinfo(
                "Podatki iz Minimaxa",
                "Počakajte — trenutno Minimax opravilo še teče.",
                parent=self.root,
            )
            return
        if not self.active_company:
            messagebox.showinfo(
                "Podatki iz Minimaxa",
                "Najprej izberi podjetje z Org_ID.",
                parent=self.root,
            )
            return
        org_id = company_registry.company_org_id(self.active_company)
        if not org_id:
            messagebox.showerror(
                "Podatki iz Minimaxa",
                "Pri podjetju manjka Org_ID.",
                parent=self.root,
            )
            return
        if self.working_dirty:
            answer = messagebox.askyesnocancel(
                "Neshranjene spremembe",
                "Trenutni podatki imajo neshranjene spremembe.\n"
                "DA = shrani delovno kopijo, nato naloži iz Minimaxa\n"
                "NE = zavrzi in naloži\n"
                "Prekliči = prekini",
                parent=self.root,
            )
            if answer is None:
                return
            if answer and self.save_working_copy(quiet=False) is None:
                return

        if not self.minimax_client or not self.minimax_client.organisation_id:
            self.connect_minimax_api(after_connect=self.load_data_from_minimax)
            return

        connected = str(self.minimax_client.organisation_id)
        if connected != str(org_id):
            self.connect_minimax_api(after_connect=self.load_data_from_minimax)
            return

        date_from, date_to = self._filter_iso_bounds()
        client = self.minimax_client
        company = dict(self.active_company)
        tax = company_registry.company_tax_number(company)
        name = company_registry.company_name(company)
        company_key = company_registry.company_key(company)
        # Nov iskani prenos: dovoli shranjevanje seje + počisti stare podatke v UI.
        self._suppress_session_remember_keys.discard((company_key, date_from, date_to))
        self._clear_dataset_for_minimax_reload()
        progress_state: dict[str, Any] = {
            "text": "Pripravljam prenos …",
            "current": 0,
            "total": 0,
            "done": False,
            "error": None,
        }
        dialog = self._open_action_progress(
            title="Podatki iz Minimaxa",
            subtitle=f"{name} (Org {org_id})  •  {date_from} – {date_to}",
            initial="Berem temeljnice knjige IR/PR …",
        )

        def progress(message: str, *, current: int = 0, total: int = 0) -> None:
            progress_state["text"] = str(message or "")
            progress_state["current"] = int(current or 0)
            progress_state["total"] = int(total or 0)

        def task() -> dict[str, Any]:
            assert client is not None
            # Svež OAuth žeton pred dolgim prenosom (sicer HTTP 401 po timeoutu).
            progress("Obnavljam Minimax prijavo …", current=0, total=0)
            client.authenticate()
            # 1) Temeljnice knjige IR/PR — zanesljiv vir (stolpci FURS, DDV-O).
            #    Če API uporabnik nima »Pregled temeljnic«, nadaljuj z moduli IR/PR.
            start = parse_iso_date(date_from) or date.today()
            end = parse_iso_date(date_to) or date.today()
            fetch_from = (start - timedelta(days=45)).isoformat()
            fetch_to = (end + timedelta(days=45)).isoformat()
            progress("Berem temeljnice knjige IR/PR …", current=0, total=0)
            ir_journals: list[Any] = []
            pr_journals: list[Any] = []
            journals_blocked = False
            journals_error = ""
            try:
                books = client.journal_books(
                    date_from=fetch_from,
                    date_to=fetch_to,
                    types=("IR", "PR"),
                    progress=progress,
                )
                ir_journals = list(books.get("IR") or [])
                pr_journals = list(books.get("PR") or [])
            except Exception as exc:
                journals_blocked = True
                journals_error = str(exc)
                progress(
                    "Temeljnice niso dostopne — berem module IR/PR …",
                    current=0,
                    total=0,
                )

            ir_in = minimax_dataset.filter_journals_by_vat_period(
                ir_journals, "IR", date_from, date_to
            )
            pr_in = minimax_dataset.filter_journals_by_vat_period(
                pr_journals, "PR", date_from, date_to
            )

            # 2) Moduli za manjkajočo knjigo ALI ko temeljnice niso dovoljene (401).
            ir_rows: list[Any] = []
            pr_rows: list[Any] = []
            if journals_blocked or not ir_in:
                progress(
                    "Berem modul izdanih računov …"
                    if journals_blocked
                    else "Ni IR temeljnic — berem modul izdanih …",
                    current=0,
                    total=0,
                )
                try:
                    ir_rows = client.invoice_book(
                        "IR", date_from=date_from, date_to=date_to
                    )
                except Exception:
                    ir_rows = []
            if journals_blocked or not pr_in:
                progress(
                    "Berem modul prejetih računov …"
                    if journals_blocked
                    else "Ni PR temeljnic — berem modul prejetih …",
                    current=0,
                    total=0,
                )
                try:
                    pr_rows = client.invoice_book(
                        "PR", date_from=date_from, date_to=date_to
                    )
                except Exception:
                    pr_rows = []

            if journals_blocked and not ir_rows and not pr_rows:
                raise minimax_api.MinimaxApiError(
                    "Minimax ne dovoli branja temeljnic (»Pregled temeljnic«), "
                    "moduli IR/PR pa tudi niso vrnili podatkov.\n\n"
                    f"{journals_error}\n\n"
                    "V Minimaxu preveri pravice API uporabnika za to firmo "
                    "(temeljnice in/ali knjige IR/PR)."
                )

            prefer = "invoices" if journals_blocked else "journals"
            progress("Sestavljam KIR/KPR …", current=1, total=1)
            dataset, sources = minimax_dataset.dataset_from_minimax_hybrid(
                ir_invoice_records=ir_rows,
                pr_invoice_records=pr_rows,
                ir_journals=ir_journals,
                pr_journals=pr_journals,
                date_from=date_from,
                date_to=date_to,
                company_name=name,
                tax_number=tax,
                org_id=str(org_id),
                prefer=prefer,
            )
            if sources.get("IR") == "invoices":
                ir_raw: list[Any] = list(ir_rows)
            else:
                ir_raw = [
                    minimax_dataset.journal_as_book_row(row, "IR") for row in ir_in
                ]
            if sources.get("PR") == "invoices":
                pr_raw: list[Any] = list(pr_rows)
            else:
                pr_raw = [
                    minimax_dataset.journal_as_book_row(row, "PR") for row in pr_in
                ]

            kind = "mixed"
            if sources.get("IR") == "invoices" and sources.get("PR") == "invoices":
                kind = "invoices"
            elif sources.get("IR") == "journals" and sources.get("PR") == "journals":
                kind = "journals"
            elif sources.get("IR") == "empty" and sources.get("PR") == "empty":
                kind = "empty"

            return {
                "dataset": dataset,
                "ir_raw": ir_raw,
                "pr_raw": pr_raw,
                "period": (date_from, date_to),
                "source_kind": kind,
                "sources": sources,
                "journals_blocked": journals_blocked,
                "journals_error": journals_error,
            }

        def finish_ui(result: Any | None, error: BaseException | None) -> None:
            self._close_action_progress(dialog)
            progress_state["done"] = True
            if error is not None:
                self.status_var.set("Prenos iz Minimaxa ni uspel.")
                self.api_status_var.set("Prenos iz Minimaxa ni uspel.")
                messagebox.showerror(
                    "Podatki iz Minimaxa",
                    f"Prenos ni uspel:\n\n{error}",
                    parent=self.root,
                )
                return
            assert result is not None
            dataset = result["dataset"]
            kind = str(result.get("source_kind") or "mixed")
            sources = result.get("sources") or {}

            def _src_sl(code: str) -> str:
                return {
                    "invoices": "knjiga",
                    "journals": "temeljnice",
                    "empty": "—",
                }.get(str(code), str(code))

            if kind == "journals":
                kind_label = "temeljnice IR/PR"
            elif kind == "invoices":
                kind_label = "knjiga IR/PR"
            elif kind == "mixed":
                kind_label = (
                    f"IR {_src_sl(sources.get('IR', ''))} / "
                    f"PR {_src_sl(sources.get('PR', ''))}"
                )
            else:
                kind_label = "brez podatkov"
            display_error: BaseException | None = None
            try:
                self.source_dataset = copy.deepcopy(dataset)
                try:
                    core.apply_saved_accounts(dataset, self._profile_config())
                except Exception:
                    pass
                self.dataset = dataset
                self.working_dirty = False
                self.pending_working_changes.clear()
                prefer = (
                    parse_iso_date(date_from) or self.filter_from_date,
                    parse_iso_date(date_to) or self.filter_to_date,
                )
                self._init_period_filter_from_dataset(prefer=prefer)
                self.knjiga_records = {
                    "IR": list(result.get("ir_raw") or []),
                    "PR": list(result.get("pr_raw") or []),
                }
                self.knjiga_period = tuple(result.get("period") or (date_from, date_to))
                # Polni stolpci FURS (7…20 / P7–P27), ne ozek API predogled.
                self.knjiga_view_mode = "json"
                if hasattr(self, "knjiga_view_var"):
                    if kind == "journals":
                        preview = "Predogled: Minimax → KIR/KPR (temeljnice)"
                    elif kind == "mixed":
                        preview = f"Predogled: Minimax → KIR/KPR ({kind_label})"
                    else:
                        preview = "Predogled: Minimax → KIR/KPR (knjiga IR/PR)"
                    self.knjiga_view_var.set(preview)
                # Najprej obnovi stolpce Knjig (polni FURS), nato tabele.
                try:
                    self._rebuild_knjiga_trees()
                except Exception as exc:
                    display_error = display_error or exc
                try:
                    self._populate_trees()
                except Exception as exc:
                    display_error = display_error or exc
                try:
                    self._update_header_and_summary()
                except Exception as exc:
                    display_error = display_error or exc
                try:
                    self.export_button.configure(state="normal")
                except Exception:
                    pass
                self.source_var.set(
                    f"Minimax {kind_label} • Org {org_id} • {date_from} – {date_to}"
                )
                if kind == "journals":
                    self.format_var.set("Format: Minimax temeljnice")
                elif kind == "mixed":
                    self.format_var.set("Format: Minimax hibrid (knjiga + temeljnice)")
                else:
                    self.format_var.set("Format: Minimax knjiga IR/PR")
                self.period_var.set(f"Obdobje: {date_from} – {date_to}")
                self.member_var.set(
                    f"Vsebina: IR {len(dataset.kir)} / PR {len(dataset.kpr)}"
                )
                try:
                    self._populate_knjiga_tree("IR")
                    self._populate_knjiga_tree("PR")
                except Exception as exc:
                    display_error = display_error or exc
                try:
                    self._populate_api_tree()
                except Exception as exc:
                    display_error = display_error or exc
                done_msg = (
                    f"Končano: {len(dataset.kir)} IR, {len(dataset.kpr)} PR "
                    f"({kind_label}, {date_from}–{date_to})."
                )
                self.status_var.set(done_msg)
                self.api_status_var.set(done_msg)
                self._record_action(
                    "minimax_load",
                    f"Org {org_id}; {kind}; {date_from}–{date_to}; "
                    f"IR {len(dataset.kir)} / PR {len(dataset.kpr)}",
                )
                try:
                    # Shrani delovno kopijo → SQL/seja bo naslednjič na voljo.
                    saved_wc = self.save_working_copy(quiet=True)
                    if saved_wc is None:
                        self._remember_current_session(title="", use_selected_id=False)
                except Exception:
                    try:
                        self._remember_current_session(title="", use_selected_id=False)
                    except Exception:
                        pass
            except Exception as exc:
                messagebox.showerror(
                    "Podatki iz Minimaxa",
                    f"Podatki so preneseni, a prikaz ni uspel:\n\n{exc}",
                    parent=self.root,
                )
                return
            if display_error is not None:
                messagebox.showwarning(
                    "Podatki iz Minimaxa",
                    f"Naloženo: IR {len(dataset.kir)}, PR {len(dataset.kpr)}.\n"
                    f"Del prikaza ni uspel:\n{display_error}",
                    parent=self.root,
                )
                return
            note = ""
            if result.get("journals_blocked"):
                note = (
                    "\n\nOpomba: Minimax ni dovolil branja temeljnic "
                    "(»Pregled temeljnic«) — uporabljen je modul knjige IR/PR."
                )
            messagebox.showinfo(
                "Podatki iz Minimaxa — končano",
                f"Prenos je končan.\n\n"
                f"Vir: {kind_label}\n"
                f"IR: {len(dataset.kir)}\n"
                f"PR: {len(dataset.kpr)}\n"
                f"Obdobje: {date_from} – {date_to}\n"
                f"Podjetje: {name} (Org {org_id})"
                f"{note}",
                parent=self.root,
            )

        def poll_progress() -> None:
            if progress_state.get("done"):
                return
            text = str(progress_state.get("text") or "")
            current = int(progress_state.get("current") or 0)
            total = int(progress_state.get("total") or 0)
            self._update_action_progress(dialog, text, current=current, total=total)
            if text:
                self.status_var.set(text)
                self.api_status_var.set(text)
            self.root.after(200, poll_progress)

        def run_worker() -> None:
            holder: dict[str, Any] = {}

            def work() -> None:
                try:
                    holder["result"] = task()
                except Exception as exc:
                    holder["error"] = exc

            worker = threading.Thread(target=work, name="MinimaxLoadData", daemon=True)
            worker.start()

            def poll_worker() -> None:
                if worker.is_alive():
                    self.root.after(100, poll_worker)
                    return
                self._set_api_busy(False)
                finish_ui(holder.get("result"), holder.get("error"))

            self.root.after(100, poll_worker)

        self._set_api_busy(True)
        self.api_status_var.set(f"Berem Minimax temeljnice IR/PR {date_from} – {date_to} …")
        self.status_var.set(f"Berem Minimax temeljnice IR/PR {date_from} – {date_to} …")
        self.root.after(200, poll_progress)
        run_worker()

    def _open_action_progress(
        self,
        *,
        title: str,
        subtitle: str,
        initial: str,
    ) -> dict[str, Any]:
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text=subtitle, wraplength=420).pack(anchor="w", pady=(4, 10))
        detail_var = tk.StringVar(value=initial)
        ttk.Label(frame, textvariable=detail_var, wraplength=420).pack(anchor="w")
        percent_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=percent_var).pack(anchor="w", pady=(6, 4))
        bar = ttk.Progressbar(frame, length=420, mode="indeterminate")
        bar.pack(fill="x", pady=(0, 8))
        bar.start(12)
        ttk.Label(
            frame,
            text="Počakajte — ne zapirajte programa med prenosom.",
            foreground="#555555",
        ).pack(anchor="w")
        win.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(40, (self.root.winfo_width() - win.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(40, (self.root.winfo_height() - win.winfo_height()) // 3)
            win.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        return {
            "win": win,
            "bar": bar,
            "detail_var": detail_var,
            "percent_var": percent_var,
            "mode": "indeterminate",
        }

    def _update_action_progress(
        self,
        dialog: dict[str, Any] | None,
        message: str,
        *,
        current: int = 0,
        total: int = 0,
    ) -> None:
        if not dialog:
            return
        win = dialog.get("win")
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        detail_var = dialog.get("detail_var")
        percent_var = dialog.get("percent_var")
        bar = dialog.get("bar")
        if detail_var is not None:
            detail_var.set(message)
        if total > 0 and bar is not None:
            if dialog.get("mode") != "determinate":
                try:
                    bar.stop()
                except tk.TclError:
                    pass
                bar.configure(mode="determinate", maximum=max(total, 1))
                dialog["mode"] = "determinate"
            bar["value"] = max(0, min(current, total))
            if percent_var is not None:
                pct = int(round(100.0 * current / total)) if total else 0
                percent_var.set(f"{current} / {total}  ({pct} %)")
        elif percent_var is not None and message:
            percent_var.set("")

    def _close_action_progress(self, dialog: dict[str, Any] | None) -> None:
        if not dialog:
            return
        win = dialog.get("win")
        bar = dialog.get("bar")
        if bar is not None:
            try:
                bar.stop()
            except tk.TclError:
                pass
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def load_source(
        self,
        source: Path,
        *,
        match_company: bool = True,
        remember: bool = True,
        prefer_period: tuple[date, date] | None = None,
    ) -> None:
        self.status_var.set(f"Berem {source.name} …")
        self.root.update_idletasks()
        preferred = str(self.config.get("source_preferred_format") or "all")
        if self._is_projest_vasco_source(source):
            self._forget_projest_vasco_last_source()
            self.status_var.set("Vasco/Excel → ProJest Studio.")
            messagebox.showinfo(
                "Vasco → ProJest",
                "Vasco (Excel IF*/kp* ali SQLite) uvažaj v ProJest Studio.\n\n"
                "KIR/KPR Studio bere FURS ZIP, JSON, XML ali CSV.",
                parent=self.root,
            )
            return
        try:
            dataset = core.load_dataset(source, preferred_format=preferred)
            if match_company:
                matched = company_registry.match_company(
                    self.companies,
                    tax_number=dataset.header.get("TaxPayerID"),
                    source_path=source,
                )
                if matched and (
                    not self.active_company
                    or company_registry.company_key(matched) != company_registry.company_key(self.active_company)
                ):
                    self._activate_company(matched)
            self.source_dataset = copy.deepcopy(dataset)
            core.apply_saved_accounts(dataset, self._profile_config())
        except Exception as exc:
            self.status_var.set("Uvoz ni uspel.")
            messagebox.showerror("Napaka pri branju", str(exc), parent=self.root)
            return
        self.dataset = dataset
        self.working_dirty = False
        self.pending_working_changes.clear()
        profile = self._profile_config()
        self.config["last_input_dir"] = str(source.parent)
        self.config["last_source_file"] = str(source)
        profile["last_input_dir"] = str(source.parent)
        profile["last_source_file"] = str(source)
        self._init_period_filter_from_dataset(prefer=prefer_period)
        self._populate_trees()
        self._update_header_and_summary()
        self.export_button.configure(state="normal")
        view = self._view_dataset() or dataset
        warning_text = f" Opozorila: {len(dataset.warnings)}." if dataset.warnings else ""
        self.status_var.set(
            f"Naloženo: {len(dataset.kir)} KIR in {len(dataset.kpr)} KPR; "
            f"filter {format_si_date(self.filter_from_date)}–{format_si_date(self.filter_to_date)}: "
            f"{len(view.kir)} IR / {len(view.kpr)} PR.{warning_text}"
        )
        if remember:
            self._remember_current_session()
        self._record_action("open", f"{source.name}; {len(dataset.kir)} KIR / {len(dataset.kpr)} KPR")

    def _sent_invoice_info(self, book: str, row: Mapping[str, Any]) -> dict[str, Any]:
        sent = self._profile_config().get("minimax_api_sent") or {}
        if not isinstance(sent, Mapping):
            return {}
        info = sent.get(f"invoice:{core.row_key(book, row)}")
        if not isinstance(info, Mapping):
            return {}
        expected_org = company_registry.company_org_id(self.active_company or {})
        if expected_org and str(info.get("organisation_id") or "") != expected_org:
            return {}
        return dict(info)

    def _sent_invoice_id(self, book: str, row: Mapping[str, Any]) -> str:
        info = self._sent_invoice_info(book, row)
        location = str(info.get("location") or "")
        resource = "issuedinvoices" if book == "IR" else "receivedinvoices"
        return minimax_browser.extract_minimax_record_id(location, resource)

    def _minimax_status_for_row(self, book: str, row: Mapping[str, Any]) -> str:
        expected_org = company_registry.company_org_id(self.active_company or {})
        connected_org = str(self.minimax_client.organisation_id or "") if self.minimax_client else ""
        if not expected_org or connected_org != expected_org:
            return "Poveži API"
        if getattr(self, "api_view_mode", "json") == "json" and not self.minimax_invoice_status_checked:
            return "JSON"
        if not self.minimax_invoice_status_checked or self.minimax_invoice_status_org != expected_org:
            return "Ni preverjeno"
        catalog = self.minimax_invoice_status_catalog.get(book, {})
        by_id = catalog.get("by_id", {})
        by_reference = catalog.get("by_reference", {})
        record_id = self._sent_invoice_id(book, row)
        if record_id and record_id in by_id:
            return str(by_id[record_id])
        reference = minimax_api.normal_invoice_reference(row.get("P3"))
        if reference and reference in by_reference:
            return str(by_reference[reference])
        return "Ni najden"

    def _row_exists_in_minimax(self, book: str, row: Mapping[str, Any]) -> bool:
        if not self.minimax_invoice_status_checked:
            return False
        status = self._minimax_status_for_row(book, row)
        return status not in {"Ni najden", "Ni preverjeno", "Poveži API", "JSON", ""}

    def _existing_refs_from_catalog(self) -> dict[str, dict[str, str]]:
        return {
            "IR": dict(self.minimax_invoice_status_catalog.get("IR", {}).get("by_reference") or {}),
            "PR": dict(self.minimax_invoice_status_catalog.get("PR", {}).get("by_reference") or {}),
        }

    def _reconcile_sent_map_with_minimax(self) -> dict[str, Any]:
        """Odstrani lokalno ODDANO sled, če listine v Minimaxu ni več; zabeleži razlike."""
        profile = self._profile_config()
        sent = profile.setdefault("minimax_api_sent", {})
        if not isinstance(sent, dict):
            sent = {}
            profile["minimax_api_sent"] = sent
        expected_org = company_registry.company_org_id(self.active_company or {})
        mode = self._api_transfer_mode()
        removed: list[str] = []
        only_program: list[str] = []
        in_both: list[str] = []
        if not self.dataset or not self.minimax_invoice_status_checked:
            return {"removed": removed, "only_program": only_program, "in_both": in_both}

        keys_to_delete: list[str] = []
        for book, rows in (("IR", self.dataset.kir), ("PR", self.dataset.kpr)):
            for row in rows:
                if not self._row_in_period(book, row):
                    continue
                if book == "IR" and core.ir_metrics(row, self.dataset.kpr)["tax_only"]:
                    continue
                invoice = str(row.get("P3") or "")
                label = f"{book} {invoice}"
                exists = self._row_exists_in_minimax(book, row)
                key = f"{mode}:{core.row_key(book, row)}"
                legacy = core.row_key(book, row) if mode == "journal" else ""
                info = sent.get(key)
                if info is None and legacy:
                    info = sent.get(legacy)
                if isinstance(info, Mapping) and expected_org and str(info.get("organisation_id") or "") != expected_org:
                    info = None
                if exists:
                    in_both.append(label)
                    self._cleared_listinas.discard(label)
                else:
                    only_program.append(label)
                    if info is not None:
                        removed.append(label)
                        self._cleared_listinas.add(label)
                        if key in sent:
                            keys_to_delete.append(key)
                        if legacy and legacy in sent:
                            keys_to_delete.append(legacy)
        for key in dict.fromkeys(keys_to_delete):
            sent.pop(key, None)
        if keys_to_delete:
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
        def label_key(value: str) -> tuple[Any, ...]:
            parts = str(value).split(" ", 1)
            return (parts[0],) + listina_sort_key(parts[-1] if len(parts) > 1 else value)

        summary = {
            "removed": sorted(removed, key=label_key),
            "only_program": sorted(only_program, key=label_key),
            "in_both": sorted(in_both, key=label_key),
            "org": expected_org,
            "mode": mode,
        }
        self.api_diff_summary = summary
        return summary

    def _api_state_for_row(self, book: str, row: Mapping[str, Any], sent_info: Mapping[str, Any] | None) -> tuple[str, str, str]:
        """Vrne (api_status, detail_prefix, tag) glede na JSON/Minimax pogled."""
        invoice = str(row.get("P3") or "")
        metrics = core.pr_metrics(row) if book == "PR" else None
        flags: list[str] = []
        if book == "PR" and metrics is not None:
            if metrics["self_assessment"]:
                flags.append("samoobdavčitev")
            flags.append("DDV se odbija" if metrics["vat_deductible"] else "DDV se ne odbija")
        vat_detail = ("; ".join(flags).capitalize() + ". ") if flags else ""

        if self.api_view_mode == "json" or not self.minimax_invoice_status_checked:
            if sent_info:
                detail = vat_detail + str(sent_info.get("location") or sent_info.get("at") or "Lokalna sled ODDANO")
                return "ODDANO", detail, "api_sent"
            return "ČAKA", vat_detail + "Lokalni JSON — še ni usklajeno z Minimaxom.", "api_ready"

        exists = self._row_exists_in_minimax(book, row)
        status = self._minimax_status_for_row(book, row)
        catalog = self.minimax_invoice_status_catalog.get(book, {})
        ref = minimax_api.normal_invoice_reference(invoice)
        record_id = ""
        if ref:
            record_id = str(catalog.get("by_reference_id", {}).get(ref) or "")
        if not record_id:
            record_id = self._sent_invoice_id(book, row)

        if exists:
            id_part = f" ID {record_id}" if record_id else ""
            detail = vat_detail + f"V Minimaxu: {status}{id_part}. Listina že obstaja — ne podvajaj."
            return "ODDANO", detail, "api_exists"
        label = f"{book} {invoice}"
        was_cleared = label in getattr(self, "_cleared_listinas", set())
        if sent_info or was_cleared:
            detail = vat_detail + "V Minimaxu ni več (zbrisano). Lokalna sled odstranjena — lahko znova ustvariš."
            return "ČAKA", detail, "api_missing"
        return "ČAKA", vat_detail + "V Minimaxu ni listine — pripravljeno za ustvarjanje.", "api_ready"

    def clear_ir_search(self) -> None:
        self.ir_search_var.set("")
        if self.dataset:
            self._populate_trees()

    def clear_pr_search(self) -> None:
        self.pr_search_var.set("")
        if self.dataset:
            self._populate_trees()

    def clear_ddvo_search(self) -> None:
        self.ddvo_search_var.set("")
        self._populate_ddvo()

    @staticmethod
    def _search_tokens(query: str) -> list[str]:
        return [token for token in re.sub(r"\s+", " ", str(query or "").strip().casefold()).split(" ") if token]

    @staticmethod
    def _haystack_matches(tokens: Sequence[str], chunks: Sequence[Any]) -> bool:
        if not tokens:
            return True
        haystack = " ".join(str(part or "") for part in chunks).casefold()
        return all(token in haystack for token in tokens)

    def _evidence_row_search_chunks(
        self,
        book: str,
        row: Mapping[str, Any],
        metrics: Mapping[str, Any],
        *,
        extra: Sequence[Any] = (),
    ) -> list[Any]:
        chunks: list[Any] = [book, *extra]
        for key, value in row.items():
            text = str(value or "").strip()
            if not text:
                continue
            chunks.append(text)
            parsed = parse_iso_date(text)
            if parsed is not None:
                chunks.append(format_si_date(parsed))
                chunks.append(parsed.isoformat())
        for key in ("gross", "net", "vat", "vat_22", "vat_95", "vat_5", "reported_vat", "expense"):
            if key not in metrics:
                continue
            amount = Decimal(str(metrics[key] or 0))
            chunks.append(format_money(amount))
            chunks.append(f"{amount:.2f}")
            chunks.append(f"{amount:.2f}".replace(".", ","))
        account = str(row.get("__konto__") or "")
        if account:
            chunks.append(account)
            chunks.append(self._account_name(account))
            chunks.append(self._account_label(account))
        return chunks

    def _populate_trees(self) -> None:
        if not self.dataset:
            return
        if not hasattr(self, "ir_tree") or not hasattr(self, "pr_tree"):
            return
        self.ir_tree.delete(*self.ir_tree.get_children())
        self.pr_tree.delete(*self.pr_tree.get_children())
        ir_tokens = self._search_tokens(self.ir_search_var.get())
        pr_tokens = self._search_tokens(self.pr_search_var.get())
        visible_ir = 0
        for index, row in enumerate(self.dataset.kir):
            if not self._row_in_period("IR", row):
                continue
            metrics = core.ir_metrics(row, self.dataset.kpr)
            tax_only = bool(metrics["tax_only"])
            account = str(row.get("__konto__") or "7601")
            status_txt = "—" if tax_only else self._minimax_status_for_row("IR", row)
            obravnava = "Samoobdavčitev → PR" if tax_only else "Izvoz v IR"
            if not self._haystack_matches(
                ir_tokens,
                self._evidence_row_search_chunks(
                    "IR",
                    row,
                    metrics,
                    extra=(status_txt, obravnava, "kupec", row.get("P5", "")),
                ),
            ):
                continue
            tags = ("tax_only",) if tax_only else (("odd",) if visible_ir % 2 else ())
            self.ir_tree.insert(
                "", "end", iid=f"ir:{index}", tags=tags,
                values=(
                    row.get("ZAPST", ""), row.get("P2", ""), row.get("P3", ""), row.get("P5", ""),
                    row.get("P6DS", ""),
                    format_money(metrics["net"]),
                    format_money(metrics["vat_22"]),
                    format_money(metrics["vat_95"]),
                    format_money(metrics["vat"]),
                    format_money(metrics["gross"]),
                    account, self._account_name(account),
                    status_txt,
                    obravnava,
                ),
            )
            visible_ir += 1
        visible_pr = 0
        for index, row in enumerate(self.dataset.kpr):
            if not self._row_in_period("PR", row):
                continue
            metrics = core.pr_metrics(row)
            self_assessment = bool(metrics["self_assessment"])
            vat_deductible = bool(metrics["vat_deductible"])
            account = str(row.get("__konto__") or "4190")
            status_txt = self._minimax_status_for_row("PR", row)
            vrsta = "Samoobdavčitev" if self_assessment else "Prejeti račun"
            if not self._haystack_matches(
                pr_tokens,
                self._evidence_row_search_chunks(
                    "PR",
                    row,
                    metrics,
                    extra=(
                        status_txt,
                        vrsta,
                        "DA" if self_assessment else "NE",
                        "DA" if vat_deductible else "NE",
                        "samoobdavčitev" if self_assessment else "",
                        "dobavitelj",
                        row.get("P6", ""),
                    ),
                ),
            ):
                continue
            tags = ("vat_not_deducted",) if not vat_deductible else (("self_assessment",) if self_assessment else (("odd",) if visible_pr % 2 else ()))
            self.pr_tree.insert(
                "", "end", iid=f"pr:{index}", tags=tags,
                values=(
                    row.get("ZAPST", ""), row.get("P2", ""), row.get("P3", ""), row.get("P6", ""),
                    row.get("P7DS", ""),
                    format_money(metrics["net"]),
                    format_money(metrics["vat_22"]),
                    format_money(metrics["vat_95"]),
                    format_money(metrics["vat"]),
                    format_money(metrics["gross"]),
                    account, self._account_name(account),
                    "DA" if self_assessment else "NE",
                    "DA" if vat_deductible else "NE",
                    status_txt,
                    vrsta,
                ),
            )
            visible_pr += 1
        self.selection_var.set("Izbranih PR: 0")
        self.ir_selection_var.set("Izbranih IR: 0")
        self._populate_api_tree()
        if hasattr(self, "knjiga_ir_tree") and self.knjiga_ir_tree is not None:
            if self.knjiga_view_mode == "json":
                self._populate_knjiga_tree("IR")
                self._populate_knjiga_tree("PR")
            elif self.knjiga_view_mode == "api":
                # Posodobi ujemanje KIR/KPR ob spremembi lokalnih podatkov.
                self._populate_knjiga_tree("IR")
                self._populate_knjiga_tree("PR")

    def _update_header_and_summary(self) -> None:
        assert self.dataset is not None
        full = self.dataset
        dataset = self._view_dataset() or full
        summary = core.dataset_summary(dataset)
        self.source_var.set(str(full.source_path))
        self.format_var.set(f"Format: {full.source_format}")
        self.period_var.set(
            f"Vir: {full.period_from} – {full.period_to}  •  "
            f"Filter: {self.filter_from_date.isoformat()} – {self.filter_to_date.isoformat()}"
        )
        members = ", ".join(full.source_members)
        self.member_var.set("Vsebina: " + (members if len(members) <= 70 else members[:67] + "…"))
        self.summary_vars["ir_count"].set(str(summary["ir_count"]))
        self.summary_vars["ir_value"].set(f"{format_money(summary['ir_net'])} EUR neto")
        self.summary_vars["pr_count"].set(str(summary["pr_count"]))
        self.summary_vars["pr_value"].set(f"{format_money(summary['pr_net'])} EUR osnov")
        self.summary_vars["tax_only"].set(str(summary["tax_only_kir_count"]))
        self.notebook.tab(0, text=f"  Izdani računi (IR)  {summary['ir_count']}  ")
        self.notebook.tab(1, text=f"  Prejeti računi (PR)  {summary['pr_count']}  ")
        self.notebook.tab(3, text=f"  Minimax API  {summary['ir_count'] + summary['pr_count']}  ")
        self.nav_tree.item("nav:ir", text=f"  Izdani računi ({summary['ir_count']})")
        self.nav_tree.item("nav:pr", text=f"  Prejeti računi ({summary['pr_count']})")
        self.nav_tree.item("nav:api", text=f"  API povezava in oddaja ({summary['ir_count'] + summary['pr_count']})")
        self._populate_ddvo()

    def _ddvo_minimax_dataset(self, base: core.KirkprDataset) -> core.KirkprDataset | None:
        """Podnabor JSON vrstic, katerih listine obstajajo v Minimax API katalogu."""
        if not self.minimax_invoice_status_checked:
            return None
        kir_rows = []
        for row in base.kir:
            metrics = core.ir_metrics(row, base.kpr)
            if metrics["tax_only"] or self._row_exists_in_minimax("IR", row):
                kir_rows.append(row)
        kpr_rows = [row for row in base.kpr if self._row_exists_in_minimax("PR", row)]
        return core.KirkprDataset(
            header=dict(base.header),
            kir=kir_rows,
            kpr=kpr_rows,
            source_path=base.source_path,
            source_format=base.source_format,
            source_members=list(base.source_members),
            warnings=list(base.warnings),
        )

    def show_ddvo_json_view(self) -> None:
        self.ddvo_view_mode = "json"
        if hasattr(self, "ddvo_json_view_button"):
            self.ddvo_json_view_button.set_kind("blue")
            self.ddvo_compare_view_button.set_kind("grey")
        self._populate_ddvo()
        self.status_var.set("DDV-O: JSON pogled (samo KIR/KPR).")

    def show_ddvo_compare_view(self) -> None:
        """Preklop na primerjavo JSON vs Minimax; po potrebi najprej osveži statuse."""
        if not self.dataset:
            messagebox.showinfo("DDV-O", "Najprej odprite KIR/KPR podatke.", parent=self.root)
            return

        def activate() -> None:
            self.ddvo_view_mode = "compare"
            if hasattr(self, "ddvo_json_view_button"):
                self.ddvo_json_view_button.set_kind("grey")
                self.ddvo_compare_view_button.set_kind("yellow")
            self._populate_ddvo()
            self.status_var.set("DDV-O: primerjava JSON (vse) ↔ Minimax (najdene listine).")

        if self.minimax_invoice_status_checked:
            activate()
            return

        def after_connect() -> None:
            self.refresh_minimax_invoice_statuses(show_message=False, after=activate)

        expected = company_registry.company_org_id(self.active_company or {})
        connected = bool(
            self.minimax_client
            and self.minimax_client.organisation_id
            and str(self.minimax_client.organisation_id) == expected
        )
        if connected:
            after_connect()
            return
        existing_label = next(
            (label for label, organisation_id in self.minimax_organisations.items() if str(organisation_id) == expected),
            "",
        )
        if self.minimax_client and existing_label:
            self.api_org_var.set(existing_label)
            self._on_api_org_selected(after_connect=after_connect)
        else:
            self.connect_minimax_api(after_connect=after_connect)

    def _populate_ddvo(self) -> None:
        if not self.dataset:
            return
        if not hasattr(self, "ddvo_tree"):
            return
        dataset = self._ddvo_view_dataset() or self.dataset
        summary = core.ddvo_summary(dataset)
        compare = self.ddvo_view_mode == "compare"
        mm_dataset = self._ddvo_minimax_dataset(dataset) if compare else None
        mm_summary = core.ddvo_summary(mm_dataset) if mm_dataset is not None else None
        mm_by_code = {
            str(field["code"]): field
            for field in (mm_summary or {}).get("fields", [])
        } if mm_summary else {}

        header = dataset.header
        taxpayer = str(header.get("TaxPayerID") or "—")
        self.ddvo_taxpayer_var.set(f"Davčna številka: {taxpayer}")
        mode_label = "JSON + Minimax" if compare else "JSON"
        self.ddvo_period_var.set(
            f"Obdobje: {dataset.period_from} – {dataset.period_to} · pogled {mode_label}"
        )
        yes_no = lambda value: "DA" if value else "NE"
        flags = [
            f"Vračilo: {yes_no(header.get('VRACILO'))}",
            f"Odbitni delež: {yes_no(header.get('ODBDELEZ'))}",
        ]
        if header.get("INSPOS"):
            flags.append("INSPOS: DA")
        if header.get("PREDLODO"):
            flags.append("PREDLODO: DA")
        flags.append(f"Samoobdavčitev: {summary['self_assessment_count']}")
        flags.append(f"DDV brez odbitka: {summary['vat_not_deducted_count']}")
        if compare and mm_dataset is not None:
            flags.append(f"Minimax listine v DDV-O: IR {len(mm_dataset.kir)} + PR {len(mm_dataset.kpr)}")
        elif compare:
            flags.append("Minimax: najprej poveži API / osveži statuse")
        self.ddvo_flags_var.set("  •  ".join(flags))

        self.ddvo_output_var.set(f"{format_money(summary['output_vat'])} EUR")
        self.ddvo_input_var.set(f"{format_money(summary['input_vat'])} EUR")
        if summary["obligation"]:
            result_value = summary["obligation"]
            result_detail = "polje 51 – obveznost"
        elif summary["excess"]:
            result_value = summary["excess"]
            result_detail = "polje 52 – presežek"
        else:
            result_value = Decimal("0")
            result_detail = "polji 51 in 52 sta 0"
        if compare and mm_summary is not None:
            result_detail += (
                f" · Minimax Σ {format_money(mm_summary['output_vat'])}"
                f" / {format_money(mm_summary['input_vat'])}"
            )
        self.ddvo_result_var.set(f"{format_money(result_value)} EUR")
        self.ddvo_result_detail_var.set(result_detail)

        control_text = (
            f"KONTROLA JSON: {format_money(summary['output_vat'])} − {format_money(summary['input_vat'])} "
            f"− {format_money(summary['obligation'])} + {format_money(summary['excess'])} "
            f"= {format_money(summary['control_difference'])} EUR"
        )
        control_status = "  ✓ USKLAJENO" if summary["control_ok"] else "  ✕ RAZLIKA"
        if compare and mm_summary is not None:
            control_text += (
                f"  |  Minimax: {format_money(mm_summary['output_vat'])}"
                f" − {format_money(mm_summary['input_vat'])}"
            )
        self.ddvo_control_var.set(control_text + control_status)
        self.ddvo_control_label.configure(
            bg=self.colors["success"] if summary["control_ok"] else self.colors["danger"],
            fg="#07150e" if summary["control_ok"] else "#ffffff",
        )

        if hasattr(self, "ddvo_json_view_button"):
            if compare:
                self.ddvo_json_view_button.set_kind("grey")
                self.ddvo_compare_view_button.set_kind("yellow")
            else:
                self.ddvo_json_view_button.set_kind("blue")
                self.ddvo_compare_view_button.set_kind("grey")

        if compare:
            self.ddvo_tree.heading("json_amt", text="JSON (KIR/KPR)")
            self.ddvo_tree.heading("minimax_amt", text="Minimax")
            self.ddvo_tree.heading("diff", text="Razlika")
            self.ddvo_tree.heading("status", text="Kontrola")
        else:
            self.ddvo_tree.heading("json_amt", text="Seštevek")
            self.ddvo_tree.heading("minimax_amt", text="DDV-O (celi EUR)")
            self.ddvo_tree.heading("diff", text="")
            self.ddvo_tree.heading("status", text="Kontrola")

        self.ddvo_tree.delete(*self.ddvo_tree.get_children())
        ddvo_tokens = self._search_tokens(self.ddvo_search_var.get())
        last_section = ""
        visible_index = 0
        zero = Decimal("0.00")
        for field in summary["fields"]:
            json_exact = Decimal(str(field["exact"] or 0))
            json_txt = format_money(json_exact)
            mm_field = mm_by_code.get(str(field["code"])) if compare else None
            if not compare:
                mm_txt = format_money(field["value"])
                diff_txt = ""
                diff_val = zero
                status_txt = field["status"]
            elif mm_summary is None:
                mm_txt = "—"
                diff_txt = "—"
                diff_val = zero
                status_txt = "?"
            else:
                mm_exact = Decimal(str((mm_field or {}).get("exact") or 0))
                mm_txt = format_money(mm_exact)
                diff_val = json_exact - mm_exact
                diff_txt = format_money(diff_val)
                status_txt = "Δ" if diff_val != 0 else field["status"]
            if not self._haystack_matches(
                ddvo_tokens,
                (
                    field["section"],
                    field["code"],
                    field["label"],
                    field["source"],
                    field["status"],
                    field.get("book", ""),
                    json_txt,
                    mm_txt,
                    diff_txt,
                    status_txt,
                ),
            ):
                continue
            section_start = field["section"] != last_section
            if field["book"] == "DDV-O":
                tags: tuple[str, ...] = ("result",)
            elif compare and diff_val != 0:
                tags = ("diff_row",)
            elif section_start:
                tags = ("section_start",)
            elif visible_index % 2:
                tags = ("odd",)
            else:
                tags = ()
            self.ddvo_tree.insert(
                "",
                "end",
                iid=f"ddvo:{field['code']}",
                tags=tags,
                values=(
                    field["section"] if section_start else "",
                    field["code"],
                    field["label"],
                    field["source"],
                    json_txt,
                    mm_txt,
                    diff_txt,
                    status_txt,
                ),
            )
            last_section = field["section"]
            visible_index += 1
        state = "KONTROLA OK" if summary["control_ok"] else "PREVERI RAZLIKO"
        suffix = " · JSON+MM" if compare else ""
        self.notebook.tab(2, text=f"  DDV-O  •  {state}{suffix}  ")

    def recalculate_ddvo(self) -> None:
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        self._populate_ddvo()
        view = self._ddvo_view_dataset() or self.dataset
        summary = core.ddvo_summary(view)
        detail = f"51={summary['obligation']:.0f}; 52={summary['excess']:.0f}; kontrola={summary['control_difference']:.0f}"
        self._record_action("ddvo", detail)
        self.status_var.set("DDV-O je ponovno izračunan; kontrolna razlika je 0 EUR." if summary["control_ok"] else "DDV-O ima kontrolno razliko.")

    def copy_ddvo_control(self) -> None:
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        view = self._ddvo_view_dataset() or self.dataset
        summary = core.ddvo_summary(view)
        text = (
            f"DDV-O {view.period_from}–{view.period_to}: "
            f"obračunani DDV {summary['output_vat']:.0f} EUR; "
            f"odbitni DDV {summary['input_vat']:.0f} EUR; "
            f"51 obveznost {summary['obligation']:.0f} EUR; "
            f"52 presežek {summary['excess']:.0f} EUR; "
            f"kontrolna razlika {summary['control_difference']:.0f} EUR."
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._record_action("ddvo_copy", text)
        self.status_var.set("Kontrolni podatek DDV-O je kopiran v odložišče.")

    def save_ddvo_report(self) -> None:
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        view = self._ddvo_view_dataset() or self.dataset
        paths = self._company_paths()
        profile = self._profile_config()
        initial = str(profile.get("last_output_dir") or (paths.workspace if paths else self.dataset.source_path.parent))
        filename = f"DDV-O_kontrolni_pregled_{view.period_from}_{view.period_to}.txt"
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Shrani kontrolni pregled DDV-O",
            initialdir=initial if Path(initial).is_dir() else str(self.dataset.source_path.parent),
            initialfile=filename,
            defaultextension=".txt",
            filetypes=[("Besedilna datoteka", "*.txt"), ("Vse datoteke", "*.*")],
        )
        if not selected:
            return
        target = Path(selected)
        try:
            target.write_text(core.ddvo_control_report(view), encoding="utf-8-sig")
            self.config["last_output_dir"] = str(target.parent)
            profile["last_output_dir"] = str(target.parent)
            self._record_action("ddvo_report", target.name)
        except OSError as exc:
            messagebox.showerror("Shranjevanje ni uspelo", str(exc), parent=self.root)
            return
        self.status_var.set(f"Kontrolni pregled DDV-O je shranjen: {target.name}")

    def _ddvo_taxpayer_kwargs(self) -> dict[str, str]:
        """Podatki zavezanca/kontakta za DDV-O XML/PDF (eDavki)."""
        firm = ""
        address = ""
        contact_name = str(self.config.get("ddvo_contact_name") or "").strip()
        contact_phone = str(self.config.get("ddvo_contact_phone") or "").strip()
        if self.active_company:
            firm = (
                str(self.active_company.get("Dolgo") or "").strip()
                or company_registry.company_name(self.active_company)
            )
            for key in ("NASLOV", "Naslov", "address", "sedez", "naslov", "street"):
                address = str(self.active_company.get(key) or "").strip()
                if address:
                    break
            if not contact_phone:
                for key in ("Telefon", "Telefon odg osebe", "phone"):
                    contact_phone = str(self.active_company.get(key) or "").strip()
                    if contact_phone:
                        break
        return {
            "company_name": firm,
            "address": address,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
        }

    def _ddvo_export_context(self) -> Any | None:
        """Vrne dataset_view ali None, če ni podatkov."""
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return None
        return self._ddvo_view_dataset() or self.dataset

    def _ddvo_initial_dir(self) -> Path:
        paths = self._company_paths()
        profile = self._profile_config()
        for candidate in (
            paths.ddv_root if paths else None,
            Path(str(profile.get("last_output_dir") or "")),
            Path(str(self.config.get("last_output_dir") or "")),
            self.dataset.source_path.parent if self.dataset else None,
        ):
            if candidate and Path(candidate).is_dir():
                return Path(candidate)
        return Path.cwd()

    def _write_ddvo_pdf(self, target: Path) -> Path:
        """Zapiše DDV-O PDF (eDavki XSLT prikaz) na podano pot."""
        import kirkpr_ddvo_pdf as ddvo_pdf

        view = self._ddvo_export_context()
        if view is None:
            raise core.KirkprError("Ni podatkov za DDV-O PDF.")
        return ddvo_pdf.build_ddvo_pdf(view, target, **self._ddvo_taxpayer_kwargs())

    def _ddvo_temp_pdf_path(self) -> Path:
        import kirkpr_ddvo_pdf as ddvo_pdf

        view = self._ddvo_view_dataset() or self.dataset
        assert view is not None
        return Path(tempfile.gettempdir()) / ddvo_pdf.default_ddvo_pdf_name(view)

    def export_ddvo_pdf_xml(self, *, ask_open_folder: bool = True) -> tuple[Path, Path] | None:
        """Tisk v PDF / izvoz: PDF + XML v TROPS\\{Zšt}\\DDV\\ (brez tiskalnika)."""
        view = self._ddvo_export_context()
        if view is None:
            return None
        import kirkpr_ddvo_pdf as ddvo_pdf
        import kirkpr_ddvo_xml as ddvo_xml

        out_dir = self._ddvo_initial_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / ddvo_pdf.default_ddvo_pdf_name(view)
        xml_path = out_dir / ddvo_xml.default_ddvo_xml_name(view)
        try:
            self._write_ddvo_pdf(pdf_path)
            ddvo_xml.write_ddvo_xml(view, xml_path, **self._ddvo_taxpayer_kwargs())
            profile = self._profile_config()
            self.config["last_output_dir"] = str(out_dir)
            profile["last_output_dir"] = str(out_dir)
            self._record_action("ddvo_export", f"{pdf_path.name} + {xml_path.name}")
        except Exception as exc:
            messagebox.showerror("Izvoz DDV-O ni uspel", str(exc), parent=self.root)
            return None
        self.status_var.set(f"DDV-O izvožen: {pdf_path.name} + {xml_path.name}")
        if ask_open_folder and messagebox.askyesno(
            "DDV-O izvoz",
            f"Shranjeno v:\n{out_dir}\n\n"
            f"• {pdf_path.name}\n• {xml_path.name}\n\nOdprem mapo?",
            parent=self.root,
        ):
            try:
                os.startfile(str(out_dir))  # type: ignore[attr-defined]
            except Exception:
                pass
        return pdf_path, xml_path

    def _confirm_ddvo_virman_payment(
        self,
        *,
        company_name: str,
        period: str,
        period_to: str,
        obligation: Decimal,
        tax_number: str,
        payer_iban: str,
        email_to: str,
        out_dir: Path,
    ) -> dict[str, Any] | None:
        """Forma z vsemi podatki; Potrdi → virman + paket za stranko."""
        import kirkpr_ddvo_virman as ddvo_virman
        import kirkpr_edavki_konto62 as edavki62

        # Vedno sveži IBAN/AJPES iz Evidence firm (ne zastarel cache).
        self._reload_active_company_from_registry()

        self.status_var.set("Pripravljam virman iz lokalnih DDV-O podatkov …")
        self.root.update_idletasks()
        clip_text = ""
        try:
            clip_text = self.root.clipboard_get()
        except tk.TclError:
            clip_text = ""
        profile = self._profile_config()
        saved_by_tax = dict(profile.get("edavki_konto62_by_tax") or {})
        tax_key = re.sub(r"\D", "", tax_number or "")
        root_by = dict(self.config.get("edavki_konto62_by_tax") or {})
        saved_credit = (
            saved_by_tax.get(tax_key)
            or root_by.get(tax_key)
            or profile.get("edavki_konto62_credit")
        )
        signed_storage = bool(
            profile.get("edavki_konto62_signed") or self.config.get("edavki_konto62_signed")
        )
        # Brez Chrome/Minimax ob odprtju — samo odložišče/shranjeno; sicer 0.
        lookup = edavki62.resolve_edavki_konto62(
            tax_number=tax_number,
            company_name=company_name,
            clipboard_text=clip_text,
            saved_value=saved_credit,
            use_chrome=False,
            signed_storage=signed_storage,
        )
        initial_credit = lookup.credit if lookup is not None else Decimal("0.00")
        if lookup is None and saved_credit not in (None, ""):
            try:
                initial_credit = core.edavki_konto62_saldo(saved_credit)
                if not signed_storage and initial_credit > 0:
                    initial_credit = -initial_credit
            except core.KirkprError:
                initial_credit = Decimal("0.00")
        source_label = (
            f"Vir: {lookup.source}" + (f" ({lookup.detail})" if lookup and lookup.detail else "")
            if lookup is not None
            else "Vir: 0,00 (ni salda 62) — po želji »Preberi z eDavkov« / Prilepi 62"
        )
        if lookup is not None and lookup.credit != 0:
            self.status_var.set(
                f"eDavki konto 62: {format_money(lookup.credit)} EUR "
                f"(stanje, {lookup.source}) → prišteje virmanu"
            )
        else:
            self.status_var.set("Konto 62 = 0,00 — virman = polje 51.")

        window = tk.Toplevel(self.root)
        window.title("Plačilni nalog DDV + paket za stranko")
        window.transient(self.root)
        window.grab_set()
        window.configure(bg=self.colors["bg"])
        # Višje okno + gumbi vedno pripeti spodaj (ne morejo izginiti pod robom).
        window.geometry("600x820")
        window.minsize(560, 720)
        try:
            window.resizable(True, True)
        except tk.TclError:
            pass

        result: dict[str, Any] | None = None
        try:
            reference = ddvo_virman.furs_ddv_reference(tax_number)
        except core.KirkprError:
            reference = "SI19…-62006"
        due = ddvo_virman.default_ddv_due_date(period_to)

        header = ttk.Frame(window, style="Header.TFrame", padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Plačilni nalog DDV → FURS", style="HeaderTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text=f"{company_name} · {period}",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        # Gumbi najprej na dno — vedno vidni.
        buttons = ttk.Frame(window, style="Panel.TFrame", padding=(18, 12))
        buttons.pack(side="bottom", fill="x")

        body = ttk.Frame(window, style="Panel.TFrame", padding=(18, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(
            body,
            text=(
                "Preveri zneske in podatke. Potrditev shrani DDV PDF + virman.xml v mapo, "
                "prepiše znesek in odpre Outlook osnutek za stranko."
            ),
            style="Muted.TLabel",
            wraplength=500,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        obligation_var = tk.StringVar(value=format_money(obligation))
        konto62_var = tk.StringVar(value=format_money(initial_credit))
        payment_var = tk.StringVar(value="")
        initial_skupaj = lookup.skupaj if lookup is not None and lookup.skupaj is not None else None
        skupaj_var = tk.StringVar(
            value=format_money(initial_skupaj) if initial_skupaj is not None else "—"
        )
        analytics_var = tk.StringVar(
            value=(lookup.analytics if lookup is not None else "")
            or (
                "Skupaj = dolžno / preplačilo iz vseh kontov na eKartici "
                "(− preplačilo, + plačilo). Ni del izračuna virmana 62."
            )
        )
        # Zadnje prebrano Skupaj (za obvestilo ob potrditvi)
        card_skupaj_box: dict[str, Any] = {
            "skupaj": initial_skupaj,
            "analytics": (lookup.analytics if lookup is not None else "") or "",
        }
        import kirkpr_ajpes_iban as ajpes_iban

        company_rec = self.active_company or {}
        # Evidenca firm = glavni vir; ne uporabi zastarelega ddvo_payer_iban pred njo.
        iban_lookup = ajpes_iban.resolve_payer_ibans(
            company_rec,
            tax_number=tax_number or company_registry.company_tax_number(company_rec),
            saved_iban="",
        )
        if not iban_lookup.selected and payer_iban:
            iban_lookup = ajpes_iban.resolve_payer_ibans(
                company_rec,
                tax_number=tax_number,
                saved_iban=str(payer_iban or profile.get("ddvo_payer_iban") or ""),
            )
        iban_choices = list(iban_lookup.ibans)
        iban_selected = iban_lookup.selected or str(payer_iban or "").strip()
        if iban_selected and iban_selected not in iban_choices:
            iban_choices = [iban_selected, *iban_choices]
        iban_var = tk.StringVar(value=iban_selected)
        iban_source_var = tk.StringVar(
            value=(
                f"Vir IBAN: {iban_lookup.source}"
                + (f" · AJPES {iban_lookup.ajpes_id}" if iban_lookup.ajpes_id else "")
                + (f" · {iban_lookup.detail}" if iban_lookup.detail else "")
            )
        )
        email_var = tk.StringVar(value=email_to or "")
        due_var = tk.StringVar(value=due.strftime("%d.%m.%Y"))
        send_email_var = tk.BooleanVar(value=bool(email_to))
        attach_pdf_var = tk.BooleanVar(value=True)
        attach_virman_var = tk.BooleanVar(value=True)
        extra_attachments: list[Path] = []
        formula_var = tk.StringVar(value="")

        def row_ro(grid_row: int, label: str, value: str) -> None:
            ttk.Label(body, text=label, style="Panel.TLabel").grid(
                row=grid_row, column=0, sticky="w", pady=4
            )
            ttk.Label(body, text=value, style="Muted.TLabel").grid(
                row=grid_row, column=1, sticky="w", padx=(12, 0), pady=4
            )

        row_ro(1, "Davčna številka", tax_number or "—")
        row_ro(2, "Prejemnik", f"{ddvo_virman.FURS_CREDITOR_NAME}")
        row_ro(3, "IBAN FURS", ddvo_virman.FURS_CREDITOR_IBAN)
        row_ro(4, "Referenca", reference)
        try:
            paths = self._company_paths()
            virmani_txt = str(paths.virmani_root) if paths else "—"
        except Exception:
            virmani_txt = "—"
        row_ro(5, "PDF (DDV)", str(out_dir))
        row_ro(6, "Virman XML", virmani_txt)

        ttk.Label(body, text="Polje 51 – obveznost", style="Panel.TLabel").grid(
            row=7, column=0, sticky="w", pady=6
        )
        ttk.Entry(body, textvariable=obligation_var, width=22, state="readonly").grid(
            row=7, column=1, sticky="ew", padx=(12, 0), pady=6
        )

        ttk.Label(body, text="eDavki konto 62 (stanje)", style="Panel.TLabel").grid(
            row=8, column=0, sticky="w", pady=6
        )
        konto_entry = ttk.Entry(body, textvariable=konto62_var, width=22)
        konto_entry.grid(row=8, column=1, sticky="ew", padx=(12, 0), pady=6)
        source_var = tk.StringVar(value=source_label)
        source_lbl = ttk.Label(body, textvariable=source_var, style="Muted.TLabel", wraplength=500)
        source_lbl.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 4))
        if lookup is None or lookup.credit <= 0:
            source_lbl.configure(foreground=self.colors.get("muted", "#888888"))

        ttk.Label(body, text="Za plačilo (51 + stanje 62)", style="Panel.TLabel").grid(
            row=10, column=0, sticky="w", pady=6
        )
        ttk.Entry(body, textvariable=payment_var, width=22, state="readonly").grid(
            row=10, column=1, sticky="ew", padx=(12, 0), pady=6
        )
        ttk.Label(body, textvariable=formula_var, style="Muted.TLabel").grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        ttk.Label(body, text="eKartica Skupaj (vsi konti)", style="Panel.TLabel").grid(
            row=12, column=0, sticky="w", pady=6
        )
        ttk.Entry(body, textvariable=skupaj_var, width=22, state="readonly").grid(
            row=12, column=1, sticky="ew", padx=(12, 0), pady=6
        )
        ttk.Label(body, textvariable=analytics_var, style="Muted.TLabel", wraplength=520).grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        ttk.Label(body, text="IBAN plačnika", style="Panel.TLabel").grid(
            row=14, column=0, sticky="w", pady=6
        )
        iban_row = ttk.Frame(body, style="Panel.TFrame")
        iban_row.grid(row=14, column=1, sticky="ew", padx=(12, 0), pady=6)
        iban_row.columnconfigure(0, weight=1)
        iban_combo = ttk.Combobox(
            iban_row,
            textvariable=iban_var,
            values=iban_choices,
            width=28,
            state="readonly" if len(iban_choices) > 1 else "normal",
        )
        iban_combo.grid(row=0, column=0, sticky="ew")
        iban_btn = ttk.Button(iban_row, text="IBAN", width=8)
        iban_btn.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(body, textvariable=iban_source_var, style="Muted.TLabel", wraplength=500).grid(
            row=15, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )

        def _apply_iban_choices(choices: list[str], selected: str, *, source: str) -> None:
            values = [c for c in choices if str(c or "").strip()]
            sel = selected if selected in values else (values[0] if values else selected)
            iban_combo.configure(values=values, state="readonly" if len(values) > 1 else "normal")
            iban_var.set(sel or "")
            iban_source_var.set(source)

        def fetch_iban_from_ajpes() -> None:
            self._reload_active_company_from_registry()
            company_rec = self.active_company or {}
            ajpes_id = ajpes_iban.company_ajpes_id(company_rec)
            if not ajpes_id and not re.sub(r"\D", "", tax_number or ""):
                messagebox.showwarning(
                    "IBAN / AJPES",
                    "V Evidenci firm manjkata AJPES šifra in davčna številka.\n"
                    "Najprej jih vpiši in shrani v Evidenco firm.",
                    parent=window,
                )
                return
            iban_btn.configure(state="disabled")
            iban_source_var.set("Berem IBAN z AJPES (eRTR) …")
            window.update_idletasks()
            holder: dict[str, Any] = {}

            def worker() -> None:
                try:
                    holder["result"] = ajpes_iban.fetch_payer_ibans_from_ajpes(
                        company_rec,
                        tax_number=tax_number,
                    )
                except Exception as exc:
                    holder["error"] = exc

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            def poll() -> None:
                if thread.is_alive():
                    window.after(120, poll)
                    return
                iban_btn.configure(state="normal")
                err = holder.get("error")
                if err is not None:
                    iban_source_var.set("AJPES: ni IBAN")
                    messagebox.showerror("IBAN / AJPES", str(err), parent=window)
                    return
                found = holder.get("result")
                if found is None or not found.ibans:
                    iban_source_var.set("AJPES: ni IBAN")
                    messagebox.showinfo(
                        "IBAN / AJPES",
                        "AJPES ni vrnil transakcijskega računa.",
                        parent=window,
                    )
                    return
                src = f"Vir IBAN: {found.source}"
                if found.ajpes_id:
                    src += f" · AJPES {found.ajpes_id}"
                if found.detail:
                    src += f" · {found.detail}"
                _apply_iban_choices(found.ibans, found.selected, source=src)
                if len(found.ibans) > 1:
                    messagebox.showinfo(
                        "IBAN / AJPES",
                        f"Najdenih {len(found.ibans)} IBAN — izberi v spustnem seznamu.",
                        parent=window,
                    )

            window.after(120, poll)

        iban_btn.configure(command=fetch_iban_from_ajpes)

        ttk.Label(body, text="Datum izvršitve", style="Panel.TLabel").grid(
            row=16, column=0, sticky="w", pady=6
        )
        ttk.Entry(body, textvariable=due_var, width=22).grid(
            row=16, column=1, sticky="ew", padx=(12, 0), pady=6
        )

        ttk.Label(body, text="E-pošta stranke", style="Panel.TLabel").grid(
            row=17, column=0, sticky="w", pady=6
        )
        ttk.Entry(body, textvariable=email_var, width=28).grid(
            row=17, column=1, sticky="ew", padx=(12, 0), pady=6
        )

        attach_box = ttk.LabelFrame(body, text="Priponke (chk)", padding=(10, 8))
        attach_box.grid(row=18, column=0, columnspan=2, sticky="ew", pady=(10, 4))
        attach_box.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            attach_box,
            text="DDV-O PDF",
            variable=attach_pdf_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            attach_box,
            text="Virman XML (SEPA pain.001)",
            variable=attach_virman_var,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Checkbutton(
            attach_box,
            text="Po potrditvi odpri Outlook z označenimi priponkami",
            variable=send_email_var,
        ).grid(row=2, column=0, sticky="w", pady=(6, 4))
        extra_var = tk.StringVar(value="Dodatne priponke: (ni)")
        ttk.Label(attach_box, textvariable=extra_var, style="Muted.TLabel", wraplength=480).grid(
            row=3, column=0, sticky="w", pady=(2, 4)
        )
        extra_btns = ttk.Frame(attach_box, style="Panel.TFrame")
        extra_btns.grid(row=4, column=0, sticky="w")

        def _refresh_extra_label() -> None:
            if not extra_attachments:
                extra_var.set("Dodatne priponke: (ni)")
                return
            names = ", ".join(path.name for path in extra_attachments[:6])
            more = f" (+{len(extra_attachments) - 6})" if len(extra_attachments) > 6 else ""
            extra_var.set(f"Dodatne priponke ({len(extra_attachments)}): {names}{more}")

        def add_extra_attachment() -> None:
            selected = filedialog.askopenfilenames(
                parent=window,
                title="Dodaj priponke k e-pošti DDV + virman",
                filetypes=[
                    ("Dokumenti", "*.pdf;*.xml;*.zip;*.xlsx;*.docx"),
                    ("PDF", "*.pdf"),
                    ("XML", "*.xml"),
                    ("Vse datoteke", "*.*"),
                ],
            )
            for item in selected:
                path = Path(item)
                if path.is_file() and path not in extra_attachments:
                    extra_attachments.append(path)
            _refresh_extra_label()

        def clear_extra_attachments() -> None:
            extra_attachments.clear()
            _refresh_extra_label()

        ttk.Button(extra_btns, text="Dodaj priponko…", command=add_extra_attachment).pack(
            side="left"
        )
        ttk.Button(extra_btns, text="Počisti dodatne", command=clear_extra_attachments).pack(
            side="left", padx=(8, 0)
        )

        def recompute(*_args: Any) -> None:
            try:
                raw62 = str(konto62_var.get() or "").strip() or "0"
                calc = core.ddvo_virman_payment(obligation, raw62)
                saldo = calc["konto62_credit"]
                payment_var.set(format_money(calc["payment"]))
                formula_var.set(
                    format_virman_formula(calc["obligation"], saldo, calc["payment"])
                )
            except core.KirkprError:
                konto62_var.set("0,00")
                payment_var.set(format_money(obligation))
                formula_var.set(format_virman_formula(obligation, 0, obligation))

        konto62_var.trace_add("write", recompute)
        recompute()

        def apply_lookup(found: edavki62.Konto62Lookup | None, *, warn: bool = False) -> None:
            if found is None:
                konto62_var.set("0,00")
                skupaj_var.set("—")
                analytics_var.set("Skupaj / analitika ni na voljo — klikni »Preberi z eDavkov«.")
                card_skupaj_box["skupaj"] = None
                card_skupaj_box["analytics"] = ""
                source_var.set("Vir: 0,00 (ni stanja na kontu 62)")
                source_lbl.configure(foreground=self.colors.get("muted", "#888888"))
                if warn:
                    messagebox.showinfo(
                        "Konto 62",
                        "Konto 62 ni prebran — vpisujem 0,00.\n\n"
                        "Po želji odpri eKartico, prilepi saldo ali klikni »Preberi z eDavkov«.",
                        parent=window,
                    )
                return
            konto62_var.set(format_money(found.credit))
            if found.skupaj is not None:
                skupaj_var.set(format_money(found.skupaj))
                card_skupaj_box["skupaj"] = found.skupaj
            else:
                skupaj_var.set("—")
                card_skupaj_box["skupaj"] = None
            if found.analytics:
                analytics_var.set(found.analytics)
                card_skupaj_box["analytics"] = found.analytics
            elif found.skupaj is not None:
                sk = found.skupaj
                tag = "preplačilo" if sk < 0 else ("dolžno plačilo" if sk > 0 else "poravnano")
                analytics_var.set(f"Skupaj {format_money(sk)} EUR — {tag} na kartici zavezanca.")
                card_skupaj_box["analytics"] = analytics_var.get()
            source_var.set(
                f"Vir: {found.source} · stanje {format_money(found.credit)}"
                + (f" · {found.detail}" if found.detail else "")
            )
            color = (
                self.colors.get("success", "#1e7a46")
                if found.credit < 0
                else self.colors.get("danger", "#b00020")
                if found.credit > 0
                else self.colors.get("muted", "#888888")
            )
            source_lbl.configure(foreground=color)

        def paste_from_clipboard() -> None:
            try:
                clip = self.root.clipboard_get()
            except tk.TclError:
                apply_lookup(None)
                return
            found = edavki62.lookup_from_clipboard(clip, tax_number=tax_number)
            if found is None:
                try:
                    found = edavki62.Konto62Lookup(
                        credit=core.edavki_konto62_saldo(clip),
                        source="odložišče",
                    )
                except core.KirkprError:
                    apply_lookup(None)
                    return
            apply_lookup(found)

        def fetch_from_edavki() -> None:
            self.status_var.set("Berem eDavki eKartico (konto 62) …")
            window.update_idletasks()
            clip = ""
            try:
                clip = self.root.clipboard_get()
            except tk.TclError:
                clip = ""
            edavki62.open_ekartica_tab(tax_number=tax_number, company_name=company_name)
            found = edavki62.resolve_edavki_konto62(
                tax_number=tax_number,
                company_name=company_name,
                clipboard_text=clip,
                saved_value=None,
                use_chrome=True,
                chrome_timeout_sec=28.0,
            )
            if found is None:
                apply_lookup(None, warn=False)
                self.status_var.set("Konto 62 = 0,00 (eKartica ni vrnila zneska).")
                return
            apply_lookup(found, warn=False)
            self.status_var.set(
                f"eDavki konto 62: {format_money(found.credit)} EUR ({found.source})"
            )

        def parse_due(text: str) -> date:
            raw = str(text or "").strip()
            for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except ValueError:
                    continue
            raise core.KirkprError(f"Neveljaven datum izvršitve: {text!r}")

        def finish(confirm: bool) -> None:
            nonlocal result
            if not confirm:
                window.destroy()
                return
            try:
                raw62 = str(konto62_var.get() or "").strip() or "0"
                calc = core.ddvo_virman_payment(obligation, raw62)
                # Če je konto 62 nič — prepiši 0, ne sprašuj.
                if calc["payment"] <= 0:
                    messagebox.showinfo(
                        "Ni plačila",
                        "Po odbitku konta 62 ni zneska za virman (0 EUR).",
                        parent=window,
                    )
                    return
                iban = ddvo_virman.normalize_iban(iban_var.get())
                if not iban.startswith("SI"):
                    raise core.KirkprError("Vnesi veljaven IBAN plačnika (SI…).")
                exec_dt = parse_due(due_var.get())
            except core.KirkprError as exc:
                messagebox.showerror("Preveri podatke", str(exc), parent=window)
                return
            # Obvestilo: na kartici zavezanca so stanja (Skupaj ≠ 0)
            sk_val = card_skupaj_box.get("skupaj")
            try:
                sk_dec = core.decimal_value(sk_val) if sk_val not in (None, "") else Decimal("0")
            except core.KirkprError:
                sk_dec = Decimal("0")
            if sk_dec != 0:
                tag = "preplačilo" if sk_dec < 0 else "dolžno plačilo"
                analytics = str(card_skupaj_box.get("analytics") or "").strip()
                notice = (
                    f"Na kartici zavezanca je stanje Skupaj = {format_money(sk_dec)} EUR ({tag}).\n\n"
                    f"To NI del izračuna virmana DDV (virman = 51 + konto 62).\n"
                    f"Konto 62 v virmanu: {format_money(calc['konto62_credit'])} EUR → "
                    f"plačilo {format_money(calc['payment'])} EUR."
                )
                if analytics:
                    notice += f"\n\nAnalitika kontov:\n{analytics}"
                if not messagebox.askokcancel(
                    "eKartica — stanja na kartici",
                    notice + "\n\nNadaljujem s potrditvijo virmana?",
                    parent=window,
                ):
                    return
            profile["edavki_konto62_credit"] = str(calc["konto62_credit"])
            profile["edavki_konto62_signed"] = True
            by_tax = dict(profile.get("edavki_konto62_by_tax") or {})
            if tax_key:
                by_tax[tax_key] = str(calc["konto62_credit"])
                profile["edavki_konto62_by_tax"] = by_tax
            root_by = dict(self.config.get("edavki_konto62_by_tax") or {})
            if tax_key:
                root_by[tax_key] = str(calc["konto62_credit"])
                self.config["edavki_konto62_by_tax"] = root_by
            self.config["edavki_konto62_signed"] = True
            profile["ddvo_payer_iban"] = iban
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(format_money(calc["payment"]))
                self.root.update_idletasks()
            except tk.TclError:
                pass
            result = {
                **calc,
                "payer_iban": iban,
                "email_to": str(email_var.get() or "").strip(),
                "execution_date": exec_dt,
                "send_email": bool(send_email_var.get()),
                "attach_pdf": bool(attach_pdf_var.get()),
                "attach_virman": bool(attach_virman_var.get()),
                "extra_attachments": list(extra_attachments),
                "reference": reference,
            }
            window.destroy()

        ttk.Button(buttons, text="Preberi z eDavkov", style="Purple.TButton", command=fetch_from_edavki).pack(side="left")
        ttk.Button(buttons, text="Prilepi 62", command=paste_from_clipboard).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="Prekliči", style="Danger.TButton", command=lambda: finish(False)).pack(side="right")
        ttk.Button(
            buttons,
            text="Potrdi → virman + paket",
            style="Success.TButton",
            command=lambda: finish(True),
        ).pack(side="right", padx=(0, 8))

        window.bind("<Escape>", lambda _e: finish(False))
        window.update_idletasks()
        need_h = max(720, header.winfo_reqheight() + body.winfo_reqheight() + buttons.winfo_reqheight() + 48)
        need_w = max(600, window.winfo_reqwidth())
        # Ne preseži zaslona — pusti rob za opravilno vrstico.
        try:
            screen_h = max(600, int(window.winfo_screenheight()) - 80)
            screen_w = max(560, int(window.winfo_screenwidth()) - 40)
            need_h = min(need_h, screen_h)
            need_w = min(need_w, screen_w)
        except tk.TclError:
            pass
        window.geometry(f"{need_w}x{need_h}")
        try:
            window.lift()
            window.focus_force()
        except tk.TclError:
            pass
        konto_entry.focus_set()
        konto_entry.selection_range(0, "end")
        window.wait_window()
        return result

    def _edit_ddvo_client_email(
        self,
        *,
        to_addr: str,
        subject: str,
        body: str,
        attachments: list[Path],
        payment_line1: str,
        payment_line2: str,
        placeholder_values: Mapping[str, str] | None = None,
        template_id: str = "",
    ) -> dict[str, str] | None:
        """HTML urejevalnik e-pošte (kot Fakturiranje): barve, krepko, font, shranjevanje."""
        import kirkpr_ddvo_email_editor as email_editor
        import kirkpr_ddvo_email_templates as email_tpl

        _ = (payment_line1, payment_line2)
        body_html = email_tpl.ensure_qr_placeholder(email_tpl.normalize_email_html(body))

        def _save_geometry(geo: str) -> None:
            geo = str(geo or "").strip()
            if not geo:
                return
            self.config["ddvo_email_editor_geometry"] = geo
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass

        def _remember_template(tid: str) -> None:
            tid = str(tid or "").strip()
            if not tid:
                return
            profile = self._profile_config()
            profile["ddvo_email_template_id"] = tid
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass

        def _remember_email_settings(data: Mapping[str, Any]) -> None:
            """Urejevalnik shrani → config (belo telo je že v ddvo_email_templates.json)."""
            profile = self._profile_config()
            tid = str(data.get("template_id") or "").strip()
            if tid:
                profile["ddvo_email_template_id"] = tid
            from_smtp = str(data.get("from_smtp") or "").strip()
            if from_smtp:
                self.config["ddvo_email_from"] = from_smtp
                profile["ddvo_email_from"] = from_smtp
            if "line_height" in data:
                self.config["ddvo_email_line_height"] = str(data.get("line_height") or "1.35")
            if "para_spacing_px" in data:
                self.config["ddvo_email_para_spacing_px"] = int(data.get("para_spacing_px") or 4)
            if "read_receipt" in data:
                self.config["ddvo_email_read_receipt"] = bool(data.get("read_receipt"))
            if "delivery_receipt" in data:
                self.config["ddvo_email_delivery_receipt"] = bool(data.get("delivery_receipt"))
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass

        return email_editor.open_ddvo_email_editor(
            self.root,
            to_addr=to_addr,
            subject=subject,
            body_html=body_html,
            attachments=attachments,
            placeholder_values=dict(placeholder_values or {}),
            template_id=template_id or "",
            geometry=str(self.config.get("ddvo_email_editor_geometry") or ""),
            on_geometry=_save_geometry,
            on_template_id=_remember_template,
            on_settings=_remember_email_settings,
            from_smtp=str(
                self.config.get("ddvo_email_from")
                or self._profile_config().get("ddvo_email_from")
                or "info@quickmb.com"
            ),
            deferred_send=str(self.config.get("ddvo_email_deferred_send") or ""),
            read_receipt=bool(self.config.get("ddvo_email_read_receipt", True)),
            delivery_receipt=bool(self.config.get("ddvo_email_delivery_receipt", True)),
            send_channel=str(self.config.get("ddvo_email_channel") or "smtp"),
            cc_addr=str(self.config.get("ddvo_email_cc") or "info@quickmb.com"),
            bcc_addr=str(self.config.get("ddvo_email_bcc") or ""),
            colors={
                "bg": self.colors.get("bg", "#0b1220"),
                "panel": self.colors.get("panel", "#121a2a"),
                "text": self.colors.get("text", "#e8eef8"),
                "muted": self.colors.get("muted", "#9aa7bd"),
                "entry": self.colors.get("panel", "#0f1724"),
            },
        )

    def _compose_outlook_from_edited(
        self,
        edited: Mapping[str, str],
        *,
        attachments: list[Path],
    ) -> tuple[bool, str]:
        """Pošlje prek SMTP ali Outlook (Od:/odloženo/potrdila)."""
        import kirkpr_ddvo_virman as ddvo_virman

        is_test = str(edited.get("test") or "").strip() in {"1", "Da", "da", "true", "True"}
        channel = str(edited.get("channel") or "smtp").strip().casefold()
        if channel not in ("smtp", "outlook"):
            channel = "smtp"
        from_smtp = str(edited.get("from_smtp") or ddvo_virman.DEFAULT_OUTLOOK_FROM).strip()
        read_receipt = str(edited.get("read_receipt") or "1") != "0"
        line_height = str(edited.get("line_height") or "1.35").strip() or "1.35"
        try:
            para_spacing_px = int(str(edited.get("para_spacing_px") or "4").strip() or "4")
        except ValueError:
            para_spacing_px = 4
        deferred: datetime | None = None
        defer_raw = str(edited.get("deferred_send") or "").strip()
        if (not is_test) and channel == "outlook" and defer_raw:
            try:
                deferred = ddvo_virman.parse_deferred_send_si(defer_raw)
            except ValueError as exc:
                return False, str(exc)
        # TEST ne prepiše shranjenih KP/Od/kanala (gre samo na info@).
        if not is_test:
            self.config["ddvo_email_from"] = from_smtp
            self.config["ddvo_email_channel"] = channel
            self.config["ddvo_email_read_receipt"] = read_receipt
            self.config["ddvo_email_delivery_receipt"] = True
            self.config["ddvo_email_line_height"] = line_height
            self.config["ddvo_email_para_spacing_px"] = para_spacing_px
            cc_addr = str(edited.get("cc") or "").strip()
            bcc_addr = str(edited.get("bcc") or "").strip()
            if cc_addr:
                self.config["ddvo_email_cc"] = cc_addr
            else:
                self.config.pop("ddvo_email_cc", None)
            if bcc_addr:
                self.config["ddvo_email_bcc"] = bcc_addr
            else:
                self.config.pop("ddvo_email_bcc", None)
            if channel == "outlook" and defer_raw:
                self.config["ddvo_email_deferred_send"] = defer_raw
            else:
                self.config.pop("ddvo_email_deferred_send", None)
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass

        cc_addr = str(edited.get("cc") or "").strip()
        bcc_addr = str(edited.get("bcc") or "").strip()

        qr_png = str(edited.get("_qr_png") or "").strip() or None
        if qr_png and not Path(qr_png).is_file():
            qr_png = None

        if channel == "smtp":
            import kirkpr_ddvo_smtp as ddvo_smtp

            holder: dict[str, Any] = {}

            def _smtp_work() -> None:
                try:
                    mode = ddvo_smtp.send_smtp(
                        to_addr=str(edited.get("to") or ""),
                        subject=str(edited.get("subject") or ""),
                        body=str(edited.get("body") or ""),
                        attachments=attachments,
                        html=True,
                        reply_to=from_smtp,
                        cc=cc_addr,
                        bcc=bcc_addr,
                        upn_qr_png=qr_png,
                        line_height=line_height,
                        para_spacing_px=para_spacing_px,
                    )
                    holder["ok"] = True
                    holder["mode"] = mode
                except Exception as exc:
                    holder["ok"] = False
                    holder["err"] = str(exc)

            wait = tk.Toplevel(self.root)
            wait.title("SMTP TEST" if is_test else "SMTP")
            wait.transient(self.root)
            wait.grab_set()
            wait.resizable(False, False)
            tk.Label(
                wait,
                text=(
                    "TEST: pošiljam na info@quickmb.com …\nNe zapiraj programa."
                    if is_test
                    else "Pošiljam prek Gmail SMTP …\nNe zapiraj programa."
                ),
                padx=24,
                pady=18,
                justify="center",
            ).pack()
            wait.update_idletasks()
            try:
                x = self.root.winfo_rootx() + 80
                y = self.root.winfo_rooty() + 80
                wait.geometry(f"+{x}+{y}")
            except tk.TclError:
                pass

            worker = threading.Thread(target=_smtp_work, name="DdvoSmtpSend", daemon=True)
            worker.start()
            while worker.is_alive():
                try:
                    self.root.update()
                except tk.TclError:
                    break
                worker.join(0.05)
            try:
                wait.grab_release()
                wait.destroy()
            except tk.TclError:
                pass

            if not holder.get("ok"):
                return False, f"SMTP napaka: {holder.get('err') or 'neznana'}"
            qr_note = " + UPN QR v telesu" if qr_png else ""
            prefix = "✓ TEST POSLAN prek SMTP" if is_test else "✓ POSLANO prek SMTP"
            return True, (
                f"{prefix} ({holder.get('mode')}){qr_note}\n"
                f"Za: {edited.get('to') or '—'}\n"
                f"KP/CC: {cc_addr or '(brez)'}\n"
                f"SKP/BCC: {bcc_addr or '(brez)'}\n"
                f"Od: {ddvo_smtp.SENDER_EMAIL}"
                + (
                    f" (Reply-To: {from_smtp})"
                    if from_smtp and from_smtp.casefold() != ddvo_smtp.SENDER_EMAIL.casefold()
                    else ""
                )
            )

        ok, mail_msg = ddvo_virman.compose_outlook_with_attachments(
            to_addr=str(edited.get("to") or ""),
            subject=str(edited.get("subject") or ""),
            body=str(edited.get("body") or ""),
            attachments=attachments,
            html=True,
            from_smtp=from_smtp,
            deferred_send=deferred,
            read_receipt=read_receipt,
            delivery_receipt=True,
            line_height=line_height,
            para_spacing_px=para_spacing_px,
            upn_qr_png=qr_png,
            send_now=True,
            cc=cc_addr,
            bcc=bcc_addr,
        )
        if ok:
            if is_test:
                head = "✓ TEST POSLAN prek Outlook"
            elif deferred is not None:
                head = "⏱ ODLOŽENO (še NI poslano)"
            else:
                head = "✓ POSLANO prek Outlook"
            mail_msg = (
                f"{head}\n"
                f"Za: {edited.get('to') or '—'}\n"
                f"KP/CC: {cc_addr or '(brez)'}\n"
                f"SKP/BCC: {bcc_addr or '(brez)'}\n"
                f"{mail_msg}"
            )
            if deferred is not None:
                mail_msg = (
                    f"{mail_msg}\n\n"
                    f"⏱ Odloženo do {deferred.strftime('%d.%m.%Y %H:%M')} — "
                    "do takrat je sporočilo v Outlook Outbox (NI še poslano)."
                )
            elif not is_test:
                mail_msg = (
                    f"{mail_msg}\n\n"
                    "✓ Zahtevano potrdilo o prejemu (dostavljeno).\n"
                    "Outlook te bo obvestil, ko strežnik potrdi dostavo."
                )
        return ok, mail_msg

    def _notify_ddvo_email_sent(
        self,
        *,
        ok: bool,
        mail_msg: str,
        company: str = "",
        period: str = "",
        payment: str = "",
        from_smtp: str = "",
        channel: str = "",
        to_addr: str = "",
        cc: str = "",
        bcc: str = "",
        test: bool = False,
    ) -> None:
        """Vedno jasno okno: poslano / napaka (Za, KP, SKP)."""
        from datetime import datetime as _dt

        chan = str(channel or "").strip().casefold() or "smtp"
        when = _dt.now().strftime("%d.%m.%Y %H:%M:%S")
        title_err = "✗ TEST NI poslan" if test else "✗ E-pošta NI poslana"
        if not ok:
            messagebox.showerror(
                title_err,
                f"{mail_msg}\n\nČas: {when}\nKanal: {chan}",
                parent=self.root,
            )
            self.status_var.set(
                f"TEST NI poslan ({chan})" if test else f"E-pošta NI poslana ({chan})"
            )
            return
        extra = (
            f"\n\n--- POTRDITEV ---\n"
            f"Čas: {when}\n"
            f"Kanal: {chan.upper()}"
            + (" (TEST → info@quickmb.com)" if test else "")
            + f"\nZa: {to_addr or '—'}\n"
            f"KP/CC: {cc or '(brez)'}\n"
            f"SKP/BCC: {bcc or '(brez)'}\n"
            f"Od: {from_smtp or '—'}"
        )
        if company or period or payment:
            extra += (
                f"\nPodjetje: {company or '—'}\n"
                f"Obdobje: {period or '—'}\n"
                f"Za plačilo: {payment or '—'} EUR"
            )
        messagebox.showinfo(
            "✓ TEST POSLAN" if test else "✓ E-pošta POSLANA",
            f"{mail_msg}{extra}",
            parent=self.root,
        )
        if test:
            self.status_var.set(f"✓ TEST poslan ({chan}) → {to_addr or '?'}")
        else:
            self.status_var.set(f"✓ E-pošta poslana ({chan}) → {to_addr or '?'}")

    def _ask_ddvo_vracilo(self, excess: Decimal) -> bool:
        """Kot Oddaje: ali zahtevamo vračilo presežka (polje 04)."""
        return bool(
            messagebox.askyesno(
                "Presežek DDV — vračilo",
                f"Presežek (polje 52): {format_money(excess)} EUR.\n\n"
                "Zahtevam vračilo presežka (polje 04 na DDV-O)?\n\n"
                "Da = vračilo · Ne = DDV ostane.",
                parent=self.root,
            )
        )

    def _apply_ddvo_vracilo_and_rewrite(
        self,
        view: Any,
        *,
        pdf_path: Path,
        xml_path: Path,
        vracilo: bool,
    ) -> None:
        """Nastavi VRACILO / f04 in ponovno zapiše PDF+XML (kot Oddaje 1.0.65)."""
        import kirkpr_ddvo_xml as ddvo_xml

        header = getattr(view, "header", None)
        if isinstance(header, dict):
            header["VRACILO"] = bool(vracilo)
        self._write_ddvo_pdf(pdf_path)
        ddvo_xml.write_ddvo_xml(view, xml_path, **self._ddvo_taxpayer_kwargs())

    def _open_ddvo_excess_email(
        self,
        *,
        view: Any,
        company: str,
        company_rec: Mapping[str, Any],
        excess: Decimal,
        vracilo: bool,
        pdf_path: Path,
        period_short: str,
    ) -> str:
        """E-pošta ob presežku: PDF, brez virmana/QR — kot DDV-O Oddaje."""
        import kirkpr_ddvo_email_templates as email_tpl
        import kirkpr_ddvo_virman as ddvo_virman

        profile = self._profile_config()
        values = email_tpl.build_placeholder_values(
            company_name=company,
            period_label=period_short,
            obligation="0,00",
            preplacilo="0,00",
            placilo="",
            reference="",
            iban="",
            datum="",
            postscript=str(
                self.config.get("ddvo_email_ps") or profile.get("ddvo_email_ps") or ""
            ).strip(),
            odgovorna_oseba=company_registry.company_responsible_person(self.active_company),
            payment_amount=Decimal("0"),
            payer_name=company,
            excess=excess,
            vracilo=bool(vracilo),
        )
        tpl_id = email_tpl.resolve_template_id(
            str(profile.get("ddvo_email_template_id") or ""),
            email_tpl.get_active_template_id(),
        )
        tpl = email_tpl.get_template(tpl_id)
        attachments = [pdf_path] if pdf_path.is_file() else []
        edited = self._edit_ddvo_client_email(
            to_addr=ddvo_virman.company_email(company_rec),
            subject=str(tpl.get("subject") or ""),
            body=str(tpl.get("body") or ""),
            attachments=attachments,
            payment_line1="",
            payment_line2="",
            placeholder_values=values,
            template_id=str(tpl.get("id") or ""),
        )
        if edited is None:
            return "E-pošta: preklicana."
        # Če uporabnik v urejevalniku spremeni vračilo — uskladi PDF f04.
        edited_vr = str(edited.get("vracilo") or "").strip() in {"1", "Da", "da", "true"}
        if edited_vr != bool(vracilo) and pdf_path.is_file():
            xml_guess = pdf_path.with_suffix(".xml")
            # PDF ime ≠ XML ime — poišči soimenjak DDV_O
            try:
                import kirkpr_ddvo_xml as ddvo_xml

                xml_path = pdf_path.parent / ddvo_xml.default_ddvo_xml_name(view)
            except Exception:
                xml_path = xml_guess if xml_guess.is_file() else pdf_path.parent / (pdf_path.stem + ".xml")
            try:
                self._apply_ddvo_vracilo_and_rewrite(
                    view, pdf_path=pdf_path, xml_path=xml_path, vracilo=edited_vr
                )
            except Exception:
                pass
        if edited.get("template_id"):
            profile["ddvo_email_template_id"] = edited["template_id"]
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
        ok, mail_msg = self._compose_outlook_from_edited(
            edited,
            attachments=self._filter_ddvo_email_attachments(attachments, edited),
        )
        self._notify_ddvo_email_sent(
            ok=ok,
            mail_msg=mail_msg,
            company=company,
            period=period_short,
            payment=f"presežek {format_money(excess)}",
            from_smtp=str(edited.get("from_smtp") or ""),
            channel=str(edited.get("channel") or ""),
            to_addr=str(edited.get("to") or ""),
            cc=str(edited.get("cc") or ""),
            bcc=str(edited.get("bcc") or ""),
            test=str(edited.get("test") or "").strip() in {"1", "Da", "da", "true", "True"},
        )
        return f"E-pošta: {mail_msg}"

    def open_ddvo_email_template_editor(self) -> None:
        """Gumb »E-pošta virman…«: urejevalnik z DEJANSKIMI zneski iz DDV-O + Outlook."""
        import kirkpr_ddvo_email_templates as email_tpl
        import kirkpr_ddvo_virman as ddvo_virman

        view = self._ddvo_export_context()
        if view is None:
            return

        summary = core.ddvo_summary(view)
        obligation = Decimal(str(summary.get("obligation") or 0))
        excess = Decimal(str(summary.get("excess") or 0))
        company_rec = self.active_company or {}
        company = company_registry.company_name(company_rec) or "Stranka"
        tax = company_registry.company_tax_number(company_rec) or str(
            view.header.get("TaxPayerID") or "00000000"
        )
        period_from = str(view.period_from)
        period_to = str(view.period_to)
        period_short = ddvo_virman.period_label_short(period_from, period_to) or "—"

        vracilo = bool(view.header.get("VRACILO")) if hasattr(view, "header") else False
        if excess > 0 and obligation <= 0:
            vracilo = self._ask_ddvo_vracilo(excess)
            if isinstance(getattr(view, "header", None), dict):
                view.header["VRACILO"] = vracilo

        profile = self._profile_config()
        tax_key = re.sub(r"\D+", "", str(tax or ""))
        saved_by_tax = dict(profile.get("edavki_konto62_by_tax") or {})
        root_by = dict(self.config.get("edavki_konto62_by_tax") or {})
        saved_credit = (
            saved_by_tax.get(tax_key)
            or root_by.get(tax_key)
            or profile.get("edavki_konto62_credit")
            or "0"
        )
        signed_storage = bool(
            profile.get("edavki_konto62_signed") or self.config.get("edavki_konto62_signed")
        )
        import kirkpr_edavki_konto62 as edavki62

        clip_text = ""
        try:
            clip_text = self.root.clipboard_get()
        except tk.TclError:
            clip_text = ""
        lookup = edavki62.resolve_edavki_konto62(
            tax_number=tax,
            company_name=company,
            clipboard_text=clip_text,
            saved_value=saved_credit,
            use_chrome=False,
            signed_storage=signed_storage,
        )
        saldo62 = lookup.credit if lookup is not None else core.edavki_konto62_saldo(saved_credit)
        if not signed_storage and saldo62 > 0 and lookup is None:
            # Stari abs kredit v configu → presežek
            saldo62 = -saldo62
        calc = core.ddvo_virman_payment(obligation, saldo62)
        try:
            ref = ddvo_virman.furs_ddv_reference(tax)
        except Exception:
            ref = "SI19 ————-62006"
        due = ddvo_virman.default_ddv_due_date(period_to)

        obl_txt = format_money(calc["obligation"])
        credit_txt = format_money(calc["konto62_credit"])
        pay_txt = format_money(calc["payment"]) if calc["payment"] > 0 else ""
        line1, line2 = ddvo_virman.format_payment_lines(
            calc["obligation"], calc["konto62_credit"], calc["payment"]
        )
        payer_street, payer_city = ddvo_virman.split_slovenian_address(
            str(company_rec.get("NASLOV") or company_rec.get("Naslov") or "")
        )
        values = email_tpl.build_placeholder_values(
            company_name=company,
            period_label=period_short,
            obligation=obl_txt if obligation > 0 or calc["payment"] > 0 else ("0,00" if excess > 0 else obl_txt),
            preplacilo=credit_txt,
            placilo=pay_txt,
            reference=ref if calc["payment"] > 0 else "",
            iban=ddvo_virman.FURS_CREDITOR_IBAN if calc["payment"] > 0 else "",
            datum=due.strftime("%d.%m.%Y") if calc["payment"] > 0 else "",
            postscript=str(
                self.config.get("ddvo_email_ps") or profile.get("ddvo_email_ps") or ""
            ).strip(),
            odgovorna_oseba=company_registry.company_responsible_person(self.active_company),
            payment_amount=calc["payment"],
            payer_name=company,
            payer_street=payer_street,
            payer_city=payer_city,
            excess=excess,
            vracilo=vracilo,
        )
        tpl_id = email_tpl.resolve_template_id(
            str(profile.get("ddvo_email_template_id") or ""),
            email_tpl.get_active_template_id(),
        )
        if str(profile.get("ddvo_email_template_id") or "") != tpl_id:
            profile["ddvo_email_template_id"] = tpl_id
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass
        tpl = email_tpl.get_template(tpl_id)

        # Priponke: zadnji DDV PDF (+ virman samo če je plačilo).
        attachments: list[Path] = []
        out_dir = self._ddvo_initial_dir()
        try:
            pdfs = sorted(out_dir.glob("*DDV*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            if pdfs:
                attachments.append(pdfs[0])
            if calc["payment"] > 0:
                virmani = sorted(
                    list(out_dir.glob("*virman*.xml")) + list(out_dir.glob("*pain*.xml")),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if virmani:
                    attachments.append(virmani[0])
        except OSError:
            pass

        edited = self._edit_ddvo_client_email(
            to_addr=ddvo_virman.company_email(company_rec),
            subject=str(tpl.get("subject") or ""),
            body=str(tpl.get("body") or ""),
            attachments=attachments,
            payment_line1=line1,
            payment_line2=line2,
            placeholder_values=values,
            template_id=str(tpl.get("id") or ""),
        )
        if edited is None:
            self.status_var.set("Predloga e-pošte: preklicano.")
            return
        if edited.get("template_id"):
            profile["ddvo_email_template_id"] = edited["template_id"]
            try:
                core.save_config(self.config, self.config_file)
            except OSError:
                pass

        if not (edited.get("subject") and edited.get("body")):
            self.status_var.set("Predloga e-pošte shranjena.")
            return

        ok, mail_msg = self._compose_outlook_from_edited(
            edited,
            attachments=self._filter_ddvo_email_attachments(attachments, edited),
        )
        self.status_var.set(f"E-pošta virman: {mail_msg}" if ok else mail_msg)
        self._notify_ddvo_email_sent(
            ok=ok,
            mail_msg=mail_msg,
            company=company,
            period=period_short,
            payment=pay_txt,
            from_smtp=str(edited.get("from_smtp") or ""),
            channel=str(edited.get("channel") or ""),
            to_addr=str(edited.get("to") or ""),
            cc=str(edited.get("cc") or ""),
            bcc=str(edited.get("bcc") or ""),
            test=str(edited.get("test") or "").strip() in {"1", "Da", "da", "true", "True"},
        )

    def _filter_ddvo_email_attachments(
        self,
        attachments: Sequence[Path],
        edited: Mapping[str, str],
    ) -> list[Path]:
        """Upošteva chk DDV-O / virman iz HTML urejevalnika e-pošte."""
        want_pdf = str(edited.get("attach_pdf", "1")).strip() != "0"
        want_virman = str(edited.get("attach_virman", "1")).strip() != "0"
        selected: list[Path] = []
        for raw in attachments:
            path = Path(raw)
            if not path.is_file():
                continue
            name = path.name.casefold()
            is_pdf = path.suffix.casefold() == ".pdf"
            is_virman = (not is_pdf) and (
                path.suffix.casefold() == ".xml" or "virman" in name or "pain" in name
            )
            if is_pdf and not want_pdf:
                continue
            if is_virman and not want_virman:
                continue
            selected.append(path)
        return selected

    def _ddvo_package_attachments(
        self,
        confirmed: Mapping[str, Any],
        *,
        pdf_path: Path | None,
        virman_path: Path | None,
    ) -> list[Path]:
        """Sestavi seznam priponk glede na chk v formi plačilnega naloga."""
        attachments: list[Path] = []
        if confirmed.get("attach_pdf", True) and pdf_path and Path(pdf_path).is_file():
            attachments.append(Path(pdf_path))
        if confirmed.get("attach_virman", True) and virman_path and Path(virman_path).is_file():
            attachments.append(Path(virman_path))
        for raw in confirmed.get("extra_attachments") or []:
            path = Path(raw)
            if path.is_file() and path not in attachments:
                attachments.append(path)
        return attachments

    def create_ddvo_pdf_virman(self) -> None:
        """Ustvari DDV-O PDF + SEPA virman; priponke za Outlook po chk."""
        import kirkpr_ddvo_virman as ddvo_virman

        view = self._ddvo_export_context()
        if view is None:
            return
        exported = self.export_ddvo_pdf_xml(ask_open_folder=False)
        if not exported:
            return
        pdf_path, xml_path = exported
        summary = core.ddvo_summary(view)
        obligation = Decimal(str(summary.get("obligation") or 0))
        excess = Decimal(str(summary.get("excess") or 0))
        company_rec = self.active_company or {}
        company = company_registry.company_name(company_rec) or "—"
        period = f"{view.period_from} – {view.period_to}"
        tax = company_registry.company_tax_number(company_rec) or str(
            view.header.get("TaxPayerID") or ""
        )
        out_dir = self._ddvo_initial_dir()
        if obligation <= 0:
            if excess > 0:
                vracilo = self._ask_ddvo_vracilo(excess)
                try:
                    self._apply_ddvo_vracilo_and_rewrite(
                        view, pdf_path=pdf_path, xml_path=xml_path, vracilo=vracilo
                    )
                except Exception as exc:
                    messagebox.showerror("DDV-O f04", str(exc), parent=self.root)
                    return
                period_short = ddvo_virman.period_label_short(
                    str(view.period_from), str(view.period_to)
                )
                do_mail = messagebox.askyesno(
                    "Presežek DDV — e-pošta",
                    f"DDV-O PDF je shranjen (vračilo: {'Da' if vracilo else 'Ne'}).\n"
                    f"Presežek: {format_money(excess)} EUR — virman ni potreben.\n\n"
                    "Odprem e-pošto stranki (PDF v prilogi)?",
                    parent=self.root,
                )
                mail_note = ""
                if do_mail:
                    mail_note = self._open_ddvo_excess_email(
                        view=view,
                        company=company,
                        company_rec=company_rec,
                        excess=excess,
                        vracilo=vracilo,
                        pdf_path=pdf_path,
                        period_short=period_short,
                    )
                messagebox.showinfo(
                    "PDF + virman",
                    (
                        f"DDV-O PDF je shranjen:\n{pdf_path}\n\n"
                        f"XML: {xml_path}\n\n"
                        f"Presežek (52): {format_money(excess)} EUR — virman ni potreben.\n"
                        f"Vračilo (04): {'Da' if vracilo else 'Ne'}"
                        + (f"\n\n{mail_note}" if mail_note else "")
                    ),
                    parent=self.root,
                )
            else:
                messagebox.showinfo(
                    "PDF + virman",
                    (
                        f"DDV-O PDF je shranjen:\n{pdf_path}\n\n"
                        f"XML: {xml_path}\n\n"
                        "Obveznost (51) je 0 — virman ni potreben."
                    ),
                    parent=self.root,
                )
            return
        confirmed = self._confirm_ddvo_virman_payment(
            company_name=company,
            period=period,
            period_to=str(view.period_to),
            obligation=obligation,
            tax_number=tax,
            payer_iban=ddvo_virman.company_iban(company_rec),
            email_to=ddvo_virman.company_email(company_rec),
            out_dir=out_dir,
        )
        if confirmed is None:
            self.status_var.set("PDF + virman: preklicano (PDF ostane shranjen).")
            return
        try:
            paths = self._company_paths()
            package = ddvo_virman.write_virman_package(
                out_dir,
                company=company_rec,
                period_from=str(view.period_from),
                period_to=str(view.period_to),
                obligation=confirmed["obligation"],
                konto62_credit=confirmed["konto62_credit"],
                payment=confirmed["payment"],
                source_pdf=pdf_path,
                payer_iban=str(confirmed["payer_iban"]),
                execution_date=confirmed["execution_date"],
                remittance=f"DDV-O {period}",
                virman_dir=paths.virmani_root if paths else None,
            )
        except Exception as exc:
            messagebox.showerror("Virman ni uspel", str(exc), parent=self.root)
            return

        attachments = self._ddvo_package_attachments(
            confirmed,
            pdf_path=package.pdf_path,
            virman_path=package.virman_path,
        )
        note = (
            f"PDF: {package.pdf_path.name}\n"
            f"Virman: {package.virman_path.name}\n"
            f"Plačilo: {format_money(package.payment)} EUR\n"
            f"Referenca: {package.reference}"
        )
        self._record_action(
            "ddvo_pdf",
            f"{package.pdf_path.name}; virman {package.virman_path.name}; "
            f"plačilo {package.payment:.2f}",
        )
        if confirmed.get("send_email"):
            import kirkpr_ddvo_email_templates as email_tpl

            ps = str(
                self.config.get("ddvo_email_ps")
                or self._profile_config().get("ddvo_email_ps")
                or ""
            ).strip()
            line1, line2 = ddvo_virman.format_payment_lines(
                package.obligation,
                package.konto62_credit,
                package.payment,
            )
            period_short = ddvo_virman.period_label_short(
                str(view.period_from), str(view.period_to)
            )
            payer_street, payer_city = ddvo_virman.split_slovenian_address(
                str(
                    (self.active_company or {}).get("NASLOV")
                    or (self.active_company or {}).get("Naslov")
                    or ""
                )
            )
            values = email_tpl.build_placeholder_values(
                company_name=company,
                period_label=period_short,
                obligation=format_money(package.obligation),
                preplacilo=format_money(package.konto62_credit),
                placilo=format_money(package.payment),
                reference=package.reference,
                iban=package.creditor_iban,
                datum=package.execution_date.strftime("%d.%m.%Y"),
                postscript=ps,
                odgovorna_oseba=company_registry.company_responsible_person(self.active_company),
                payment_amount=package.payment,
                payer_name=company,
                payer_street=payer_street,
                payer_city=payer_city,
            )
            tpl_id = email_tpl.resolve_template_id(
                str(self._profile_config().get("ddvo_email_template_id") or ""),
                email_tpl.get_active_template_id(),
            )
            tpl = email_tpl.get_template(tpl_id)
            edited = self._edit_ddvo_client_email(
                to_addr=str(confirmed.get("email_to") or package.email_to),
                subject=str(tpl.get("subject") or ""),
                body=str(tpl.get("body") or ""),
                attachments=attachments,
                payment_line1=line1,
                payment_line2=line2,
                placeholder_values=values,
                template_id=str(tpl.get("id") or ""),
            )
            if edited is None:
                note += "\n\nE-pošta preklicana."
            else:
                ok, mail_msg = self._compose_outlook_from_edited(
                    edited,
                    attachments=self._filter_ddvo_email_attachments(attachments, edited),
                )
                note += f"\n\nE-pošta: {mail_msg}"
                self._notify_ddvo_email_sent(
                    ok=ok,
                    mail_msg=mail_msg,
                    company=company,
                    period=period,
                    payment=format_money(package.payment),
                    from_smtp=str(edited.get("from_smtp") or ""),
                    channel=str(edited.get("channel") or ""),
                    to_addr=str(edited.get("to") or ""),
                    cc=str(edited.get("cc") or ""),
                    bcc=str(edited.get("bcc") or ""),
                    test=str(edited.get("test") or "").strip() in {"1", "Da", "da", "true", "True"},
                )

        self.status_var.set(
            f"PDF + virman: {package.pdf_path.name} · {format_money(package.payment)} EUR"
        )
        messagebox.showinfo(
            "PDF + virman",
            (
                f"Podjetje: {company}\nObdobje: {period}\n\n{note}\n\n"
                f"Mapa PDF: {package.out_dir}\nMapa Virmani: {package.virman_dir}\n"
                f"Priponke ({len(attachments)}): "
                + (", ".join(path.name for path in attachments) or "(nobena)")
            ),
            parent=self.root,
        )
        if messagebox.askyesno(
            "DDV-O mapa",
            f"Odprem mapo z izvozom?\n\n{package.out_dir}",
            parent=self.root,
        ):
            try:
                os.startfile(str(package.out_dir))  # type: ignore[attr-defined]
            except Exception:
                pass

    def print_ddvo_minimax(self) -> None:
        """Glavni tisk: Minimax uskladitev → DDV PDF → forma → virman + e-pošta."""
        import kirkpr_ddvo_virman as ddvo_virman

        view = self._ddvo_export_context()
        if view is None:
            return

        def after_ready() -> None:
            self.ddvo_view_mode = "compare"
            self._populate_ddvo()
            exported = self.export_ddvo_pdf_xml(ask_open_folder=False)
            if not exported:
                return
            pdf_path, xml_path = exported
            summary = core.ddvo_summary(view)
            obligation = Decimal(str(summary.get("obligation") or 0))
            excess = Decimal(str(summary.get("excess") or 0))
            company_rec = self.active_company or {}
            company = company_registry.company_name(company_rec) or "—"
            period = f"{view.period_from} – {view.period_to}"
            tax = company_registry.company_tax_number(company_rec) or str(
                view.header.get("TaxPayerID") or ""
            )
            out_dir = self._ddvo_initial_dir()
            virman_note = ""
            payment_detail = ""
            package_dir = out_dir
            if obligation > 0:
                confirmed = self._confirm_ddvo_virman_payment(
                    company_name=company,
                    period=period,
                    period_to=str(view.period_to),
                    obligation=obligation,
                    tax_number=tax,
                    payer_iban=ddvo_virman.company_iban(company_rec),
                    email_to=ddvo_virman.company_email(company_rec),
                    out_dir=out_dir,
                )
                if confirmed is None:
                    virman_note = (
                        f"\n\nVirman preklican. Polje 51: {format_money(obligation)} EUR."
                    )
                else:
                    try:
                        paths = self._company_paths()
                        package = ddvo_virman.write_virman_package(
                            out_dir,
                            company=company_rec,
                            period_from=str(view.period_from),
                            period_to=str(view.period_to),
                            obligation=confirmed["obligation"],
                            konto62_credit=confirmed["konto62_credit"],
                            payment=confirmed["payment"],
                            source_pdf=pdf_path,
                            payer_iban=str(confirmed["payer_iban"]),
                            execution_date=confirmed["execution_date"],
                            remittance=f"DDV-O {period}",
                            virman_dir=paths.virmani_root if paths else None,
                        )
                    except Exception as exc:
                        messagebox.showerror(
                            "Virman ni uspel",
                            str(exc),
                            parent=self.root,
                        )
                        return
                    package_dir = package.out_dir
                    payment_detail = (
                        f"; plačilo {package.payment:.2f}; "
                        f"62={package.konto62_credit:.2f}; {package.virman_path.name}"
                    )
                    virman_note = (
                        f"\n\nPaket za stranko:\n"
                        f"• PDF: {package.pdf_path}\n"
                        f"• Virman: {package.virman_path}\n"
                        f"• Polje 51: {format_money(package.obligation)} EUR\n"
                        f"• eDavki 62: {format_money(package.konto62_credit)} EUR\n"
                        f"• Plačilo: {format_money(package.payment)} EUR\n"
                        f"• Referenca: {package.reference}\n"
                        f"• IBAN FURS: {package.creditor_iban}\n"
                        f"Mapa PDF: {package.out_dir}\n"
                        f"Mapa Virmani: {package.virman_dir}"
                    )
                    if confirmed.get("send_email"):
                        import kirkpr_ddvo_email_templates as email_tpl

                        ps = str(
                            self.config.get("ddvo_email_ps")
                            or self._profile_config().get("ddvo_email_ps")
                            or ""
                        ).strip()
                        line1, line2 = ddvo_virman.format_payment_lines(
                            package.obligation,
                            package.konto62_credit,
                            package.payment,
                        )
                        obl_txt = format_money(package.obligation)
                        credit_txt = format_money(package.konto62_credit)
                        pay_txt = format_money(package.payment)
                        period_short = ddvo_virman.period_label_short(
                            str(view.period_from), str(view.period_to)
                        )
                        payer_street, payer_city = ddvo_virman.split_slovenian_address(
                            str(
                                (self.active_company or {}).get("NASLOV")
                                or (self.active_company or {}).get("Naslov")
                                or ""
                            )
                        )
                        values = email_tpl.build_placeholder_values(
                            company_name=company,
                            period_label=period_short,
                            obligation=obl_txt,
                            preplacilo=credit_txt,
                            placilo=pay_txt,
                            reference=package.reference,
                            iban=package.creditor_iban,
                            datum=package.execution_date.strftime("%d.%m.%Y"),
                            postscript=ps,
                            odgovorna_oseba=company_registry.company_responsible_person(
                                self.active_company
                            ),
                            payment_amount=package.payment,
                            payer_name=company,
                            payer_street=payer_street,
                            payer_city=payer_city,
                        )
                        tpl_id = email_tpl.resolve_template_id(
                            str(self._profile_config().get("ddvo_email_template_id") or ""),
                            email_tpl.get_active_template_id(),
                        )
                        tpl = email_tpl.get_template(tpl_id)
                        subject = email_tpl.render_placeholders(str(tpl.get("subject") or ""), values)
                        body_html = email_tpl.render_placeholders(str(tpl.get("body") or ""), values)
                        attachments = self._ddvo_package_attachments(
                            confirmed,
                            pdf_path=package.pdf_path,
                            virman_path=package.virman_path,
                        )
                        # V urejevalnik damo predlogo z placeholderji (ne render), da jih lahko urejaš.
                        edited = self._edit_ddvo_client_email(
                            to_addr=str(confirmed.get("email_to") or package.email_to),
                            subject=str(tpl.get("subject") or subject),
                            body=str(tpl.get("body") or body_html),
                            attachments=attachments,
                            payment_line1=line1,
                            payment_line2=line2,
                            placeholder_values=values,
                            template_id=str(tpl.get("id") or ""),
                        )
                        if edited is None:
                            virman_note += "\n\nE-pošta: preklicana (virman/PDF sta shranjena)."
                        else:
                            if edited.get("template_id"):
                                profile = self._profile_config()
                                profile["ddvo_email_template_id"] = edited["template_id"]
                                try:
                                    core.save_config(self.config, self.config_file)
                                except OSError:
                                    pass
                            ok, mail_msg = self._compose_outlook_from_edited(
                                edited,
                                attachments=attachments,
                            )
                            virman_note += f"\n\nE-pošta: {mail_msg}"
                            self._notify_ddvo_email_sent(
                                ok=ok,
                                mail_msg=mail_msg,
                                company=company,
                                period=period_short,
                                payment=pay_txt,
                                from_smtp=str(edited.get("from_smtp") or ""),
                                channel=str(edited.get("channel") or ""),
                                to_addr=str(edited.get("to") or ""),
                                cc=str(edited.get("cc") or ""),
                                bcc=str(edited.get("bcc") or ""),
                                test=str(edited.get("test") or "").strip()
                                in {"1", "Da", "da", "true", "True"},
                            )
                            if not ok:
                                try:
                                    os.startfile(str(package.out_dir))  # type: ignore[attr-defined]
                                except Exception:
                                    pass
            elif excess > 0:
                vracilo = self._ask_ddvo_vracilo(excess)
                try:
                    self._apply_ddvo_vracilo_and_rewrite(
                        view, pdf_path=pdf_path, xml_path=xml_path, vracilo=vracilo
                    )
                except Exception as exc:
                    messagebox.showerror("DDV-O f04", str(exc), parent=self.root)
                    return
                period_short = ddvo_virman.period_label_short(
                    str(view.period_from), str(view.period_to)
                )
                virman_note = (
                    f"\n\nPresežek DDV (polje 52): {format_money(excess)} EUR — virman ni potreben."
                    f"\nVračilo (04): {'Da' if vracilo else 'Ne'}"
                )
                if messagebox.askyesno(
                    "Presežek DDV — e-pošta",
                    f"Presežek: {format_money(excess)} EUR.\n"
                    f"Vračilo: {'Da' if vracilo else 'Ne'}.\n\n"
                    "Odprem e-pošto stranki (PDF, brez virmana)?",
                    parent=self.root,
                ):
                    virman_note += "\n" + self._open_ddvo_excess_email(
                        view=view,
                        company=company,
                        company_rec=self.active_company or {},
                        excess=excess,
                        vracilo=vracilo,
                        pdf_path=pdf_path,
                        period_short=period_short,
                    )
            else:
                virman_note = "\n\nObveznost in presežek sta 0 — virman ni potreben."

            self._record_action(
                "ddvo_minimax",
                f"{pdf_path.name}; obveznost {obligation:.2f}; presežek {excess:.2f}{payment_detail}",
            )
            self.status_var.set(
                f"Minimax DDV-O: {pdf_path.name} · obveznost {format_money(obligation)} EUR"
            )
            messagebox.showinfo(
                "Minimax — DDV-O tisk",
                (
                    f"Podjetje: {company}\n"
                    f"Obdobje: {period}\n\n"
                    f"Uskladitev JSON ↔ Minimax je prikazana na zavihku.\n"
                    f"Izvoz obrazca:\n• {pdf_path}\n• {xml_path}"
                    f"{virman_note}"
                ),
                parent=self.root,
            )
            if messagebox.askyesno(
                "DDV-O mapa",
                f"Odprem mapo z izvozom?\n\n{package_dir}",
                parent=self.root,
            ):
                try:
                    os.startfile(str(package_dir))  # type: ignore[attr-defined]
                except Exception:
                    pass

        if self.minimax_invoice_status_checked:
            after_ready()
            return

        def after_connect() -> None:
            self.refresh_minimax_invoice_statuses(show_message=False, after=after_ready)

        expected = company_registry.company_org_id(self.active_company or {})
        connected = bool(
            self.minimax_client
            and self.minimax_client.organisation_id
            and str(self.minimax_client.organisation_id) == expected
        )
        if connected:
            after_connect()
            return
        existing_label = next(
            (label for label, organisation_id in self.minimax_organisations.items() if str(organisation_id) == expected),
            "",
        )
        if self.minimax_client and existing_label:
            self.api_org_var.set(existing_label)
            self._on_api_org_selected(after_connect=after_connect)
        else:
            self.connect_minimax_api(after_connect=after_connect)

    def save_ddvo_pdf(self) -> None:
        """Shrani DDV-O PDF drugam (dialog)."""
        view = self._ddvo_export_context()
        if view is None:
            return
        import kirkpr_ddvo_pdf as ddvo_pdf

        profile = self._profile_config()
        initial = self._ddvo_initial_dir()
        filename = ddvo_pdf.default_ddvo_pdf_name(view)
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Shrani DDV-O PDF (oblika eDavki)",
            initialdir=str(initial),
            initialfile=filename,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("Vse datoteke", "*.*")],
        )
        if not selected:
            return
        target = Path(selected)
        try:
            self._write_ddvo_pdf(target)
            self.config["last_output_dir"] = str(target.parent)
            profile["last_output_dir"] = str(target.parent)
            self._record_action("ddvo_pdf", target.name)
        except Exception as exc:
            messagebox.showerror("Shranjevanje PDF ni uspelo", str(exc), parent=self.root)
            return
        self.status_var.set(f"DDV-O PDF shranjen: {target.name}")
        if messagebox.askyesno(
            "DDV-O PDF",
            f"PDF shranjen:\n{target}\n\nOdprem mapo?",
            parent=self.root,
        ):
            try:
                os.startfile(str(target.parent))  # type: ignore[attr-defined]
            except Exception:
                pass

    def save_ddvo_xml(self) -> None:
        """Shrani DDV-O XML drugam (dialog)."""
        view = self._ddvo_export_context()
        if view is None:
            return
        import kirkpr_ddvo_xml as ddvo_xml

        profile = self._profile_config()
        initial = self._ddvo_initial_dir()
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Shrani DDV-O XML (shema DDV_O_11)",
            initialdir=str(initial),
            initialfile=ddvo_xml.default_ddvo_xml_name(view),
            defaultextension=".xml",
            filetypes=[("XML", "*.xml"), ("Vse datoteke", "*.*")],
        )
        if not selected:
            return
        target = Path(selected)
        try:
            ddvo_xml.write_ddvo_xml(view, target, **self._ddvo_taxpayer_kwargs())
            self.config["last_output_dir"] = str(target.parent)
            profile["last_output_dir"] = str(target.parent)
            self._record_action("ddvo_xml", target.name)
        except Exception as exc:
            messagebox.showerror("Shranjevanje XML ni uspelo", str(exc), parent=self.root)
            return
        self.status_var.set(f"DDV-O XML shranjen: {target.name}")
        if messagebox.askyesno(
            "DDV-O XML",
            f"XML shranjen:\n{target}\n\nOdprem mapo?",
            parent=self.root,
        ):
            try:
                os.startfile(str(target.parent))  # type: ignore[attr-defined]
            except Exception:
                pass

    def preview_ddvo_pdf(self) -> None:
        """Predogled DDV-O PDF v privzetem pregledovalniku."""
        if self._ddvo_export_context() is None:
            return
        target = self._ddvo_temp_pdf_path()
        try:
            self._write_ddvo_pdf(target)
            self._record_action("ddvo_preview", target.name)
        except Exception as exc:
            messagebox.showerror("Predogled PDF ni uspel", str(exc), parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror(
                "Predogled",
                f"PDF je shranjen, a ga ni bilo mogoče odpreti:\n{target}\n\n{exc}",
                parent=self.root,
            )
            return
        self.status_var.set(f"Predogled DDV-O: {target.name}")

    def _run_api_worker(
        self,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        busy_text: str,
    ) -> None:
        if self.api_busy:
            messagebox.showinfo(
                "Minimax API",
                "Počakajte — trenutno Minimax opravilo še teče.",
                parent=self.root,
            )
            return
        self._set_api_busy(True)
        self.api_status_var.set(busy_text)
        holder: dict[str, Any] = {}

        def run() -> None:
            try:
                holder["result"] = task()
            except Exception as exc:
                holder["error"] = exc

        worker = threading.Thread(target=run, name="MinimaxApiWorker", daemon=True)
        worker.start()

        def poll() -> None:
            if worker.is_alive():
                self.root.after(100, poll)
                return
            self._set_api_busy(False)
            error = holder.get("error")
            if error is not None:
                self.api_status_var.set("Povezava oziroma API opravilo ni uspelo.")
                self.api_connection_label.configure(bg=self.colors["danger"], fg="#ffffff")
                messagebox.showerror("Minimax API", str(error), parent=self.root)
                return
            try:
                on_success(holder.get("result"))
            except Exception as exc:
                self.api_status_var.set("API opravilo je vrnilo napako pri prikazu.")
                messagebox.showerror("Minimax API", str(exc), parent=self.root)

        self.root.after(100, poll)

    def _set_api_busy(self, busy: bool) -> None:
        self.api_busy = busy
        has_target = bool(self.active_company and company_registry.company_org_id(self.active_company))
        self.api_connect_button.configure(state="disabled" if busy or not has_target else "normal")
        if hasattr(self, "minimax_data_button"):
            self.minimax_data_button.configure(state="disabled" if busy or not has_target else "normal")
        ready = bool(self.minimax_client and self.minimax_client.organisation_id and self.dataset)
        self.api_validate_button.configure(state="normal" if ready and not busy else "disabled")
        can_send = ready and not busy and any(
            self.api_tree.set(item, "api_status") == "OK" for item in self.api_tree.selection()
        )
        self.api_send_button.configure(state="normal" if can_send else "disabled")
        transfer_state = "normal" if self.dataset and has_target and not busy else "disabled"
        for button in getattr(self, "api_transfer_buttons", ()):
            button.configure(state=transfer_state)
        if hasattr(self, "api_retry_failed_button"):
            has_failed = bool(
                hasattr(self, "api_tree")
                and any(self.api_tree.set(item, "api_status") == "NAPAKA" for item in self.api_tree.get_children())
            )
            self.api_retry_failed_button.configure(
                state="normal" if self.dataset and has_target and not busy and has_failed else "disabled"
            )
        for button in getattr(self, "api_browser_buttons", ()):
            button.configure(state="disabled" if busy else "normal")
        if hasattr(self, "api_open_company_button"):
            self.api_open_company_button.configure(state="normal" if has_target and not busy else "disabled")
        if hasattr(self, "api_latest_received_button"):
            can_read_received = bool(self.minimax_client and self.minimax_client.organisation_id and not busy)
            self.api_latest_received_button.configure(state="normal" if can_read_received else "disabled")
        if hasattr(self, "api_refresh_status_button"):
            can_refresh_status = bool(
                self.dataset and self.minimax_client and self.minimax_client.organisation_id and not busy
            )
            self.api_refresh_status_button.configure(state="normal" if can_refresh_status else "disabled")
        if hasattr(self, "api_download_attachment_button"):
            selected = self.api_tree.selection() if hasattr(self, "api_tree") else ()
            can_download = bool(
                ready and not busy and len(selected) == 1
                and self.api_tree.set(selected[0], "book") == "PR"
                and self._sent_invoice_id("PR", self._api_item_row(selected[0])[1])
            )
            self.api_download_attachment_button.configure(state="normal" if can_download else "disabled")
            self.api_local_attachment_button.configure(state="normal" if ready and not busy else "disabled")
            supplier_ok = bool(
                ready and not busy and len(selected) == 1
                and self.api_tree.set(selected[0], "book") == "PR"
                and "QUICK" in self.api_tree.set(selected[0], "party").upper()
            ) if selected else False
            self.api_supplier_attachment_button.configure(state="normal" if supplier_ok else "disabled")
            self.api_attach_supplier_pdf_button.configure(state="normal" if supplier_ok else "disabled")
        if hasattr(self, "api_open_draft_button"):
            selected = self.api_tree.selection() if hasattr(self, "api_tree") else ()
            can_open = False
            if len(selected) == 1:
                item = selected[0]
                can_open = bool(
                    self._api_transfer_mode() == "invoice"
                    and self.api_tree.set(item, "book") == "PR"
                    and self.api_tree.set(item, "api_status") == "ODDANO"
                )
            self.api_open_draft_button.configure(state="normal" if can_open and not busy else "disabled")
        if hasattr(self, "api_batch_pr_button"):
            can_batch = False
            if hasattr(self, "api_tree") and self._api_transfer_mode() == "invoice" and not busy:
                for item in self.api_tree.selection() or self.api_tree.get_children():
                    if (
                        self.api_tree.set(item, "book") == "PR"
                        and self.api_tree.set(item, "api_status") == "ODDANO"
                    ):
                        can_batch = True
                        break
            self.api_batch_pr_button.configure(state="normal" if can_batch else "disabled")

    def choose_minimax_settings(self) -> None:
        current = Path(self.api_settings_path_var.get())
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Izberite Minimax API nastavitve",
            initialdir=str(current.parent if current.parent.is_dir() else Path.cwd()),
            filetypes=[("JSON nastavitve", "*.json"), ("Vse datoteke", "*.*")],
        )
        if not selected:
            return
        self.api_settings_path_var.set(selected)
        self.config["minimax_settings_path"] = selected
        self.minimax_client = None
        self.minimax_organisations.clear()
        self._clear_minimax_invoice_statuses()
        if self.dataset:
            self._populate_trees()
        self.api_org_var.set("")
        self.api_status_var.set("Izbrane so nove nastavitve; povezavo ponovno preverite.")
        self.api_connection_label.configure(bg=self.colors["warning"], fg="#07150e")
        self._save_session_state()
        self._set_api_busy(False)

    def toggle_api_connection_panel(self) -> str:
        """Strne ali razširi visoki panel povezave in brskalnika."""
        if getattr(self, "api_connection_expanded", False):
            self.api_connection_panel.pack_forget()
            self.api_connection_expanded = False
            self.api_connection_toggle_button.configure(text="▸ Povezava / nastavitve")
        else:
            self.api_connection_panel.pack(fill="x", pady=(0, 5), before=self.api_status_actions)
            self.api_connection_expanded = True
            self.api_connection_toggle_button.configure(text="▾ Skrij povezavo / nastavitve")
        return "break"

    def _api_transfer_mode(self) -> str:
        return "invoice" if self.api_transfer_mode_var.get().strip().startswith("Izdani/") else "journal"

    @staticmethod
    def _api_reference_id(value: str) -> str:
        match = re.match(r"\s*(\d+)\b", str(value or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _api_vat_type_code(value: str) -> str:
        text = str(value or "").strip()
        if not text or text.startswith("—"):
            return ""
        return text.split("—", 1)[0].strip().upper()

    def _api_transfer_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "numbering_ir_id": self._api_reference_id(self.api_ir_numbering_var.get()),
            "numbering_pr_id": self._api_reference_id(self.api_pr_numbering_var.get()),
            "item_ir_id": self._api_reference_id(self.api_ir_item_var.get()),
            "due_days": self.api_due_days_var.get().strip() or "8",
            "vat_type_ir": self._api_vat_type_code(self.api_vat_type_ir_var.get()) or "OD",
            "vat_type_pr": self._api_vat_type_code(self.api_vat_type_pr_var.get()),
            "pr_companion_journal": bool(self.api_pr_companion_var.get()),
        }
        if self.minimax_invoice_status_checked:
            options["existing_refs"] = self._existing_refs_from_catalog()
        return options

    def _load_api_profile_options(self, profile: Mapping[str, Any]) -> None:
        mode = str(profile.get("minimax_api_transfer_mode") or self.config.get("minimax_api_transfer_mode") or "journal")
        self.api_transfer_mode_var.set(
            "Izdani/Prejeti račun — osnutek" if mode == "invoice" else "Temeljnica + DDV"
        )
        self.api_ir_numbering_var.set(str(profile.get("minimax_ir_numbering_id") or ""))
        self.api_pr_numbering_var.set(str(profile.get("minimax_pr_numbering_id") or ""))
        self.api_ir_item_var.set(str(profile.get("minimax_ir_item_id") or ""))
        self.api_due_days_var.set(str(profile.get("minimax_due_days") or "8"))
        ir_type = str(profile.get("minimax_vat_type_ir") or "OD")
        pr_type = str(profile.get("minimax_vat_type_pr") or "")
        self.api_vat_type_ir_var.set(ir_type)
        self.api_vat_type_pr_var.set(pr_type or "— običajni PR (brez posebne vrste)")
        self.api_pr_companion_var.set(bool(profile.get("minimax_pr_companion_journal", False)))
        if hasattr(self, "api_mode_combo"):
            self._on_api_mode_changed(save=False)

    def _sync_api_reference_choices(
        self,
        ir_numberings: list[Mapping[str, Any]],
        pr_numberings: list[Mapping[str, Any]],
        items: list[Mapping[str, Any]],
        vat_types: list[Mapping[str, Any]],
    ) -> None:
        def numbering_values(records: list[Mapping[str, Any]], variable: tk.StringVar) -> list[str]:
            values = [str(item.get("label") or "") for item in records if str(item.get("label") or "")]
            current_id = self._api_reference_id(variable.get())
            chosen = next(
                (label for label in values if current_id and self._api_reference_id(label) == current_id),
                values[0] if values else variable.get(),
            )
            variable.set(chosen)
            return values

        self.api_ir_numbering_values = numbering_values(ir_numberings, self.api_ir_numbering_var)
        self.api_pr_numbering_values = numbering_values(pr_numberings, self.api_pr_numbering_var)
        self.api_ir_item_values = numbering_values(items, self.api_ir_item_var)
        ir_values = [
            str(item.get("label") or "") for item in vat_types
            if str(item.get("book") or "").upper() in {"", "IR"}
        ]
        pr_values = [
            str(item.get("label") or "") for item in vat_types
            if str(item.get("book") or "").upper() in {"", "PR"}
        ]
        self.api_vat_type_ir_values = list(dict.fromkeys(ir_values or ["OD — Obračuna se DDV"]))
        self.api_vat_type_pr_values = ["— običajni PR (brez posebne vrste)"] + list(dict.fromkeys(pr_values))

        def select_vat(variable: tk.StringVar, values: list[str], default: str) -> None:
            code = self._api_vat_type_code(variable.get())
            matching = next((item for item in values if self._api_vat_type_code(item) == code and code), "")
            variable.set(matching or default)

        select_vat(self.api_vat_type_ir_var, self.api_vat_type_ir_values, self.api_vat_type_ir_values[0])
        select_vat(self.api_vat_type_pr_var, self.api_vat_type_pr_values, self.api_vat_type_pr_values[0])
        self._save_api_options()

    def _on_api_mode_changed(self, _event: tk.Event | None = None, *, save: bool = True) -> None:
        if not hasattr(self, "api_status_combo"):
            return
        invoice_mode = self._api_transfer_mode() == "invoice"
        self.api_status_combo.configure(state="disabled" if invoice_mode else "readonly")
        if invoice_mode:
            if self.api_pr_companion_var.get():
                self.api_help_var.set(
                    "PR dobi tudi ločeno osnutno temeljnico s kontom odhodka in DDV. V Minimaxu potrdite samo en dokument."
                )
            else:
                self.api_help_var.set(
                    "IR/PR se ustvarijo kot osnutki. IR je treba izdati, PR pa v Minimaxu dopolniti s knjižbo stroška in DDV."
                )
            labels = ("Ustvari vse IR", "Ustvari vse PR", "Ustvari IR + PR")
        else:
            self.api_help_var.set(
                "Oddaja ustvari temeljnico, nato DDV-vrstico doda z ločenim API-klicem in preveri njen zapis."
            )
            labels = ("Prenesi vse IR", "Prenesi vse PR", "Prenesi IR + PR")
        for button, text in zip(getattr(self, "api_transfer_buttons", ()), labels):
            button.configure(text=text)
        if hasattr(self, "api_tree"):
            self._populate_api_tree()
        if save:
            self._save_api_options()

    def open_api_transfer_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Nastavitve Minimax DDV in računov")
        window.transient(self.root)
        window.grab_set()
        window.geometry("900x650")
        window.minsize(760, 590)
        window.configure(bg=self.colors["bg"])

        header = ttk.Frame(window, style="Header.TFrame", padding=(20, 16))
        header.pack(fill="x")
        ttk.Label(header, text="Ročne nastavitve prenosa", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Šifranti se naložijo iz izbranega podjetja. ID lahko po potrebi vpišete tudi ročno.",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        form = ttk.Frame(window, style="Panel.TFrame", padding=(22, 18))
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Številčenje IR (prazno = privzeto):", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        ir_combo = ttk.Combobox(form, textvariable=self.api_ir_numbering_var, values=self.api_ir_numbering_values)
        ir_combo.grid(row=0, column=1, sticky="ew", padx=(18, 0), pady=6)
        ttk.Label(form, text="Številčenje PR (prazno = privzeto):", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        pr_combo = ttk.Combobox(form, textvariable=self.api_pr_numbering_var, values=self.api_pr_numbering_values)
        pr_combo.grid(row=1, column=1, sticky="ew", padx=(18, 0), pady=6)
        ttk.Label(form, text="Artikel za izdane račune IR:", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(
            form, textvariable=self.api_ir_item_var, values=self.api_ir_item_values
        ).grid(row=2, column=1, sticky="ew", padx=(18, 0), pady=6)
        ttk.Label(form, text="Rok plačila v dnevih:", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.api_due_days_var, width=12).grid(row=3, column=1, sticky="w", padx=(18, 0), pady=6)
        ttk.Label(form, text="Vrsta obračuna DDV za IR:", style="Panel.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Combobox(
            form, textvariable=self.api_vat_type_ir_var, values=self.api_vat_type_ir_values
        ).grid(row=4, column=1, sticky="ew", padx=(18, 0), pady=6)
        ttk.Label(form, text="Vrsta obračuna DDV za PR:", style="Panel.TLabel").grid(row=5, column=0, sticky="w", pady=6)
        ttk.Combobox(
            form, textvariable=self.api_vat_type_pr_var, values=self.api_vat_type_pr_values
        ).grid(row=5, column=1, sticky="ew", padx=(18, 0), pady=6)
        companion = ttk.Checkbutton(
            form,
            text="PR: ustvari tudi ločeno temeljnico + DDV (oba ostaneta osnutka)",
            variable=self.api_pr_companion_var,
        )
        companion.grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 4))
        note = (
            "Način Temeljnica + DDV prenese konto, dvostavno knjižbo in DDV evidenco.\n"
            "Če številčenje pustite prazno, Minimax uporabi svoje privzeto številčenje; po potrebi lahko vpišete njegov ID.\n"
            "Za IR je obvezen obstoječi artikel; program po povezavi sam izbere prvi artikel tipa Storitev, izbiro pa lahko spremenite.\n"
            "Način Račun ustvari varen osnutek: pri IR Minimax dodeli svojo številko ob izdaji; "
            "pri PR njegov API sprejme samo glavo in znesek. Če vključite zgornjo možnost, program zato "
            "ustvari še ločeno osnutno temeljnico s popravljenim kontom odhodka in DDV. Dokumenta nista "
            "API-povezana: v Minimaxu potrdite samo PR ali samo temeljnico, nikoli obeh."
        )
        ttk.Label(form, text=note, style="Muted.TLabel", wraplength=750, justify="left").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0)
        )

        buttons = ttk.Frame(window, style="Panel.TFrame", padding=(20, 12))
        buttons.pack(fill="x")

        def save_and_close() -> None:
            try:
                due_days = int(self.api_due_days_var.get().strip())
                if due_days < 0 or due_days > 3650:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Neveljaven rok", "Rok mora biti celo število od 0 do 3650 dni.", parent=window)
                return
            self._save_api_options()
            self._on_api_mode_changed(save=False)
            window.destroy()
            self.status_var.set("Nastavitve DDV in API računov so shranjene za izbrano podjetje.")

        ttk.Button(buttons, text="Prekliči", style="Danger.TButton", command=window.destroy).pack(side="right")
        ttk.Button(buttons, text="Shrani nastavitve", style="Success.TButton", command=save_and_close).pack(side="right", padx=(0, 8))
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def _save_api_options(self, _event: tk.Event | None = None) -> None:
        selected_org = str(
            self.minimax_organisations.get(self.api_org_var.get(), "")
            or company_registry.company_org_id(self.active_company or {})
            or self._profile_config().get("minimax_selected_org_id")
            or ""
        )
        self.config["minimax_selected_org_id"] = selected_org
        profile = self._profile_config()
        profile["minimax_selected_org_id"] = selected_org
        self.config["minimax_journal_status"] = self._api_journal_status()
        mode = self._api_transfer_mode()
        self.config["minimax_api_transfer_mode"] = mode
        profile["minimax_api_transfer_mode"] = mode
        options = self._api_transfer_options()
        profile["minimax_ir_numbering_id"] = options["numbering_ir_id"]
        profile["minimax_pr_numbering_id"] = options["numbering_pr_id"]
        profile["minimax_ir_item_id"] = options["item_ir_id"]
        profile["minimax_due_days"] = options["due_days"]
        profile["minimax_vat_type_ir"] = options["vat_type_ir"]
        profile["minimax_vat_type_pr"] = options["vat_type_pr"]
        profile["minimax_pr_companion_journal"] = options["pr_companion_journal"]
        self.config["minimax_settings_path"] = self.api_settings_path_var.get().strip()
        try:
            self._save_session_state()
        except OSError:
            pass

    def _api_journal_status(self) -> str:
        return "P" if self.api_journal_status_var.get().strip().upper().startswith("P") else "O"

    def _automatic_org_label(self, settings: minimax_api.ApiSettings) -> str:
        saved = (
            company_registry.company_org_id(self.active_company or {})
            or str(self._profile_config().get("minimax_selected_org_id") or "")
            or str(self.config.get("minimax_selected_org_id") or "")
        )
        if saved:
            for label, organisation_id in self.minimax_organisations.items():
                if str(organisation_id) == saved:
                    return label
        source_token = re.sub(r"[^0-9a-z]+", "", str(self.dataset.source_path.name if self.dataset else "").casefold())
        matches: list[tuple[int, str]] = []
        for label in self.minimax_organisations:
            name = label.split(" — ", 1)[-1]
            name_token = re.sub(r"[^0-9a-z]+", "", name.casefold())
            first_word = re.sub(r"[^0-9a-z]+", "", name.split()[0].casefold()) if name.split() else ""
            if name_token and name_token in source_token:
                matches.append((len(name_token), label))
            elif len(first_word) >= 4 and first_word in source_token:
                matches.append((len(first_word), label))
        if matches:
            return max(matches)[1]
        if settings.organisation_id:
            for label, organisation_id in self.minimax_organisations.items():
                if str(organisation_id) == settings.organisation_id:
                    return label
        return next(iter(self.minimax_organisations), "")

    def connect_minimax_api(self, after_connect: Callable[[], None] | None = None) -> None:
        if not self.active_company:
            messagebox.showinfo("Izberite podjetje", "Najprej izberite podjetje v levem seznamu.", parent=self.root)
            return
        expected_org = company_registry.company_org_id(self.active_company)
        if not expected_org:
            messagebox.showerror(
                "Manjka Org_ID",
                f"Podjetje {company_registry.company_name(self.active_company)} nima vpisanega Minimax Org_ID.",
                parent=self.root,
            )
            return
        self._clear_minimax_invoice_statuses()
        if self.dataset:
            self._populate_trees()
        settings_path = Path(self.api_settings_path_var.get())

        def task() -> tuple[minimax_api.MinimaxClient, minimax_api.ApiSettings, list[dict[str, Any]]]:
            settings = minimax_api.ApiSettings.from_file(settings_path)
            client = minimax_api.MinimaxClient(settings)
            client.authenticate()
            organisations = client.organisations()
            if not organisations:
                raise minimax_api.MinimaxApiError("Prijava je uspela, vendar API ni vrnil nobene organizacije.")
            return client, settings, organisations

        def success(result: Any) -> None:
            client, settings, organisations = result
            self.minimax_client = client
            labels = [client.organisation_label(record) for record in organisations]
            self.minimax_organisations = {
                label: int(label.split(" — ", 1)[0]) for label in labels if label.split(" — ", 1)[0].isdigit()
            }
            selected = next(
                (label for label, organisation_id in self.minimax_organisations.items() if str(organisation_id) == expected_org),
                "",
            )
            if not selected:
                self.api_status_var.set(f"Org_ID {expected_org} ni dostopen s prijavljenim Minimax uporabnikom.")
                self.api_connection_label.configure(bg=self.colors["danger"], fg="#ffffff")
                messagebox.showerror(
                    "Organizacija ni dostopna",
                    f"Minimax uporabnik nima dostopa do Org_ID {expected_org} za podjetje "
                    f"{company_registry.company_name(self.active_company or {})}.",
                    parent=self.root,
                )
                return
            self.api_org_var.set(selected)
            self.api_status_var.set(f"OAuth prijava je uspela; dostopnih organizacij: {len(labels)}. Nalagam šifrante …")
            self.api_connection_label.configure(bg=self.colors["accent"], fg="#ffffff")
            self._save_api_options()
            self._on_api_org_selected(after_connect=after_connect)

        self._run_api_worker(task, success, busy_text="Prijavljam se v Minimax OAuth …")

    def _on_api_org_selected(
        self,
        _event: tk.Event | None = None,
        *,
        after_connect: Callable[[], None] | None = None,
    ) -> None:
        if not self.minimax_client:
            return
        label = self.api_org_var.get()
        organisation_id = self.minimax_organisations.get(label)
        if not organisation_id:
            return
        if self.active_company:
            expected = company_registry.company_org_id(self.active_company)
            if not expected:
                messagebox.showwarning(
                    "Manjka Org_ID",
                    "Izbrano podjetje v EvidenciFirm nima Org_ID. Najprej ga dopolnite ali izberite drugo podjetje.",
                    parent=self.root,
                )
                return
            if str(organisation_id) != expected:
                expected_label = next(
                    (item for item, value in self.minimax_organisations.items() if str(value) == expected),
                    "",
                )
                if expected_label:
                    self.api_org_var.set(expected_label)
                messagebox.showwarning(
                    "Organizacijo določa podjetje",
                    f"Za {company_registry.company_name(self.active_company)} je dovoljen Org_ID {expected}.\n"
                    "Za drugo organizacijo najprej izberite drugo podjetje v levem drevesu.",
                    parent=self.root,
                )
                return
        self._save_api_options()

        def task() -> tuple[
            dict[str, int],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, str]],
        ]:
            assert self.minimax_client is not None
            self.minimax_client.select_organisation(organisation_id)
            counts = self.minimax_client.refresh_references()
            effective_date = self.dataset.period_to if self.dataset else datetime.now().date().isoformat()
            return (
                counts,
                self.minimax_client.account_catalog(),
                self.minimax_client.document_numbering_catalog("IR"),
                self.minimax_client.document_numbering_catalog("PR"),
                self.minimax_client.item_catalog(),
                self.minimax_client.vat_accounting_type_catalog(effective_date),
            )

        def success(result: Any) -> None:
            counts, account_catalog, ir_numberings, pr_numberings, items, vat_types = result
            self._set_account_catalog(account_catalog)
            self._sync_api_reference_choices(ir_numberings, pr_numberings, items, vat_types)
            warn = []
            try:
                warn = list(self.minimax_client.reference_warnings()) if self.minimax_client else []
            except Exception:
                warn = []
            status = (
                f"POVEZANO: {label}  •  konti {counts.get('accounts', 0)}  •  "
                f"stranke {counts.get('customers', 0)}  "
                f"•  DDV stopnje {counts.get('vatrates', 0)}  •  "
                f"valute {counts.get('currencies', 0)}  "
                f"•  artikli {counts.get('items', 0)}  •  "
                f"vrste temeljnic {counts.get('journaltypes', 0)}  "
                f"•  številčenja {counts.get('document_numberings', 0)}"
            )
            if warn:
                status += f"  •  opozorila šifrantov: {len(warn)}"
            self.api_status_var.set(status)
            self.api_connection_label.configure(bg=self.colors["success"], fg="#07150e")
            self._record_action("api_connect", label)
            self.status_var.set(f"Minimax API je povezan z organizacijo {label}.")
            self._clear_minimax_invoice_statuses()
            self.minimax_invoice_status_org = str(organisation_id)
            if self.dataset:
                self._populate_trees()
            else:
                self._populate_api_tree()
            self._set_api_busy(False)
            if warn:
                messagebox.showwarning(
                    "Minimax šifranti — delni dostop",
                    (
                        f"Organizacija {label} je povezana, a Minimax ni dovolil "
                        "vseh šifrantov (pogosto »Pregled sistemskih šifrantov«).\n\n"
                        + "\n".join(warn[:8])
                        + (
                            "\n\n… in še več."
                            if len(warn) > 8
                            else ""
                        )
                        + "\n\nČe manjkajo konti/stranke, v Minimaxu preveri pravice "
                        "API uporabnika za to firmo."
                    ),
                    parent=self.root,
                )
            if after_connect:
                after_connect()
            elif self.dataset:
                self.refresh_minimax_invoice_statuses(show_message=False)

        self._run_api_worker(task, success, busy_text=f"Nalagam šifrante organizacije {label} …")

    def _active_org_matches_api(self, *, show_error: bool = True) -> bool:
        if not self.active_company or not self.minimax_client:
            return True
        expected = company_registry.company_org_id(self.active_company)
        actual = str(self.minimax_client.organisation_id or "")
        if not expected:
            if show_error:
                messagebox.showerror(
                    "Podjetje nima Org_ID",
                    f"Podjetje {company_registry.company_name(self.active_company)} v EvidenciFirm nima vpisanega Minimax Org_ID.",
                    parent=self.root,
                )
            return False
        if expected == actual:
            return True
        if show_error:
            messagebox.showerror(
                "Napačna Minimax organizacija",
                f"Izbrano podjetje: {company_registry.company_name(self.active_company)}\n"
                f"Pričakovani Org_ID: {expected}\n"
                f"Povezani Org_ID: {actual}\n\n"
                "V levem drevesu ponovno izberite podjetje in povežite njegov Minimax API.",
                parent=self.root,
            )
        return False

    def _api_row_matches_search(
        self,
        book: str,
        row: Mapping[str, Any],
        metrics: Mapping[str, Any],
        *,
        invoice_status: str,
        api_status: str,
        detail: str,
        account_label: str,
        tokens: Sequence[str],
    ) -> bool:
        """True, če vsi iskalni žetoni najdejo zadetek kjerkoli v podatkih vrstice."""
        return self._haystack_matches(
            tokens,
            self._evidence_row_search_chunks(
                book,
                row,
                metrics,
                extra=(invoice_status, api_status, detail, account_label),
            ),
        )

    def clear_api_search(self) -> None:
        self.api_search_var.set("")
        self._populate_api_tree()

    def _populate_api_tree(self) -> None:
        if not hasattr(self, "api_tree"):
            return
        self.api_tree.delete(*self.api_tree.get_children())
        self.api_item_sent_info = {}
        if not self.dataset:
            self.api_selection_var.set("Izbranih za oddajo: 0")
            return
        profile = self._profile_config()
        sent = profile.get("minimax_api_sent") or {}
        transfer_mode = self._api_transfer_mode()
        selected_org = str(profile.get("minimax_selected_org_id") or self.config.get("minimax_selected_org_id") or "")
        search_tokens = self._search_tokens(self.api_search_var.get())
        # Prikaz in oddaja po listini (P3), omejeno na izbrano obdobje.
        ir_entries = [
            (index, row)
            for index, row in enumerate(self.dataset.kir)
            if self._row_in_period("IR", row) and not core.ir_metrics(row, self.dataset.kpr)["tax_only"]
        ]
        ir_entries.sort(key=lambda item: listina_sort_key(item[1].get("P3")))
        pr_entries = [
            (index, row)
            for index, row in enumerate(self.dataset.kpr)
            if self._row_in_period("PR", row)
        ]
        pr_entries.sort(key=lambda item: listina_sort_key(item[1].get("P3")))

        def sent_for(book: str, row: Mapping[str, Any]) -> dict[str, Any] | None:
            key = core.row_key(book, row)
            mode_key = f"{transfer_mode}:{key}"
            saved_info = sent.get(mode_key) if isinstance(sent, dict) else None
            if saved_info is None and transfer_mode == "journal" and isinstance(sent, dict):
                saved_info = sent.get(key)
            if isinstance(saved_info, dict) and str(saved_info.get("organisation_id") or "") == selected_org:
                return saved_info
            return None

        shown = 0
        total_candidates = 0
        for index, row in ir_entries:
            if self.api_view_filter not in {"ALL", "IR"}:
                continue
            total_candidates += 1
            metrics = core.ir_metrics(row, self.dataset.kpr)
            sent_info = sent_for("IR", row)
            api_status, detail, tag = self._api_state_for_row("IR", row, sent_info)
            invoice_status = self._minimax_status_for_row("IR", row)
            account_label = self._account_label(row.get("__konto__", "7601"))
            if not self._api_row_matches_search(
                "IR",
                row,
                metrics,
                invoice_status=invoice_status,
                api_status=api_status,
                detail=detail,
                account_label=account_label,
                tokens=search_tokens,
            ):
                continue
            item = f"api:IR:{index}"
            self.api_tree.insert(
                "", "end", iid=item, tags=(tag,),
                values=("IR", row.get("P3", ""), row.get("P5", ""), row.get("P6DS", ""),
                        format_money(metrics["gross"]), account_label,
                        invoice_status, api_status, detail),
            )
            shown += 1
            if sent_info or api_status == "ODDANO":
                self.api_item_sent_info[item] = dict(sent_info or {})
        for index, row in pr_entries:
            if self.api_view_filter not in {"ALL", "PR"}:
                continue
            total_candidates += 1
            metrics = core.pr_metrics(row)
            sent_info = sent_for("PR", row)
            api_status, detail, tag = self._api_state_for_row("PR", row, sent_info)
            invoice_status = self._minimax_status_for_row("PR", row)
            account_label = self._account_label(row.get("__konto__", "4190"))
            if not self._api_row_matches_search(
                "PR",
                row,
                metrics,
                invoice_status=invoice_status,
                api_status=api_status,
                detail=detail,
                account_label=account_label,
                tokens=search_tokens,
            ):
                continue
            item = f"api:PR:{index}"
            self.api_tree.insert(
                "", "end", iid=item, tags=(tag,),
                values=("PR", row.get("P3", ""), row.get("P6", ""), row.get("P7DS", ""),
                        format_money(metrics["gross"]),
                        account_label,
                        invoice_status,
                        api_status,
                        detail),
            )
            shown += 1
            if sent_info or api_status == "ODDANO":
                self.api_item_sent_info[item] = dict(sent_info or {})
        filter_labels = {"ALL": "Prikaz: vsi računi", "IR": "Prikaz: samo IR", "PR": "Prikaz: samo PR"}
        mode_label = "JSON" if self.api_view_mode == "json" else "Minimax"
        search_note = f" • išči {shown}/{total_candidates}" if search_tokens else f" • {shown}"
        self.api_view_filter_var.set(f"{filter_labels[self.api_view_filter]} • {mode_label}{search_note}")
        self.api_selection_var.set("Izbranih za oddajo: 0")
        self._set_api_busy(self.api_busy)

    def _api_item_row(self, item: str) -> tuple[str, dict[str, Any]]:
        if not self.dataset:
            raise ValueError("Ni odprtih podatkov.")
        _prefix, book, raw_index = item.split(":", 2)
        index = int(raw_index)
        row = self.dataset.kir[index] if book == "IR" else self.dataset.kpr[index]
        return book, row

    def _selected_api_rows(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Izbrane vrstice vedno v vrstnem redu listine (IR pred PR)."""
        rows: list[tuple[str, str, dict[str, Any]]] = []
        for item in self.api_tree.selection():
            book, row = self._api_item_row(item)
            rows.append((item, book, row))
        rows.sort(
            key=lambda entry: (
                0 if entry[1] == "IR" else 1,
                listina_sort_key(entry[2].get("P3")),
            )
        )
        return rows

    def _on_api_tree_selection(self, _event: tk.Event | None = None) -> None:
        selected = self.api_tree.selection()
        self.api_selection_var.set(f"Izbranih za oddajo: {len(selected)}")
        self._set_api_busy(self.api_busy)

    def set_api_view_filter(self, book: str) -> str:
        """Prikaze vse API vrstice ali samo izdane oziroma prejete racune."""
        requested = str(book or "ALL").upper()
        if requested not in {"ALL", "IR", "PR"}:
            requested = "ALL"
        self.api_view_filter = requested
        self._profile_config()["minimax_api_view_filter"] = requested
        try:
            self._save_session_state()
        except OSError:
            pass
        self._populate_api_tree()
        return "break"

    def open_api_row_from_double_click(self, event: tk.Event) -> str:
        """PR-osnutek odpre v Playwrightu; druge vrstice ohranijo prikaz API rezultata."""
        item = self.api_tree.identify_row(event.y)
        if not item:
            return "break"
        self.api_tree.selection_set(item)
        self.api_tree.focus(item)
        self._on_api_tree_selection()
        if (
            self.api_tree.set(item, "book") == "PR"
            and self.api_tree.set(item, "api_status") == "ODDANO"
            and self._api_transfer_mode() == "invoice"
        ):
            return self.open_selected_api_draft()
        return self.show_api_result_details()

    def check_minimax_browser_session(self) -> None:
        """Preveri skupni persistentni profil brez branja ali izvoza cookies."""
        def success(status: Any) -> None:
            profile = str(getattr(status, "profile_path", "") or "")
            if profile:
                profile_path = Path(profile)
                short_profile = f"…\\{profile_path.parent.name}\\{profile_path.name}"
                self.playwright_profile_var.set(f"Profil: {short_profile} • brez izvoza piškotkov")
            if status and status.ready and status.logged_in:
                self.playwright_session_var.set("Seja: PRIJAVLJENA")
                self.api_connection_label.configure(bg=self.colors["success"], fg="#07140e")
                self.status_var.set("Skupna Playwright seja je prijavljena in uporabna za dostopna podjetja.")
                self._record_action("browser_session", "prijavljena")
                return
            self.playwright_session_var.set("Seja: NI PRIJAVLJENA / JE POTEKLA")
            self.api_connection_label.configure(bg=self.colors["warning"], fg="#07150e")
            message = status.message if status else "Preverjanje seje ni uspelo."
            self.status_var.set(message)

        self._run_api_worker(
            minimax_browser.check_session,
            success,
            busy_text="Preverjam skupno Playwright sejo …",
        )

    def login_minimax_browser(self) -> None:
        """Odpre enkratno prijavo v skupni Playwright profil za vsa podjetja."""
        ready, detail = minimax_browser.automation_ready()
        if not ready:
            messagebox.showerror("Playwright ni pripravljen", detail, parent=self.root)
            return

        def success(result: Any) -> None:
            if result and result.ok:
                self.api_status_var.set("Prijava za avtomatizacijo je pripravljena.")
                self.playwright_session_var.set("Seja: shranjena, preverjam …")
                profile = minimax_browser.shared_profile_path()
                if profile:
                    profile_path = Path(profile)
                    self.playwright_profile_var.set(
                        f"Profil: …\\{profile_path.parent.name}\\{profile_path.name} • za vsa dostopna podjetja"
                    )
                self.api_connection_label.configure(bg=self.colors["success"], fg="#07140e")
                self.status_var.set("Minimax Playwright seja je shranjena; preverjam veljavnost.")
                messagebox.showinfo("Minimax prijava", result.message, parent=self.root)
                self.check_minimax_browser_session()
                return
            message = result.message if result else "Prijava ni uspela."
            self.playwright_session_var.set("Seja: prijava ni uspela")
            self.api_status_var.set("Prijava za avtomatizacijo ni uspela.")
            self.api_connection_label.configure(bg=self.colors["danger"], fg="#ffffff")
            messagebox.showerror("Minimax prijava", message, parent=self.root)

        self._run_api_worker(
            minimax_browser.ensure_minimax_login,
            success,
            busy_text="Odprta je prijava v Minimax; dokončajte jo v brskalniku …",
        )

    def open_selected_company_browser(self) -> None:
        """V skupnem profilu odpre podjetje iz leve EvidenceFirm izbire."""
        if not self.active_company:
            messagebox.showinfo("Ni podjetja", "V levem seznamu najprej izberite podjetje.", parent=self.root)
            return
        organisation_id = company_registry.company_org_id(self.active_company)
        organisation_name = company_registry.company_name(self.active_company)
        if not organisation_id:
            messagebox.showerror(
                "Manjka Org_ID",
                f"Podjetje {organisation_name} v EvidenciFirm nima Minimax Org_ID.",
                parent=self.root,
            )
            return

        def task() -> Any:
            return minimax_browser.open_organisation(
                organisation_id=organisation_id,
                organisation_name=organisation_name,
            )

        def success(result: Any) -> None:
            if result and result.ok:
                self.playwright_session_var.set(f"Seja: {organisation_name} ({organisation_id})")
                self._record_action("browser_company", f"{organisation_name}; Org_ID {organisation_id}")
                self.status_var.set(
                    f"Playwright je odprl {organisation_name} (Org_ID {organisation_id}); seja ostane shranjena."
                )
                return
            message = result.message if result else "Odpiranje podjetja ni uspelo."
            if result and result.need_login:
                self.playwright_session_var.set("Seja: potrebna je enkratna prijava")
                if messagebox.askyesno(
                    "Potrebna je prijava",
                    message + "\n\nNaj odprem skupno enkratno prijavo?",
                    parent=self.root,
                ):
                    self.login_minimax_browser()
                return
            messagebox.showerror("Minimax podjetje", message, parent=self.root)

        self._run_api_worker(
            task,
            success,
            busy_text=(
                f"Odpiram {organisation_name} (Org_ID {organisation_id}) prek Moje organizacije. "
                "Po koncu zaprite Playwright okno …"
            ),
        )

    def save_minimax_browser_diagnostic(self) -> None:
        """Shrani samo vidne oznake organizacij; brez cookies, gesel in skritih polj."""
        if not self.active_company:
            messagebox.showinfo("Ni podjetja", "V levem seznamu najprej izberite podjetje.", parent=self.root)
            return
        organisation_id = company_registry.company_org_id(self.active_company)
        organisation_name = company_registry.company_name(self.active_company)
        if not organisation_id:
            messagebox.showerror("Manjka Org_ID", f"Podjetje {organisation_name} nima Org_ID.", parent=self.root)
            return
        safe_name = company_registry.safe_name(organisation_name, "podjetje")
        initial_dir = self.last_export_dir if self.last_export_dir and self.last_export_dir.is_dir() else Path(__file__).resolve().parent
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Shrani varno diagnostiko izbire organizacije",
            initialdir=str(initial_dir),
            initialfile=f"Minimax_organizacija_{safe_name}_{organisation_id}.json",
            defaultextension=".json",
            filetypes=[("JSON diagnostika", "*.json"), ("Vse datoteke", "*.*")],
        )
        if not selected:
            return

        def task() -> Any:
            return minimax_browser.save_organisation_diagnostic(
                organisation_id=organisation_id,
                organisation_name=organisation_name,
                output_path=selected,
            )

        def success(result: Any) -> None:
            if result and result.ok:
                self._record_action("browser_diagnostic", Path(selected).name)
                self.status_var.set(result.message)
                messagebox.showinfo(
                    "Varna diagnostika",
                    result.message + "\n\nDatoteka ne vsebuje piškotkov, gesel ali skritih obrazčnih polj.",
                    parent=self.root,
                )
                return
            message = result.message if result else "Diagnostika ni uspela."
            if result and result.need_login:
                self.playwright_session_var.set("Seja: potrebna je enkratna prijava")
            messagebox.showerror("Varna diagnostika", message, parent=self.root)

        self._run_api_worker(
            task,
            success,
            busy_text=f"Pripravljam varen diagnostični pregled za {organisation_name} …",
        )

    def open_selected_api_draft(self) -> str:
        """Odpre poslani PR-osnutek in pripravi odhodek s kontom iz KPR."""
        selected = self.api_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Odpri PR-osnutek",
                "Izberite natanko en oddani prejeti račun.",
                parent=self.root,
            )
            return "break"
        item = selected[0]
        book, row = self._api_item_row(item)
        if book != "PR":
            messagebox.showinfo(
                "Odpri PR-osnutek",
                "Samodejni vnos odhodka je namenjen prejetim računom (PR).",
                parent=self.root,
            )
            return "break"
        if self._api_transfer_mode() != "invoice" or self.api_tree.set(item, "api_status") != "ODDANO":
            messagebox.showinfo(
                "PR-osnutek še ni na voljo",
                "Najprej ustvarite PR v načinu »Izdani/Prejeti račun — osnutek«.",
                parent=self.root,
            )
            return "break"

        sent_info = dict(self.api_item_sent_info.get(item) or {})
        location = str(sent_info.get("location") or "")
        received_id = minimax_browser.extract_minimax_record_id(location, "receivedinvoices")
        organisation_id = str(
            sent_info.get("organisation_id")
            or company_registry.company_org_id(self.active_company or {})
            or ""
        )
        account = self._account_code(str(row.get("__konto__") or "")) or "4190"
        invoice = str(row.get("P3") or self.api_tree.set(item, "invoice") or "")
        organisation_name = company_registry.company_name(self.active_company or {})
        metrics = core.pr_metrics(row)
        if not received_id:
            messagebox.showerror(
                "ID PR ni najden",
                "V shranjenem odgovoru Minimax API ni ID prejetega računa.\n\n" + (location or "Ni Location podatka."),
                parent=self.root,
            )
            return "break"

        pack = self._confirm_pr_chrome_pack(
            invoice=invoice or received_id,
            organisation_name=organisation_name or organisation_id,
            account=account,
            metrics=metrics,
        )
        if pack is None:
            return "break"
        account = pack["account"]
        base_22 = pack["base_22"]
        base_95 = pack["base_95"]
        base_5 = pack["base_5"]
        auto_confirm = bool(pack["confirm"])

        def task() -> Any:
            return minimax_browser.open_received_draft_in_chrome(
                organisation_id=organisation_id,
                received_invoice_id=received_id,
                organisation_name=organisation_name,
                document_reference=invoice,
                expense_account=account,
                confirm=auto_confirm,
                base_22=base_22,
                base_95=base_95,
                base_5=base_5,
                vat_22=metrics.get("vat_22") or 0,
                vat_95=metrics.get("vat_95") or 0,
                vat_5=metrics.get("vat_5") or 0,
            )

        def success(result: Any) -> None:
            if result and result.ok:
                self._record_action(
                    "browser_open",
                    f"PR {invoice}; konto {account}; osnove 22/9,5/5",
                )
                action = "vnos in potrditev" if auto_confirm else "vnos brez končne potrditve"
                self.api_status_var.set(
                    f"PR {invoice}: poslan v Chrome; konto {account} + osnove, {action}."
                )
                self.status_var.set(result.message)
                return
            message = result.message if result else "Odpiranje osnutka ni uspelo."
            if result and result.need_login:
                self.api_status_var.set("Chrome seja še ni prijavljena v Minimax.")
                if messagebox.askyesno(
                    "Potrebna je prijava",
                    message + "\n\nNaj zdaj odprem prijavo v Minimax?",
                    parent=self.root,
                ):
                    self.login_minimax_browser()
                return
            self.api_status_var.set(f"PR {invoice}: avtomatizacija ni uspela.")
            messagebox.showerror("Minimax Chrome", message, parent=self.root)

        self._run_api_worker(
            task,
            success,
            busy_text=(
                f"Odpiram PR {invoice}: konto {account} in osnove DDV. "
                + ("Po vnosu bo kliknjen tudi Potrdi. " if auto_confirm else "Končna potrditev ostane ročna. ")
                + "Uporabljam prijavljeni Chrome in razširitev Minimax v1.3.7+ …"
            ),
        )
        return "break"

    def batch_confirm_pr_drafts_playwright(self) -> str:
        """Serija oddanih PR-osnutkov: konto/osnove iz vsake listine, Playwright batch."""
        if self._api_transfer_mode() != "invoice":
            messagebox.showinfo(
                "Serija PR",
                "Način mora biti »Izdani/Prejeti račun — osnutek« (invoice).",
                parent=self.root,
            )
            return "break"
        organisation_id = str(
            company_registry.company_org_id(self.active_company or {}) or ""
        ).strip()
        organisation_name = company_registry.company_name(self.active_company or {})
        if not organisation_id.isdigit():
            messagebox.showerror(
                "Serija PR",
                "Manjka Minimax Org_ID aktivnega podjetja.",
                parent=self.root,
            )
            return "break"

        selected = list(self.api_tree.selection() or ())
        candidates = selected if selected else list(self.api_tree.get_children())
        items_payload: list[dict[str, Any]] = []
        missing_konto: list[str] = []
        for tree_item in candidates:
            if self.api_tree.set(tree_item, "book") != "PR":
                continue
            if self.api_tree.set(tree_item, "api_status") != "ODDANO":
                continue
            book, row = self._api_item_row(tree_item)
            if book != "PR":
                continue
            sent_info = dict(self.api_item_sent_info.get(tree_item) or {})
            location = str(sent_info.get("location") or "")
            received_id = minimax_browser.extract_minimax_record_id(location, "receivedinvoices")
            if not received_id:
                # Fallback: shranjen ID v sent map / stolpec
                received_id = str(self._sent_invoice_id("PR", row) or "").strip()
            if not str(received_id).isdigit():
                continue
            invoice = str(row.get("P3") or self.api_tree.set(tree_item, "invoice") or "").strip()
            # Konto IZ LISTINE (document_accounts / __konto__), ne skupni 4190 za vse.
            account = self._account_code(str(row.get("__konto__") or "")).strip()
            if not account:
                missing_konto.append(invoice or received_id)
                continue
            metrics = core.pr_metrics(row)
            items_payload.append(
                {
                    "org_id": organisation_id,
                    "org_name": organisation_name,
                    "received_invoice_id": str(received_id),
                    "document_reference": invoice,
                    "expense_account": account,
                    "base_22": metrics.get("base_22") or 0,
                    "base_95": metrics.get("base_95") or 0,
                    "base_5": metrics.get("base_5") or 0,
                    "ref_key": tree_item,
                }
            )

        if missing_konto:
            messagebox.showwarning(
                "Manjka konto na listini",
                "Te listine nimajo konta odhodka (__konto__) — najprej ga vpišite v KPR:\n\n"
                + "\n".join(missing_konto[:15])
                + ("\n…" if len(missing_konto) > 15 else ""),
                parent=self.root,
            )
        if not items_payload:
            messagebox.showinfo(
                "Serija PR",
                "Ni oddanih PR-osnutkov z ReceivedInvoiceId in kontom iz listine.",
                parent=self.root,
            )
            return "break"

        # Brez nove prijave: CDP če :9222 že teče, sicer razširitev v OBSTOJEČEM Chromu.
        detected = minimax_browser.detect_minimax_firm_cdp()
        cdp_ready = bool(detected.get("ok") or detected.get("port"))
        det_name = str(detected.get("org_name") or "").strip()
        if cdp_ready and det_name:
            self.api_status_var.set(f"CDP: obstoječi Minimax »{det_name}«")
        engine = (
            "CDP — že odprt Chrome"
            if cdp_ready
            else "Chrome razširitev — obstoječi zavihek (brez nove prijave)"
        )

        # A/Q: Da = Potrdi, Ne = samo odhodek, Prekliči = stop
        choice = messagebox.askyesnocancel(
            "Serija PR — odhodek",
            (
                f"Motor: {engine}\n"
                f"Obdelam {len(items_payload)} PR za {organisation_name} "
                f"(Org {organisation_id}).\n"
                "Ni nove prijave / novega profila — uporablja odprt Minimax.\n\n"
                "Konto in osnove: iz vsake KPR listine (__konto__).\n\n"
                "Da = Nov odhodek + konto + osnove + Potrdi\n"
                "Ne = samo odhodek/osnove (brez Potrdi)\n"
                "Prekliči = ne zaženi"
            ),
            parent=self.root,
        )
        if choice is None:
            return "break"
        auto_confirm = bool(choice)

        def task() -> list[dict[str, Any]]:
            def progress(text: str) -> None:
                self.root.after(0, lambda t=text: self.api_status_var.set(t))

            return minimax_browser.confirm_pr_drafts_batch(
                items_payload,
                auto_confirm=auto_confirm,
                progress=progress,
                prefer_cdp=True,
                prefer_extension=True,
                expected_org_name=organisation_name,
                expected_org_id=organisation_id,
            )

        def success(results: Any) -> None:
            rows = list(results or [])
            ok_n = sum(1 for r in rows if r.get("ok"))
            conf_n = sum(1 for r in rows if r.get("confirmed"))
            fail = [r for r in rows if not r.get("ok")]
            self._record_action(
                "browser_batch_pr",
                f"{ok_n}/{len(rows)} ok, {conf_n} potrjenih; confirm={auto_confirm}",
            )
            self.api_status_var.set(
                f"Serija PR: {ok_n}/{len(rows)} uspešnih, {conf_n} potrjenih."
            )
            lines = [
                f"{r.get('ref') or r.get('received_invoice_id')}: "
                f"konto {r.get('expense_account') or '?'} — "
                f"{'OK' if r.get('ok') else 'NAPAKA'}"
                + (", potrjen" if r.get("confirmed") else "")
                + (f" · {r.get('message')}" if r.get("message") else "")
                for r in rows[:40]
            ]
            if fail and any(r.get("need_login") for r in fail):
                if messagebox.askyesno(
                    "Potrebna je prijava",
                    "Playwright seja ni prijavljena.\n\nNaj odprem prijavo?",
                    parent=self.root,
                ):
                    self.login_minimax_browser()
            messagebox.showinfo(
                "Serija PR — rezultat",
                "\n".join(lines) if lines else "Brez rezultatov.",
                parent=self.root,
            )

        self._run_api_worker(
            task,
            success,
            busy_text=(
                f"Serija {len(items_payload)} PR: konto iz listine + osnove"
                + (" + Potrdi" if auto_confirm else "")
                + " (Playwright, ista firma)…"
            ),
        )
        return "break"

    def _confirm_pr_chrome_pack(
        self,
        *,
        invoice: str,
        organisation_name: str,
        account: str,
        metrics: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Mini forma: 3 sloti (konto, osnova 22%, osnova 9,5%) + potrditev."""
        window = tk.Toplevel(self.root)
        window.title("KIR/KPR paketek za Chrome")
        window.transient(self.root)
        window.grab_set()
        window.configure(bg=self.colors["bg"])
        window.geometry("460x420")
        window.minsize(420, 380)

        result: dict[str, Any] = {"cancelled": True}

        header = ttk.Frame(window, style="Header.TFrame", padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Potrdi 3 vrednosti za Minimax", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=f"PR {invoice} · {organisation_name}",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(window, style="Panel.TFrame", padding=(18, 14))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(
            body,
            text="Iz KPR (osnova = DDV ÷ stopnja). Popravi po potrebi, nato odpri.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        account_var = tk.StringVar(value=str(account or "4190"))
        # Vedno pokaži vse tri osnove (tudi 0,00) — uporabnik odkljuka, če ne gre v paketek.
        base22_var = tk.StringVar(value=format_money(metrics.get("base_22") or 0))
        base95_var = tk.StringVar(value=format_money(metrics.get("base_95") or 0))
        base5_var = tk.StringVar(value=format_money(metrics.get("base_5") or 0))
        use22_var = tk.BooleanVar(value=True)
        use95_var = tk.BooleanVar(value=True)
        use5_var = tk.BooleanVar(value=True)

        def row_field(
            grid_row: int,
            label: str,
            variable: tk.StringVar,
            *,
            enabled_var: tk.BooleanVar | None = None,
            hint: str = "",
        ) -> None:
            if enabled_var is not None:
                ttk.Checkbutton(body, text=label, variable=enabled_var).grid(
                    row=grid_row, column=0, sticky="w", pady=6
                )
            else:
                ttk.Label(body, text=label, style="Panel.TLabel").grid(
                    row=grid_row, column=0, sticky="w", pady=6
                )
            entry = ttk.Entry(body, textvariable=variable, width=18)
            entry.grid(row=grid_row, column=1, sticky="ew", padx=(12, 0), pady=6)
            if hint:
                ttk.Label(body, text=hint, style="Muted.TLabel").grid(
                    row=grid_row + 1, column=1, sticky="w", padx=(12, 0)
                )

        row_field(1, "1. Konto odhodka", account_var)
        vat22 = metrics.get("vat_22") or 0
        vat95 = metrics.get("vat_95") or 0
        vat5 = metrics.get("vat_5") or 0
        row_field(
            3,
            "2. Osnova 22%",
            base22_var,
            enabled_var=use22_var,
            hint=f"DDV 22% = {format_money(vat22)} EUR",
        )
        row_field(
            5,
            "3. Osnova 9,5%",
            base95_var,
            enabled_var=use95_var,
            hint=f"DDV 9,5% = {format_money(vat95)} EUR",
        )
        row_field(
            7,
            "Osnova 5%",
            base5_var,
            enabled_var=use5_var,
            hint=f"DDV 5% = {format_money(vat5)} EUR",
        )

        ttk.Label(
            body,
            text=(
                f"KPR neto {format_money(metrics.get('net') or 0)} EUR · "
                f"DDV skupaj {format_money(metrics.get('reported_vat') or 0)} EUR"
            ),
            style="Muted.TLabel",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 0))

        buttons = ttk.Frame(window, style="Panel.TFrame", padding=(18, 10))
        buttons.pack(fill="x")

        def parse_money(text: str) -> Decimal:
            raw = str(text or "").strip()
            if not raw:
                return Decimal("0")
            return core.decimal_value(raw)

        def finish(confirm: bool) -> None:
            try:
                code = self._validated_account_code(account_var.get())
                b22 = parse_money(base22_var.get()) if use22_var.get() else Decimal("0")
                b95 = parse_money(base95_var.get()) if use95_var.get() else Decimal("0")
                b5 = parse_money(base5_var.get()) if use5_var.get() else Decimal("0")
            except (core.KirkprError, Exception) as exc:
                messagebox.showerror("Paketek", str(exc), parent=window)
                return
            result.clear()
            result.update(
                {
                    "cancelled": False,
                    "account": code,
                    "base_22": b22,
                    "base_95": b95,
                    "base_5": b5,
                    "confirm": confirm,
                }
            )
            window.destroy()

        ttk.Button(buttons, text="Prekliči", style="Danger.TButton", command=window.destroy).pack(side="left")
        ttk.Button(
            buttons,
            text="Odpri (ročni Potrdi)",
            command=lambda: finish(False),
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            buttons,
            text="Odpri + Potrdi",
            style="Success.TButton",
            command=lambda: finish(True),
        ).pack(side="right")

        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.wait_window()
        if result.get("cancelled", True):
            return None
        return result

    def refresh_minimax_invoice_statuses(
        self,
        show_message: bool = True,
        after: Callable[[], None] | None = None,
    ) -> str:
        """Osveži stolpec Status v IR/PR iz Minimax API za aktivno podjetje."""
        if not self.dataset or not self.minimax_client or not self.minimax_client.organisation_id:
            if show_message:
                messagebox.showinfo(
                    "Statusi Minimax",
                    "Najprej odprite KIR/KPR podatke in povežite Minimax API z izbranim podjetjem.",
                    parent=self.root,
                )
            if after:
                after()
            return "break"
        if not self._active_org_matches_api(show_error=show_message):
            if after:
                after()
            return "break"

        client = self.minimax_client
        dataset = self.dataset
        organisation_id = str(client.organisation_id or "")
        date_from, date_to = self._filter_iso_bounds()
        exact_records: list[tuple[str, str, str]] = []
        for book, rows in (("IR", dataset.kir), ("PR", dataset.kpr)):
            for row in rows:
                if not self._row_in_period(book, row):
                    continue
                record_id = self._sent_invoice_id(book, row)
                if record_id:
                    exact_records.append((book, record_id, str(row.get("P3") or "")))

        def task() -> tuple[dict[str, dict[str, dict[str, str]]], list[str], bool]:
            catalog: dict[str, dict[str, dict[str, str]]] = {
                "IR": {"by_reference": {}, "by_id": {}, "by_reference_id": {}},
                "PR": {"by_reference": {}, "by_id": {}, "by_reference_id": {}},
            }
            warnings: list[str] = []
            any_success = False
            try:
                loaded = client.invoice_status_catalog(date_from=date_from, date_to=date_to)
                for book in ("IR", "PR"):
                    for index_name in ("by_reference", "by_id", "by_reference_id"):
                        values = loaded.get(book, {}).get(index_name, {})
                        if isinstance(values, Mapping):
                            catalog[book][index_name].update(
                                {str(key): str(value) for key, value in values.items()}
                            )
                any_success = True
            except Exception as exc:
                warnings.append(f"Seznama računov ni bilo mogoče prebrati: {exc}")

            seen: set[tuple[str, str]] = set()
            for book, record_id, fallback_reference in exact_records:
                marker = (book, record_id)
                if marker in seen:
                    continue
                seen.add(marker)
                if record_id in catalog[book]["by_id"]:
                    continue
                try:
                    status, api_reference = client.invoice_status_by_id(book, record_id)
                    catalog[book]["by_id"][record_id] = status
                    reference = minimax_api.normal_invoice_reference(api_reference or fallback_reference)
                    if reference:
                        catalog[book]["by_reference"][reference] = status
                        catalog[book]["by_reference_id"][reference] = record_id
                    any_success = True
                except Exception as exc:
                    # Zbrisani ID v Minimaxu — ne štej kot fatalno napako.
                    warnings.append(f"{book} ID {record_id}: ni več v Minimaxu ({exc})")
            return catalog, warnings, any_success

        def success(result: Any) -> None:
            catalog, warnings, any_success = result
            self.minimax_invoice_status_catalog = catalog
            self.minimax_invoice_status_org = organisation_id
            self.minimax_invoice_status_checked = bool(any_success)
            self.api_view_mode = "minimax"
            if any_success:
                self._reconcile_sent_map_with_minimax()
            self._populate_trees()
            diff = self.api_diff_summary or {}
            ir_count = max(len(catalog["IR"]["by_reference"]), len(catalog["IR"]["by_id"]))
            pr_count = max(len(catalog["PR"]["by_reference"]), len(catalog["PR"]["by_id"]))
            if any_success:
                message = (
                    f"Minimax pogled: IR {ir_count}, PR {pr_count}. "
                    f"Samo v programu: {len(diff.get('only_program') or [])}, "
                    f"že v Minimaxu: {len(diff.get('in_both') or [])}, "
                    f"odstranjenih lokalnih sledi: {len(diff.get('removed') or [])}."
                )
                if warnings:
                    message += f" Opozorila: {len(warnings)}."
                self.api_status_var.set(message)
                self.status_var.set(message)
                if show_message:
                    self._record_action("api_statuses", f"IR {ir_count}; PR {pr_count}")
                    self._show_api_diff_dialog(message, warnings)
            else:
                message = "Povezava deluje, vendar statusov računov ni bilo mogoče prebrati."
                self.api_status_var.set(message)
                self.status_var.set(message)
                if show_message:
                    detail = "\n".join(warnings[:5])
                    messagebox.showwarning(
                        "Statusi Minimax",
                        message + (f"\n\n{detail}" if detail else ""),
                        parent=self.root,
                    )
            if after:
                after()

        self._run_api_worker(
            task,
            success,
            busy_text=f"Preverjam statuse IR in PR v Minimaxu za obdobje {date_from}–{date_to} …",
        )
        return "break"

    def download_selected_invoice_attachments(self) -> str:
        """Prenese priponke izbranega PR po njegovem dejanskem Minimax API ID-ju."""
        selected = self.api_tree.selection() if hasattr(self, "api_tree") else ()
        if len(selected) != 1:
            messagebox.showinfo("Priponka PR", "Izberite natanko en prejeti račun.", parent=self.root)
            return "break"
        item = selected[0]
        book, row = self._api_item_row(item)
        if book != "PR":
            messagebox.showinfo("Priponka PR", "Priponke dobavitelja so na voljo pri prejetem računu.", parent=self.root)
            return "break"
        if not self.minimax_client or not self.minimax_client.organisation_id:
            messagebox.showinfo("Priponka PR", "Najprej povežite Minimax API.", parent=self.root)
            return "break"
        if not self._active_org_matches_api(show_error=True):
            return "break"
        record_id = self._sent_invoice_id("PR", row)
        if not record_id:
            messagebox.showwarning(
                "Priponka PR",
                "Za izbrani PR ni shranjen dejanski ReceivedInvoiceId. Najprej osvežite statuse ali ustvarite PR prek API.",
                parent=self.root,
            )
            return "break"
        partner = str(row.get("P6") or "Dobavitelj").strip()
        reference = str(row.get("P3") or record_id).strip()
        profile = self._profile_config()
        initial = str(profile.get("last_output_dir") or self.config.get("last_output_dir") or self.dataset.source_path.parent)
        selected_dir = filedialog.askdirectory(
            parent=self.root,
            title=f"Mapa za priponke PR {reference} — {partner}",
            initialdir=initial,
        )
        if not selected_dir:
            return "break"
        target_dir = Path(selected_dir)
        client = self.minimax_client

        def task() -> list[Path]:
            attachments = client.invoice_attachments("PR", record_id)
            if not attachments:
                raise minimax_api.MinimaxApiError(
                    f"PR {reference} ({partner}) v Minimaxu nima priponk. "
                    "Za neposredni IR QUICK M.B. mora biti njihova organizacija dostopna z istim API pooblastilom."
                )
            written: list[Path] = []
            target_dir.mkdir(parents=True, exist_ok=True)
            for attachment in attachments:
                filename, data = client.attachment_file(attachment)
                destination = target_dir / filename
                counter = 2
                while destination.exists():
                    destination = target_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
                    counter += 1
                destination.write_bytes(data)
                written.append(destination)
            return written

        def success(result: Any) -> None:
            files = [Path(path) for path in (result or [])]
            profile["last_output_dir"] = str(target_dir)
            self.config["last_output_dir"] = str(target_dir)
            self._save_session_state()
            message = f"Prenesenih priponk: {len(files)} za PR {reference} ({partner})."
            self.api_status_var.set(message)
            self.status_var.set(message)
            messagebox.showinfo("Priponke PR", message + "\n\n" + "\n".join(str(path) for path in files), parent=self.root)

        self._run_api_worker(task, success, busy_text=f"Prenašam priponke PR {reference} — {partner} …")
        return "break"

    def import_attachment_from_folder(self) -> str:
        """Kopira lokalne priponke v dinamično mapo izbranega podjetja in PR."""
        selected = self.api_tree.selection() if hasattr(self, "api_tree") else ()
        if len(selected) != 1 or self.api_tree.set(selected[0], "book") != "PR":
            messagebox.showinfo("Priponka iz mape", "Najprej označite natanko en PR.", parent=self.root)
            return "break"
        _book, row = self._api_item_row(selected[0])
        sources = filedialog.askopenfilenames(parent=self.root, title="Izberite priponke", filetypes=[("Vse datoteke", "*.*")])
        if not sources:
            return "break"
        start, end = self._filter_iso_bounds()
        paths = company_registry.company_paths(
            self.active_company or {},
            start,
            end,
            trops_root=self._trops_root(),
        )
        reference = company_registry.safe_name(row.get("P3"), "PR")
        partner = company_registry.safe_name(row.get("P6"), "dobavitelj")
        destination = paths.workspace / "Priponke" / f"{reference}_{partner}"
        destination.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        for source in map(Path, sources):
            target = destination / source.name
            counter = 2
            while target.exists():
                target = destination / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            shutil.copy2(source, target)
            copied.append(target)
        message = f"V dinamično mapo je kopiranih {len(copied)} priponk."
        self.api_status_var.set(message)
        messagebox.showinfo("Priponka iz mape", message + f"\n\n{destination}", parent=self.root)
        return "break"

    def download_supplier_issued_attachment(self) -> str:
        """Prenese PDF iz IR dobaviteljeve organizacije prek istega API pooblastila."""
        selected = self.api_tree.selection() if hasattr(self, "api_tree") else ()
        if len(selected) != 1 or self.api_tree.set(selected[0], "book") != "PR":
            messagebox.showinfo("Dobaviteljev IR", "Najprej označite en PR dobavitelja QUICK M.B.", parent=self.root)
            return "break"
        _book, row = self._api_item_row(selected[0])
        supplier = str(row.get("P6") or "").strip()
        if "QUICK" not in supplier.upper():
            messagebox.showwarning("Dobaviteljev IR", "Izbrani PR ni dobavitelja QUICK M.B.", parent=self.root)
            return "break"
        if not self.minimax_client or not self.minimax_client.organisation_id or not self.dataset:
            messagebox.showinfo("Dobaviteljev IR", "Najprej povežite Minimax API za KLUG.", parent=self.root)
            return "break"
        metrics = core.pr_metrics(row)
        customer_name = company_registry.company_name(self.active_company or {})
        customer_tax = company_registry.company_tax_number(self.active_company or {})
        start, end = self._filter_iso_bounds()
        company_paths = company_registry.company_paths(
            self.active_company or {},
            start,
            end,
            trops_root=self._trops_root(),
        )
        reference = company_registry.safe_name(row.get("P3"), "PR")
        target_dir = company_paths.attachments / f"{reference}_QUICK_MB"
        client = self.minimax_client

        def task() -> tuple[dict[str, Any], list[Path]]:
            invoice, attachments = client.supplier_issued_invoice_attachments(
                supplier_name=supplier,
                customer_name=customer_name,
                customer_tax_id=customer_tax,
                gross_total=Decimal(metrics["gross"]),
                invoice_date=str(row.get("P5") or row.get("P2") or ""),
                date_from=start,
                date_to=end,
            )
            if not attachments:
                raise minimax_api.MinimaxApiError("Najdeni IR QUICK M.B. nima API priponke/PDF.")
            target_dir.mkdir(parents=True, exist_ok=True)
            written: list[Path] = []
            for attachment in attachments:
                filename, data = client.attachment_file(attachment)
                target = target_dir / filename
                counter = 2
                while target.exists():
                    target = target_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
                    counter += 1
                target.write_bytes(data)
                written.append(target)
            return invoice, written

        def success(result: Any) -> None:
            invoice, files = result
            number = minimax_api.supplier_invoice_number(invoice) or str(invoice.get("IssuedInvoiceId") or "")
            message = f"IR QUICK M.B. {number}: prenesenih priponk {len(files)}."
            self.api_status_var.set(message)
            self.status_var.set(message)
            self._profile_config()["last_output_dir"] = str(target_dir)
            self.config["last_output_dir"] = str(target_dir)
            self._save_session_state()
            messagebox.showinfo(
                "QUICK M.B. → KLUG PDF",
                message + "\n\nSamodejno shranjeno v:\n" + str(target_dir) + "\n\n" + "\n".join(str(path) for path in files),
                parent=self.root,
            )

        self._run_api_worker(task, success, busy_text="Iščem IR QUICK M.B. za KLUG in prenašam PDF …")
        return "break"

    def attach_supplier_pdf_to_selected_received_invoice(self) -> str:
        """PDF iz QUICK M.B. IR neposredno doda na izbrani KLUG PR prek API."""
        selected = self.api_tree.selection() if hasattr(self, "api_tree") else ()
        if len(selected) != 1 or self.api_tree.set(selected[0], "book") != "PR":
            messagebox.showinfo("QUICK PDF → PR", "Najprej označite natanko en PR.", parent=self.root)
            return "break"
        item = selected[0]
        _book, row = self._api_item_row(item)
        supplier = str(row.get("P6") or "").strip()
        if "QUICK" not in supplier.upper():
            messagebox.showwarning("QUICK PDF → PR", "Izbrani PR ni dobavitelja QUICK M.B.", parent=self.root)
            return "break"
        if not self.minimax_client or not self.minimax_client.organisation_id or not self.dataset:
            messagebox.showinfo("QUICK PDF → PR", "Najprej povežite Minimax API za izbrano podjetje.", parent=self.root)
            return "break"
        if not self._active_org_matches_api(show_error=True):
            return "break"

        client = self.minimax_client
        target_org = int(client.organisation_id)
        metrics = core.pr_metrics(row)
        reference = str(row.get("P3") or "PR").strip()
        customer_name = company_registry.company_name(self.active_company or {})
        customer_tax = company_registry.company_tax_number(self.active_company or {})
        stored_target_id = self._sent_invoice_id("PR", row)

        def prepare() -> dict[str, Any]:
            if stored_target_id:
                target_id = int(stored_target_id)
                target = client.get(f"orgs/{target_org}/receivedinvoices/{target_id}")
                if not isinstance(target, Mapping):
                    raise minimax_api.MinimaxApiError(f"Minimax ni vrnil PR ID {target_id}.")
                target = dict(target)
            else:
                date_from, date_to = self._filter_iso_bounds()
                target = client.find_received_invoice(
                    document_reference=reference,
                    supplier_name=supplier,
                    gross_total=Decimal(metrics["gross"]),
                    invoice_date=str(row.get("P5") or row.get("P2") or ""),
                    date_from=date_from,
                    date_to=date_to,
                )
                target_id = minimax_api._record_id(target) or 0
            if not target_id:
                raise minimax_api.MinimaxApiError("Ciljni PR nima veljavnega ReceivedInvoiceId.")

            date_from, date_to = self._filter_iso_bounds()
            invoice, source_attachments = client.supplier_issued_invoice_attachments(
                supplier_name=supplier,
                customer_name=customer_name,
                customer_tax_id=customer_tax,
                gross_total=Decimal(metrics["gross"]),
                invoice_date=str(row.get("P5") or row.get("P2") or ""),
                date_from=date_from,
                date_to=date_to,
            )
            pdfs: list[tuple[str, bytes, str]] = []
            for attachment in source_attachments:
                filename, data = client.attachment_file(attachment)
                mime = str(attachment.get("AttachmentMimeType") or "application/pdf")
                if Path(filename).suffix.casefold() == ".pdf" or mime.casefold() == "application/pdf":
                    pdfs.append((filename, data, mime))
            if not pdfs:
                raise minimax_api.MinimaxApiError("Izvorni IR QUICK M.B. nima PDF-priponke.")

            client.select_organisation(target_org)
            existing = client.invoice_attachments("PR", target_id)
            existing_names = {
                str(a.get("AttachmentFileName") or a.get("FileName") or "").strip().casefold()
                for a in existing
            }
            new_pdfs = [pdf for pdf in pdfs if pdf[0].strip().casefold() not in existing_names]
            return {
                "target_id": target_id,
                "target_status": minimax_api.invoice_record_status(target),
                "source_number": minimax_api.supplier_invoice_number(invoice),
                "pdfs": new_pdfs,
                "already_present": len(pdfs) - len(new_pdfs),
            }

        def prepared(result: Any) -> None:
            data = dict(result or {})
            pdfs = list(data.get("pdfs") or [])
            if not pdfs:
                message = (
                    f"PDF računa {data.get('source_number') or ''} je na PR {reference} že dodan; "
                    "podvojena priponka ni bila ustvarjena."
                )
                self.api_status_var.set(message)
                messagebox.showinfo("QUICK PDF → PR", message, parent=self.root)
                return
            filenames = "\n".join(f"• {pdf[0]}" for pdf in pdfs)
            confirmed = messagebox.askyesno(
                "Potrditev dodajanja priponke",
                f"Izvorni IR QUICK M.B.: {data.get('source_number')}\n"
                f"Ciljni KLUG PR: {reference}\n"
                f"ReceivedInvoiceId: {data.get('target_id')}\n"
                f"Status: {data.get('target_status')}\n\n"
                f"Na dokument bo dodano:\n{filenames}\n\nNadaljujem?",
                parent=self.root,
            )
            if not confirmed:
                self.api_status_var.set("Dodajanje PDF-priponke je preklicano.")
                return

            def upload() -> dict[str, Any]:
                client.select_organisation(target_org)
                for filename, content, mime in pdfs:
                    client.add_invoice_attachment(
                        "PR", data["target_id"], filename=filename, data=content, mime_type=mime
                    )
                verified = client.invoice_attachments("PR", data["target_id"])
                verified_names = {
                    str(a.get("AttachmentFileName") or a.get("FileName") or "").strip().casefold()
                    for a in verified
                }
                missing = [name for name, _content, _mime in pdfs if name.casefold() not in verified_names]
                if missing:
                    raise minimax_api.MinimaxApiError(
                        "API po prenosu ni potrdil priponk: " + ", ".join(missing)
                    )
                return {"count": len(pdfs), "names": [pdf[0] for pdf in pdfs]}

            def uploaded(upload_result: Any) -> None:
                names = list((upload_result or {}).get("names") or [])
                message = (
                    f"Na PR {reference} je neposredno prek API dodan QUICK PDF: "
                    + ", ".join(names)
                )
                self.api_status_var.set(message)
                self.status_var.set(message)
                self._record_action("api_attachment", f"PR {reference}; {', '.join(names)}")
                messagebox.showinfo("QUICK PDF → PR", message, parent=self.root)

            self._run_api_worker(upload, uploaded, busy_text=f"Dodajam QUICK PDF na PR {reference} …")

        self._run_api_worker(
            prepare,
            prepared,
            busy_text=f"Preverjam QUICK PDF in ciljni PR {reference} …",
        )
        return "break"

    def show_latest_confirmed_received_invoice(self) -> str:
        """Prek API pokaže zadnji potrjeni PR izbranega podjetja in njegov pravi ID."""
        if not self.minimax_client or not self.minimax_client.organisation_id:
            messagebox.showinfo(
                "Minimax API",
                "Najprej se povežite z izbranim podjetjem.",
                parent=self.root,
            )
            return "break"
        if not self._active_org_matches_api():
            return "break"

        def task() -> Any:
            assert self.minimax_client is not None
            return self.minimax_client.latest_confirmed_received_invoice()

        def success(record: Any) -> None:
            if not record:
                messagebox.showinfo(
                    "Zadnji potrjeni PR",
                    "Minimax API za izbrano podjetje ni vrnil potrjenega prejetega računa.",
                    parent=self.root,
                )
                return
            received_id = minimax_api.MinimaxClient.received_invoice_id(record)
            reference = str(
                record.get("InvoiceNumber")
                or record.get("DocumentNumber")
                or record.get("Reference")
                or ""
            ).strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(str(received_id or ""))
            self.root.update_idletasks()
            self.api_status_var.set(
                f"Zadnji potrjeni PR: {reference or 'brez reference'} • ReceivedInvoiceId {received_id}; ID je kopiran."
            )
            messagebox.showinfo(
                "Zadnji potrjeni PR",
                (
                    f"Listina: {reference or '—'}\n"
                    f"ReceivedInvoiceId: {received_id or '—'}\n"
                    f"Status: {record.get('Status') or 'P'}\n\n"
                    "ID je kopiran v odložišče. Naslednjega ID-ja program ne ugiba kot +1; "
                    "za nov osnutek uporabi ID iz njegovega API odgovora."
                ),
                parent=self.root,
            )

        self._run_api_worker(task, success, busy_text="Prek API iščem zadnji potrjeni prejeti račun …")
        return "break"

    def show_api_result_details(self, event: tk.Event | None = None) -> str:
        item = self.api_tree.identify_row(event.y) if event is not None else ""
        if item:
            self.api_tree.selection_set(item)
            self.api_tree.focus(item)
        else:
            item = self.api_tree.focus() or next(iter(self.api_tree.selection()), "")
        if not item:
            messagebox.showinfo("API rezultat", "Najprej izberite vrstico.", parent=self.root)
            return "break"
        book = self.api_tree.set(item, "book")
        invoice = self.api_tree.set(item, "invoice")
        state = self.api_tree.set(item, "api_status")
        detail = self.api_tree.set(item, "detail") or "Ni dodatnih podatkov."

        window = tk.Toplevel(self.root)
        window.title(f"Minimax API rezultat — {book} {invoice}")
        window.transient(self.root)
        window.geometry("940x390")
        window.minsize(680, 300)
        window.configure(bg=self.colors["bg"])
        header = ttk.Frame(window, style="Header.TFrame", padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text=f"{book} {invoice} • {state}", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Celoten odgovor Minimax API; besedilo lahko kopirate za diagnostiko.",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        text_box = tk.Text(
            window,
            wrap="word",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            padx=16,
            pady=14,
            font=("Consolas", 10),
        )
        text_box.pack(fill="both", expand=True, padx=14, pady=14)
        text_box.insert("1.0", detail)
        buttons = ttk.Frame(window, style="Panel.TFrame", padding=(14, 0, 14, 14))
        buttons.pack(fill="x")

        def copy_detail() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(detail)
            self.status_var.set("Celoten Minimax API rezultat je kopiran v odložišče.")

        ttk.Button(buttons, text="Zapri", command=window.destroy).pack(side="right")
        ttk.Button(buttons, text="Kopiraj rezultat", style="Accent.TButton", command=copy_detail).pack(
            side="right", padx=(0, 8)
        )
        text_box.focus_set()
        return "break"

    def select_api_rows(self, book: str) -> str:
        requested = str(book or "ALL").upper()
        if requested not in {"ALL", "IR", "PR"}:
            requested = "ALL"
        if self.api_view_filter != requested:
            self.set_api_view_filter(requested)
        selected = []
        for item in self.api_tree.get_children():
            if requested != "ALL" and self.api_tree.set(item, "book") != requested:
                continue
            if self.api_tree.set(item, "api_status") == "ODDANO":
                continue
            # Ne izberi vrstic, ki že obstajajo v Minimaxu (po listini).
            try:
                row_book, row = self._api_item_row(item)
            except Exception:
                continue
            if self.minimax_invoice_status_checked and self._row_exists_in_minimax(row_book, row):
                continue
            selected.append(item)
        # Treeview.selection_set ohrani vrstni red drevesa (že urejen po listini).
        self.api_tree.selection_set(selected)
        self._on_api_tree_selection()
        return "break"

    def show_json_api_view(self) -> None:
        """Lokalni JSON/KIR-KPR pogled — podatkov ne spreminja."""
        if not self.dataset:
            messagebox.showinfo("JSON pogled", "Najprej odprite KIR/KPR podatke.", parent=self.root)
            return
        self.api_view_mode = "json"
        self._populate_trees()
        payload = self._local_json_view_payload()
        self._show_text_dialog(
            "JSON pogled (lokalni podatki)",
            json.dumps(payload, ensure_ascii=False, indent=2),
            note="Samo za branje. Podatki v programu in Minimaxu se ne spremenijo.",
        )
        self.api_status_var.set("JSON pogled: prikaz lokalnih KIR/KPR podatkov (brez sprememb).")
        self._record_action("api_validate", "JSON pogled")

    def show_minimax_api_view(self) -> None:
        """Prebere Minimax, zabeleži Status/API stanje in pokaže razliko."""
        if not self.dataset:
            messagebox.showinfo("Minimax pogled", "Najprej odprite KIR/KPR podatke.", parent=self.root)
            return

        def after_connect() -> None:
            self.refresh_minimax_invoice_statuses(show_message=True)

        expected = company_registry.company_org_id(self.active_company or {})
        connected = bool(
            self.minimax_client
            and self.minimax_client.organisation_id
            and str(self.minimax_client.organisation_id) == expected
        )
        if connected:
            after_connect()
            return
        existing_label = next(
            (label for label, organisation_id in self.minimax_organisations.items() if str(organisation_id) == expected),
            "",
        )
        if self.minimax_client and existing_label:
            self.api_org_var.set(existing_label)
            self._on_api_org_selected(after_connect=after_connect)
        else:
            self.connect_minimax_api(after_connect=after_connect)

    def _local_json_view_payload(self) -> dict[str, Any]:
        assert self.dataset is not None
        rows = []
        for book, source in (("IR", self.dataset.kir), ("PR", self.dataset.kpr)):
            for row in source:
                if not self._row_in_period(book, row):
                    continue
                if book == "IR" and core.ir_metrics(row, self.dataset.kpr)["tax_only"]:
                    continue
                booking = row_booking_date(book, row)
                rows.append(
                    {
                        "book": book,
                        "listina": str(row.get("P3") or ""),
                        "datum": booking.isoformat() if booking else "",
                        "partner": str(row.get("P5") if book == "IR" else row.get("P6") or ""),
                        "konto": str(row.get("__konto__") or ("7601" if book == "IR" else "4190")),
                        "api_local_sent": bool(self._sent_invoice_info(book, row)),
                    }
                )
        rows.sort(key=lambda item: (0 if item["book"] == "IR" else 1, listina_sort_key(item["listina"])))
        return {
            "view": "json",
            "source": str(self.dataset.source_path),
            "source_period_from": self.dataset.period_from,
            "source_period_to": self.dataset.period_to,
            "filter_from": self.filter_from_date.isoformat(),
            "filter_to": self.filter_to_date.isoformat(),
            "count": len(rows),
            "rows": rows,
        }

    def _show_api_diff_dialog(self, headline: str, warnings: list[str] | None = None) -> None:
        diff = self.api_diff_summary or {}
        only_program = list(diff.get("only_program") or [])
        in_both = list(diff.get("in_both") or [])
        removed = list(diff.get("removed") or [])
        lines = [
            headline,
            "",
            "RAZLIKA: program (JSON/KIR-KPR) ↔ Minimax",
            f"• Samo v programu (ni v Minimaxu): {len(only_program)}",
            f"• V obeh (listina že obstaja): {len(in_both)}",
            f"• Lokalna ODDANO sled odstranjena (v Minimaxu zbrisano): {len(removed)}",
            "",
        ]
        if removed:
            lines.append("Zbrisano v Minimaxu / odstranjena lokalna sled:")
            lines.extend(f"  - {item}" for item in removed[:40])
            if len(removed) > 40:
                lines.append(f"  … še {len(removed) - 40}")
            lines.append("")
        if only_program:
            lines.append("Pripravljeno za ustvarjanje (ni v Minimaxu):")
            lines.extend(f"  - {item}" for item in only_program[:40])
            if len(only_program) > 40:
                lines.append(f"  … še {len(only_program) - 40}")
            lines.append("")
        if in_both:
            lines.append("Že v Minimaxu (listina se ne sme podvajati):")
            lines.extend(f"  - {item}" for item in in_both[:40])
            if len(in_both) > 40:
                lines.append(f"  … še {len(in_both) - 40}")
            lines.append("")
        if warnings:
            lines.append("Opozorila:")
            lines.extend(f"  - {item}" for item in warnings[:12])
        self._show_text_dialog("Minimax pogled — razlika", "\n".join(lines))

    def _show_text_dialog(self, title: str, text: str, *, note: str = "") -> None:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.geometry("820x560")
        window.minsize(640, 420)
        window.configure(bg=self.colors["bg"])
        frame = ttk.Frame(window, style="Card.TFrame", padding=(14, 12))
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(frame, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        if note:
            ttk.Label(frame, text=note, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        box = tk.Text(frame, wrap="word", font=("Consolas", 10), **gui_style.text_area_kwargs())
        box.pack(fill="both", expand=True)
        box.insert("1.0", text)
        box.configure(state="disabled")
        ttk.Button(frame, text="Zapri", command=window.destroy).pack(anchor="e", pady=(10, 0))

    def transfer_api_group(self, book: str) -> None:
        """Uskladi z Minimaxom, izbere samo manjkajoče listine, predpreveri in odda."""
        if self.api_busy:
            return
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR podatke.", parent=self.root)
            return
        if book not in {"IR", "PR", "ALL"}:
            return

        def validate_and_offer_send() -> None:
            self.select_api_rows(book)
            if not self.api_tree.selection():
                label = "IR" if book == "IR" else "PR" if book == "PR" else "IR ali PR"
                messagebox.showinfo(
                    "Ni računov za prenos",
                    f"Ni računov skupine {label} za ustvarjanje.\n\n"
                    "Vsi imajo listino že v Minimaxu ali so označeni ODDANO.\n"
                    "Uporabi »Minimax pogled« za razliko program ↔ Minimax.",
                    parent=self.root,
                )
                return
            self.validate_api_selection(
                on_complete=lambda all_ok: self.send_api_selection() if all_ok else None,
            )

        def after_sync() -> None:
            validate_and_offer_send()

        def ensure_minimax_view_then_send() -> None:
            # Vedno najprej uskladi živo stanje Minimaxa, nato prenesi razliko.
            self.refresh_minimax_invoice_statuses(show_message=False, after=after_sync)

        expected = company_registry.company_org_id(self.active_company or {})
        connected = bool(
            self.minimax_client
            and self.minimax_client.organisation_id
            and str(self.minimax_client.organisation_id) == expected
        )
        if connected:
            ensure_minimax_view_then_send()
            return

        existing_label = next(
            (label for label, organisation_id in self.minimax_organisations.items() if str(organisation_id) == expected),
            "",
        )
        if self.minimax_client and existing_label:
            self.api_org_var.set(existing_label)
            self._on_api_org_selected(after_connect=ensure_minimax_view_then_send)
        else:
            self.connect_minimax_api(after_connect=ensure_minimax_view_then_send)

    def validate_api_selection(self, on_complete: Callable[[bool], None] | None = None) -> None:
        if not self.dataset or not self.minimax_client or not self.minimax_client.organisation_id:
            messagebox.showinfo("Minimax API", "Najprej odprite podatke in povežite Minimax API.", parent=self.root)
            return
        if not self._active_org_matches_api():
            return
        selected = [entry for entry in self._selected_api_rows() if self.api_tree.set(entry[0], "api_status") != "ODDANO"]
        if not selected:
            messagebox.showinfo("Ni izbire", "Izberite enega ali več še neoddanih računov.", parent=self.root)
            return
        if not self.save_accounts(quiet=True):
            return
        for item, _book, _row in selected:
            self.api_tree.set(item, "api_status", "PREVERJAM")
            self.api_tree.set(item, "detail", "Preverjam partnerja, konte, DDV stopnje in ravnotežje …")
        status = self._api_journal_status()
        mode = self._api_transfer_mode()
        options = self._api_transfer_options()

        def task() -> list[dict[str, str]]:
            assert self.minimax_client is not None and self.dataset is not None
            self.log.info(
                "API predpreverjanje: %s računov, način=%s, status=%s, org=%s",
                len(selected),
                mode,
                status,
                self.minimax_client.organisation_id,
            )
            return self.minimax_client.validate_rows(
                self.dataset,
                [(book, row) for _item, book, row in selected],
                status=status,
                mode=mode,
                options=options,
            )

        def success(results: Any) -> None:
            ok = 0
            for (item, _book, _row), result in zip(selected, results):
                state = result["status"]
                self.api_tree.set(item, "api_status", state)
                self.api_tree.set(item, "detail", result["detail"])
                self.api_tree.item(item, tags=(("api_ok",) if state == "OK" else ("api_error",)))
                ok += state == "OK"
                if state != "OK":
                    self.log.warning(
                        "Predpreverjanje %s: %s",
                        item,
                        kirkpr_logging.safe_detail(result.get("detail")),
                    )
            self.api_status_var.set(f"Predpreverjanje: {ok} od {len(results)} računov je pripravljenih za oddajo.")
            self._record_action("api_validate", f"{ok}/{len(results)} pripravljeno")
            self.status_var.set(f"Minimax API predpreverjanje: {ok}/{len(results)} pripravljeno.")
            self.log.info("API predpreverjanje končano: %s/%s OK", ok, len(results))
            self._set_api_busy(False)
            if ok != len(results):
                messagebox.showwarning(
                    "Predpreverjanje ni popolno",
                    "Nekateri računi niso pripravljeni. Podrobnosti so v stolpcu Rezultat / napaka.",
                    parent=self.root,
                )
            if on_complete:
                on_complete(bool(results) and ok == len(results))

        self._run_api_worker(task, success, busy_text=f"Predpreverjam {len(selected)} računov proti Minimax šifrantom …")

    def send_api_selection(self) -> None:
        if not self.dataset or not self.minimax_client or not self.minimax_client.organisation_id:
            return
        if not self._active_org_matches_api():
            return
        selected = self._selected_api_rows()
        if not selected:
            messagebox.showinfo("Ni izbire", "Izberite račune za oddajo.", parent=self.root)
            return
        not_ready = [item for item, _book, _row in selected if self.api_tree.set(item, "api_status") != "OK"]
        if not_ready:
            messagebox.showinfo(
                "Najprej predpreverite",
                "Oddati je mogoče samo vrstice s stanjem OK. Kliknite »Predpreveri izbrane«.",
                parent=self.root,
            )
            return
        status = self._api_journal_status()
        mode = self._api_transfer_mode()
        options = self._api_transfer_options()
        status_label = "osnutek računa" if mode == "invoice" else ("osnutek" if status == "O" else "potrjeno")
        org_label = self.api_org_var.get()
        ir_count = sum(book == "IR" for _item, book, _row in selected)
        pr_count = sum(book == "PR" for _item, book, _row in selected)
        if mode == "invoice":
            if options.get("pr_companion_journal") and pr_count:
                document_lines = (
                    f"Izdani računi (osnutki): {ir_count}\nPrejeti računi (osnutki): {pr_count}\n"
                    f"Ločene PR temeljnice z odhodkom in DDV (osnutki): {pr_count}\n\n"
                    "POZOR: PR in spremljevalna temeljnica nista API-povezana. V Minimaxu potrdite samo enega; "
                    "potrditev obeh bi podvojila obveznost do dobavitelja."
                )
            else:
                document_lines = (
                    f"Izdani računi (osnutki): {ir_count}\nPrejeti računi (osnutki): {pr_count}\n"
                    "IR se po pregledu v Minimaxu izda. Pri PR je po prenosu treba ročno dodati konto/strošek in DDV ter račun potrditi."
                )
        else:
            document_lines = (
                f"Izdane temeljnice: {ir_count}\nPrejete temeljnice: {pr_count}\n"
                "Po temeljnici bo program z ločenim klicem dodal in preveril še DDV-vrstico."
            )
        confirm = messagebox.askyesno(
            "Potrditev neposredne oddaje",
            f"Organizacija: {org_label}\n"
            f"{document_lines}\n"
            f"Stanje: {status_label}\n\n"
            "Dokumenti bodo neposredno ustvarjeni v Minimaxu. Nadaljujem?",
            parent=self.root,
        )
        if not confirm:
            return
        for item, _book, _row in selected:
            self.api_tree.set(item, "api_status", "ODDAJAM")
            self.api_tree.set(
                item,
                "detail",
                (
                    "Ustvarjam PR-osnutek in ločeno osnutno temeljnico …"
                    if mode == "invoice" and options.get("pr_companion_journal") and _book == "PR"
                    else "Ustvarjam osnutek računa v Minimaxu …"
                ) if mode == "invoice" else "Pošiljam temeljnico in DDV v Minimax …",
            )

        def task() -> list[dict[str, Any]]:
            assert self.minimax_client is not None and self.dataset is not None
            self.log.info(
                "API oddaja: %s računov, način=%s, status=%s, org=%s",
                len(selected),
                mode,
                status,
                self.minimax_client.organisation_id,
            )
            results: list[dict[str, Any]] = []
            for item, book, row in selected:
                reference = str(row.get("P3") or "")
                try:
                    response = self.minimax_client.send_row(
                        self.dataset,
                        book,
                        row,
                        status=status,
                        mode=mode,
                        options=options,
                    )
                    detail = response.location or f"HTTP {response.status}"
                    self.log.info("Oddano %s %s → %s", book, reference, kirkpr_logging.safe_detail(detail))
                    results.append({"item": item, "book": book, "row": row, "ok": True, "detail": detail})
                except Exception as exc:
                    self.log.error("Napaka oddaje %s %s: %s", book, reference, kirkpr_logging.safe_detail(exc))
                    results.append({"item": item, "book": book, "row": row, "ok": False, "detail": str(exc)})
            return results

        def success(results: Any) -> None:
            sent_map = self._profile_config().setdefault("minimax_api_sent", {})
            ok = 0
            summary_rows: list[dict[str, Any]] = []
            for result in results:
                item = result["item"]
                reference = str(result["row"].get("P3") or "")
                if result["ok"]:
                    ok += 1
                    self.api_tree.set(item, "api_status", "ODDANO")
                    self.api_tree.item(item, tags=("api_sent",))
                    key = f"{mode}:{core.row_key(result['book'], result['row'])}"
                    sent_info = {
                        "organisation_id": self.minimax_client.organisation_id if self.minimax_client else "",
                        "location": result["detail"],
                        "mode": mode,
                        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    }
                    sent_map[key] = sent_info
                    self.api_item_sent_info[item] = dict(sent_info)
                    _prefix, book_code, raw_index = item.split(":", 2)
                    invoice_reference = minimax_api.normal_invoice_reference(result["row"].get("P3"))
                    resource = "issuedinvoices" if book_code == "IR" else "receivedinvoices"
                    record_id = minimax_browser.extract_minimax_record_id(result["detail"], resource)
                    if mode == "invoice":
                        source_tree = self.ir_tree if book_code == "IR" else self.pr_tree
                        source_item = f"{book_code.lower()}:{raw_index}"
                        if source_item in source_tree.get_children():
                            source_tree.set(source_item, "minimax_status", "Osnutek")
                        if record_id:
                            self.minimax_invoice_status_catalog[book_code]["by_id"][record_id] = "Osnutek"
                        if invoice_reference:
                            self.minimax_invoice_status_catalog[book_code]["by_reference"][invoice_reference] = "Osnutek"
                            if record_id:
                                self.minimax_invoice_status_catalog[book_code].setdefault("by_reference_id", {})[
                                    invoice_reference
                                ] = record_id
                    elif invoice_reference:
                        # Tudi pri temeljnicah zabeleži listino, da se ne podvoji.
                        self.minimax_invoice_status_catalog[book_code]["by_reference"][invoice_reference] = "Osnutek"
                    self.minimax_invoice_status_checked = True
                    self.api_view_mode = "minimax"
                    self._cleared_listinas.discard(f"{book_code} {result['row'].get('P3') or ''}")
                    summary_rows.append(
                        {
                            "book": result["book"],
                            "invoice": reference,
                            "ok": True,
                            "location": result["detail"],
                        }
                    )
                else:
                    self.api_tree.set(item, "api_status", "NAPAKA")
                    self.api_tree.item(item, tags=("api_error",))
                    summary_rows.append(
                        {
                            "book": result["book"],
                            "invoice": reference,
                            "ok": False,
                            "error": result["detail"],
                        }
                    )
                self.api_tree.set(item, "detail", result["detail"])
            failed = len(results) - ok
            self._record_action("api_send", f"oddano {ok}, napake {failed}; {org_label}")
            self.api_status_var.set(f"API oddaja zaključena: uspešno {ok}, napake {failed}.")
            self.status_var.set(f"Minimax API: uspešno oddano {ok}, napake {failed}.")
            summary_path = self._write_api_send_summary(
                org_label=org_label,
                mode=mode,
                status=status,
                ok=ok,
                failed=failed,
                rows=summary_rows,
            )
            self._set_api_busy(False)
            if failed:
                extra = f"\n\nPovzetek: {summary_path}" if summary_path else ""
                messagebox.showwarning(
                    "Delna oddaja",
                    f"Uspešno oddano: {ok}\nNapake: {failed}\n\n"
                    f"Preverite stolpec Rezultat / napaka ali gumb »Ponovi NAPAKA«.{extra}",
                    parent=self.root,
                )
            else:
                noun = "osnutkov računov" if mode == "invoice" else "temeljnic z DDV"
                extra = f"\n\nPovzetek: {summary_path}" if summary_path else ""
                messagebox.showinfo(
                    "Minimax API",
                    f"Vseh {ok} {noun} je uspešno oddanih v Minimax.{extra}",
                    parent=self.root,
                )

        busy_kind = "osnutkov računov" if mode == "invoice" else "temeljnic z DDV"
        self._run_api_worker(task, success, busy_text=f"Oddajam {len(selected)} {busy_kind} v Minimax …")

    def _build_document_fields_panel(
        self,
        parent: ttk.Frame,
        book: str,
        row: Mapping[str, Any],
    ) -> dict[str, tk.StringVar]:
        """V prejšnji obrazec doda urejanje vseh podatkov in zneskov KIR/KPR."""
        labels = IR_FIELD_LABELS if book == "IR" else PR_FIELD_LABELS
        evidence = "KIR" if book == "IR" else "KPR"
        panel = ttk.Frame(parent, style="Card.TFrame", padding=(14, 11))
        panel.pack(fill="both", expand=True, pady=(12, 0))

        title_row = ttk.Frame(panel, style="Card.TFrame")
        title_row.pack(fill="x", pady=(0, 8))
        ttk.Label(
            title_row,
            text="Zneski in ostali podatki računa",
            style="Card.TLabel",
            font=("Segoe UI Semibold", 10),
        ).pack(side="left")
        ttk.Label(
            title_row,
            text=f"Spremembe veljajo za delovno kopijo {evidence}; izvor ostane nespremenjen.",
            style="CardMuted.TLabel",
        ).pack(side="right")

        canvas_frame = ttk.Frame(panel, style="Card.TFrame")
        canvas_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            canvas_frame,
            bg=self.colors["card"],
            highlightthickness=0,
            height=235,
        )
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        fields_frame = ttk.Frame(canvas, style="Card.TFrame", padding=(2, 2, 8, 2))
        window_id = canvas.create_window((0, 0), window=fields_frame, anchor="nw")
        fields_frame.columnconfigure(1, weight=1)
        fields_frame.columnconfigure(3, weight=1)
        fields_frame.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )

        variables: dict[str, tk.StringVar] = {}
        for index, (field_name, label) in enumerate(labels.items()):
            line = index // 2
            group = index % 2
            column = group * 2
            ddvo_codes = core.ddvo_codes_for_field(book, field_name)
            ddvo_suffix = f" · DDV-O {', '.join(ddvo_codes)}" if ddvo_codes else ""
            ttk.Label(
                fields_frame,
                text=f"{field_name} — {label}{ddvo_suffix}",
                style="CardMuted.TLabel",
            ).grid(row=line, column=column, sticky="w", padx=(0 if group == 0 else 14, 7), pady=4)
            raw_value = row.get(field_name)
            shown_value = format_money(raw_value) if is_money_field(book, field_name) else ("" if raw_value is None else str(raw_value))
            variable = tk.StringVar(value=shown_value)
            variables[field_name] = variable
            entry = ttk.Entry(
                fields_frame,
                textvariable=variable,
                width=22,
                justify="right" if is_money_field(book, field_name) else "left",
            )
            entry.grid(
                row=line,
                column=column + 1,
                sticky="ew",
                padx=(0, 8),
                pady=4,
            )
            if field_name in VAT_BASE_RATE_FIELDS:
                entry.bind(
                    "<Double-Button-1>",
                    lambda _event, fn=field_name, var=variable, parent_win=parent.winfo_toplevel(): (
                        self._copy_vat_base_from_field(fn, var, parent=parent_win)
                    ),
                )
                ToolTip(
                    entry,
                    "Dvojni klik: izračuna osnovo (DDV ÷ stopnja), "
                    "jo kopira v odložišče in prikaže sporočilo.",
                )
        return variables

    def _copy_vat_base_from_field(
        self,
        field_name: str,
        variable: tk.StringVar,
        *,
        parent: tk.Misc | None = None,
    ) -> str:
        """Ob dvojnem kliku: osnova = DDV / stopnja → clipboard + msg."""
        parent_win = parent or self.root
        rate_info = VAT_BASE_RATE_FIELDS.get(field_name)
        if rate_info is None:
            return "break"
        rate, rate_label = rate_info
        try:
            vat = core.decimal_value(variable.get())
        except core.KirkprError as exc:
            messagebox.showerror("Osnova iz DDV", str(exc), parent=parent_win)
            return "break"
        if vat == 0:
            messagebox.showinfo(
                "Osnova iz DDV",
                f"{field_name}: DDV {rate_label} je 0 — osnove ni.",
                parent=parent_win,
            )
            return "break"
        base = (vat / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line = (
            f"- osnova {rate_label} = {format_money(base)} / "
            f"DDV {rate_label} = {format_money(vat)}"
        )
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(format_money(base))
            self.root.update_idletasks()
        except tk.TclError:
            messagebox.showerror(
                "Osnova iz DDV",
                f"Izračunano, a odložišče ni dosegljivo:\n{line}",
                parent=parent_win,
            )
            return "break"
        messagebox.showinfo(
            "Osnova iz DDV → odložišče",
            f"{line}\n\nV odložišču (za lepljenje): {format_money(base)}",
            parent=parent_win,
        )
        self.status_var.set(f"Osnova {rate_label} {format_money(base)} EUR kopirana v odložišče.")
        return "break"

    @staticmethod
    def _validated_document_changes(
        book: str,
        row: Mapping[str, Any],
        variables: Mapping[str, tk.StringVar],
    ) -> dict[str, Any]:
        """Najprej validira vsa polja na kopiji, da ob napaki ni delnega shranjevanja."""
        candidate = copy.deepcopy(dict(row))
        changes: dict[str, Any] = {}
        for field_name, variable in variables.items():
            entered = variable.get()
            current = "" if row.get(field_name) is None else str(row.get(field_name))
            if entered == current:
                continue
            if is_money_field(book, field_name):
                try:
                    if core.decimal_value(entered) == core.decimal_value(row.get(field_name)):
                        continue
                except core.KirkprError:
                    pass
            normalized = core.update_working_row(book, candidate, field_name, entered)
            changes[field_name] = normalized
        return changes

    def _on_ir_selection(self, _event: tk.Event | None = None) -> None:
        selected = self.ir_tree.selection()
        self.ir_selection_var.set(f"Izbranih IR: {len(selected)}")
        if not selected:
            return
        accounts = {str(self.ir_tree.set(item, "account")) for item in selected}
        self.ir_account_var.set(self._account_label(accounts.pop()) if len(accounts) == 1 else "")
        self._refresh_account_name_labels()

    def _on_ir_double_click(self, event: tk.Event) -> None:
        item = self.ir_tree.identify_row(event.y)
        if item:
            self.ir_tree.selection_set(item)
            self.open_ir_editor(item)

    def open_ir_editor(self, item: str | None = None) -> None:
        """Odpre modalno formo za popravek konta in opisa enega IR."""
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        if not item:
            selected = self.ir_tree.selection()
            if len(selected) != 1:
                messagebox.showinfo(
                    "Izberite en račun",
                    "Za podrobno urejanje izberite natanko en izdani račun.",
                    parent=self.root,
                )
                return
            item = selected[0]
        try:
            index = int(item.split(":", 1)[1])
            row = self.dataset.kir[index]
        except (ValueError, IndexError):
            return

        if self.ir_editor and self.ir_editor.winfo_exists():
            self.ir_editor.destroy()

        metrics = core.ir_metrics(row, self.dataset.kpr)
        window = tk.Toplevel(self.root)
        self.ir_editor = window
        window.title(f"Popravek IR — {row.get('P3') or 'brez številke'}")
        window.configure(bg=self.colors["bg"])
        window.resizable(True, True)
        window.transient(self.root)
        window.grab_set()

        width, height = 960, 840
        window.minsize(820, 700)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + max(20, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(20, (self.root.winfo_height() - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

        header = tk.Frame(window, bg=self.colors["panel_alt"], padx=22, pady=17)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Popravek izdanega računa",
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"{row.get('P3') or 'Brez številke'}  •  {row.get('P5') or 'Neznan kupec'}",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.Frame(window, padding=(18, 16))
        body.pack(fill="both", expand=True)
        info = ttk.Frame(body, style="Card.TFrame", padding=(16, 13))
        info.pack(fill="x")
        info.columnconfigure(1, weight=1)
        info.columnconfigure(3, weight=1)
        status = "Samoobdavčitev — ne izvozi se kot IR" if metrics["tax_only"] else "Izvoz v IR"
        details = (
            ("Datum DDV", row.get("P2", ""), "Datum računa", row.get("P4", "")),
            ("Listina", row.get("P3", ""), "ID za DDV", row.get("P6DS", "")),
            ("Neto", f"{format_money(metrics['net'])} EUR", "DDV", f"{format_money(metrics['vat'])} EUR"),
            ("Skupaj", f"{format_money(metrics['gross'])} EUR", "Obravnava", status),
        )
        for line, (left_label, left_value, right_label, right_value) in enumerate(details):
            ttk.Label(info, text=left_label + ":", style="CardMuted.TLabel").grid(row=line, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Label(info, text=str(left_value), style="Card.TLabel").grid(row=line, column=1, sticky="w", padx=(0, 24), pady=4)
            ttk.Label(info, text=right_label + ":", style="CardMuted.TLabel").grid(row=line, column=2, sticky="w", padx=(0, 8), pady=4)
            ttk.Label(info, text=str(right_value), style="Card.TLabel").grid(row=line, column=3, sticky="w", pady=4)

        edit = ttk.Frame(body, style="Card.TFrame", padding=(16, 14))
        edit.pack(fill="x", pady=(12, 0))
        edit.columnconfigure(1, weight=1)
        ttk.Label(edit, text="Konto prihodka", style="Card.TLabel", font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w", padx=(0, 16), pady=(0, 9))
        current_account = str(row.get("__konto__") or "7601")
        account_var = tk.StringVar(value=self._account_label(current_account))
        account_entry = ttk.Combobox(edit, textvariable=account_var, values=self._account_choices(), width=48)
        account_entry.grid(row=0, column=1, sticky="ew", pady=(0, 9))

        editor_account_name = tk.StringVar(value=self._account_name(current_account))
        update_editor_account_name = lambda: editor_account_name.set(
            self._account_name(self._account_code(account_var.get()))
        )
        self._configure_account_filter(account_entry, account_var, update_editor_account_name)
        ttk.Label(edit, text="Naziv konta", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 16), pady=(0, 9))
        ttk.Label(edit, textvariable=editor_account_name, style="Card.TLabel").grid(row=1, column=1, sticky="w", pady=(0, 9))
        account_entry.bind(
            "<<ComboboxSelected>>",
            lambda _event: update_editor_account_name(),
        )

        ttk.Label(edit, text="Opis knjižbe", style="Card.TLabel", font=("Segoe UI Semibold", 10)).grid(row=2, column=0, sticky="w", padx=(0, 16), pady=(0, 9))
        description_var = tk.StringVar(value=str(row.get("__opis__") or row.get("P3") or ""))
        description_entry = ttk.Entry(edit, textvariable=description_var)
        description_entry.grid(row=2, column=1, sticky="ew", pady=(0, 9))

        customer_rule_var = tk.BooleanVar(value=self.remember_customer_var.get())
        ttk.Checkbutton(
            edit,
            text="Zapomni si ta konto za kupca pri prihodnjih računih",
            variable=customer_rule_var,
            style="Card.TCheckbutton",
        ).grid(row=3, column=1, sticky="w")

        hint_text = (
            "Ta KIR vrstica je samoobdavčitev in se ne izvozi kot izdani račun. Popravek bo kljub temu shranjen."
            if metrics["tax_only"]
            else "Konto se uporabi na prihodkovni vrstici temeljnice. Opis se prenese v glavo in vrstice Minimax temeljnice."
        )
        ttk.Label(
            body,
            text=hint_text,
            style="Muted.TLabel",
            wraplength=630,
            justify="left",
        ).pack(fill="x", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", side="bottom", pady=(12, 0))

        document_vars = self._build_document_fields_panel(body, "IR", row)

        ttk.Label(
            buttons,
            text="»Shrani trenutni zapis« začasno pripravi popravek; generalni zapis potrdite z »Shrani delovno kopijo«.",
            style="Muted.TLabel",
        ).pack(side="left")

        def close_editor() -> None:
            window.grab_release()
            window.destroy()
            self.ir_editor = None

        def save_temporary() -> None:
            try:
                account = self._validated_account_code(account_var.get())
            except core.KirkprError as exc:
                messagebox.showerror("Neveljaven konto", str(exc), parent=window)
                return
            description = description_var.get().strip()
            try:
                document_changes = self._validated_document_changes("IR", row, document_vars)
                validation_config = copy.deepcopy(self._profile_config())
                core.remember_account(
                    validation_config,
                    "IR",
                    row,
                    account,
                    supplier_rule=customer_rule_var.get(),
                )
                core.remember_description(validation_config, "IR", row, description)
            except (OSError, core.KirkprError) as exc:
                messagebox.showerror("Začasno shranjevanje ni uspelo", str(exc), parent=window)
                return

            change_count = len(document_changes)
            change_count += account != str(row.get("__konto__") or "7601")
            change_count += description != str(row.get("__opis__") or row.get("P3") or "")
            if not change_count:
                self.status_var.set(f"IR {row.get('P3')}: ni sprememb za začasno shranjevanje.")
                close_editor()
                return
            document_name = str(row.get("P3") or "brez številke")
            try:
                core.remember_account(
                    self._profile_config(),
                    "IR",
                    row,
                    account,
                    supplier_rule=customer_rule_var.get(),
                )
                core.remember_description(self._profile_config(), "IR", row, description)
                row.update(document_changes)
                row["__konto__"] = account
                row["__opis__"] = description
                self.ir_account_var.set(account)
                self.config["last_ir_account"] = account
            except core.KirkprError as exc:
                messagebox.showerror("Popravka ni mogoče shraniti", str(exc), parent=window)
                return
            detail = f"IR {document_name}: {change_count} sprememb, konto {account}"
            self._mark_working_dirty(detail)
            self._populate_trees()
            self._populate_api_tree()
            self.remember_customer_var.set(customer_rule_var.get())
            self.status_var.set(
                f"IR {document_name}: {change_count} sprememb je začasno shranjenih. "
                "Za generalni zapis kliknite »Shrani delovno kopijo«."
            )
            close_editor()

        ttk.Button(buttons, text="Prekliči", style="Danger.TButton", command=close_editor).pack(side="right")
        ttk.Button(
            buttons,
            text="Shrani trenutni zapis",
            style="Success.TButton",
            command=save_temporary,
        ).pack(side="right", padx=(0, 8))
        window.protocol("WM_DELETE_WINDOW", close_editor)
        window.bind("<Escape>", lambda _event: close_editor())
        window.bind("<Control-s>", lambda _event: save_temporary())
        window.bind("<Control-Return>", lambda _event: save_temporary())
        account_entry.focus_set()
        account_entry.selection_range(0, "end")

    def _select_all_ir(self, _event: tk.Event | None = None) -> str:
        self.ir_tree.selection_set(self.ir_tree.get_children())
        return "break"

    def set_selected_ir_account(self, account: str) -> None:
        self.ir_account_var.set(account)
        self.apply_ir_account()

    def apply_ir_account(self) -> None:
        if not self.dataset:
            return
        selected = self.ir_tree.selection()
        if not selected:
            messagebox.showinfo("Izberite račune", "Najprej izberite enega ali več izdanih računov.", parent=self.root)
            return
        try:
            account = self._validated_account_code(self.ir_account_var.get())
        except core.KirkprError as exc:
            messagebox.showerror("Neveljaven konto", str(exc), parent=self.root)
            return
        changed = 0
        try:
            for item in selected:
                index = int(item.split(":", 1)[1])
                row = self.dataset.kir[index]
                core.remember_account(
                    self._profile_config(),
                    "IR",
                    row,
                    account,
                    supplier_rule=self.remember_customer_var.get(),
                )
                row["__konto__"] = account
                self.ir_tree.set(item, "account", account)
                self.ir_tree.set(item, "account_name", self._account_name(account))
                changed += 1
        except (ValueError, core.KirkprError) as exc:
            messagebox.showerror("Neveljaven konto", str(exc), parent=self.root)
            return
        self.config["last_ir_account"] = account
        self._profile_config()["last_ir_account"] = account
        try:
            self._record_action("account_change", f"{changed} IR → konto {account}")
        except OSError as exc:
            messagebox.showerror("Shranjevanje ni uspelo", str(exc), parent=self.root)
            return
        self._populate_api_tree()
        self._mark_working_dirty()
        self.save_working_copy(quiet=True)
        self.status_var.set(f"Konto {account} je nastavljen na {changed} IR in samodejno shranjen.")

    def _on_pr_selection(self, _event: tk.Event | None = None) -> None:
        selected = self.pr_tree.selection()
        self.selection_var.set(f"Izbranih PR: {len(selected)}")
        if not selected:
            return
        accounts = {str(self.pr_tree.set(item, "account")) for item in selected}
        self.account_var.set(self._account_label(accounts.pop()) if len(accounts) == 1 else "")
        self._refresh_account_name_labels()

    def _on_pr_double_click(self, event: tk.Event) -> None:
        item = self.pr_tree.identify_row(event.y)
        if item:
            self.pr_tree.selection_set(item)
            self.open_pr_editor(item)

    def open_pr_editor(self, item: str | None = None) -> None:
        """Odpre modalno formo za popravek konta in opisa enega PR."""
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        if not item:
            selected = self.pr_tree.selection()
            if len(selected) != 1:
                messagebox.showinfo(
                    "Izberite en račun",
                    "Za podrobno urejanje izberite natanko en prejeti račun.",
                    parent=self.root,
                )
                return
            item = selected[0]
        try:
            index = int(item.split(":", 1)[1])
            row = self.dataset.kpr[index]
        except (ValueError, IndexError):
            return

        if self.pr_editor and self.pr_editor.winfo_exists():
            self.pr_editor.destroy()

        metrics = core.pr_metrics(row)
        window = tk.Toplevel(self.root)
        self.pr_editor = window
        window.title(f"Popravek PR — {row.get('P3') or 'brez številke'}")
        window.configure(bg=self.colors["bg"])
        window.resizable(True, True)
        window.transient(self.root)
        window.grab_set()

        width, height = 980, 880
        window.minsize(840, 740)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + max(20, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(20, (self.root.winfo_height() - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

        header = tk.Frame(window, bg=self.colors["panel_alt"], padx=22, pady=17)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Popravek prejetega računa",
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"{row.get('P3') or 'Brez številke'}  •  {row.get('P6') or 'Neznan dobavitelj'}",
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.Frame(window, padding=(18, 16))
        body.pack(fill="both", expand=True)
        info = ttk.Frame(body, style="Card.TFrame", padding=(16, 13))
        info.pack(fill="x")
        info.columnconfigure(1, weight=1)
        info.columnconfigure(3, weight=1)
        self_assessment = bool(metrics["self_assessment"])
        vat_deductible = bool(metrics["vat_deductible"])
        details = (
            ("Datum knjiženja", row.get("P2", ""), "Datum računa", row.get("P5", "")),
            ("Listina", row.get("P3", ""), "ID za DDV", row.get("P7DS", "")),
            (
                "Osnova",
                f"{format_money(metrics['net'])} EUR",
                "Odbitni DDV" if vat_deductible else "DDV v strošku",
                f"{format_money(metrics['vat'] if vat_deductible else metrics['reported_vat'])} EUR",
            ),
            (
                "Obveznost",
                f"{format_money(metrics['gross'])} EUR",
                "Vrsta",
                "Samoobdavčitev" if self_assessment else "Prejeti račun",
            ),
        )
        for line, (left_label, left_value, right_label, right_value) in enumerate(details):
            ttk.Label(info, text=left_label + ":", style="CardMuted.TLabel").grid(row=line, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Label(info, text=str(left_value), style="Card.TLabel").grid(row=line, column=1, sticky="w", padx=(0, 24), pady=4)
            ttk.Label(info, text=right_label + ":", style="CardMuted.TLabel").grid(row=line, column=2, sticky="w", padx=(0, 8), pady=4)
            ttk.Label(info, text=str(right_value), style="Card.TLabel").grid(row=line, column=3, sticky="w", pady=4)

        edit = ttk.Frame(body, style="Card.TFrame", padding=(16, 14))
        edit.pack(fill="x", pady=(12, 0))
        edit.columnconfigure(1, weight=1)
        ttk.Label(edit, text="Konto stroška/sredstva", style="Card.TLabel", font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w", padx=(0, 16), pady=(0, 9))
        current_account = str(row.get("__konto__") or "4190")
        account_var = tk.StringVar(value=self._account_label(current_account))
        account_entry = ttk.Combobox(edit, textvariable=account_var, values=self._account_choices(), width=48)
        account_entry.grid(row=0, column=1, sticky="ew", pady=(0, 9))

        editor_account_name = tk.StringVar(value=self._account_name(current_account))
        update_editor_account_name = lambda: editor_account_name.set(
            self._account_name(self._account_code(account_var.get()))
        )
        self._configure_account_filter(account_entry, account_var, update_editor_account_name)
        ttk.Label(edit, text="Naziv konta", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 16), pady=(0, 9))
        ttk.Label(edit, textvariable=editor_account_name, style="Card.TLabel").grid(row=1, column=1, sticky="w", pady=(0, 9))
        account_entry.bind(
            "<<ComboboxSelected>>",
            lambda _event: update_editor_account_name(),
        )

        ttk.Label(edit, text="Opis knjižbe", style="Card.TLabel", font=("Segoe UI Semibold", 10)).grid(row=2, column=0, sticky="w", padx=(0, 16), pady=(0, 9))
        description_var = tk.StringVar(value=str(row.get("__opis__") or row.get("P3") or ""))
        description_entry = ttk.Entry(edit, textvariable=description_var)
        description_entry.grid(row=2, column=1, sticky="ew", pady=(0, 9))

        supplier_rule_var = tk.BooleanVar(value=self.remember_supplier_var.get())
        ttk.Checkbutton(
            edit,
            text="Zapomni si konto, samoobdavčitev in DDV se odbija za dobavitelja",
            variable=supplier_rule_var,
            style="Card.TCheckbutton",
        ).grid(row=3, column=1, sticky="w")

        self_assessment_var = tk.BooleanVar(value=self_assessment)
        ttk.Checkbutton(
            edit,
            text="Samoobdavčitev",
            variable=self_assessment_var,
            style="Card.TCheckbutton",
        ).grid(row=4, column=1, sticky="w", pady=(7, 0))

        vat_deductible_var = tk.BooleanVar(value=vat_deductible)
        ttk.Checkbutton(
            edit,
            text="DDV se odbija",
            variable=vat_deductible_var,
            style="Card.TCheckbutton",
        ).grid(row=5, column=1, sticky="w", pady=(7, 0))

        offer_from = str(row.get("__vat_offer_from__") or "").strip()
        if self_assessment or offer_from:
            offer_txt = (
                f"Ponujeno v tem PR: Samoobdavčitev={'DA' if self_assessment else 'NE'}, "
                f"DDV se odbija={'DA' if vat_deductible else 'NE'}"
                + (f" (vir: {offer_from})." if offer_from else ".")
            )
            ttk.Label(edit, text=offer_txt, style="CardMuted.TLabel", wraplength=560).grid(
                row=6, column=1, sticky="w", pady=(6, 0)
            )

        hint = ttk.Label(
            body,
            text=(
                "Nastavitvi sta enaki kot pri odhodku v Minimaxu. Če je v KPR zabeležena samoobdavčitev "
                "(P9–P11) ali si jo shranil za dobavitelja, ju obrazec samodejno ponudi. "
                "Pri samoobdavčitvi program knjiži obračunani DDV v dobro; odbitni DDV knjiži v breme "
                "samo, če je označeno »DDV se odbija«. Brez odbitka se DDV prišteje stroškovnemu kontu."
            ),
            style="Muted.TLabel",
            wraplength=630,
            justify="left",
        )
        hint.pack(fill="x", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", side="bottom", pady=(12, 0))

        document_vars = self._build_document_fields_panel(body, "PR", row)

        ttk.Label(
            buttons,
            text="»Shrani trenutni zapis« začasno pripravi popravek; generalni zapis potrdite z »Shrani delovno kopijo«.",
            style="Muted.TLabel",
        ).pack(side="left")

        def close_editor() -> None:
            window.grab_release()
            window.destroy()
            self.pr_editor = None

        def save_temporary() -> None:
            try:
                account = self._validated_account_code(account_var.get())
            except core.KirkprError as exc:
                messagebox.showerror("Neveljaven konto", str(exc), parent=window)
                return
            description = description_var.get().strip()
            try:
                document_changes = self._validated_document_changes("PR", row, document_vars)
                validation_config = copy.deepcopy(self._profile_config())
                core.remember_account(
                    validation_config,
                    "PR",
                    row,
                    account,
                    supplier_rule=supplier_rule_var.get(),
                )
                core.remember_description(validation_config, "PR", row, description)
                core.remember_self_assessment(
                    validation_config,
                    row,
                    self_assessment_var.get(),
                    supplier_rule=supplier_rule_var.get(),
                )
                core.remember_vat_deductible(
                    validation_config,
                    row,
                    vat_deductible_var.get(),
                    supplier_rule=supplier_rule_var.get(),
                )
            except (OSError, core.KirkprError) as exc:
                messagebox.showerror("Začasno shranjevanje ni uspelo", str(exc), parent=window)
                return

            change_count = len(document_changes)
            change_count += account != str(row.get("__konto__") or "4190")
            change_count += description != str(row.get("__opis__") or row.get("P3") or "")
            change_count += self_assessment_var.get() != core.is_self_assessment(row)
            change_count += vat_deductible_var.get() != core.vat_is_deductible(row)
            if not change_count:
                self.status_var.set(f"PR {row.get('P3')}: ni sprememb za začasno shranjevanje.")
                close_editor()
                return
            document_name = str(row.get("P3") or "brez številke")
            try:
                core.remember_account(
                    self._profile_config(),
                    "PR",
                    row,
                    account,
                    supplier_rule=supplier_rule_var.get(),
                )
                core.remember_description(self._profile_config(), "PR", row, description)
                core.remember_self_assessment(
                    self._profile_config(),
                    row,
                    self_assessment_var.get(),
                    supplier_rule=supplier_rule_var.get(),
                )
                core.remember_vat_deductible(
                    self._profile_config(),
                    row,
                    vat_deductible_var.get(),
                    supplier_rule=supplier_rule_var.get(),
                )
                row.update(document_changes)
                row["__konto__"] = account
                row["__opis__"] = description
                row["__samoobdavcitev__"] = self_assessment_var.get()
                row["__ddv_se_odbija__"] = vat_deductible_var.get()
                row["__vat_offer_from__"] = (
                    "dobavitelj" if supplier_rule_var.get() else "ta listina"
                )
                self.account_var.set(account)
                self.config["last_account"] = account
            except core.KirkprError as exc:
                messagebox.showerror("Popravka ni mogoče shraniti", str(exc), parent=window)
                return
            self._populate_trees()
            self._update_header_and_summary()
            if item in self.pr_tree.get_children():
                self.pr_tree.selection_set(item)
                self.pr_tree.see(item)
            self.remember_supplier_var.set(supplier_rule_var.get())
            detail = f"PR {document_name}: {change_count} sprememb, konto {account}"
            self._mark_working_dirty(detail)
            self.status_var.set(
                f"PR {document_name}: {change_count} sprememb je začasno shranjenih. "
                "Za generalni zapis kliknite »Shrani delovno kopijo«."
            )
            close_editor()

        ttk.Button(buttons, text="Prekliči", style="Danger.TButton", command=close_editor).pack(side="right")
        ttk.Button(
            buttons,
            text="Shrani trenutni zapis",
            style="Success.TButton",
            command=save_temporary,
        ).pack(side="right", padx=(0, 8))
        window.protocol("WM_DELETE_WINDOW", close_editor)
        window.bind("<Escape>", lambda _event: close_editor())
        window.bind("<Control-s>", lambda _event: save_temporary())
        window.bind("<Control-Return>", lambda _event: save_temporary())
        account_entry.focus_set()
        account_entry.selection_range(0, "end")

    def open_data_editor(self, book: str) -> None:
        """Uredi polja delovne vrstice ob vzporednem prikazu nespremenjenega izvora."""
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        source_tree = self.ir_tree if book == "IR" else self.pr_tree
        selected = source_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo("Izberite en račun", "Za urejanje podatkov izberite natanko en račun.", parent=self.root)
            return
        item = selected[0]
        try:
            index = int(item.split(":", 1)[1])
            rows = self.dataset.kir if book == "IR" else self.dataset.kpr
            original_rows = (
                self.source_dataset.kir if book == "IR" else self.source_dataset.kpr
            ) if self.source_dataset else rows
            row = rows[index]
            original_row = original_rows[index]
        except (ValueError, IndexError):
            return

        labels = IR_FIELD_LABELS if book == "IR" else PR_FIELD_LABELS
        fields = list(labels)
        window = tk.Toplevel(self.root)
        window.title(f"Delovna kopija {book} — {row.get('P3') or 'brez številke'}")
        window.configure(bg=self.colors["bg"])
        window.geometry("1260x720")
        window.minsize(1050, 600)
        window.transient(self.root)
        window.grab_set()

        header = ttk.Frame(window, style="Header.TFrame", padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="Urejanje podatkov delovne kopije", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Izvorna vrednost ostane nespremenjena. KIR/KPR pokaže mesto v evidenci, "
                "DDV-O pa neposredno polje obrazca; za XML/API se uporabi delovna vrednost."
            ),
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        frame = ttk.Frame(window, padding=(14, 12))
        frame.pack(fill="both", expand=True)
        data_tree = ttk.Treeview(
            frame,
            columns=("field", "label", "evidence", "ddvo", "original", "working"),
            show="headings",
            selectmode="browse",
            style="Studio.Treeview",
        )
        data_tree.heading("field", text="Polje")
        data_tree.heading("label", text="Pomen")
        data_tree.heading("evidence", text="KIR/KPR")
        data_tree.heading("ddvo", text="DDV-O")
        data_tree.heading("original", text="Izvorna vrednost (samo branje)")
        data_tree.heading("working", text="Delovna vrednost za Minimax")
        data_tree.column("field", width=70, anchor="center", stretch=False)
        data_tree.column("label", width=225, stretch=True)
        data_tree.column("evidence", width=95, anchor="center", stretch=False)
        data_tree.column("ddvo", width=85, anchor="center", stretch=False)
        data_tree.column("original", width=265, stretch=True)
        data_tree.column("working", width=265, stretch=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=data_tree.yview)
        data_tree.configure(yscrollcommand=scrollbar.set)
        data_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        gui_style.apply_tree_tags(data_tree, "changed")

        def display(field_name: str, value: Any) -> str:
            if is_money_field(book, field_name):
                return format_money(value)
            return "" if value is None else str(value)

        for field_name in fields:
            original_value = display(field_name, original_row.get(field_name, ""))
            working_value = display(field_name, row.get(field_name, ""))
            tags = ("changed",) if original_value != working_value else ()
            evidence_book = "KIR" if book == "IR" else "KPR"
            evidence_reference = f"{evidence_book} {field_name}"
            ddvo_codes = core.ddvo_codes_for_field(book, field_name)
            ddvo_reference = ", ".join(ddvo_codes) if ddvo_codes else "—"
            data_tree.insert(
                "",
                "end",
                iid=f"field:{field_name}",
                values=(
                    field_name,
                    labels[field_name],
                    evidence_reference,
                    ddvo_reference,
                    original_value,
                    working_value,
                ),
                tags=tags,
            )

        editor = ttk.Frame(window, style="Card.TFrame", padding=(16, 12))
        editor.pack(fill="x", padx=14, pady=(0, 12))
        editor.columnconfigure(1, weight=1)
        selected_field_var = tk.StringVar(value="Izberite polje")
        edit_value_var = tk.StringVar(value="")
        ttk.Label(editor, textvariable=selected_field_var, style="Card.TLabel", width=28).grid(row=0, column=0, sticky="w", padx=(0, 10))
        value_entry = ttk.Entry(editor, textvariable=edit_value_var)
        value_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        def on_field_select(_event: tk.Event | None = None) -> None:
            selection = data_tree.selection()
            if not selection:
                return
            field_name = selection[0].split(":", 1)[1]
            selected_field_var.set(f"{field_name} — {labels[field_name]}")
            edit_value_var.set(display(field_name, row.get(field_name, "")))
            value_entry.focus_set()
            value_entry.selection_range(0, "end")

        def apply_value() -> bool:
            selection = data_tree.selection()
            if not selection:
                messagebox.showinfo("Izberite polje", "Najprej izberite vrstico s poljem.", parent=window)
                return False
            field_name = selection[0].split(":", 1)[1]
            try:
                normalized = core.update_working_row(book, row, field_name, edit_value_var.get())
            except core.KirkprError as exc:
                messagebox.showerror("Neveljavna vrednost", str(exc), parent=window)
                return False
            original_value = display(field_name, original_row.get(field_name, ""))
            working_value = display(field_name, normalized)
            data_tree.set(selection[0], "working", working_value)
            data_tree.item(selection[0], tags=(("changed",) if original_value != working_value else ()))
            self._populate_trees()
            self._update_header_and_summary()
            self._mark_working_dirty(f"{book} {row.get('P3')}: polje {field_name}")
            if source_tree.exists(item):
                source_tree.selection_set(item)
                source_tree.see(item)
            self._record_action("data_edit", f"{book} {row.get('P3')}: {field_name}")
            self.status_var.set(f"Spremenjeno {field_name}; izvorna vrednost je ostala nespremenjena.")
            return True

        def save_copy() -> None:
            if data_tree.selection() and edit_value_var.get() != data_tree.set(data_tree.selection()[0], "working"):
                if not apply_value():
                    return
            self.save_working_copy()

        ttk.Button(editor, text="Uporabi vrednost", style="Accent.TButton", command=apply_value).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(editor, text="Shrani delovno kopijo", style="Success.TButton", command=save_copy).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(editor, text="Zapri", command=window.destroy).grid(row=0, column=4)
        data_tree.bind("<<TreeviewSelect>>", on_field_select)
        data_tree.bind("<Double-1>", on_field_select)
        value_entry.bind("<Return>", lambda _event: apply_value())
        window.bind("<Control-s>", lambda _event: save_copy())
        window.bind("<Escape>", lambda _event: window.destroy())
        if data_tree.get_children():
            data_tree.selection_set(data_tree.get_children()[0])
            on_field_select()

    def _select_all_pr(self, _event: tk.Event | None = None) -> str:
        self.pr_tree.selection_set(self.pr_tree.get_children())
        return "break"

    def set_selected_account(self, account: str) -> None:
        self.account_var.set(account)
        self.apply_account()

    def set_selected_vat_deductible(self, enabled: bool) -> None:
        """Na izbranih PR nastavi Minimaxovo možnost »DDV se odbija«."""
        if not self.dataset:
            return
        selected = self.pr_tree.selection()
        if not selected:
            messagebox.showinfo("Izberite račune", "Najprej izberite enega ali več prejetih računov.", parent=self.root)
            return
        changed = 0
        try:
            for item in selected:
                index = int(item.split(":", 1)[1])
                row = self.dataset.kpr[index]
                row["__ddv_se_odbija__"] = bool(enabled)
                core.remember_vat_deductible(self._profile_config(), row, enabled)
                changed += 1
            self._record_action(
                "vat_settings",
                f"{changed} PR; DDV se odbija {'DA' if enabled else 'NE'}",
            )
        except (ValueError, IndexError, OSError) as exc:
            messagebox.showerror("Nastavitve ni mogoče shraniti", str(exc), parent=self.root)
            return
        selected_items = tuple(selected)
        self._populate_trees()
        self._update_header_and_summary()
        existing = [item for item in selected_items if item in self.pr_tree.get_children()]
        if existing:
            self.pr_tree.selection_set(existing)
            self.pr_tree.see(existing[0])
        self._mark_working_dirty()
        self.save_working_copy(quiet=True)
        self.status_var.set(
            f"DDV se odbija = {'DA' if enabled else 'NE'} je nastavljeno na {changed} PR in samodejno shranjeno."
        )

    def apply_account(self) -> None:
        if not self.dataset:
            return
        selected = self.pr_tree.selection()
        if not selected:
            messagebox.showinfo("Izberite račune", "Najprej izberite enega ali več prejetih računov.", parent=self.root)
            return
        try:
            account = self._validated_account_code(self.account_var.get())
        except core.KirkprError as exc:
            messagebox.showerror("Neveljaven konto", str(exc), parent=self.root)
            return
        changed = 0
        try:
            for item in selected:
                index = int(item.split(":", 1)[1])
                row = self.dataset.kpr[index]
                core.remember_account(
                    self._profile_config(),
                    "PR",
                    row,
                    account,
                    supplier_rule=self.remember_supplier_var.get(),
                )
                row["__konto__"] = account
                self.pr_tree.set(item, "account", account)
                self.pr_tree.set(item, "account_name", self._account_name(account))
                changed += 1
        except (ValueError, core.KirkprError) as exc:
            messagebox.showerror("Neveljaven konto", str(exc), parent=self.root)
            return
        self.config["last_account"] = account
        self._profile_config()["last_account"] = account
        try:
            self._record_action("account_change", f"{changed} PR → konto {account}")
        except OSError as exc:
            messagebox.showerror("Shranjevanje ni uspelo", str(exc), parent=self.root)
            return
        self._populate_api_tree()
        self._mark_working_dirty()
        self.save_working_copy(quiet=True)
        self.status_var.set(f"Konto {account} je nastavljen na {changed} PR in samodejno shranjen.")

    def save_accounts(self, quiet: bool = False) -> bool:
        if not self.dataset:
            if not quiet:
                messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return False
        profile = self._profile_config()
        for row in self.dataset.kir:
            core.remember_account(profile, "IR", row, str(row.get("__konto__") or "7601"), supplier_rule=False)
            core.remember_description(profile, "IR", row, str(row.get("__opis__") or row.get("P3") or ""))
        for row in self.dataset.kpr:
            core.remember_account(profile, "PR", row, str(row.get("__konto__") or "4190"), supplier_rule=False)
            core.remember_description(profile, "PR", row, str(row.get("__opis__") or row.get("P3") or ""))
            core.remember_self_assessment(profile, row, core.is_self_assessment(row))
            core.remember_vat_deductible(profile, row, core.vat_is_deductible(row))
        try:
            self._record_action("save", f"{len(self.dataset.kir)} KIR / {len(self.dataset.kpr)} KPR")
            saved = self.config_file
        except OSError as exc:
            messagebox.showerror("Shranjevanje ni uspelo", str(exc), parent=self.root)
            return False
        self.status_var.set(f"Konta so shranjena v {saved.name}.")
        working_copy = self.save_working_copy(quiet=True)
        if working_copy is None:
            return False
        if not quiet:
            messagebox.showinfo(
                "Spremembe shranjene",
                f"Konta, pravila in delovna kopija so shranjeni.\n\n{working_copy}\n\nIzvorna datoteka ni bila spremenjena.",
                parent=self.root,
            )
        return True

    def save_working_copy(self, quiet: bool = False) -> Path | None:
        if not self.dataset:
            if not quiet:
                messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return None
        if not quiet and self.working_dirty:
            details = self.pending_working_changes[-10:]
            summary = "\n".join(f"• {detail}" for detail in details)
            if len(self.pending_working_changes) > len(details):
                summary += f"\n• … in še {len(self.pending_working_changes) - len(details)} sprememb"
            if not summary:
                summary = "• Spremenjeni podatki delovne kopije"
            confirmed = messagebox.askyesno(
                "Potrdi generalno shranjevanje",
                "Začasno pripravljeni popravki:\n\n"
                f"{summary}\n\n"
                "Naj jih zapišem v novo delovno kopijo? Izvorna datoteka bo ostala nespremenjena.",
                parent=self.root,
            )
            if not confirmed:
                self.status_var.set("Generalno shranjevanje je preklicano; začasni popravki ostajajo v programu.")
                return None
        paths = self._company_paths()
        source_stem = company_registry.safe_name(self.dataset.source_path.stem, "KIRKPR")
        filename = f"{source_stem}_MINIMAX_UREJENO.json"
        if paths:
            target = paths.working_copies / filename
        else:
            target = self.dataset.source_path.parent / filename
            if not quiet:
                selected = filedialog.asksaveasfilename(
                    parent=self.root,
                    title="Shrani Minimax delovno kopijo",
                    initialdir=str(target.parent),
                    initialfile=target.name,
                    defaultextension=".json",
                    filetypes=[("JSON delovna kopija", "*.json")],
                )
                if not selected:
                    return None
                target = Path(selected)
        company_info: dict[str, Any] = {}
        if self.active_company:
            company_info = {
                "Zšt": company_registry.company_zst(self.active_company),
                "Kratko ime": company_registry.company_name(self.active_company),
                "DAVČNA": company_registry.company_tax_number(self.active_company),
                "Org_ID": company_registry.company_org_id(self.active_company),
            }
        try:
            saved = core.save_working_copy(self.dataset, target, company=company_info)
            profile = self._profile_config()
            profile["last_working_copy"] = str(saved)
            self.config["last_working_copy"] = str(saved)
            self.working_dirty = False
            self.pending_working_changes.clear()
            self._remember_current_session(working_copy=saved)
            if quiet:
                core.save_config(self.config, self.config_file)
            else:
                self._record_action("working_copy", saved.name)
        except (OSError, core.KirkprError) as exc:
            if not quiet:
                messagebox.showerror("Delovne kopije ni mogoče shraniti", str(exc), parent=self.root)
            else:
                self.status_var.set(f"Opozorilo: delovne kopije ni mogoče shraniti: {exc}")
            return None
        self.format_var.set(f"Format: {self.dataset.source_format} • delovna kopija: {saved.name}")
        self.status_var.set(f"Delovna kopija je shranjena: {saved}. Izvorna datoteka je nespremenjena.")
        if not quiet:
            messagebox.showinfo(
                "Delovna kopija shranjena",
                f"Urejeni podatki so shranjeni pod novim imenom:\n\n{saved}\n\nIzvorna datoteka ni bila spremenjena.",
                parent=self.root,
            )
        return saved

    def export_files(self) -> None:
        if not self.dataset:
            messagebox.showinfo("Ni podatkov", "Najprej odprite KIR/KPR datoteko.", parent=self.root)
            return
        profile = self._profile_config()
        paths = self._company_paths()
        if paths:
            destination = paths.exports
            selected = str(destination.parent)
        else:
            initial = str(profile.get("last_output_dir") or self.config.get("last_output_dir") or self.dataset.source_path.parent)
            selected = filedialog.askdirectory(
                parent=self.root,
                title="Izberite mapo za Minimax XML in ZIP",
                initialdir=initial if Path(initial).is_dir() else str(self.dataset.source_path.parent),
                mustexist=True,
            )
            if not selected:
                return
            start, end = self._filter_iso_bounds()
            token = f"{start}_{end}"
            destination = Path(selected) / f"Minimax_XML_{token}"
        if not self.save_accounts(quiet=True):
            return
        view = self._view_dataset() or self.dataset
        self.status_var.set(
            f"Ustvarjam Minimax XML za filter {view.period_from}–{view.period_to} …"
        )
        self.root.update_idletasks()
        try:
            result = core.export_minimax(view, destination)
        except Exception as exc:
            self.status_var.set("Izvoz ni uspel.")
            messagebox.showerror("Napaka pri izvozu", str(exc), parent=self.root)
            return
        self.last_export_dir = destination
        self.config["last_output_dir"] = str(Path(selected))
        self.config["last_export_dir"] = str(destination)
        self.config["last_export_archive"] = str(result.archive)
        profile["last_output_dir"] = str(Path(selected))
        profile["last_export_dir"] = str(destination)
        profile["last_export_archive"] = str(result.archive)
        self._record_action("export", f"{result.issued_count} IR / {result.received_count} PR; {result.archive.name}")
        validation = "XSD preverjanje uspešno" if result.xsd_validated else "XML ustvarjen; XSD ni bila najdena"
        self.status_var.set(f"Izvoz končan: {result.issued_count} IR, {result.received_count} PR. {validation}.")
        answer = messagebox.askyesno(
            "Minimax izvoz je pripravljen",
            f"Ustvarjeno:\n\n"
            f"• {result.issued_xml.name}\n"
            f"• {result.received_xml.name}\n"
            f"• {result.archive.name}\n"
            f"• {result.report.name}\n\n"
            f"{validation}.\n\nOdpreti izhodno mapo?",
            parent=self.root,
        )
        if answer:
            open_in_file_manager(destination)

    def open_last_export(self) -> None:
        if self.last_export_dir and self.last_export_dir.is_dir():
            open_in_file_manager(self.last_export_dir)
            return
        directory = Path(str(self._profile_config().get("last_output_dir") or self.config.get("last_output_dir") or ""))
        if directory.is_dir():
            open_in_file_manager(directory)
        else:
            messagebox.showinfo("Ni izvoza", "Prejšnja izhodna mapa ni shranjena ali ne obstaja več.", parent=self.root)

    def _sort_tree(self, tree: ttk.Treeview, column: str, reverse: bool) -> None:
        money_sort_cols = {
            "zapst", "net", "vat", "vat_22", "vat_95", "vat_5", "gross", "amount",
            *[f"p{i}" for i in range(7, 28)],
        }

        def key(item: str) -> tuple[int, Any]:
            value = tree.set(item, column)
            if column in money_sort_cols:
                try:
                    return 0, core.decimal_value(value)
                except core.KirkprError:
                    pass
            return 1, value.casefold()

        children = list(tree.get_children(""))
        totals = [item for item in children if str(item).endswith(":totals") or "totals" in tree.item(item, "tags")]
        data = [item for item in children if item not in totals]
        items = sorted(data, key=key, reverse=reverse) + totals
        for position, item in enumerate(items):
            tree.move(item, "", position)
        tree.heading(column, command=lambda: self._sort_tree(tree, column, not reverse))

    def show_format_help(self) -> None:
        messagebox.showinfo(
            "Podprti formati / pravila ZIP",
            "Vhod (pridobivanje):\n\n"
            "• FURS DDV_KIR_KPR v JSON ali XML\n"
            "• CSV z glavo P2, P3 … in oznako KIR/KPR\n"
            "• ZIP z JSON / XML / CSV znotraj (skupaj ali ločeno KIR + KPR)\n"
            "• Minimax API — gumb »Podatki iz Minimaxa« (firma + obdobje)\n\n"
            "Pravila branja ZIP:\n"
            "1. Prebere vse člane .json, .xml, .csv\n"
            "2. Prednostni format (JSON/XML/CSV), če obstaja v ZIP-u\n"
            "3. Sicer najpopolnejši vir (več vrstic, obe knjigi; JSON > XML > CSV)\n"
            "4. Manjkajoči KIR ali KPR dopolni iz drugega člana\n"
            "5. Ugnezdeni ZIP: 1 nivo, če zunanji nima uporabnih podatkov\n\n"
            "Prenos v Minimax:\n"
            "• Minimax API — neposredna oddaja IR/PR\n"
            "• Datoteka XML za uvoz — Minimax XML (IR+PR) + ZIP\n\n"
            "Pri CSV: ločilo ;/,/tab/|, UTF-8 ali Windows-1250, zneski 1.234,56.",
            parent=self.root,
        )

    def retry_failed_api_rows(self) -> None:
        """Označi vrstice NAPAKA, jih predpreveri in ob uspehu ponudi oddajo."""
        if not hasattr(self, "api_tree"):
            return
        failed = [
            item
            for item in self.api_tree.get_children()
            if self.api_tree.set(item, "api_status") == "NAPAKA"
        ]
        if not failed:
            messagebox.showinfo("Ponovi NAPAKA", "Ni vrstic s stanjem NAPAKA.", parent=self.root)
            return
        self.api_tree.selection_set(failed)
        self.api_tree.focus(failed[0])
        self._on_api_tree_selection()
        self.log.info("Ponovna oddaja: označenih %s napak", len(failed))
        self.validate_api_selection(
            on_complete=lambda all_ok: self.send_api_selection() if all_ok else None,
        )

    def _write_api_send_summary(
        self,
        *,
        org_label: str,
        mode: str,
        status: str,
        ok: int,
        failed: int,
        rows: list[dict[str, Any]],
    ) -> Path | None:
        """Zapiše JSON povzetek zadnje API oddaje (brez gesel)."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = {
            "app_version": APP_VERSION,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "organisation": org_label,
            "mode": mode,
            "status": status,
            "ok": ok,
            "failed": failed,
            "rows": rows,
        }
        paths = self._company_paths()
        folder = paths.workspace / "API_oddaje" if paths else Path(__file__).resolve().parent / "API_oddaje"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"api_oddaja_{stamp}.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.log.info("Povzetek API oddaje: %s", target)
            return target
        except OSError as exc:
            self.log.warning("Povzetka API oddaje ni bilo mogoče shraniti: %s", exc)
            return None

    def _continue_source_transfer(self, mode: str) -> None:
        """Po pridobitvi nadaljuje prenos: Minimax API ali XML datoteka za uvoz."""
        choice = str(mode or "xml").strip().casefold()
        if choice not in {"api", "xml"}:
            choice = "xml"
        if not self.dataset:
            messagebox.showinfo(
                "Prenos",
                "Najprej pridobi KIR/KPR podatke v program.",
                parent=self.root,
            )
            return
        if choice == "xml":
            self.status_var.set("Prenos: pripravljam Minimax XML datoteke za uvoz …")
            self.export_files()
            return
        try:
            self.notebook.select(3)
        except tk.TclError:
            pass
        self.status_var.set("Prenos: Minimax API — povezava in oddaja …")
        self.root.after(120, lambda: self.transfer_api_group("ALL"))

    def open_source_acquisition_settings(self) -> None:
        """Pridobi KIR/KPR iz ZIP/JSON/XML/CSV in izberi prenos (API ali XML uvoz)."""
        window = tk.Toplevel(self.root)
        window.title("Pridobivanje in prenos — ZIP / API / XML")
        window.transient(self.root)
        window.grab_set()
        window.geometry("840x720")
        window.minsize(740, 640)
        window.configure(bg=self.colors["bg"])

        frame = ttk.Frame(window, style="Card.TFrame", padding=(18, 16))
        frame.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(frame, text="Pridobivanje podatkov (KIR / KPR)", style="SectionTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            frame,
            text="1) Izberi vir (ZIP/JSON/XML/CSV)  →  2) Izberi prenos v Minimax "
            "(API ali XML datoteka za uvoz)  →  3) Pridobi / Prenesi.",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=(4, 10))

        profile = self._profile_config()
        dir_var = tk.StringVar(
            value=str(
                self.config.get("source_input_dir")
                or profile.get("last_input_dir")
                or self.config.get("last_input_dir")
                or ""
            )
        )
        fmt_var = tk.StringVar(value=str(self.config.get("source_preferred_format") or "all"))
        file_var = tk.StringVar(
            value=str(profile.get("last_source_file") or self.config.get("last_source_file") or "")
        )
        reopen_var = tk.BooleanVar(value=bool(self.auto_reopen_var.get()))
        transfer_raw = str(self.config.get("source_transfer_mode") or "xml").strip().casefold()
        if transfer_raw not in {"api", "xml"}:
            transfer_raw = "xml"
        transfer_var = tk.StringVar(value=transfer_raw)
        after_var = tk.BooleanVar(value=bool(self.config.get("source_transfer_after_acquire")))
        summary_var = tk.StringVar(value="Izberi datoteko za pregled vsebine.")

        file_line = ttk.Frame(frame, style="Card.TFrame")
        file_line.pack(fill="x", pady=(0, 6))
        ttk.Label(file_line, text="Vir:", style="CardMuted.TLabel", width=14).pack(side="left")
        ttk.Entry(file_line, textvariable=file_var).pack(side="left", fill="x", expand=True, padx=(0, 8))

        preview = tk.Text(
            frame,
            height=10,
            wrap="word",
            font=("Consolas", 9),
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=8,
        )
        preview.pack(fill="both", expand=True, pady=(4, 6))
        preview.configure(state="disabled")

        def _set_preview(text: str) -> None:
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("1.0", text)
            preview.configure(state="disabled")

        def _probe(path_text: str | None = None) -> dict[str, Any] | None:
            path = Path(str(path_text if path_text is not None else file_var.get()).strip())
            if not path.name:
                summary_var.set("Izberi datoteko za pregled vsebine.")
                _set_preview("(ni izbrane datoteke)")
                return None
            if not path.is_file():
                summary_var.set(f"Datoteka ne obstaja: {path}")
                _set_preview(f"Datoteka ne obstaja:\n{path}")
                return None
            try:
                info = core.inspect_source(
                    path,
                    preferred_format=str(fmt_var.get() or "all"),
                )
            except Exception as exc:
                summary_var.set(f"Pregled ni uspel: {exc}")
                _set_preview(str(exc))
                return None

            lines = [
                f"Datoteka: {info.get('name')}",
                f"Velikost: {max(1, int(int(info.get('size') or 0) / 1024))} KB",
                f"Format: {info.get('format') or info.get('suffix') or '?'}",
                f"Prednost v ZIP: {(info.get('preferred_format') or 'all').upper()}",
                "",
                "Pravila ZIP: člani JSON / XML / CSV (tudi ločeno KIR+KPR);",
                "ugnezdeni ZIP 1 nivo; prednostni format, sicer najpopolnejši (JSON>XML>CSV).",
            ]
            if info.get("error"):
                lines.append("")
                lines.append("NAPAKA — podatkov ni mogoče pridobiti:")
                lines.append(str(info["error"]))
                members = list(info.get("members") or [])
                if members:
                    lines.append("")
                    lines.append(f"Vsebina ZIP ({len(members)}):")
                    for name in members[:40]:
                        lines.append(f"  · {name}")
                    if len(members) > 40:
                        lines.append(f"  … +{len(members) - 40}")
                summary_var.set("V ZIP/datoteki ni uporabnih KIR/KPR podatkov.")
                _set_preview("\n".join(lines))
                return info

            lines.extend(
                [
                    f"Davčna: {info.get('tax_id') or '(ni)'}",
                    f"Obdobje: {info.get('period_from') or '?'} – {info.get('period_to') or '?'}",
                    f"KIR (IR): {info.get('kir', 0)}",
                    f"KPR (PR): {info.get('kpr', 0)}",
                ]
            )
            usable = list(info.get("usable_members") or [])
            if usable:
                lines.append("")
                lines.append("Uporabljene datoteke iz vira:")
                for name in usable:
                    lines.append(f"  ✓ {name}")
            members = list(info.get("members") or [])
            if info.get("suffix") == ".zip" and members:
                lines.append("")
                lines.append(f"Celotna vsebina ZIP ({len(members)}):")
                for name in members[:25]:
                    mark = "✓" if name in usable or any(name in u for u in usable) else "·"
                    lines.append(f"  {mark} {name}")
                if len(members) > 25:
                    lines.append(f"  … +{len(members) - 25}")
            for warn in list(info.get("rejected") or [])[:4]:
                lines.append(f"Opozorilo: {warn}")
            mode_label = (
                "Minimax API"
                if transfer_var.get() == "api"
                else "XML datoteka za uvoz"
            )
            summary_var.set(
                f"Pripravljeno: {info.get('kir', 0)} KIR + {info.get('kpr', 0)} KPR"
                f"  ·  prenos: {mode_label}"
            )
            _set_preview("\n".join(lines))
            return info

        def pick_file() -> None:
            preferred = str(fmt_var.get() or "all").strip().casefold() or "all"
            picker_pref = "zip" if preferred == "all" else preferred
            selected = filedialog.askopenfilename(
                parent=window,
                title="Izberi ZIP / JSON / XML / CSV za pridobivanje KIR/KPR",
                initialdir=dir_var.get().strip() or self._source_picker_initial_dir(),
                filetypes=self._source_filetypes(picker_pref),
            )
            if not selected:
                return
            file_var.set(selected)
            if not dir_var.get().strip():
                dir_var.set(str(Path(selected).parent))
            _probe(selected)

        ttk.Button(file_line, text="Izberi…", width=10, command=pick_file).pack(side="left", padx=(0, 4))
        ttk.Button(file_line, text="Preglej", width=8, command=lambda: _probe()).pack(side="left")

        ttk.Label(frame, textvariable=summary_var, style="Muted.TLabel", wraplength=780).pack(
            anchor="w", pady=(0, 6)
        )

        transfer_box = ttk.LabelFrame(frame, text="Prenos v Minimax", padding=(10, 8))
        transfer_box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            transfer_box,
            text="Kam grejo pridobljeni podatki:",
            style="CardMuted.TLabel",
        ).pack(anchor="w")
        ttk.Radiobutton(
            transfer_box,
            text="Minimax API — neposredna oddaja IR/PR (povezava + predpreverjanje)",
            variable=transfer_var,
            value="api",
            command=lambda: _probe(),
        ).pack(anchor="w", pady=(4, 2))
        ttk.Radiobutton(
            transfer_box,
            text="Datoteka XML za uvoz — Minimax XML (IR + PR) + ZIP arhiv",
            variable=transfer_var,
            value="xml",
            command=lambda: _probe(),
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            transfer_box,
            text="Po »Pridobi v program« samodejno nadaljuj s prenosom (enako kot »Pridobi in prenesi«)",
            variable=after_var,
        ).pack(anchor="w", pady=(8, 0))

        opts = ttk.LabelFrame(frame, text="Vir (Ctrl+O)", padding=(10, 8))
        opts.pack(fill="x", pady=(0, 8))

        dir_line = ttk.Frame(opts, style="Card.TFrame")
        dir_line.pack(fill="x", pady=2)
        ttk.Label(dir_line, text="Privzeta mapa:", style="CardMuted.TLabel", width=16).pack(side="left")
        ttk.Entry(dir_line, textvariable=dir_var).pack(side="left", fill="x", expand=True, padx=(0, 8))

        def browse_dir() -> None:
            start = dir_var.get().strip() or self._source_picker_initial_dir()
            path = filedialog.askdirectory(
                parent=window,
                title="Mapa za KIR/KPR (ZIP/JSON/XML/CSV)",
                initialdir=start if Path(start).is_dir() else str(Path.cwd()),
            )
            if path:
                dir_var.set(path)

        ttk.Button(dir_line, text="…", width=3, command=browse_dir).pack(side="left")

        fmt_line = ttk.Frame(opts, style="Card.TFrame")
        fmt_line.pack(fill="x", pady=(6, 2))
        ttk.Label(fmt_line, text="Prednost v ZIP:", style="CardMuted.TLabel", width=16).pack(
            side="left"
        )
        for value, label in (
            ("zip", "ZIP"),
            ("json", "JSON"),
            ("xml", "XML"),
            ("csv", "CSV"),
            ("all", "Vsi"),
        ):
            ttk.Radiobutton(
                fmt_line,
                text=label,
                variable=fmt_var,
                value=value,
                command=lambda: _probe(),
            ).pack(side="left", padx=(0, 10))

        ttk.Checkbutton(
            opts,
            text="Ob zagonu samodejno odpri zadnjo datoteko",
            variable=reopen_var,
        ).pack(anchor="w", pady=(6, 0))

        def save_settings() -> bool:
            folder = dir_var.get().strip()
            preferred = str(fmt_var.get() or "all").strip().casefold() or "all"
            if preferred not in {"all", "zip", "json", "xml", "csv"}:
                preferred = "all"
            transfer_mode = str(transfer_var.get() or "xml").strip().casefold()
            if transfer_mode not in {"api", "xml"}:
                transfer_mode = "xml"
            self.config["source_input_dir"] = folder
            self.config["source_preferred_format"] = preferred
            self.config["source_transfer_mode"] = transfer_mode
            self.config["source_transfer_after_acquire"] = bool(after_var.get())
            self.auto_reopen_var.set(bool(reopen_var.get()))
            self.config["auto_reopen_last_source"] = bool(reopen_var.get())
            last_path = file_var.get().strip()
            if last_path:
                self.config["last_source_file"] = last_path
                self.config["last_input_dir"] = str(Path(last_path).parent)
                profile["last_source_file"] = last_path
                profile["last_input_dir"] = str(Path(last_path).parent)
            elif folder:
                self.config["last_input_dir"] = folder
                profile["last_input_dir"] = folder
            try:
                core.save_config(self.config, self.config_file)
            except OSError as exc:
                messagebox.showerror(
                    "Pridobivanje podatkov",
                    f"Shranjevanje ni uspelo:\n{exc}",
                    parent=window,
                )
                return False
            return True

        def acquire(*, and_transfer: bool = False) -> None:
            path = Path(file_var.get().strip())
            if not path.is_file():
                pick_file()
                path = Path(file_var.get().strip())
            if not path.is_file():
                messagebox.showwarning(
                    "Pridobivanje podatkov",
                    "Najprej izberi ZIP, JSON, XML ali CSV datoteko.",
                    parent=window,
                )
                return
            info = _probe(str(path))
            if info and info.get("error"):
                messagebox.showerror(
                    "Pridobivanje podatkov",
                    str(info.get("error") or "Podatkov ni mogoče pridobiti."),
                    parent=window,
                )
                return
            do_transfer = bool(and_transfer or after_var.get())
            if not save_settings():
                return
            transfer_mode = str(transfer_var.get() or "xml").strip().casefold()
            window.destroy()
            self.load_source(path)
            if self.dataset is None:
                return
            mode_label = "Minimax API" if transfer_mode == "api" else "XML datoteka za uvoz"
            members = ", ".join(self.dataset.source_members) or path.name
            if do_transfer:
                self.status_var.set(
                    f"Pridobljeno iz ZIP/vira: {len(self.dataset.kir)} KIR / "
                    f"{len(self.dataset.kpr)} KPR ({self.dataset.source_format}) — "
                    f"prenos: {mode_label}"
                )
                self.root.after(80, lambda: self._continue_source_transfer(transfer_mode))
                return
            messagebox.showinfo(
                "Pridobivanje podatkov",
                f"Pridobljeno iz: {path.name}\n\n"
                f"Format: {self.dataset.source_format}\n"
                f"Člani ZIP/vira: {members}\n"
                f"KIR (IR): {len(self.dataset.kir)}\n"
                f"KPR (PR): {len(self.dataset.kpr)}\n"
                f"Prenos (nastavljen): {mode_label}\n\n"
                "Za prenos uporabi »Pridobi in prenesi« ali gumbe "
                "Izvozi XML / Minimax API.",
                parent=self.root,
            )

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Zapri", style="Danger.TButton", command=window.destroy).pack(
            side="right"
        )
        ttk.Button(
            buttons,
            text="Pridobi in prenesi",
            style="Accent.TButton",
            command=lambda: acquire(and_transfer=True),
        ).pack(side="right", padx=(0, 8))
        ttk.Button(
            buttons,
            text="Samo pridobi",
            style="Success.TButton",
            command=lambda: acquire(and_transfer=False),
        ).pack(side="right", padx=(0, 8))
        ttk.Button(
            buttons,
            text="Shrani nastavitve",
            command=lambda: save_settings()
            and messagebox.showinfo(
                "Pridobivanje podatkov",
                "Nastavitve so shranjene.\n\n"
                f"Prednost v ZIP: {(fmt_var.get() or 'all').upper()}\n"
                f"Prenos: {'Minimax API' if transfer_var.get() == 'api' else 'XML za uvoz'}",
                parent=window,
            ),
        ).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Formati / pravila", command=self.show_format_help).pack(
            side="left"
        )

        if file_var.get().strip():
            _probe()

    def open_path_settings(self) -> None:
        """Dialog za poti: EvidencaFirm, TROPS, Minimax nastavitve."""
        window = tk.Toplevel(self.root)
        window.title("Nastavitve poti")
        window.transient(self.root)
        window.grab_set()
        window.geometry("720x320")
        window.minsize(640, 280)
        window.configure(bg=self.colors["bg"])

        frame = ttk.Frame(window, style="Card.TFrame", padding=(18, 16))
        frame.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(frame, text="Poti okolja (Cursor izdaja)", style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Spremembe veljajo takoj in se shranijo v lokalno konfiguracijo te mape.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        registry_var = tk.StringVar(value=str(self.config.get("company_registry_path") or ""))
        trops_var = tk.StringVar(value=str(self.config.get("trops_root") or company_registry.DEFAULT_TROPS_ROOT))
        settings_var = tk.StringVar(value=str(self.config.get("minimax_settings_path") or ""))

        def row(label: str, variable: tk.StringVar, browse: Callable[[], None]) -> None:
            line = ttk.Frame(frame, style="Card.TFrame")
            line.pack(fill="x", pady=5)
            ttk.Label(line, text=label, style="CardMuted.TLabel", width=22).pack(side="left")
            ttk.Entry(line, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 8))
            ttk.Button(line, text="…", width=3, command=browse).pack(side="left")

        def browse_registry() -> None:
            path = filedialog.askopenfilename(
                parent=window,
                title="Izberi firme_evidenca.json",
                filetypes=[("JSON", "*.json"), ("Vse datoteke", "*.*")],
            )
            if path:
                registry_var.set(path)

        def browse_trops() -> None:
            path = filedialog.askdirectory(parent=window, title="Izberi korensko mapo TROPS")
            if path:
                trops_var.set(path)

        def browse_settings() -> None:
            path = filedialog.askopenfilename(
                parent=window,
                title="Izberi Minimax API nastavitve",
                filetypes=[("JSON", "*.json"), ("Vse datoteke", "*.*")],
            )
            if path:
                settings_var.set(path)

        row("EvidencaFirm JSON:", registry_var, browse_registry)
        row("TROPS koren:", trops_var, browse_trops)
        row("Minimax settings:", settings_var, browse_settings)

        def save() -> None:
            self.config["company_registry_path"] = registry_var.get().strip()
            self.config["trops_root"] = trops_var.get().strip()
            self.config["minimax_settings_path"] = settings_var.get().strip()
            try:
                core.save_config(self.config, self.config_file)
            except OSError as exc:
                messagebox.showerror("Nastavitve poti", f"Shranjevanje ni uspelo:\n{exc}", parent=window)
                return
            preferred = str(self.config.get("company_registry_path") or "")
            self.company_registry_path, self.companies = company_registry.load_companies(preferred or None)
            if hasattr(self, "_populate_company_tree"):
                try:
                    self._populate_company_tree()
                except Exception:
                    pass
            self.log.info(
                "Posodobljene poti: registry=%s trops=%s settings=%s",
                self.config.get("company_registry_path"),
                self.config.get("trops_root"),
                self.config.get("minimax_settings_path"),
            )
            self.status_var.set("Nastavitve poti so shranjene.")
            window.destroy()

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Prekliči", style="Danger.TButton", command=window.destroy).pack(side="right")
        ttk.Button(buttons, text="Shrani", style="Success.TButton", command=save).pack(side="right", padx=(0, 8))

    def open_log_file(self) -> None:
        path = kirkpr_logging.default_log_path()
        if not path.exists():
            messagebox.showinfo("Dnevnik", f"Dnevnik še ne obstaja:\n{path}", parent=self.root)
            return
        open_in_file_manager(path)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError:
            pass

    def show_cursor_changelog(self) -> None:
        messagebox.showinfo(
            "Kaj je novega (Cursor)",
            f"{APP_DISPLAY_TITLE}\n\n"
            "• Samostojni program v mapi D:\\PISARNA\\Python\\KirKpr\n"
            "• Strukturiran dnevnik KIRKPR_studio.log\n"
            "• Meni: Nastavitve poti (EvidencaFirm, TROPS, Minimax settings)\n"
            "• Gumb »Ponovi NAPAKA« za ponovno oddajo neuspešnih vrstic\n"
            "• JSON povzetek vsake API oddaje v mapi API_oddaje\n"
            "• CLI: --validate, --dry-run, --summary-json\n"
            "• API tabela in oddaja sta urejeni po listini (P3)\n"
            "• JSON pogled / Minimax pogled + razlika program ↔ Minimax\n"
            "• ODDANO se počisti, če je osnutek v Minimaxu zbrisan\n"
            "• Listina (vezna št.) se pred ustvarjanjem ne sme podvajati\n"
            "• Filter obdobja (‹ mesec/jan-mar… › + datum od/do, P4) za JSON in Minimax\n\n"
            "Zahtevana Chrome razširitev: v" + CHROME_EXTENSION_VERSION,
            parent=self.root,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "O programu",
            f"{APP_DISPLAY_TITLE}\n"
            f"Izdaja: {APP_EDITION}\n\n"
            "Pretvornik za izdane in prejete račune z urejanjem PR kontov, "
            "dvostavno bilančno kontrolo in Minimax XSD-validacijo.\n\n"
            "Privzeti konto storitev PR: 4190\n"
            f"Dnevnik: {kirkpr_logging.default_log_path()}",
            parent=self.root,
        )


def cli_convert(input_path: Path, output_dir: Path, xsd_path: Path | None = None) -> int:
    log = kirkpr_logging.get_logger()
    config = core.load_config()
    dataset = core.load_dataset(input_path)
    core.apply_saved_accounts(dataset, config)
    result = core.export_minimax(dataset, output_dir, xsd_path=xsd_path)
    print(f"Izdani računi: {result.issued_count} -> {result.issued_xml}")
    print(f"Prejeti računi: {result.received_count} -> {result.received_xml}")
    print(f"ZIP: {result.archive}")
    print(f"XSD-validacija: {'DA' if result.xsd_validated else 'NE'}")
    log.info("CLI izvoz: IR=%s PR=%s xsd=%s", result.issued_count, result.received_count, result.xsd_validated)
    return 0


def cli_validate(input_path: Path, *, summary_json: Path | None = None) -> int:
    """Brez GUI preveri podatke, DDV-O kontrolo in izpiše povzetek."""
    log = kirkpr_logging.setup_logging(console=True)
    config = core.load_config()
    dataset = core.load_dataset(input_path)
    core.apply_saved_accounts(dataset, config)
    summary = core.dataset_summary(dataset)
    ddvo = core.ddvo_summary(dataset)
    print(f"Vir: {dataset.source_path}")
    print(f"Format: {dataset.source_format}")
    print(f"Obdobje: {dataset.period_from} do {dataset.period_to}")
    print(f"IR: {summary.get('ir_count', len(dataset.kir))} | PR: {summary.get('pr_count', len(dataset.kpr))}")
    print(f"DDV-O 51 (obveznost): {ddvo['obligation']} EUR")
    print(f"DDV-O 52 (presežek): {ddvo['excess']} EUR")
    print(f"Kontrola DDV-O: {'OK' if ddvo['control_ok'] else 'NAPAKA'} (razlika {ddvo['control_difference']})")
    if dataset.warnings:
        print("Opozorila:")
        for warning in dataset.warnings:
            print(f"  - {warning}")
    payload = {
        "source": str(dataset.source_path),
        "period_from": dataset.period_from,
        "period_to": dataset.period_to,
        "summary": {key: str(value) for key, value in summary.items()},
        "ddvo": {
            "obligation": str(ddvo["obligation"]),
            "excess": str(ddvo["excess"]),
            "control_ok": ddvo["control_ok"],
            "control_difference": str(ddvo["control_difference"]),
        },
        "warnings": list(dataset.warnings),
    }
    if summary_json:
        summary_json = Path(summary_json)
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"JSON povzetek: {summary_json}")
    log.info("CLI validate: control_ok=%s", ddvo["control_ok"])
    return 0 if ddvo["control_ok"] else 1


def cli_dry_run(input_path: Path, xsd_path: Path | None = None) -> int:
    """Izvoz v začasno mapo za preverjanje XSD, nato pobriše izhod."""
    log = kirkpr_logging.setup_logging(console=True)
    config = core.load_config()
    dataset = core.load_dataset(input_path)
    core.apply_saved_accounts(dataset, config)
    with tempfile.TemporaryDirectory(prefix="kirkpr_dryrun_") as temp_dir:
        result = core.export_minimax(dataset, Path(temp_dir), xsd_path=xsd_path, create_archive=True)
        print("DRY-RUN (datoteke niso ohranjene)")
        print(f"Izdani računi: {result.issued_count}")
        print(f"Prejeti računi: {result.received_count}")
        print(f"XSD-validacija: {'DA' if result.xsd_validated else 'NE'}")
        print(f"Začasni ZIP: {result.archive.name}")
        log.info(
            "CLI dry-run: IR=%s PR=%s xsd=%s",
            result.issued_count,
            result.received_count,
            result.xsd_validated,
        )
        schema = xsd_path or core.find_xsd()
        if schema and not result.xsd_validated:
            return 1
        return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pretvori FURS KIR/KPR (ZIP/JSON/XML/CSV) v Minimax XML. Cursor izdaja doda --validate/--dry-run.",
    )
    parser.add_argument("input", nargs="?", type=Path, help="Vhodna ZIP, JSON, XML ali CSV datoteka")
    parser.add_argument("--output", "-o", type=Path, help="Izhodna mapa; če je podana, program deluje brez forme")
    parser.add_argument("--xsd", type=Path, help="Izbirna pot do miniMAXUvozKnjigovodstvo.xsd")
    parser.add_argument("--validate", action="store_true", help="Samo preveri podatke in DDV-O (brez izvoza/GUI)")
    parser.add_argument("--dry-run", action="store_true", help="Izvoz v začasno mapo + XSD, brez trajnega zapisa")
    parser.add_argument("--summary-json", type=Path, help="Pri --validate zapiše JSON povzetek na to pot")
    parser.add_argument("--log-level", default="", help="DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.log_level:
        kirkpr_logging.setup_logging(level=args.log_level, console=True)

    if args.validate or args.dry_run or args.output:
        if not args.input:
            print("Napaka: pri CLI načinu morate podati vhodno datoteko.", file=sys.stderr)
            return 2
        try:
            if args.validate:
                return cli_validate(args.input, summary_json=args.summary_json)
            if args.dry_run:
                return cli_dry_run(args.input, args.xsd)
            return cli_convert(args.input, args.output, args.xsd)
        except Exception as exc:
            print(f"Napaka: {exc}", file=sys.stderr)
            kirkpr_logging.get_logger().exception("CLI napaka")
            return 1

    root = tk.Tk()
    ConverterApp(root, args.input)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
