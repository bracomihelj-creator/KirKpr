# -*- coding: utf-8 -*-
"""Most med WebView2 vmesnikom in obstoječimi funkcijami KirKpr.

Ta modul ne uvaja novih izračunov, DDV pravil, XML izvoza ali API oddaje.
Samo kliče kirkpr_minimax_core, register podjetij in pomožne funkcije obdobja.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import kirkpr_company_registry as registry
import kirkpr_minimax_core as core
import convert_KIrKpr_to_minimax as gui_helpers

APP_VERSION = "5.0.01"
APP_TITLE = "KIR/KPR \u2192 Minimax Studio"
APP_EDITION = "WebView2"


def _money(value: Any) -> str:
    return gui_helpers.format_money(value)


def _dec(value: Any) -> str:
    try:
        return f"{core.decimal_value(value):.2f}"
    except core.KirkprError:
        return "0.00"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _company_public(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": registry.company_key(record),
        "name": registry.company_name(record),
        "zst": registry.company_zst(record),
        "tax": registry.company_tax_number(record),
        "org_id": registry.company_org_id(record),
        "oddaja_ddv": registry.company_oddaja_ddv(record),
        "responsible": registry.company_responsible_person(record),
    }


class KirKprService:
    """Stanje seje za namizni vmesnik 5.0.01 (brez Tk)."""

    def __init__(self, *, config_path: Path | None = None, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parent).resolve()
        self.config_path = Path(config_path) if config_path else core.config_path(self.base_dir)
        self.config = core.load_config(self.config_path)
        self.dataset: core.KirkprDataset | None = None
        self.companies: list[dict[str, Any]] = []
        self.registry_file: Path | None = None
        self.selected_company: dict[str, Any] | None = None
        self.period_from: date | None = None
        self.period_to: date | None = None
        self.period_label = ""
        self.search_ir = ""
        self.search_pr = ""
        self.search_ddvo = ""
        self._reload_companies()
        self._restore_selected_company()

    def _reload_companies(self) -> None:
        preferred = self.config.get("company_registry_path") or None
        self.registry_file, rows = registry.load_companies(preferred)
        self.companies = [dict(row) for row in rows]

    def _restore_selected_company(self) -> None:
        key = str(self.config.get("selected_company_key") or "").strip()
        if key:
            found = registry.find_company(self.companies, key)
            if found:
                self.selected_company = found
                return
        self.selected_company = None

    def _period_tuple(self) -> tuple[date, date] | None:
        if self.period_from and self.period_to:
            return self.period_from, self.period_to
        return None

    def _row_in_period(self, book: str, row: Mapping[str, Any]) -> bool:
        bounds = self._period_tuple()
        if bounds is None:
            return True
        parsed = gui_helpers.row_filter_date(book, row)
        if parsed is None:
            return True
        start, end = bounds
        return start <= parsed <= end

    def _row_in_ddvo_period(self, row: Mapping[str, Any]) -> bool:
        bounds = self._period_tuple()
        if bounds is None:
            return True
        start, end = bounds
        header_year = start.year
        if self.dataset:
            header_from = gui_helpers.parse_iso_date(self.dataset.period_from)
            if header_from is not None:
                header_year = header_from.year
        return gui_helpers.row_in_ddvo_period(row, start, end, header_year=header_year)

    def _ddvo_view_dataset(self) -> core.KirkprDataset | None:
        if not self.dataset:
            return None
        bounds = self._period_tuple()
        header_from = gui_helpers.parse_iso_date(self.dataset.period_from)
        header_to = gui_helpers.parse_iso_date(self.dataset.period_to)
        if bounds is None or (
            header_from and header_to and bounds[0] <= header_from and bounds[1] >= header_to
        ):
            return self.dataset
        start, end = bounds
        header = dict(self.dataset.header)
        header['OBDOBJE_OD'] = start.isoformat()
        header['OBDOBJE_DO'] = end.isoformat()
        return core.KirkprDataset(
            header=header,
            kir=[row for row in self.dataset.kir if self._row_in_ddvo_period(row)],
            kpr=[row for row in self.dataset.kpr if self._row_in_ddvo_period(row)],
            source_path=self.dataset.source_path,
            source_format=self.dataset.source_format,
            source_members=list(self.dataset.source_members),
            warnings=list(self.dataset.warnings),
        )

    def _set_period_from_dataset(self) -> None:
        if not self.dataset:
            return
        start = gui_helpers.parse_iso_date(self.dataset.period_from)
        end = gui_helpers.parse_iso_date(self.dataset.period_to)
        if start and end:
            self.period_from, self.period_to = start, end
            self.period_label = gui_helpers.period_label_for_range(start, end)

    def _state(self) -> dict[str, Any]:
        summary = None
        if self.dataset:
            raw = core.dataset_summary(self.dataset)
            summary = {
                "ir_count": raw["ir_count"],
                "kir_count": raw["kir_count"],
                "tax_only_kir_count": raw["tax_only_kir_count"],
                "pr_count": raw["pr_count"],
                "ir_net": _money(raw["ir_net"]),
                "ir_vat": _money(raw["ir_vat"]),
                "pr_net": _money(raw["pr_net"]),
                "pr_vat": _money(raw["pr_vat"]),
                "source": str(self.dataset.source_path),
                "source_name": self.dataset.source_path.name,
                "source_format": self.dataset.source_format,
                "warnings": list(self.dataset.warnings),
                "period_from": self.dataset.period_from,
                "period_to": self.dataset.period_to,
            }
        company = _company_public(self.selected_company) if self.selected_company else None
        return {
            "ok": True,
            "version": APP_VERSION,
            "title": f"{APP_TITLE} v{APP_VERSION}",
            "edition": APP_EDITION,
            "company": company,
            "period_from": self.period_from.isoformat() if self.period_from else "",
            "period_to": self.period_to.isoformat() if self.period_to else "",
            "period_label": self.period_label,
            "has_data": self.dataset is not None,
            "summary": summary,
            "paths": {
                "config": str(self.config_path),
                "registry": str(self.registry_file or self.config.get("company_registry_path") or ""),
                "trops_root": str(self.config.get("trops_root") or ""),
                "minimax_settings": str(self.config.get("minimax_settings_path") or ""),
                "last_source": str(self.config.get("last_source_file") or ""),
            },
        }

    def boot(self) -> dict[str, Any]:
        state = self._state()
        state["companies"] = [_company_public(c) for c in self.companies]
        state["company_count"] = len(self.companies)
        return state

    def list_companies(self, search: str = "") -> dict[str, Any]:
        self._reload_companies()
        needle = str(search or "").casefold().strip()
        rows = [_company_public(c) for c in self.companies]
        if needle:
            rows = [
                r
                for r in rows
                if needle in " ".join(str(r.get(k) or "") for k in ("name", "zst", "tax", "org_id", "key")).casefold()
            ]
        return {"ok": True, "rows": rows, "registry": str(self.registry_file or ""), "count": len(rows)}

    def select_company(self, key: str = "") -> dict[str, Any]:
        self._reload_companies()
        wanted = str(key or "").strip()
        found = registry.find_company(self.companies, wanted) if wanted else None
        self.selected_company = found
        if found:
            oddaja = registry.company_oddaja_ddv(found)
            # Samo predlaga obdobje, če podatki še niso naloženi.
            if self.dataset is None:
                bounds = gui_helpers.period_bounds_for_oddaja_ddv(oddaja) if oddaja else None
                if bounds:
                    self.period_from, self.period_to = bounds
                    self.period_label = gui_helpers.period_label_for_range(*bounds)
        return self._state()

    def set_period(self, period_from: str = "", period_to: str = "", label: str = "") -> dict[str, Any]:
        start = gui_helpers.parse_iso_date(period_from)
        end = gui_helpers.parse_iso_date(period_to)
        if start and end:
            if end < start:
                start, end = end, start
            self.period_from, self.period_to = start, end
            self.period_label = label or gui_helpers.period_label_for_range(start, end)
        elif not period_from and not period_to:
            self.period_from = self.period_to = None
            self.period_label = "Celotno obdobje podatkov"
        return self._state()

    def shift_period(self, delta: int = 1) -> dict[str, Any]:
        if not (self.period_from and self.period_to):
            self._set_period_from_dataset()
        if not (self.period_from and self.period_to):
            return self._state()
        # Premik za en mesec, kot v Tk vmesniku.
        step = -1 if int(delta) < 0 else 1
        year, month = self.period_from.year, self.period_from.month + step
        if month < 1:
            year, month = year - 1, 12
        elif month > 12:
            year, month = year + 1, 1
        start, end = gui_helpers.month_bounds(year, month)
        self.period_from, self.period_to = start, end
        self.period_label = gui_helpers.period_label_for_range(start, end)
        return self._state()

    def reset_period(self) -> dict[str, Any]:
        if self.dataset:
            self._set_period_from_dataset()
        else:
            self.period_from = self.period_to = None
            self.period_label = ""
        return self._state()

    def load_source(self, path: str, *, preferred_format: str | None = None) -> dict[str, Any]:
        source = Path(path).expanduser()
        preferred = preferred_format or str(self.config.get("source_preferred_format") or "all")
        dataset = core.load_dataset(source, preferred_format=preferred)
        core.apply_saved_accounts(dataset, self.config)
        if self.selected_company is None:
            tax = dataset.header.get("TaxPayerID") or dataset.header.get("Davcna") or ""
            match = registry.match_company(self.companies, tax_number=tax, source_path=dataset.source_path)
            if match:
                self.selected_company = match
        self.dataset = dataset
        self._set_period_from_dataset()
        state = self._state()
        state["msg"] = f"Naloženo: {dataset.source_path.name} ({len(dataset.kir)} IR, {len(dataset.kpr)} PR)."
        return state

    def _haystack_matches(self, tokens: list[str], chunks: list[Any]) -> bool:
        if not tokens:
            return True
        hay = " ".join(str(c or "") for c in chunks).casefold()
        return all(token in hay for token in tokens)

    def _tokens(self, text: str) -> list[str]:
        return [part for part in str(text or "").casefold().split() if part]

    def list_ir(self, search: str = "") -> dict[str, Any]:
        self.search_ir = search
        return self._list_book("IR", search)

    def list_pr(self, search: str = "") -> dict[str, Any]:
        self.search_pr = search
        return self._list_book("PR", search)

    def _list_book(self, book: str, search: str) -> dict[str, Any]:
        if self.dataset is None:
            return {"ok": True, "rows": [], "count": 0, "visible": 0, "has_data": False}
        tokens = self._tokens(search)
        rows_out: list[dict[str, Any]] = []
        source_rows = self.dataset.kir if book == "IR" else self.dataset.kpr
        for index, row in enumerate(source_rows):
            if not self._row_in_period(book, row):
                continue
            if book == "IR":
                metrics = core.ir_metrics(row, self.dataset.kpr)
                tax_only = bool(metrics["tax_only"])
                account = str(row.get("__konto__") or self.config.get("ir_revenue_account") or "7601")
                obravnava = "Samoobdavčitev \u2192 PR" if tax_only else "Izvoz v IR"
                party = str(row.get("P5") or "")
                tax_id = str(row.get("P6DS") or "")
                item = {
                    "id": f"ir:{index}",
                    "zapst": str(row.get("ZAPST") or ""),
                    "date": str(row.get("P2") or ""),
                    "invoice": str(row.get("P3") or ""),
                    "party": party,
                    "tax_id": tax_id,
                    "net": _money(metrics["net"]),
                    "vat_22": _money(metrics["vat_22"]),
                    "vat_95": _money(metrics["vat_95"]),
                    "vat": _money(metrics["vat"]),
                    "gross": _money(metrics["gross"]),
                    "account": account,
                    "minimax_status": "\u2014",
                    "status": obravnava,
                    "tax_only": tax_only,
                    "tag": "tax_only" if tax_only else "",
                }
                extra = [obravnava, "kupec", party]
            else:
                metrics = core.pr_metrics(row)
                self_assessment = bool(metrics["self_assessment"])
                vat_deductible = bool(metrics["vat_deductible"])
                account = str(row.get("__konto__") or self.config.get("pr_default_account") or "4190")
                vrsta = "Samoobdavčitev" if self_assessment else "Prejeti račun"
                party = str(row.get("P6") or "")
                tax_id = str(row.get("P7DS") or "")
                item = {
                    "id": f"pr:{index}",
                    "zapst": str(row.get("ZAPST") or ""),
                    "date": str(row.get("P2") or ""),
                    "invoice": str(row.get("P3") or ""),
                    "party": party,
                    "tax_id": tax_id,
                    "net": _money(metrics["net"]),
                    "vat_22": _money(metrics["vat_22"]),
                    "vat_95": _money(metrics["vat_95"]),
                    "vat": _money(metrics["vat"]),
                    "gross": _money(metrics["gross"]),
                    "account": account,
                    "self_tax": "DA" if self_assessment else "NE",
                    "vat_deductible": "DA" if vat_deductible else "NE",
                    "minimax_status": "\u2014",
                    "status": vrsta,
                    "self_assessment": self_assessment,
                    "tag": "vat_not_deducted" if not vat_deductible else ("self_assessment" if self_assessment else ""),
                }
                extra = [vrsta, "dobavitelj", party, item["self_tax"], item["vat_deductible"]]
            chunks = [
                item["zapst"],
                item["date"],
                item["invoice"],
                item["party"],
                item["tax_id"],
                item["net"],
                item["vat"],
                item["gross"],
                item["account"],
                item["status"],
                *extra,
            ]
            if not self._haystack_matches(tokens, chunks):
                continue
            rows_out.append(item)
        return {
            "ok": True,
            "book": book,
            "rows": rows_out,
            "count": len(source_rows),
            "visible": len(rows_out),
            "has_data": True,
        }

    def ddvo(self, search: str = "") -> dict[str, Any]:
        self.search_ddvo = search
        if self.dataset is None:
            return {"ok": True, "has_data": False, "fields": [], "control_ok": True}
        view = self._ddvo_view_dataset() or self.dataset
        raw = core.ddvo_summary(view)
        tokens = self._tokens(search)
        fields = []
        for item in raw["fields"]:
            row = {
                "section": item.get("section") or "",
                "code": item.get("code") or "",
                "label": item.get("label") or "",
                "book": item.get("book") or "",
                "source": item.get("source") or "",
                "exact": _money(item.get("exact")),
                "value": _money(item.get("value")),
                "difference": _money(item.get("difference")),
                "status": item.get("status") or "",
            }
            if tokens and not self._haystack_matches(tokens, list(row.values())):
                continue
            fields.append(row)
        return {
            "ok": True,
            "has_data": True,
            "fields": fields,
            "output_vat": _money(raw["output_vat"]),
            "input_vat": _money(raw["input_vat"]),
            "obligation": _money(raw["obligation"]),
            "excess": _money(raw["excess"]),
            "control_difference": _money(raw["control_difference"]),
            "control_ok": bool(raw["control_ok"]),
            "self_assessment_count": raw["self_assessment_count"],
            "vat_not_deducted_count": raw["vat_not_deducted_count"],
            "taxpayer": str(self.dataset.header.get("TaxPayerID") or ""),
            "period_from": self.dataset.period_from,
            "period_to": self.dataset.period_to,
        }

    def path_settings(self) -> dict[str, Any]:
        return {
            "ok": True,
            "company_registry_path": str(self.config.get("company_registry_path") or ""),
            "trops_root": str(self.config.get("trops_root") or ""),
            "minimax_settings_path": str(self.config.get("minimax_settings_path") or ""),
        }

    def save_path_settings(
        self,
        *,
        company_registry_path: str = "",
        trops_root: str = "",
        minimax_settings_path: str = "",
    ) -> dict[str, Any]:
        self.config["company_registry_path"] = str(company_registry_path or "").strip()
        self.config["trops_root"] = str(trops_root or "").strip()
        self.config["minimax_settings_path"] = str(minimax_settings_path or "").strip()
        core.save_config(self.config, self.config_path)
        self._reload_companies()
        state = self._state()
        state["msg"] = "Nastavitve poti so shranjene."
        state["paths_form"] = self.path_settings()
        return state

    def open_last_source(self) -> dict[str, Any]:
        path = str(self.config.get("last_source_file") or "").strip()
        if not path or not Path(path).is_file():
            return {"ok": False, "error": "Zadnja datoteka ni shranjena ali ne obstaja več.", "msg": "Zadnja datoteka ni shranjena ali ne obstaja več."}
        return self.load_source(path)