# -*- coding: utf-8 -*-
"""Most med WebView2 vmesnikom in obstoječimi funkcijami KirKpr.

Ta modul ne uvaja novih izračunov, DDV pravil, XML izvoza ali API oddaje.
Samo kliče kirkpr_minimax_core, register podjetij in pomožne funkcije obdobja.
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

import kirkpr_company_registry as registry
import kirkpr_sessions_db as sessions_db
import minimax_api_client as minimax_api
import kirkpr_minimax_core as core
import convert_KIrKpr_to_minimax as gui_helpers

APP_VERSION = "5.0.06"
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

    def __init__(self, *, config_path: Path | None = None, base_dir: Path | None = None, sessions_db_path: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parent).resolve()
        self.config_path = Path(config_path) if config_path else core.config_path(self.base_dir)
        self.config = core.load_config(self.config_path)
        self.dataset: core.KirkprDataset | None = None
        self.source_dataset: core.KirkprDataset | None = None
        self.companies: list[dict[str, Any]] = []
        self.registry_file: Path | None = None
        self.selected_company: dict[str, Any] | None = None
        self.period_from: date | None = None
        self.period_to: date | None = None
        self.period_label = ""
        self.search_ir = ""
        self.search_pr = ""
        self.search_ddvo = ""
        self.account_catalog: dict[str, str] = {}
        self.remember_customer = True
        self.remember_supplier = True
        self.working_dirty = False
        self.pending_working_changes: list[str] = []
        self.knjiga_view_mode = "json"
        self.knjiga_records: dict[str, list[dict[str, Any]]] = {"IR": [], "PR": []}
        self.knjiga_period: tuple[str, str] | None = None
        self.minimax_client = None
        self._selected_session_id: int | None = None
        db_path = Path(sessions_db_path) if sessions_db_path else sessions_db.default_db_path(self.base_dir)
        self.sessions_db = sessions_db.SessionsDb(db_path)
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
            "working_dirty": self.working_dirty,
            "auto_reopen": bool(self.config.get("auto_reopen_last_source")),
            "theme": str(self.config.get("ui_theme") or "light"),
            "selected_session_id": self._selected_session_id,
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
        self.source_dataset = copy.deepcopy(dataset)
        core.apply_saved_accounts(dataset, self._profile_config())
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

    def _profile_config(self) -> dict[str, Any]:
        if not self.selected_company:
            return self.config
        return core.company_profile(self.config, registry.company_key(self.selected_company))

    def _mark_working_dirty(self, detail: str = "") -> None:
        self.working_dirty = True
        if detail:
            self.pending_working_changes.append(detail)

    def _persist_config(self) -> None:
        core.save_config(self.config, self.config_path)

    def _parse_row_id(self, row_id: str) -> tuple[str, int]:
        text = str(row_id or "").strip()
        if ":" not in text:
            raise core.KirkprError("Manjka oznaka vrstice.")
        book, _, raw_index = text.partition(":")
        book = book.upper()
        if book not in {"IR", "PR"}:
            raise core.KirkprError("Oznaka vrstice mora biti IR ali PR.")
        try:
            index = int(raw_index)
        except ValueError as exc:
            raise core.KirkprError("Neveljavna oznaka vrstice.") from exc
        return book, index

    def _row_by_id(self, row_id: str) -> tuple[str, int, dict[str, Any]]:
        if self.dataset is None:
            raise core.KirkprError("Najprej odprite KIR/KPR datoteko.")
        book, index = self._parse_row_id(row_id)
        rows = self.dataset.kir if book == "IR" else self.dataset.kpr
        if index < 0 or index >= len(rows):
            raise core.KirkprError("Vrstica ne obstaja.")
        return book, index, rows[index]

    def _account_name(self, account: Any) -> str:
        return self.account_catalog.get(str(account or "").strip(), "")

    def _account_label(self, account: Any) -> str:
        code = core.normalize_account_code(account)
        name = self._account_name(code)
        return f"{code} — {name}" if code and name else code

    def _validated_account_code(self, value: Any) -> str:
        catalog = self.account_catalog or None
        return core.validate_minimax_account_code(value, catalog=catalog)

    def account_choices(self, query: str = "") -> dict[str, Any]:
        codes = list(gui_helpers.COMMON_PR_ACCOUNTS + gui_helpers.COMMON_IR_ACCOUNTS)
        if self.dataset:
            for row in (*self.dataset.kir, *self.dataset.kpr):
                code = str(row.get("__konto__") or "").strip()
                if code:
                    codes.append(code)
        for code in self.account_catalog:
            codes.append(code)
        unique: list[str] = []
        seen: set[str] = set()
        for code in codes:
            normalized = core.normalize_account_code(code)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)

        def sort_key(code: str) -> tuple[int, int, str]:
            return (0, int(code), code) if code.isdigit() else (1, 0, code.casefold())

        labels = [self._account_label(code) for code in sorted(unique, key=sort_key)]
        terms = gui_helpers.ConverterApp._account_search_value(query).split() if query else []
        if terms:
            labels = [
                label
                for label in labels
                if all(term in gui_helpers.ConverterApp._account_search_value(label) for term in terms)
            ]
        return {"ok": True, "rows": labels}

    def _validated_document_changes(
        self,
        book: str,
        row: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        candidate = copy.deepcopy(dict(row))
        changes: dict[str, Any] = {}
        for field_name, raw in values.items():
            entered = str(raw)
            current = "" if row.get(field_name) is None else str(row.get(field_name))
            if entered == current:
                continue
            if gui_helpers.is_money_field(book, field_name):
                try:
                    if core.decimal_value(entered) == core.decimal_value(row.get(field_name)):
                        continue
                except core.KirkprError:
                    pass
            normalized = core.update_working_row(book, candidate, field_name, entered)
            changes[field_name] = normalized
        return changes

    def get_editor(self, row_id: str) -> dict[str, Any]:
        book, index, row = self._row_by_id(row_id)
        labels = gui_helpers.IR_FIELD_LABELS if book == "IR" else gui_helpers.PR_FIELD_LABELS
        default_account = "7601" if book == "IR" else "4190"
        account = str(row.get("__konto__") or default_account)
        fields = []
        for field_name, label in labels.items():
            raw_value = row.get(field_name)
            money = gui_helpers.is_money_field(book, field_name)
            shown = gui_helpers.format_money(raw_value) if money else ("" if raw_value is None else str(raw_value))
            ddvo = core.ddvo_codes_for_field(book, field_name)
            fields.append({
                "name": field_name,
                "label": label,
                "value": shown,
                "money": money,
                "vat_base": field_name in gui_helpers.VAT_BASE_RATE_FIELDS,
                "ddvo": list(ddvo),
            })
        payload: dict[str, Any] = {
            "ok": True,
            "id": f"{book.lower()}:{index}",
            "book": book,
            "invoice": str(row.get("P3") or ""),
            "party": str(row.get("P5") if book == "IR" else row.get("P6") or ""),
            "account": account,
            "account_label": self._account_label(account),
            "account_name": self._account_name(account),
            "description": str(row.get("__opis__") or row.get("P3") or ""),
            "remember_rule": self.remember_customer if book == "IR" else self.remember_supplier,
            "fields": fields,
        }
        if book == "PR":
            metrics = core.pr_metrics(row)
            payload["self_assessment"] = bool(metrics["self_assessment"])
            payload["vat_deductible"] = bool(metrics["vat_deductible"])
        return payload

    def save_editor(self, row_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        book, _index, row = self._row_by_id(row_id)
        default_account = "7601" if book == "IR" else "4190"
        account = self._validated_account_code(payload.get("account") or default_account)
        description = str(payload.get("description") or "").strip()
        remember_rule = bool(payload.get("remember_rule"))
        values = payload.get("fields") if isinstance(payload.get("fields"), Mapping) else {}
        document_changes = self._validated_document_changes(book, row, values)
        validation_config = copy.deepcopy(self._profile_config())
        core.remember_account(validation_config, book, row, account, supplier_rule=remember_rule)
        core.remember_description(validation_config, book, row, description)
        change_count = len(document_changes)
        change_count += account != str(row.get("__konto__") or default_account)
        change_count += description != str(row.get("__opis__") or row.get("P3") or "")
        if book == "PR":
            self_assessment = bool(payload.get("self_assessment"))
            vat_deductible = bool(payload.get("vat_deductible"))
            core.remember_self_assessment(validation_config, row, self_assessment, supplier_rule=remember_rule)
            core.remember_vat_deductible(validation_config, row, vat_deductible, supplier_rule=remember_rule)
            change_count += self_assessment != core.is_self_assessment(row)
            change_count += vat_deductible != core.vat_is_deductible(row)
        if not change_count:
            state = self._state()
            state["msg"] = f"{book} {row.get('P3')}: ni sprememb za začasno shranjevanje."
            return state
        document_name = str(row.get("P3") or "brez številke")
        profile = self._profile_config()
        core.remember_account(profile, book, row, account, supplier_rule=remember_rule)
        core.remember_description(profile, book, row, description)
        row.update(document_changes)
        row["__konto__"] = account
        row["__opis__"] = description
        if book == "PR":
            core.remember_self_assessment(profile, row, self_assessment, supplier_rule=remember_rule)
            core.remember_vat_deductible(profile, row, vat_deductible, supplier_rule=remember_rule)
            row["__samoobdavcitev__"] = self_assessment
            row["__ddv_se_odbija__"] = vat_deductible
            row["__vat_offer_from__"] = "dobavitelj" if remember_rule else "ta listina"
            self.config["last_account"] = account
            self.remember_supplier = remember_rule
        else:
            self.config["last_ir_account"] = account
            self.remember_customer = remember_rule
        detail = f"{book} {document_name}: {change_count} sprememb, konto {account}"
        self._mark_working_dirty(detail)
        self._persist_config()
        state = self._state()
        state["msg"] = (
            f"{book} {document_name}: {change_count} sprememb je začasno shranjenih. "
            "Za generalni zapis kliknite »Shrani delovno kopijo«."
        )
        return state

    def apply_accounts(
        self,
        book: str,
        ids: list[str],
        account: str,
        *,
        remember_rule: bool = False,
        persist_working: bool = True,
    ) -> dict[str, Any]:
        if self.dataset is None:
            return {"ok": False, "error": "Najprej odprite KIR/KPR datoteko.", "msg": "Najprej odprite KIR/KPR datoteko."}
        book = str(book or "").upper()
        if book not in {"IR", "PR"}:
            return {"ok": False, "error": "Knjiga mora biti IR ali PR.", "msg": "Knjiga mora biti IR ali PR."}
        selected = [str(item) for item in (ids or []) if str(item).strip()]
        if not selected:
            msg = "Najprej izberite enega ali več " + ("izdanih" if book == "IR" else "prejetih") + " računov."
            return {"ok": False, "error": msg, "msg": msg}
        account_code = self._validated_account_code(account)
        changed = 0
        profile = self._profile_config()
        for row_id in selected:
            row_book, _index, row = self._row_by_id(row_id)
            if row_book != book:
                raise core.KirkprError(f"Vrstica {row_id} ni v knjigi {book}.")
            core.remember_account(profile, book, row, account_code, supplier_rule=remember_rule)
            row["__konto__"] = account_code
            changed += 1
        if book == "IR":
            self.config["last_ir_account"] = account_code
            self._profile_config()["last_ir_account"] = account_code
            self.remember_customer = remember_rule
        else:
            self.config["last_account"] = account_code
            self._profile_config()["last_account"] = account_code
            self.remember_supplier = remember_rule
        self._mark_working_dirty(f"{changed} {book} → konto {account_code}")
        self._persist_config()
        saved = None
        if persist_working:
            saved = self.save_working_copy(quiet=True)
        state = self._state()
        state["changed"] = changed
        if saved:
            state["working_copy"] = str(saved)
            state["msg"] = f"Konto {account_code} je nastavljen na {changed} {book} in samodejno shranjen."
        else:
            state["msg"] = f"Konto {account_code} je nastavljen na {changed} {book}."
        return state

    def set_vat_deductible(self, ids: list[str], enabled: bool, *, persist_working: bool = True) -> dict[str, Any]:
        if self.dataset is None:
            return {"ok": False, "error": "Najprej odprite KIR/KPR datoteko.", "msg": "Najprej odprite KIR/KPR datoteko."}
        selected = [str(item) for item in (ids or []) if str(item).strip()]
        if not selected:
            msg = "Najprej izberite enega ali več prejetih računov."
            return {"ok": False, "error": msg, "msg": msg}
        changed = 0
        profile = self._profile_config()
        for row_id in selected:
            book, _index, row = self._row_by_id(row_id)
            if book != "PR":
                raise core.KirkprError("DDV se odbija velja samo za prejete račune.")
            row["__ddv_se_odbija__"] = bool(enabled)
            core.remember_vat_deductible(profile, row, enabled)
            changed += 1
        self._mark_working_dirty(f"{changed} PR; DDV se odbija {'DA' if enabled else 'NE'}")
        self._persist_config()
        if persist_working:
            self.save_working_copy(quiet=True)
        state = self._state()
        state["changed"] = changed
        state["msg"] = (
            f"DDV se odbija = {'DA' if enabled else 'NE'} je nastavljeno na {changed} PR"
            + (" in samodejno shranjeno." if persist_working else ".")
        )
        return state

    def compute_vat_base(self, field_name: str, value: Any) -> dict[str, Any]:
        rate_info = gui_helpers.VAT_BASE_RATE_FIELDS.get(str(field_name or "").upper())
        if rate_info is None:
            return {"ok": False, "error": "To polje nima stopnje za izračun osnove.", "msg": "To polje nima stopnje za izračun osnove."}
        rate, rate_label = rate_info
        vat = core.decimal_value(value)
        if vat == 0:
            msg = f"{field_name}: DDV {rate_label} je 0 — osnove ni."
            return {"ok": False, "error": msg, "msg": msg}
        base = (vat / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "ok": True,
            "field": field_name,
            "rate_label": rate_label,
            "vat": gui_helpers.format_money(vat),
            "base": gui_helpers.format_money(base),
            "base_raw": f"{base:.2f}",
            "msg": f"- osnova {rate_label} = {gui_helpers.format_money(base)} / DDV {rate_label} = {gui_helpers.format_money(vat)}",
        }

    def save_working_copy(self, *, quiet: bool = True, target: str = "") -> Path | None:
        if self.dataset is None:
            if quiet:
                return None
            raise core.KirkprError("Najprej odprite KIR/KPR datoteko.")
        if target:
            path = Path(target)
        else:
            source_stem = registry.safe_name(self.dataset.source_path.stem, "KIRKPR")
            filename = f"{source_stem}_MINIMAX_UREJENO.json"
            paths = None
            if self.selected_company:
                start = self.period_from.isoformat() if self.period_from else self.dataset.period_from
                end = self.period_to.isoformat() if self.period_to else self.dataset.period_to
                try:
                    paths = registry.company_paths(
                        self.selected_company,
                        start,
                        end,
                        trops_root=registry.resolve_trops_root(str(self.config.get("trops_root") or "") or None),
                    )
                except ValueError:
                    paths = None
            path = (paths.working_copies / filename) if paths else (self.dataset.source_path.parent / filename)
        company_info: dict[str, Any] = {}
        if self.selected_company:
            company_info = {
                "Zšt": registry.company_zst(self.selected_company),
                "Kratko ime": registry.company_name(self.selected_company),
                "DAVČNA": registry.company_tax_number(self.selected_company),
                "Org_ID": registry.company_org_id(self.selected_company),
            }
        saved = core.save_working_copy(self.dataset, path, company=company_info)
        profile = self._profile_config()
        profile["last_working_copy"] = str(saved)
        self.config["last_working_copy"] = str(saved)
        self.working_dirty = False
        self.pending_working_changes.clear()
        self._persist_config()
        return saved

    def save_working_copy_action(self, target: str = "") -> dict[str, Any]:
        saved = self.save_working_copy(quiet=False, target=target)
        state = self._state()
        if saved is None:
            state["ok"] = False
            state["error"] = state["msg"] = "Delovne kopije ni bilo mogoče shraniti."
            return state
        state["working_copy"] = str(saved)
        state["msg"] = f"Delovna kopija je shranjena: {saved}. Izvorna datoteka je nespremenjena."
        return state

    def get_data_editor(self, row_id: str) -> dict[str, Any]:
        book, index, row = self._row_by_id(row_id)
        original_rows = None
        if self.source_dataset is not None:
            original_rows = self.source_dataset.kir if book == "IR" else self.source_dataset.kpr
        original_row = original_rows[index] if original_rows is not None and 0 <= index < len(original_rows) else row
        labels = gui_helpers.IR_FIELD_LABELS if book == "IR" else gui_helpers.PR_FIELD_LABELS
        evidence_book = "KIR" if book == "IR" else "KPR"
        fields = []
        changed = 0
        for field_name, label in labels.items():
            def display(name: str, value: Any) -> str:
                if gui_helpers.is_money_field(book, name):
                    return gui_helpers.format_money(value)
                return "" if value is None else str(value)

            original_value = display(field_name, original_row.get(field_name, ""))
            working_value = display(field_name, row.get(field_name, ""))
            is_changed = original_value != working_value
            if is_changed:
                changed += 1
            ddvo = core.ddvo_codes_for_field(book, field_name)
            fields.append({
                "name": field_name,
                "label": label,
                "evidence": f"{evidence_book} {field_name}",
                "ddvo": ", ".join(ddvo) if ddvo else "—",
                "original": original_value,
                "working": working_value,
                "changed": is_changed,
                "money": gui_helpers.is_money_field(book, field_name),
            })
        return {
            "ok": True,
            "id": f"{book.lower()}:{index}",
            "book": book,
            "invoice": str(row.get("P3") or ""),
            "party": str(row.get("P5") if book == "IR" else row.get("P6") or ""),
            "changed": changed,
            "fields": fields,
        }

    def apply_data_field(self, row_id: str, field_name: str, value: Any) -> dict[str, Any]:
        book, _index, row = self._row_by_id(row_id)
        field = str(field_name or "").strip()
        if not field:
            raise core.KirkprError("Najprej izberite vrstico s poljem.")
        normalized = core.update_working_row(book, row, field, value)
        detail = f"{book} {row.get('P3')}: polje {field}"
        self._mark_working_dirty(detail)
        self.config["last_action"] = "data_edit"
        self.config["last_action_detail"] = detail
        self._persist_config()
        editor = self.get_data_editor(row_id)
        state = self._state()
        state["editor"] = editor
        state["normalized"] = _jsonable(normalized)
        state["msg"] = f"Spremenjeno {field}; izvorna vrednost je ostala nespremenjena."
        return state


    def _ddvo_view_or_error(self) -> core.KirkprDataset:
        if self.dataset is None:
            raise core.KirkprError("Najprej odprite KIR/KPR datoteko.")
        return self._ddvo_view_dataset() or self.dataset

    def _ddvo_taxpayer_kwargs(self) -> dict[str, str]:
        firm = ""
        address = ""
        contact_name = str(self.config.get("ddvo_contact_name") or "").strip()
        contact_phone = str(self.config.get("ddvo_contact_phone") or "").strip()
        if self.selected_company:
            firm = (
                str(self.selected_company.get("Dolgo") or "").strip()
                or registry.company_name(self.selected_company)
            )
            for key in ("NASLOV", "Naslov", "address", "sedez", "naslov", "street"):
                address = str(self.selected_company.get(key) or "").strip()
                if address:
                    break
            if not contact_phone:
                for key in ("Telefon", "Telefon odg osebe", "phone"):
                    contact_phone = str(self.selected_company.get(key) or "").strip()
                    if contact_phone:
                        break
        return {
            "company_name": firm,
            "address": address,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
        }

    def _ddvo_initial_dir(self, out_dir: str = "") -> Path:
        if out_dir:
            path = Path(out_dir).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            return path
        paths = None
        if self.selected_company:
            start = self.period_from.isoformat() if self.period_from else (self.dataset.period_from if self.dataset else "")
            end = self.period_to.isoformat() if self.period_to else (self.dataset.period_to if self.dataset else "")
            try:
                paths = registry.company_paths(
                    self.selected_company,
                    start,
                    end,
                    trops_root=registry.resolve_trops_root(str(self.config.get("trops_root") or "") or None),
                )
            except ValueError:
                paths = None
        profile = self._profile_config()
        for candidate in (
            paths.ddv_root if paths else None,
            Path(str(profile.get("last_output_dir") or "")),
            Path(str(self.config.get("last_output_dir") or "")),
            self.dataset.source_path.parent if self.dataset else None,
        ):
            if candidate and Path(candidate).is_dir():
                return Path(candidate)
        fallback = (self.dataset.source_path.parent if self.dataset else Path.cwd())
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _remember_output_dir(self, folder: Path, action: str, detail: str) -> None:
        self.config["last_output_dir"] = str(folder)
        self._profile_config()["last_output_dir"] = str(folder)
        self.config["last_action"] = action
        self.config["last_action_detail"] = detail
        self._persist_config()

    def export_ddvo(self, kind: str = "both", target: str = "", out_dir: str = "") -> dict[str, Any]:
        import kirkpr_ddvo_pdf as ddvo_pdf
        import kirkpr_ddvo_xml as ddvo_xml

        view = self._ddvo_view_or_error()
        kind = str(kind or "both").strip().lower()
        folder = self._ddvo_initial_dir(out_dir)
        paths: dict[str, str] = {}
        if kind in {"report", "pregled"}:
            name = f"DDV-O_kontrolni_pregled_{view.period_from}_{view.period_to}.txt"
            path = Path(target) if target else folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(core.ddvo_control_report(view), encoding="utf-8-sig")
            paths["report"] = str(path)
            self._remember_output_dir(path.parent, "ddvo_report", path.name)
            state = self._state()
            state["export_paths"] = dict(paths)
            state["msg"] = f"Kontrolni pregled DDV-O je shranjen: {path.name}"
            return state
        if kind in {"pdf", "xml", "both", "pdf_xml", "export"}:
            pdf_path = Path(target) if (target and kind == "pdf") else folder / ddvo_pdf.default_ddvo_pdf_name(view)
            xml_path = Path(target) if (target and kind == "xml") else folder / ddvo_xml.default_ddvo_xml_name(view)
            taxpayer = self._ddvo_taxpayer_kwargs()
            if kind in {"pdf", "both", "pdf_xml", "export"}:
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                ddvo_pdf.build_ddvo_pdf(view, pdf_path, **taxpayer)
                paths["pdf"] = str(pdf_path)
            if kind in {"xml", "both", "pdf_xml", "export"}:
                xml_path.parent.mkdir(parents=True, exist_ok=True)
                ddvo_xml.write_ddvo_xml(view, xml_path, **taxpayer)
                paths["xml"] = str(xml_path)
            action = "ddvo_export" if "pdf" in paths and "xml" in paths else ("ddvo_pdf" if "pdf" in paths else "ddvo_xml")
            detail = " + ".join(Path(p).name for p in paths.values())
            self._remember_output_dir(Path(next(iter(paths.values()))).parent, action, detail)
            state = self._state()
            state["export_paths"] = paths
            state["msg"] = f"DDV-O shranjen: {detail}"
            return state
        raise core.KirkprError("Neznana vrsta izvoza DDV-O.")

    def preview_ddvo(self, open_file: bool = False) -> dict[str, Any]:
        import kirkpr_ddvo_pdf as ddvo_pdf

        view = self._ddvo_view_or_error()
        target = Path(tempfile.gettempdir()) / ddvo_pdf.default_ddvo_pdf_name(view)
        ddvo_pdf.build_ddvo_pdf(view, target, **self._ddvo_taxpayer_kwargs())
        html_path = target.with_suffix(".html")
        ddvo_pdf.write_ddvo_preview_html(view, html_path, **self._ddvo_taxpayer_kwargs())
        self.config["last_action"] = "ddvo_preview"
        self.config["last_action_detail"] = target.name
        self._persist_config()
        if open_file:
            self.open_export_path(str(target))
        state = self._state()
        state["export_paths"] = {"pdf": str(target), "html": str(html_path)}
        state["msg"] = f"Predogled DDV-O: {target.name}"
        return state

    def virman_quote(self, konto62: Any = "0") -> dict[str, Any]:
        view = self._ddvo_view_or_error()
        summary = core.ddvo_summary(view)
        quoted = core.ddvo_virman_payment(summary.get("obligation"), konto62)
        return {
            "ok": True,
            "obligation": gui_helpers.format_money(quoted["obligation"]),
            "excess": gui_helpers.format_money(summary.get("excess")),
            "konto62_saldo": gui_helpers.format_money(quoted["konto62_saldo"]),
            "payment": gui_helpers.format_money(quoted["payment"]),
            "formula": gui_helpers.format_virman_formula(quoted["obligation"], quoted["konto62_saldo"], quoted["payment"]),
            "needs_virman": quoted["obligation"] > 0,
            "period_from": view.period_from,
            "period_to": view.period_to,
            "company": _company_public(self.selected_company) if self.selected_company else None,
        }

    def create_virman_package(
        self,
        *,
        konto62: Any = "0",
        payer_iban: str = "",
        execution_date: str = "",
        out_dir: str = "",
        source_pdf: str = "",
    ) -> dict[str, Any]:
        """Ustvari PDF+XML in po potrebi virman. E-pošte ne odpre in je ne pošlje."""
        import kirkpr_ddvo_virman as ddvo_virman

        view = self._ddvo_view_or_error()
        if not self.selected_company:
            raise core.KirkprError("Za virman najprej izberite podjetje.")
        folder = self._ddvo_initial_dir(out_dir)
        exported = self.export_ddvo("both", out_dir=str(folder))
        if exported.get("ok") is False:
            return exported
        paths = dict(exported.get("export_paths") or {})
        pdf_path = Path(source_pdf or paths.get("pdf") or "")
        quoted = core.ddvo_virman_payment(core.ddvo_summary(view).get("obligation"), konto62)
        if quoted["obligation"] <= 0:
            state = self._state()
            state["export_paths"] = paths
            state["virman"] = None
            state["quote"] = self.virman_quote(konto62)
            state["msg"] = (
                f"DDV-O PDF in XML sta shranjena. "
                f"Obveznost (51) je 0 — virman ni potreben."
            )
            return state
        exec_dt = gui_helpers.parse_iso_date(execution_date)
        paths_obj = None
        try:
            paths_obj = registry.company_paths(
                self.selected_company,
                str(view.period_from),
                str(view.period_to),
                trops_root=registry.resolve_trops_root(str(self.config.get("trops_root") or "") or None),
            )
        except ValueError:
            paths_obj = None
        if out_dir:
            virman_dir = folder / "Virmani"
        else:
            virman_dir = paths_obj.virmani_root if paths_obj else folder / "Virmani"
        package = ddvo_virman.write_virman_package(
            folder,
            company=self.selected_company,
            period_from=str(view.period_from),
            period_to=str(view.period_to),
            obligation=quoted["obligation"],
            konto62_credit=quoted["konto62_credit"],
            payment=quoted["payment"],
            source_pdf=pdf_path,
            payer_iban=payer_iban,
            execution_date=exec_dt,
            remittance=f"DDV-O {view.period_from} – {view.period_to}",
            virman_dir=virman_dir,
        )
        paths["pdf"] = str(package.pdf_path)
        paths["virman"] = str(package.virman_path)
        self._remember_output_dir(
            folder,
            "ddvo_pdf",
            f"{package.pdf_path.name}; virman {package.virman_path.name}; plačilo {package.payment:.2f}",
        )
        state = self._state()
        state["export_paths"] = paths
        state["virman"] = {
            "pdf": str(package.pdf_path),
            "virman": str(package.virman_path),
            "payment": gui_helpers.format_money(package.payment),
            "obligation": gui_helpers.format_money(package.obligation),
            "reference": package.reference,
            "execution_date": package.execution_date.isoformat() if package.execution_date else "",
        }
        state["msg"] = (
            f"PDF: {package.pdf_path.name}; virman: {package.virman_path.name}; "
            f"plačilo {gui_helpers.format_money(package.payment)} EUR. E-pošta ni bila odprta."
        )
        return state

    def open_export_path(self, path: str) -> dict[str, Any]:
        target = Path(path)
        if not target.exists():
            raise core.KirkprError("Datoteka ali mapa ne obstaja.")
        gui_helpers.open_in_file_manager(target)
        return {"ok": True, "path": str(target), "msg": f"Odprto: {target}"}


    def _knjiga_cell_date(self, row: Mapping[str, Any], field: str) -> str:
        parsed = gui_helpers.parse_iso_date(row.get(field))
        if parsed is not None:
            return gui_helpers.format_si_date(parsed)
        return str(row.get(field) or "").strip()

    def _knjiga_cell_obdobje(self, row: Mapping[str, Any]) -> str:
        if self.period_from and self.period_to:
            f0, f1 = self.period_from, self.period_to
            if (
                f0.year == f1.year
                and f0.month != f1.month
                and f0.day == 1
                and f1 == gui_helpers.month_bounds(f1.year, f1.month)[1]
            ):
                return f"{f0.month:02d}-{f1.month:02d}.{str(f0.year)[-2:]}"
        raw = str(row.get("OBDOBJE") or "").strip()
        if not re.fullmatch(r"\d{4}", raw):
            return raw
        m1 = int(raw[:2])
        m2 = int(raw[2:])
        year = self.period_from.year if self.period_from else date.today().year
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            yy = str(year)[-2:]
            if m1 == m2:
                return f"{m1:02d}.{yy}"
            return f"{m1:02d}-{m2:02d}.{yy}"
        parsed = gui_helpers.parse_obdobje_mmyy(raw)
        if parsed is not None:
            y, m = parsed
            return f"{m:02d}.{str(y)[-2:]}"
        return raw

    def _knjiga_cell_money(self, row: Mapping[str, Any], field: str) -> str:
        raw = row.get(field)
        if raw in (None, ""):
            return "0,00"
        return gui_helpers.format_money(raw)

    def _knjiga_money_columns(self, book: str, mode: str) -> tuple[str, ...]:
        if mode == "api":
            return ("amount",)
        if book == "IR":
            return tuple(f"p{i}" for i in range(7, 28))
        return tuple(f"p{i}" for i in range(8, 22))

    def _knjiga_column_field(self, column: str) -> str:
        if column.startswith("p") and column[1:].isdigit():
            return column.upper()
        return column

    def _knjiga_column_spec(self, book: str, mode: str) -> tuple[list[str], dict[str, str]]:
        if mode == "api":
            columns = ["zapst", "api_id", "date", "invoice", "party", "tax_id", "amount", "status", "match"]
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
            return columns, headings
        if book == "IR":
            columns = [
                "zapst", "obdobje", "p2", "p3", "p4", "p5", "p6ds", "p6",
                "p7", "p8", "p9", "p10", "p11", "p12", "p13",
                "p14", "p15", "p16", "p17", "p18", "p19", "p20", "p21", "p22",
                "p23", "p24", "p25", "p26", "p27",
            ]
            headings = {
                "zapst": "1 ZŠT", "obdobje": "2 Obdobje", "p2": "3 Dat knj",
                "p3": "4 Listina", "p4": "Dat list", "p5": "Kupec",
                "p6ds": "ID za DDV", "p6": "Drž",
                "p7": "7 Vred brez DDV", "p8": "8 Samoobd", "p9": "9 Oprošč",
                "p10": "10 EU blago", "p11": "11 EU stor", "p12": "12 Prod dalj", "p13": "13 Montaža",
                "p14": "14 DDV 22%", "p15": "15 DDV 9,5%", "p16": "16 DDV 5%",
                "p17": "17 EU DDV 22%", "p18": "18 EU stor 22%", "p19": "19 EU DDV 9,5%",
                "p20": "20 EU stor 9,5%", "p21": "21 EU DDV 5%", "p22": "22 EU stor 5%",
                "p23": "23 Samoobd 22%", "p24": "24 Samoobd 9,5%", "p25": "25 Samoobd 5%",
                "p26": "26 Uvoz DDV", "p27": "27 Neobdavč",
            }
        else:
            columns = [
                "zapst", "obdobje", "p2", "p4", "p3", "p5", "p6", "p7ds", "p7",
                "p8", "p9", "p10", "p11", "p12", "p13", "p14", "p15", "p16",
                "p17", "p18", "p19", "p20", "p21",
            ]
            headings = {
                "zapst": "1 ZŠT", "obdobje": "2 Obdobje", "p2": "3 Dat knj",
                "p4": "4 Dat pr", "p3": "5 Listina", "p5": "6 Dat list",
                "p6": "7 Dobavitelj", "p7ds": "ID za DDV", "p7": "Drž",
                "p8": "8 Vred brez DDV", "p9": "9 Samoobd", "p10": "10 Prid BL",
                "p11": "11 Prej ST", "p12": "12 Neprem", "p13": "13 OS",
                "p14": "14 Oprošč", "p15": "15 Opr nepr", "p16": "16 Opr OS",
                "p17": "17 Neodb DDV", "p18": "18 VST 22%", "p19": "19 VST 9,5%",
                "p20": "20 VST 5%", "p21": "21 Pavšal",
            }
        headings = {
            col: (
                f"{text} →{'+'.join(core.ddvo_codes_for_field(book, self._knjiga_column_field(col)))}"
                if core.ddvo_codes_for_field(book, self._knjiga_column_field(col))
                else text
            )
            for col, text in headings.items()
        }
        return columns, headings

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

    def set_knjiga_mode(self, mode: str = "json") -> dict[str, Any]:
        wanted = "api" if str(mode or "").strip().lower() == "api" else "json"
        self.knjiga_view_mode = wanted
        state = self._state()
        state["knjiga_mode"] = self.knjiga_view_mode
        state["msg"] = "Knjige: predogled Minimax API." if wanted == "api" else "Knjige: predogled JSON."
        return state

    def list_knjiga(
        self,
        book: str = "IR",
        search: str = "",
        mode: str = "",
        *,
        hide_zero: bool = False,
    ) -> dict[str, Any]:
        book = str(book or "IR").upper()
        if book not in {"IR", "PR"}:
            raise core.KirkprError("Knjiga mora biti IR ali PR.")
        mode = str(mode or self.knjiga_view_mode or "json").strip().lower()
        if mode not in {"json", "api"}:
            mode = "json"
        if mode == "api":
            return self._list_knjiga_api(book, search)
        return self._list_knjiga_json(book, search, hide_zero=hide_zero)

    def _list_knjiga_json(self, book: str, search: str, *, hide_zero: bool) -> dict[str, Any]:
        columns, headings = self._knjiga_column_spec(book, "json")
        money_cols = self._knjiga_money_columns(book, "json")
        tokens = self._tokens(search)
        totals: dict[str, Decimal] = {col: Decimal("0") for col in money_cols}
        rows_out: list[dict[str, Any]] = []
        if self.dataset is None:
            return {
                "ok": True, "book": book, "mode": "json", "rows": [], "visible": 0,
                "count": 0, "has_data": False,
                "columns": [{"key": c, "label": headings[c], "money": c in money_cols} for c in columns],
                "totals": {c: gui_helpers.format_money(0) for c in money_cols},
                "summary": "JSON: najprej odpri KIR/KPR podatke.",
            }
        source_rows = self.dataset.kir if book == "IR" else self.dataset.kpr
        for index, row in enumerate(source_rows):
            if not self._row_in_ddvo_period(row):
                continue
            if book == "IR":
                metrics = core.ir_metrics(row, self.dataset.kpr)
                tax_only = bool(metrics.get("tax_only"))
                item = {
                    "id": f"kir:{index}",
                    "zapst": str(row.get("ZAPST") or ""),
                    "obdobje": self._knjiga_cell_obdobje(row),
                    "p2": self._knjiga_cell_date(row, "P2"),
                    "p3": str(row.get("P3") or ""),
                    "p4": self._knjiga_cell_date(row, "P4"),
                    "p5": str(row.get("P5") or ""),
                    "p6ds": str(row.get("P6DS") or ""),
                    "p6": str(row.get("P6") or ""),
                    **{f"p{i}": self._knjiga_cell_money(row, f"P{i}") for i in range(7, 28)},
                    "tag": "tax_only" if tax_only else "",
                }
                extra = [item["p3"], item["p5"], item["p6ds"], "samoobdavčitev" if tax_only else "izdani"]
            else:
                metrics = core.pr_metrics(row)
                self_assessment = bool(metrics.get("self_assessment"))
                vat_deductible = bool(metrics.get("vat_deductible"))
                item = {
                    "id": f"kpr:{index}",
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
                    "tag": "vat_not_deducted" if not vat_deductible else ("self_assessment" if self_assessment else ""),
                }
                extra = [item["p3"], item["p6"], item["p7ds"], "samoobdavčitev" if self_assessment else "prejeti"]
            if not self._haystack_matches(tokens, list(item.values()) + extra):
                continue
            for col in money_cols:
                field = self._knjiga_column_field(col)
                try:
                    totals[col] += core.decimal_value(row.get(field))
                except core.KirkprError:
                    pass
            rows_out.append(item)

        visible_cols = list(columns)
        if hide_zero:
            identity = {"zapst", "obdobje", "p2", "p3", "p4", "p5", "p6", "p6ds", "p7", "p7ds"}
            visible_cols = [c for c in columns if c not in money_cols or totals[c] != 0 or c in identity]
        col_meta = [
            {
                "key": c,
                "label": headings[c],
                "money": c in money_cols,
                "ddvo": list(core.ddvo_codes_for_field(book, self._knjiga_column_field(c))),
            }
            for c in visible_cols
        ]
        ir_n = sum(1 for r in self.dataset.kir if self._row_in_ddvo_period(r))
        pr_n = sum(1 for r in self.dataset.kpr if self._row_in_ddvo_period(r))
        return {
            "ok": True,
            "book": book,
            "mode": "json",
            "rows": rows_out,
            "visible": len(rows_out),
            "count": ir_n if book == "IR" else pr_n,
            "has_data": True,
            "columns": col_meta,
            "totals": {c: gui_helpers.format_money(totals[c]) for c in money_cols},
            "summary": f"Predogled JSON (KIR/KPR). IR {ir_n}, PR {pr_n}.",
        }

    def _list_knjiga_api(self, book: str, search: str) -> dict[str, Any]:
        columns, headings = self._knjiga_column_spec(book, "api")
        money_cols = self._knjiga_money_columns(book, "api")
        tokens = self._tokens(search)
        totals: dict[str, Decimal] = {col: Decimal("0") for col in money_cols}
        rows_out: list[dict[str, Any]] = []
        local_refs = self._local_book_refs(book)
        api_refs: set[str] = set()
        visible = 0
        for record in self.knjiga_records.get(book) or []:
            ref = minimax_api.invoice_record_reference(record)
            ref_key = minimax_api.normal_invoice_reference(ref)
            if ref_key:
                api_refs.add(ref_key)
            match = "V KIR/KPR" if ref_key and ref_key in local_refs else "Samo v Minimax"
            rid = record.get("IssuedInvoiceId") if book == "IR" else record.get("ReceivedInvoiceId")
            if rid is None:
                for key in ("ID", "Id", "id"):
                    if record.get(key) is not None:
                        rid = record.get(key)
                        break
            amount = minimax_api.invoice_record_amount(record)
            item = {
                "id": f"k{book.lower()}:api:{visible}",
                "zapst": str(visible + 1),
                "api_id": str(rid or ""),
                "date": minimax_api.invoice_record_date(record),
                "invoice": ref,
                "party": minimax_api.invoice_record_party(record),
                "tax_id": minimax_api.invoice_record_tax_id(record),
                "amount": gui_helpers.format_money(amount),
                "status": minimax_api.invoice_record_status(record),
                "match": match,
                "tag": "match_ok" if match == "V KIR/KPR" else "match_api_only",
            }
            if not self._haystack_matches(tokens, list(item.values())):
                continue
            try:
                totals["amount"] += core.decimal_value(amount)
            except (core.KirkprError, KeyError):
                pass
            rows_out.append(item)
            visible += 1
        for ref_key, row in local_refs.items():
            if ref_key in api_refs:
                continue
            item = {
                "id": f"k{book.lower()}:local:{visible}",
                "zapst": str(visible + 1),
                "api_id": "",
                "date": str(row.get("P2") or row.get("P4") or ""),
                "invoice": str(row.get("P3") or ""),
                "party": str(row.get("P5") or "") if book == "IR" else str(row.get("P6") or ""),
                "tax_id": str(row.get("P6DS") or "") if book == "IR" else str(row.get("P7DS") or ""),
                "amount": "",
                "status": "",
                "match": "Manjka v Minimax",
                "tag": "match_local_only",
            }
            if not self._haystack_matches(tokens, list(item.values())):
                continue
            rows_out.append(item)
            visible += 1
        has_api = bool(self.knjiga_records.get("IR") or self.knjiga_records.get("PR"))
        summary = (
            "Minimax API: ni naloženih knjig — klikni »Osveži API«."
            if not has_api
            else f"Predogled Minimax API. Stolpec KIR/KPR = ujemanje z lokalnim JSON."
        )
        return {
            "ok": True,
            "book": book,
            "mode": "api",
            "rows": rows_out,
            "visible": len(rows_out),
            "count": len(self.knjiga_records.get(book) or []),
            "has_data": has_api or bool(local_refs),
            "columns": [{"key": c, "label": headings[c], "money": c in money_cols} for c in columns],
            "totals": {c: gui_helpers.format_money(totals[c]) for c in money_cols},
            "summary": summary,
        }

    def refresh_knjige_from_api(self) -> dict[str, Any]:
        if not self.selected_company:
            raise core.KirkprError("Najprej izberi podjetje.")
        client = self.minimax_client
        if client is None or not getattr(client, "organisation_id", None):
            raise core.KirkprError("Najprej poveži Minimax API.")
        date_from = self.period_from.isoformat() if self.period_from else (self.dataset.period_from if self.dataset else "")
        date_to = self.period_to.isoformat() if self.period_to else (self.dataset.period_to if self.dataset else "")
        result = {
            "IR": client.invoice_book("IR", date_from=date_from, date_to=date_to),
            "PR": client.invoice_book("PR", date_from=date_from, date_to=date_to),
            "period": (date_from, date_to),
        }
        self.knjiga_records = {
            "IR": list(result.get("IR") or []),
            "PR": list(result.get("PR") or []),
        }
        self.knjiga_period = tuple(result.get("period") or (date_from, date_to))
        self.knjiga_view_mode = "api"
        ir_n = len(self.knjiga_records["IR"])
        pr_n = len(self.knjiga_records["PR"])
        state = self._state()
        state["knjiga_mode"] = "api"
        state["msg"] = f"Knjige API: IR {ir_n}, PR {pr_n}."
        return state


    def list_sessions(self, limit: int = 50) -> dict[str, Any]:
        rows = []
        for entry in self.sessions_db.list_sessions(limit=limit):
            rows.append({
                "id": entry.get("id"),
                "title": entry.get("title") or entry.get("label") or "",
                "label": entry.get("label") or entry.get("title") or "",
                "company_key": entry.get("company_key") or "",
                "company_label": entry.get("company_label") or "",
                "period_from": str(entry.get("period_from") or "")[:10],
                "period_to": str(entry.get("period_to") or "")[:10],
                "source": str(entry.get("source_path") or entry.get("source") or ""),
                "working_copy": str(entry.get("working_copy") or ""),
                "notes": entry.get("notes") or "",
                "updated_at": str(entry.get("updated_at") or ""),
                "minimax": self._session_is_minimax(entry),
            })
        return {"ok": True, "rows": rows, "selected_id": self._selected_session_id, "db": str(self.sessions_db.path)}

    @staticmethod
    def _session_is_minimax(entry: Mapping[str, Any]) -> bool:
        text = " ".join(
            str(entry.get(key) or "")
            for key in ("title", "label", "source", "source_path", "working_copy")
        ).casefold()
        return "minimax" in text or ".virtual" in text

    def _session_period_bounds(self, entry: Mapping[str, Any]) -> tuple[date, date] | None:
        start = gui_helpers.parse_iso_date(entry.get("period_from"))
        end = gui_helpers.parse_iso_date(entry.get("period_to"))
        if start and end:
            if end < start:
                start, end = end, start
            return start, end
        return None

    def _session_file_usable(self, path: Path | None, prefer: tuple[date, date] | None) -> tuple[bool, str]:
        if path is None or not path.is_file():
            return False, "ni shranjene datoteke"
        text = str(path).replace("\\", "/")
        if prefer is not None:
            start, end = prefer
            start_s, end_s = start.isoformat(), end.isoformat()
            ym = f"{start.year}-{start.month:02d}"
            periods_in_path = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
            if periods_in_path and start_s not in text and end_s not in text and ym not in text:
                return False, f"datoteka je za drugo obdobje ({periods_in_path[0]}…), seja je {start_s}–{end_s}"
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return True, path.name
        if isinstance(raw, Mapping):
            payload = raw.get("DDV_KIR_KPR") if isinstance(raw.get("DDV_KIR_KPR"), Mapping) else raw
            if isinstance(payload, Mapping):
                kir = payload.get("Lista_KIR") or {}
                kpr = payload.get("Lista_KPR") or {}
                kir_rows = kir.get("KIR", []) if isinstance(kir, Mapping) else kir
                kpr_rows = kpr.get("KPR", []) if isinstance(kpr, Mapping) else kpr
                n_kir = len(kir_rows or []) if isinstance(kir_rows, list) else 0
                n_kpr = len(kpr_rows or []) if isinstance(kpr_rows, list) else 0
                if n_kir == 0 and n_kpr == 0 and ("MINIMAX_DELOVNA_KOPIJA" in raw or "DDV_KIR_KPR" in raw):
                    return False, "delovna kopija je prazna (0 IR/PR)"
        return True, path.name

    def _apply_session_company_and_period(self, entry: Mapping[str, Any]) -> bool:
        company_key = str(entry.get("company_key") or "")
        company = registry.find_company(self.companies, company_key) if company_key else None
        if company:
            self.selected_company = company
        prefer = self._session_period_bounds(entry)
        if prefer is None:
            return False
        self.set_period(prefer[0].isoformat(), prefer[1].isoformat())
        return True

    def _remember_current_session(self, *, title: str = "", notes: str = "", use_selected_id: bool = False) -> dict[str, Any] | None:
        if not self.selected_company or not self.dataset:
            return None
        key = registry.company_key(self.selected_company)
        zst = registry.company_zst(self.selected_company) or "—"
        name = registry.company_name(self.selected_company)
        period_from = self.period_from.isoformat() if self.period_from else (self.dataset.period_from or "")
        period_to = self.period_to.isoformat() if self.period_to else (self.dataset.period_to or "")
        wc = str(self._profile_config().get("last_working_copy") or "") or None
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
        if entry and entry.get("id"):
            self._selected_session_id = int(entry["id"])
        return entry

    def save_session(self, title: str = "", notes: str = "") -> dict[str, Any]:
        if self.dataset is None:
            raise core.KirkprError("Najprej odpri KIR/KPR podatke.")
        if not self.selected_company:
            raise core.KirkprError("Za shranjevanje seje izberi podjetje.")
        if self.working_dirty:
            self.save_working_copy(quiet=True)
        current = self.sessions_db.get(self._selected_session_id) if self._selected_session_id else None
        active_key = registry.company_key(self.selected_company)
        use_selected = bool(current and str(current.get("company_key") or "") == active_key)
        if not use_selected:
            self._selected_session_id = None
        default_title = title.strip()
        if not default_title:
            zst = registry.company_zst(self.selected_company) or "—"
            name = registry.company_name(self.selected_company)
            default_title = core.format_recent_session_label(
                {
                    "company_label": f"{zst} {name}",
                    "period_from": self.period_from.isoformat() if self.period_from else "",
                    "period_to": self.period_to.isoformat() if self.period_to else "",
                    "source": str(self.dataset.source_path),
                    "working_copy": str(self._profile_config().get("last_working_copy") or ""),
                }
            )
        entry = self._remember_current_session(title=default_title, notes=notes, use_selected_id=use_selected)
        self._persist_config()
        state = self._state()
        state["sessions"] = self.list_sessions()["rows"]
        if entry:
            state["msg"] = f"Seja shranjena: {entry.get('label') or default_title}"
        else:
            state["ok"] = False
            state["error"] = state["msg"] = "Seje ni bilo mogoče shraniti."
        return state

    def open_session(self, session_id: int) -> dict[str, Any]:
        entry = self.sessions_db.get(int(session_id))
        if not entry:
            raise core.KirkprError("Ni izbrane seje.")
        self._selected_session_id = int(entry.get("id") or 0) or None
        applied = self._apply_session_company_and_period(entry)
        if self._session_is_minimax(entry):
            state = self._state()
            state["needs_minimax"] = True
            state["msg"] = "To je Minimax seja. Za svež prenos uporabi Minimax API; shranjena datoteka se ni samodejno naložila."
            return state
        path = self.sessions_db.open_path(entry)
        prefer = self._session_period_bounds(entry)
        usable, reason = self._session_file_usable(path, prefer)
        if usable and path is not None:
            loaded = self.load_source(str(path))
            loaded["msg"] = f"Odprta seja: {entry.get('label') or entry.get('title') or path.name}"
            loaded["sessions"] = self.list_sessions()["rows"]
            return loaded
        if not applied and path is None:
            raise core.KirkprError("Datoteka za to sejo ne obstaja več (premik/brisanje). Lahko jo zbrišeš s seznama.")
        state = self._state()
        state["msg"] = (
            "Seja: firma in obdobje sta nastavljena, datoteka pa ni na voljo"
            + (f" ({reason})." if reason else ".")
        )
        return state

    def update_session(self, session_id: int, title: str = "", notes: str = "") -> dict[str, Any]:
        entry = self.sessions_db.update_meta(int(session_id), title=title, notes=notes)
        if not entry:
            raise core.KirkprError("Seje ni mogoče posodobiti.")
        state = self._state()
        state["sessions"] = self.list_sessions()["rows"]
        state["msg"] = f"Seja posodobljena: {entry.get('title') or entry.get('label')}"
        return state

    def delete_session(self, session_id: int) -> dict[str, Any]:
        entry = self.sessions_db.get(int(session_id))
        if not entry:
            raise core.KirkprError("Seje ni na seznamu.")
        label = entry.get("label") or entry.get("title") or str(session_id)
        deleted = self.sessions_db.delete(int(session_id))
        if self._selected_session_id == int(session_id):
            self._selected_session_id = None
        if not deleted:
            raise core.KirkprError(f"Seje ni bilo mogoče izbrisati (id={session_id}).")
        state = self._state()
        state["sessions"] = self.list_sessions()["rows"]
        state["msg"] = f"Seja odstranjena: {label}"
        return state

    def set_auto_reopen(self, enabled: bool) -> dict[str, Any]:
        self.config["auto_reopen_last_source"] = bool(enabled)
        self._persist_config()
        state = self._state()
        state["msg"] = "Samodejno odpiranje zadnje datoteke je " + ("vključeno." if enabled else "izključeno.")
        return state

    def set_theme(self, theme: str = "light") -> dict[str, Any]:
        value = "dark" if str(theme or "").strip().lower() == "dark" else "light"
        self.config["ui_theme"] = value
        self._persist_config()
        state = self._state()
        state["msg"] = "Videz: " + ("temna" if value == "dark" else "svetla") + " tema."
        return state

    def save_accounts(self) -> dict[str, Any]:
        if self.dataset is None:
            raise core.KirkprError("Najprej odprite KIR/KPR datoteko.")
        profile = self._profile_config()
        for row in self.dataset.kir:
            core.remember_account(profile, "IR", row, str(row.get("__konto__") or "7601"), supplier_rule=False)
            core.remember_description(profile, "IR", row, str(row.get("__opis__") or row.get("P3") or ""))
        for row in self.dataset.kpr:
            core.remember_account(profile, "PR", row, str(row.get("__konto__") or "4190"), supplier_rule=False)
            core.remember_description(profile, "PR", row, str(row.get("__opis__") or row.get("P3") or ""))
            core.remember_self_assessment(profile, row, core.is_self_assessment(row))
            core.remember_vat_deductible(profile, row, core.vat_is_deductible(row))
        self._persist_config()
        saved = self.save_working_copy(quiet=True)
        state = self._state()
        if saved:
            state["working_copy"] = str(saved)
        state["msg"] = "Konta, pravila in delovna kopija so shranjeni. Izvorna datoteka ni bila spremenjena."
        return state

    def help_topic(self, topic: str = "about") -> dict[str, Any]:
        name = str(topic or "about").strip().lower()
        import kirkpr_logging
        if name in {"formats", "format", "formati"}:
            title = "Podprti formati / pravila ZIP"
            body = (
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
                "Pri CSV: ločilo ;/,/tab/|, UTF-8 ali Windows-1250, zneski 1.234,56."
            )
        elif name in {"changelog", "novosti"}:
            title = "Kaj je novega"
            body = (
                f"{APP_TITLE} v{APP_VERSION}\n\n"
                "• Samostojni program v mapi D:\\PISARNA\\Python\\KirKpr\n"
                "• Vmesnik WebView2 po zgledu Trops Studio 5\n"
                "• Strukturiran dnevnik KIRKPR_studio.log\n"
                "• Meni: Nastavitve poti (EvidencaFirm, TROPS, Minimax settings)\n"
                "• Gumb »Ponovi NAPAKA« za ponovno oddajo neuspešnih vrstic\n"
                "• JSON povzetek vsake API oddaje v mapi API_oddaje\n"
                "• CLI: --validate, --dry-run, --summary-json\n"
                "• JSON pogled / Minimax pogled + razlika program ↔ Minimax\n"
                "• Filter obdobja za JSON in Minimax"
            )
        else:
            title = "O programu"
            body = (
                f"{APP_TITLE} v{APP_VERSION}\n"
                f"Izdaja: {APP_EDITION}\n\n"
                "Pretvornik za izdane in prejete račune z urejanjem PR kontov, "
                "dvostavno bilančno kontrolo in Minimax XSD-validacijo.\n\n"
                "Privzeti konto storitev PR: 4190\n"
                f"Dnevnik: {kirkpr_logging.default_log_path()}"
            )
        return {"ok": True, "topic": name, "title": title, "body": body}

    def log_path(self) -> dict[str, Any]:
        import kirkpr_logging
        path = kirkpr_logging.default_log_path()
        return {"ok": True, "path": str(path), "exists": Path(path).is_file()}
