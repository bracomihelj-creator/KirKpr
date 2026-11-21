# -*- coding: utf-8 -*-
"""Most med WebView2 vmesnikom in obstoječimi funkcijami KirKpr.

Ta modul ne uvaja novih izračunov, DDV pravil, XML izvoza ali API oddaje.
Samo kliče kirkpr_minimax_core, register podjetij in pomožne funkcije obdobja.
"""
from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

import kirkpr_company_registry as registry
import kirkpr_minimax_core as core
import convert_KIrKpr_to_minimax as gui_helpers

APP_VERSION = "5.0.03"
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
