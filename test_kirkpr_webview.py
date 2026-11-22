# -*- coding: utf-8 -*-
"""Kadenski testi za WebView2 most (brez zagona GUI in brez vpisa v pravo konfiguracijo)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import kirkpr_minimax_core as core
import kirkpr_company_registry as registry
from kirkpr_webview_service import APP_VERSION, KirKprService


def _sample_payload() -> dict:
    return {
        "Glava": {
            "OBDOBJE_OD": "2026-04-01",
            "OBDOBJE_DO": "2026-04-30",
            "TaxPayerID": "12345678",
        },
        "Lista_KIR": {
            "KIR": [
                {
                    "ZAPST": "1",
                    "P2": "2026-04-10", "P4": "2026-04-10",
                    "P3": "IR-1",
                    "P5": "Kupec d.o.o.",
                    "P6DS": "SI12345678",
                    "P7": "100.00",
                    "P14": "22.00",
                }
            ]
        },
        "Lista_KPR": {
            "KPR": [
                {
                    "ZAPST": "1",
                    "P2": "2026-04-12", "P4": "2026-04-12",
                    "P3": "PR-1",
                    "P6": "Dobavitelj d.o.o.",
                    "P7DS": "SI87654321",
                    "P8": "200.00",
                    "P18": "44.00",
                }
            ]
        },
    }



class _FakeResponse:
    def __init__(self, location="https://moj.minimax.si/api/orgs/99/receivedinvoices/123", status=201):
        self.location = location
        self.status = status


class _FakeMinimaxClient:
    def __init__(self, organisation_id="99"):
        self.organisation_id = organisation_id
        self.sent = []
        self.validate_result = "OK"
        self.validate_detail = "pripravljeno"

    def validate_rows(self, dataset, selections, status="O", mode="journal", options=None, progress=None):
        return [{"status": self.validate_result, "detail": self.validate_detail} for _ in selections]

    def send_row(self, dataset, book, row, status="O", *, mode="journal", options=None):
        self.sent.append({"book": book, "invoice": row.get("P3"), "status": status, "mode": mode, "options": dict(options or {})})
        return _FakeResponse()

    def invoice_attachments(self, book, record_id):
        return [{"id": record_id}]

    def attachment_file(self, attachment):
        return ("priloga.pdf", b"%PDF-fake")

    def supplier_issued_invoice_attachments(self, **kwargs):
        return {"IssuedInvoiceId": 7, "Number": "IR-Q"}, [{"id": 2}]


class WebviewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.config_path = self.base / "convert_KIrKpr_to_minimax_config.json"
        self.config_path.write_text(
            json.dumps(core.default_config(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.sample = self.base / "sample.json"
        self.sample.write_text(json.dumps(_sample_payload(), ensure_ascii=False), encoding="utf-8")
        self.svc = KirKprService(config_path=self.config_path, base_dir=self.base)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_version_is_5_0_09(self) -> None:
        self.assertEqual("5.0.09", APP_VERSION)
        boot = self.svc.boot()
        self.assertTrue(boot["ok"])
        self.assertEqual("5.0.09", boot["version"])
        self.assertFalse(boot["has_data"])

    def test_theme_and_look_defaults_and_persist_in_temp_config(self) -> None:
        boot = self.svc.boot()
        self.assertEqual("light", boot["theme"])
        self.assertEqual("t5", boot["look"])
        themed = self.svc.set_theme("dark")
        self.assertEqual("dark", themed["theme"])
        looked = self.svc.set_look("t4")
        self.assertEqual("t4", looked["look"])
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual("dark", saved.get("ui_theme"))
        self.assertEqual("t4", saved.get("ui_look"))
        again = KirKprService(config_path=self.config_path, base_dir=self.base)
        boot2 = again.boot()
        self.assertEqual("dark", boot2["theme"])
        self.assertEqual("t4", boot2["look"])

    def test_restored_company_gets_period_suggestion(self) -> None:
        company = {"Zšt": "7", "Kratko ime": "Test d.o.o.", "oddaja DDV": "Mesečni"}
        key = "zst-7"
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["selected_company_key"] = key
        self.config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        svc = KirKprService(config_path=self.config_path, base_dir=self.base)
        svc.companies = [company]
        svc._restore_selected_company()
        state = svc._state()
        self.assertIsNotNone(svc.selected_company)
        self.assertTrue(state["period_from"])
        self.assertTrue(state["period_to"])
        self.assertTrue(state["period_label"])
        self.assertNotEqual("—", state["period_label"])

    def test_load_source_lists_ir_pr_and_ddvo(self) -> None:
        result = self.svc.load_source(str(self.sample))
        self.assertTrue(result["ok"])
        self.assertTrue(result["has_data"])
        self.assertEqual("2026-04-01", result["period_from"])
        self.assertEqual("2026-04-30", result["period_to"])
        self.assertEqual(1, result["summary"]["ir_count"])
        self.assertEqual(1, result["summary"]["pr_count"])

        ir = self.svc.list_ir()
        self.assertEqual(1, ir["visible"])
        self.assertEqual("IR-1", ir["rows"][0]["invoice"])
        self.assertEqual("Kupec d.o.o.", ir["rows"][0]["party"])
        self.assertIn("122", ir["rows"][0]["gross"])  # 100 + 22, slovenski zapis

        pr = self.svc.list_pr()
        self.assertEqual(1, pr["visible"])
        self.assertEqual("PR-1", pr["rows"][0]["invoice"])

        ddvo = self.svc.ddvo()
        self.assertTrue(ddvo["has_data"])
        self.assertTrue(len(ddvo["fields"]) >= 5)
        self.assertIn("control_ok", ddvo)

    def test_search_and_period_filter(self) -> None:
        self.svc.load_source(str(self.sample))
        self.assertEqual(0, self.svc.list_ir("neznani-niz")["visible"])
        self.assertEqual(1, self.svc.list_ir("IR-1")["visible"])
        self.svc.set_period("2026-05-01", "2026-05-31")
        self.assertEqual(0, self.svc.list_ir()["visible"])
        self.svc.reset_period()
        self.assertEqual(1, self.svc.list_ir()["visible"])

    def _prepare_company_trops(self):
        trops = self.base / "TROPS"
        ddv = trops / "07" / "DDV"
        ddv.mkdir(parents=True)
        self.svc.config["trops_root"] = str(trops)
        self.svc.selected_company = {"Zšt": "7", "Kratko ime": "Test d.o.o.", "oddaja DDV": "Mesečni"}
        return trops, ddv

    def test_dialog_directories_prefer_company_ddv(self) -> None:
        trops, ddv = self._prepare_company_trops()
        dirs = self.svc.dialog_directories()
        self.assertEqual(str(ddv), dirs["open"])
        self.assertEqual(str(ddv), dirs["save"])
        boot = self.svc.boot()
        self.assertEqual(str(ddv), boot["dialog_dirs"]["open"])
        # dialog helpers must not create Virmani or other folders
        names = {path.name for path in trops.rglob("*")}
        self.assertNotIn("Virmani", names)

    def test_dialog_directories_source_input_dir_wins_if_exists(self) -> None:
        trops, ddv = self._prepare_company_trops()
        custom = self.base / "vhod"
        custom.mkdir()
        self.svc.config["source_input_dir"] = str(custom)
        dirs = self.svc.dialog_directories()
        self.assertEqual(str(custom), dirs["open"])
        self.assertEqual(str(ddv), dirs["save"])

    def test_bridge_dialog_kwargs_sets_directory_only_if_exists(self) -> None:
        from host_webview import Bridge
        missing = self.base / "ni_te_mape"
        self.assertNotIn("directory", Bridge.dialog_kwargs(directory=str(missing)))
        existing = self.base / "obstaja"
        existing.mkdir()
        kw = Bridge.dialog_kwargs(directory=str(existing), file_types=["JSON (*.json)"])
        self.assertEqual(str(existing), kw["directory"])
        self.assertEqual(("JSON (*.json)",), kw["file_types"])
        file_path = existing / "x.txt"
        file_path.write_text("x", encoding="utf-8")
        kw = Bridge.dialog_kwargs(directory=str(file_path))
        self.assertEqual(str(existing), kw["directory"])

    def test_load_source_remembers_file_in_temp_config(self) -> None:
        state = self.svc.load_source(str(self.sample))
        self.assertTrue(state["has_data"])
        self.assertEqual(str(self.sample), self.svc.config["last_source_file"])
        self.assertEqual(str(self.sample.parent), self.svc.config["last_input_dir"])
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(str(self.sample), saved["last_source_file"])
        self.assertEqual(str(self.sample.parent), saved["last_input_dir"])

    def test_load_source_remembers_file_per_company_profile(self) -> None:
        other = self.base / "druga_mapa"
        other.mkdir()
        other_file = other / "druga.json"
        other_file.write_text(self.sample.read_text(encoding="utf-8"), encoding="utf-8")
        company = {"Zšt": "7", "Kratko ime": "Test d.o.o.", "oddaja DDV": "Mesečni"}
        self.svc.companies = [company]
        self.svc.selected_company = company
        self.svc.load_source(str(other_file))
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        key = registry.company_key(company)
        profile = saved["company_profiles"][key]
        self.assertEqual(str(other_file), profile["last_source_file"])
        self.assertEqual(str(other), profile["last_input_dir"])
        self.assertEqual(str(other_file), saved["last_source_file"])
        again = KirKprService(config_path=self.config_path, base_dir=self.base)
        again.companies = [company]
        again.selected_company = company
        opened = again.open_last_source()
        self.assertTrue(opened["has_data"])
        self.assertEqual(str(other_file), str(again.dataset.source_path))

    def test_boot_auto_reopens_last_source_when_enabled(self) -> None:
        self.svc.load_source(str(self.sample))
        again = KirKprService(config_path=self.config_path, base_dir=self.base)
        boot = again.boot()
        self.assertTrue(boot["has_data"])
        self.assertEqual(str(self.sample), str(again.dataset.source_path))
        refresh = again.boot()
        self.assertTrue(refresh["has_data"])

    def test_boot_skips_auto_reopen_when_disabled(self) -> None:
        self.svc.load_source(str(self.sample))
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["auto_reopen_last_source"] = False
        self.config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        again = KirKprService(config_path=self.config_path, base_dir=self.base)
        boot = again.boot()
        self.assertFalse(boot["has_data"])
        self.assertIsNone(again.dataset)

    def test_boot_skips_vasco_last_source_and_forgets_it(self) -> None:
        vasco = self.base / "vasco.xlsx"
        vasco.write_bytes(b"PK\x03\x04fake")
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["last_source_file"] = str(vasco)
        cfg["auto_reopen_last_source"] = True
        self.config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        again = KirKprService(config_path=self.config_path, base_dir=self.base)
        boot = again.boot()
        self.assertFalse(boot["has_data"])
        self.assertTrue(boot.get("vasco_skipped"))
        self.assertIn("Vasco", boot["msg"])
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual("", saved.get("last_source_file") or "")

    def test_ddvo_control_and_payment_text(self) -> None:
        self.svc.load_source(str(self.sample))
        ctrl = self.svc.ddvo_control_text()
        self.assertTrue(ctrl["ok"])
        self.assertIn("DDV-O", ctrl["text"])
        self.assertIn("kontrolna razlika", ctrl["text"])
        pay = self.svc.virman_payment_text("0")
        self.assertTrue(pay["ok"])
        self.assertTrue(pay["text"])

    def test_parse_konto62_clipboard_reads_saldo(self) -> None:
        parsed = self.svc.parse_konto62_clipboard("123,45")
        self.assertTrue(parsed["ok"])
        self.assertIn("123,45", parsed["value"])

    def test_save_working_copy_includes_saved_path_in_temp(self) -> None:
        self.svc.load_source(str(self.sample))
        target = self.base / "kopija.json"
        state = self.svc.save_working_copy_action(str(target))
        self.assertTrue(target.is_file())
        self.assertEqual(str(target), state["saved_path"])

    def test_export_ddvo_report_includes_saved_path_in_temp(self) -> None:
        self.svc.load_source(str(self.sample))
        out = self.base / "izvoz"
        out.mkdir()
        state = self.svc.export_ddvo("report", out_dir=str(out))
        self.assertTrue(state.get("saved_path"))
        self.assertTrue(Path(state["saved_path"]).is_file())
        self.assertEqual(out, Path(state["saved_path"]).parent)

    def test_bridge_copy_text_roundtrip(self) -> None:
        from host_webview import Bridge
        previous = None
        try:
            previous = Bridge.get_text()
        except Exception:
            previous = None
        token = "KIRKPR-CLIP-" + str(self.base)
        try:
            if not Bridge.copy_text(token):
                self.skipTest("Odlozisce ni na voljo v tem okolju.")
            self.assertEqual(token, Bridge.get_text())
        finally:
            if previous is not None:
                Bridge.copy_text(previous)

    def test_path_settings_write_only_given_config(self) -> None:
        before = self.config_path.read_text(encoding="utf-8")
        self.svc.save_path_settings(
            company_registry_path=str(self.base / "firme.json"),
            trops_root=str(self.base / "trops"),
            minimax_settings_path=str(self.base / "settings.json"),
        )
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertTrue(data["company_registry_path"].endswith("firme.json"))
        self.assertTrue(data["trops_root"].endswith("trops"))
        # Ne sme posegati v privzeto konfiguracijo projekta.
        project_cfg = Path(r"D:\PISARNA\Python\KirKpr\convert_KIrKpr_to_minimax_config.json")
        if project_cfg.is_file():
            self.assertNotEqual(project_cfg.resolve(), self.config_path.resolve())
        self.assertNotEqual(before, self.config_path.read_text(encoding="utf-8"))



    def test_apply_account_and_editor_on_temp_files_only(self) -> None:
        project_cfg = Path(r"D:\\PISARNA\\Python\\KirKpr\\convert_KIrKpr_to_minimax_config.json")
        project_before = project_cfg.read_bytes() if project_cfg.is_file() else None
        self.svc.load_source(str(self.sample))
        result = self.svc.apply_accounts("IR", ["ir:0"], "7610", remember_rule=True, persist_working=True)
        self.assertTrue(result["ok"])
        self.assertEqual("7610", self.svc.dataset.kir[0]["__konto__"])
        self.assertEqual("7610", self.svc.list_ir()["rows"][0]["account"])
        self.assertIn("7610", json.dumps(json.loads(self.config_path.read_text(encoding="utf-8")), ensure_ascii=False))
        working = self.sample.parent / "sample_MINIMAX_UREJENO.json"
        self.assertTrue(working.is_file())
        self.assertNotEqual(working.resolve(), self.sample.resolve())

        editor = self.svc.get_editor("pr:0")
        self.assertTrue(editor["ok"])
        self.assertEqual("PR-1", editor["invoice"])
        self.assertTrue(any(f["name"] == "P8" for f in editor["fields"]))
        saved = self.svc.save_editor(
            "pr:0",
            {
                "account": "4190",
                "description": "Popravljen opis PR-1",
                "remember_rule": True,
                "self_assessment": False,
                "vat_deductible": False,
                "fields": {"P8": "250,00"},
            },
        )
        self.assertTrue(saved["ok"])
        self.assertTrue(saved["working_dirty"])
        self.assertEqual("Popravljen opis PR-1", self.svc.dataset.kpr[0]["__opis__"])
        self.assertFalse(self.svc.dataset.kpr[0]["__ddv_se_odbija__"])

        vat = self.svc.set_vat_deductible(["pr:0"], True, persist_working=False)
        self.assertTrue(vat["ok"])
        self.assertTrue(self.svc.dataset.kpr[0]["__ddv_se_odbija__"])

        base = self.svc.compute_vat_base("P14", "22,00")
        self.assertTrue(base["ok"])
        self.assertEqual("100,00", base["base"])

        with self.assertRaises(core.KirkprError):
            self.svc.apply_accounts("IR", ["ir:0"], "417", persist_working=False)

        if project_before is not None:
            self.assertEqual(project_before, project_cfg.read_bytes())


    def test_data_editor_changes_working_copy_only(self) -> None:
        project_cfg = Path(r"D:\PISARNA\Python\KirKpr\convert_KIrKpr_to_minimax_config.json")
        project_before = project_cfg.read_bytes() if project_cfg.is_file() else None
        self.svc.load_source(str(self.sample))
        original_p7 = self.svc.source_dataset.kir[0]["P7"]
        editor = self.svc.get_data_editor("ir:0")
        self.assertTrue(editor["ok"])
        self.assertEqual("IR-1", editor["invoice"])
        p7 = next(f for f in editor["fields"] if f["name"] == "P7")
        self.assertEqual(p7["original"], p7["working"])
        self.assertFalse(p7["changed"])
        result = self.svc.apply_data_field("ir:0", "P7", "150,00")
        self.assertTrue(result["ok"])
        self.assertTrue(result["working_dirty"])
        updated = next(f for f in result["editor"]["fields"] if f["name"] == "P7")
        self.assertTrue(updated["changed"])
        self.assertEqual("150,00", updated["working"])
        self.assertEqual("100,00", updated["original"])
        self.assertEqual(original_p7, self.svc.source_dataset.kir[0]["P7"])
        self.assertNotEqual(original_p7, self.svc.dataset.kir[0]["P7"])
        if project_before is not None:
            self.assertEqual(project_before, project_cfg.read_bytes())


    def test_ddvo_export_xml_report_and_virman_quote_in_temp(self) -> None:
        project_cfg = Path(r"D:\PISARNA\Python\KirKpr\convert_KIrKpr_to_minimax_config.json")
        project_before = project_cfg.read_bytes() if project_cfg.is_file() else None
        out = self.base / "ddvo_out"
        out.mkdir()
        self.svc.load_source(str(self.sample))
        report = self.svc.export_ddvo("report", out_dir=str(out))
        self.assertTrue(report["ok"])
        report_path = Path(report["export_paths"]["report"])
        self.assertTrue(report_path.is_file())
        self.assertEqual(report_path.parent.resolve(), out.resolve())
        self.assertIn("DDV-O", report_path.read_text(encoding="utf-8-sig"))

        xml = self.svc.export_ddvo("xml", out_dir=str(out))
        self.assertTrue(xml["ok"])
        xml_path = Path(xml["export_paths"]["xml"])
        self.assertTrue(xml_path.is_file())
        self.assertTrue(xml_path.name.lower().endswith(".xml"))
        self.assertIn("DDV", xml_path.read_text(encoding="utf-8"))

        quote = self.svc.virman_quote("0")
        self.assertTrue(quote["ok"])
        self.assertIn("needs_virman", quote)
        self.assertTrue(quote["payment"])

        if project_before is not None:
            self.assertEqual(project_before, project_cfg.read_bytes())


    def test_knjiga_json_and_api_views_without_network(self) -> None:
        project_cfg = Path(r"D:\PISARNA\Python\KirKpr\convert_KIrKpr_to_minimax_config.json")
        project_before = project_cfg.read_bytes() if project_cfg.is_file() else None
        self.svc.load_source(str(self.sample))
        data = self.svc.list_knjiga("IR", mode="json")
        self.assertTrue(data["ok"])
        self.assertEqual("json", data["mode"])
        self.assertEqual(1, data["visible"])
        self.assertEqual("IR-1", data["rows"][0]["p3"])
        self.assertIn("100,00", data["rows"][0]["p7"])
        self.assertTrue(any(c["key"] == "p14" for c in data["columns"]))
        hidden = self.svc.list_knjiga("IR", mode="json", hide_zero=True)
        hidden_keys = [c["key"] for c in hidden["columns"]]
        self.assertIn("p7", hidden_keys)
        self.assertIn("p14", hidden_keys)
        self.assertNotIn("p27", hidden_keys)

        pr = self.svc.list_knjiga("PR", mode="json")
        self.assertEqual(1, pr["visible"])
        self.assertEqual("PR-1", pr["rows"][0]["p3"])

        self.svc.knjiga_records = {
            "IR": [{
                "IssuedInvoiceId": 99,
                "InvoiceNumber": "IR-1",
                "DateIssued": "2026-04-10",
                "CustomerName": "Kupec d.o.o.",
                "InvoiceAmount": "122.00",
                "Status": "O",
            }],
            "PR": [],
        }
        api_view = self.svc.list_knjiga("IR", mode="api")
        self.assertEqual("api", api_view["mode"])
        matches = [row["match"] for row in api_view["rows"]]
        self.assertIn("V KIR/KPR", matches)
        with self.assertRaises(core.KirkprError):
            self.svc.refresh_knjige_from_api()
        if project_before is not None:
            self.assertEqual(project_before, project_cfg.read_bytes())


    def test_sessions_and_help_use_temp_db_only(self) -> None:
        project_cfg = Path(r"D:\PISARNA\Python\KirKpr\convert_KIrKpr_to_minimax_config.json")
        project_sess = Path(r"D:\PISARNA\Python\KirKpr\kirkpr_sessions.sqlite3")
        cfg_before = project_cfg.read_bytes() if project_cfg.is_file() else None
        sess_before = project_sess.read_bytes() if project_sess.is_file() else None
        company = {"Zšt": "99", "Kratko ime": "Test d.o.o.", "DAVČNA": "12345678"}
        self.svc.companies = [company]
        self.svc.selected_company = company
        self.svc.load_source(str(self.sample))
        saved = self.svc.save_session("Test seja april")
        self.assertTrue(saved["ok"])
        rows = self.svc.list_sessions()["rows"]
        self.assertEqual(1, len(rows))
        self.assertIn("Test seja april", rows[0]["title"] or rows[0]["label"])
        self.assertTrue(str(self.svc.sessions_db.path).startswith(str(self.base)))
        opened = self.svc.open_session(int(rows[0]["id"]))
        self.assertTrue(opened["ok"])
        self.assertTrue(opened["has_data"])
        deleted = self.svc.delete_session(int(rows[0]["id"]))
        self.assertTrue(deleted["ok"])
        self.assertEqual(0, len(self.svc.list_sessions()["rows"]))
        help_page = self.svc.help_topic("formats")
        self.assertIn("FURS", help_page["body"])
        if cfg_before is not None:
            self.assertEqual(cfg_before, project_cfg.read_bytes())
        if sess_before is not None:
            self.assertEqual(sess_before, project_sess.read_bytes())
        else:
            self.assertFalse(project_sess.exists())

    def _prepare_api(self):
        self.svc.selected_company = {
            "Kratko ime": "Test d.o.o.",
            "Org_ID": "99",
            "DAVČNA": "12345678",
            "Zšt": "1",
        }
        client = _FakeMinimaxClient()
        self.svc.minimax_client = client
        self.svc.minimax_org_label = "99 — Test d.o.o."
        self.svc.load_source(str(self.sample))
        return client

    def test_connect_requires_company_and_settings(self) -> None:
        with self.assertRaises(core.KirkprError):
            self.svc.connect_minimax_api()
        self.svc.selected_company = {"Kratko ime": "Brez Org"}
        with self.assertRaises(core.KirkprError):
            self.svc.connect_minimax_api()
        self.svc.selected_company = {"Kratko ime": "Test d.o.o.", "Org_ID": "99"}
        with self.assertRaises(core.KirkprError):
            self.svc.connect_minimax_api(str(self.base / "manjka.json"))

    def test_list_api_and_validate_without_real_client_send(self) -> None:
        client = self._prepare_api()
        listed = self.svc.list_api()
        self.assertEqual(2, listed["visible"])
        ids = [row["id"] for row in listed["rows"]]
        self.assertIn("api:IR:0", ids)
        self.assertIn("api:PR:0", ids)
        validated = self.svc.validate_api_selection(ids)
        self.assertTrue(validated["all_ok"])
        self.assertEqual("OK", validated["rows"][0]["api_status"])
        self.assertEqual([], client.sent)

    def test_send_requires_confirmation_and_never_fires_without_it(self) -> None:
        client = self._prepare_api()
        ids = [row["id"] for row in self.svc.list_api()["rows"]]
        self.svc.validate_api_selection(ids)
        with self.assertRaises(core.KirkprError) as ctx:
            self.svc.send_api_selection(ids, confirm=False)
        self.assertIn("potrditvi", str(ctx.exception))
        self.assertEqual([], client.sent)
        preview = self.svc.preview_api_send(ids)
        self.assertTrue(preview["ok"])
        self.assertIn("Nadaljujem?", preview["prompt"])
        self.assertEqual([], client.sent)
        out = self.base / "api_summaries"
        sent = self.svc.send_api_selection(ids, confirm=True, summary_dir=str(out))
        self.assertEqual(2, sent["sent"])
        self.assertEqual(2, len(client.sent))
        self.assertTrue(Path(sent["summary_path"]).is_file())
        self.assertEqual(out.resolve(), Path(sent["summary_path"]).parent.resolve())

    def test_retry_failed_validates_but_does_not_send(self) -> None:
        client = self._prepare_api()
        ids = [row["id"] for row in self.svc.list_api()["rows"]]
        client.validate_result = "NAPAKA"
        client.validate_detail = "ni pripravljeno"
        self.svc.validate_api_selection(ids)
        self.assertEqual("NAPAKA", self.svc.list_api()["rows"][0]["api_status"])
        client.validate_result = "OK"
        client.validate_detail = "pripravljeno"
        retried = self.svc.retry_failed_api_rows()
        self.assertTrue(retried["all_ok"])
        self.assertEqual([], client.sent)
        self.assertIn("Oddaj izbrane", retried["msg"])

    def test_attachments_stay_in_temp_and_supplier_guard(self) -> None:
        client = self._prepare_api()
        ir_id, pr_id = "api:IR:0", "api:PR:0"
        with self.assertRaises(core.KirkprError):
            self.svc.download_invoice_attachments(pr_id, out_dir="")
        with self.assertRaises(core.KirkprError):
            self.svc.download_supplier_issued_attachment(pr_id, out_dir=str(self.base / "quick"))
        source = self.base / "priponka.txt"
        source.write_text("ok", encoding="utf-8")
        dest = self.base / "priponke_out"
        imported = self.svc.import_attachment_from_folder(pr_id, [str(source)], dest_dir=str(dest))
        self.assertEqual(1, len(imported["files"]))
        self.assertTrue(Path(imported["files"][0]).is_file())
        self.assertEqual(dest.resolve(), Path(imported["out_dir"]).resolve())
        self.svc._sent_invoice_id = lambda book, row: "123"
        down_dir = self.base / "download_att"
        downloaded = self.svc.download_invoice_attachments(pr_id, out_dir=str(down_dir))
        self.assertEqual(1, len(downloaded["files"]))
        self.assertTrue(Path(downloaded["files"][0]).is_file())
        self.svc.dataset.kpr[0]["P6"] = "QUICK M.B."
        quick_dir = self.base / "quick_out"
        quick = self.svc.download_supplier_issued_attachment(pr_id, out_dir=str(quick_dir))
        self.assertEqual(1, len(quick["files"]))
        self.assertTrue(Path(quick["files"][0]).is_file())
        self.assertEqual([], client.sent)
        with self.assertRaises(core.KirkprError):
            self.svc.download_invoice_attachments(ir_id, out_dir=str(down_dir))



    def test_email_editor_save_and_send_requires_confirmation(self) -> None:
        project_tpl = Path(r"D:\PISARNA\Python\KirKpr\ddvo_email_templates.json")
        tpl_before = project_tpl.read_bytes() if project_tpl.is_file() else None
        self.svc.selected_company = {
            "Kratko ime": "Test d.o.o.",
            "Org_ID": "99",
            "DAVČNA": "12345678",
            "Zšt": "1",
            "E-mail": "stranka@example.com",
        }
        self.svc.load_source(str(self.sample))
        editor = self.svc.get_email_editor()
        self.assertTrue(editor["ok"])
        self.assertTrue(editor["template_id"])
        self.assertTrue(editor["rendered_subject"] or editor["subject"])
        saved = self.svc.save_email_template(
            template_id=editor["template_id"],
            title=editor.get("title") or "Test predloga",
            subject=editor.get("subject") or "DDV {obdobje}",
            body=editor.get("body") or "<p>Pozdravljeni</p>",
        )
        self.assertTrue(saved["ok"])
        local_tpl = self.base / "ddvo_email_templates.json"
        self.assertTrue(local_tpl.is_file())
        if tpl_before is not None:
            self.assertEqual(tpl_before, project_tpl.read_bytes())
        preview = self.svc.preview_email_send({
            "to": "stranka@example.com",
            "subject": saved.get("rendered_subject") or saved.get("subject") or "Test",
            "body": saved.get("rendered_body") or saved.get("body") or "<p>Test</p>",
            "channel": "smtp",
        })
        self.assertTrue(preview["ok"])
        self.assertIn("Nadaljujem?", preview["prompt"])
        with self.assertRaises(core.KirkprError) as ctx:
            self.svc.send_email({
                "to": "stranka@example.com",
                "subject": "Ne sme se poslati",
                "body": "<p>Ne sme se poslati</p>",
                "channel": "smtp",
            }, confirm=False)
        self.assertIn("potrditvi", str(ctx.exception))
        # Tudi TEST zahteva potrditev in se v testih ne sme izvesti.
        with self.assertRaises(core.KirkprError):
            self.svc.send_email({
                "to": "stranka@example.com",
                "subject": "TEST ne sme iti ven",
                "body": "<p>x</p>",
                "channel": "smtp",
                "test": True,
            }, confirm=False)
        if tpl_before is not None:
            self.assertEqual(tpl_before, project_tpl.read_bytes())


if __name__ == "__main__":
    unittest.main()

import json as _json
import threading
import urllib.error
import urllib.request

from kirkpr_webview_service import KirKprService
from host_webview import AppServer

class HostHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name)
        self.config_path = self.base_dir / "convert_KIrKpr_to_minimax_config.json"
        self.config_path.write_text(
            _json.dumps(core.default_config(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.sample = self.base_dir / "sample.json"
        self.sample.write_text(_json.dumps(_sample_payload(), ensure_ascii=False), encoding="utf-8")
        service = KirKprService(config_path=self.config_path, base_dir=self.base_dir)
        self.server = AppServer(service)
        self.thread = threading.Thread(target=self.server.serve_forever, name="kirkpr-test-http", daemon=True)
        self.thread.start()
        self.origin = "http://%s" % self.server.allowed_host

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def _open(self, path, data=None, ticket=True):
        url = self.origin + path
        if ticket:
            url += ("&" if "?" in path else "?") + "ticket=" + self.server.token
        body = None if data is None else _json.dumps(data).encode("utf-8")
        headers = {"Host": self.server.allowed_host}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, _json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = _json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                parsed = {"raw": raw.decode("utf-8", "replace")}
            return exc.code, parsed

    def test_boot_requires_ticket(self) -> None:
        code, body = self._open("/api/boot", ticket=False)
        self.assertEqual(403, code)
        self.assertFalse(body.get("ok", True))

    def test_boot_and_load_source_via_http(self) -> None:
        code, body = self._open("/api/boot")
        self.assertEqual(200, code)
        self.assertEqual("5.0.09", body["version"])
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        self.assertTrue(body.get("has_data"))
        code, ir = self._open("/api/ir")
        self.assertEqual(200, code)
        self.assertEqual(1, ir["visible"])
        self.assertEqual("IR-1", ir["rows"][0]["invoice"])

    def test_editor_and_apply_via_http(self) -> None:
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        code, editor = self._open("/api/row?id=ir:0")
        self.assertEqual(200, code)
        self.assertEqual("IR-1", editor["invoice"])
        code, applied = self._open("/api/action", {
            "name": "apply_accounts",
            "book": "IR",
            "ids": ["ir:0"],
            "account": "7620",
            "remember_rule": True,
            "persist_working": False,
        })
        self.assertEqual(200, code)
        self.assertTrue(applied.get("ok"))
        code, ir = self._open("/api/ir")
        self.assertEqual("7620", ir["rows"][0]["account"])

    def test_data_editor_via_http(self) -> None:
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        code, editor = self._open("/api/data-editor?id=pr:0")
        self.assertEqual(200, code)
        self.assertEqual("PR-1", editor["invoice"])
        code, applied = self._open("/api/data-editor/apply", {"id": "pr:0", "field": "P8", "value": "210,00"})
        self.assertEqual(200, code)
        self.assertTrue(applied.get("ok"))
        p8 = next(f for f in applied["editor"]["fields"] if f["name"] == "P8")
        self.assertEqual("210,00", p8["working"])
        self.assertTrue(p8["changed"])

    def test_ddvo_export_via_http_stays_in_temp(self) -> None:
        out = self.base_dir / "http_ddvo"
        out.mkdir()
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        code, exported = self._open("/api/action", {
            "name": "export_ddvo",
            "kind": "xml",
            "out_dir": str(out),
            "sync": True,
        })
        self.assertEqual(200, code)
        self.assertTrue(exported.get("ok"))
        xml_path = Path(exported["export_paths"]["xml"])
        self.assertTrue(xml_path.is_file())
        self.assertEqual(xml_path.parent.resolve(), out.resolve())
        code, quote = self._open("/api/ddvo/quote?konto62=0")
        self.assertEqual(200, code)
        self.assertTrue(quote.get("ok"))

    def test_knjiga_json_via_http(self) -> None:
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        code, data = self._open("/api/knjige?book=IR&mode=json")
        self.assertEqual(200, code)
        self.assertEqual(1, data["visible"])
        self.assertEqual("IR-1", data["rows"][0]["p3"])

    def test_sessions_and_help_via_http(self) -> None:
        code, body = self._open("/api/help?topic=about")
        self.assertEqual(200, code)
        self.assertIn("4190", body["body"])
        code, sessions = self._open("/api/sessions")
        self.assertEqual(200, code)
        self.assertTrue(sessions.get("ok"))
        self.assertIn("rows", sessions)


    def test_minimax_list_and_send_without_confirm_via_http(self) -> None:
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        self.server.service.selected_company = {
            "Kratko ime": "Test d.o.o.",
            "Org_ID": "99",
            "DAVČNA": "12345678",
            "Zšt": "1",
        }
        client = _FakeMinimaxClient()
        self.server.service.minimax_client = client
        self.server.service.minimax_org_label = "99 — Test d.o.o."
        code, data = self._open("/api/minimax")
        self.assertEqual(200, code)
        self.assertEqual(2, data["visible"])
        ids = [row["id"] for row in data["rows"]]
        code, validated = self._open("/api/action", {"name": "validate_api_selection", "ids": ids, "sync": True})
        self.assertEqual(200, code)
        self.assertTrue(validated.get("all_ok"))
        code, refused = self._open("/api/action", {"name": "send_api_selection", "ids": ids, "confirm": False, "sync": True})
        self.assertEqual(400, code)
        self.assertIn("potrditvi", refused.get("msg") or refused.get("error") or "")
        self.assertEqual([], client.sent)

    def test_email_preview_and_send_without_confirm_via_http(self) -> None:
        code, body = self._open("/api/action", {"name": "load_source", "path": str(self.sample), "sync": True})
        self.assertEqual(200, code)
        self.server.service.selected_company = {
            "Kratko ime": "Test d.o.o.",
            "Org_ID": "99",
            "DAVČNA": "12345678",
            "Zšt": "1",
        }
        code, editor = self._open("/api/email")
        self.assertEqual(200, code)
        self.assertTrue(editor.get("template_id"))
        code, refused = self._open("/api/action", {
            "name": "send_email",
            "to": "stranka@example.com",
            "subject": "Ne sme se poslati",
            "body": "<p>x</p>",
            "channel": "smtp",
            "confirm": False,
            "sync": True,
        })
        self.assertEqual(400, code)
        self.assertIn("potrditvi", refused.get("msg") or refused.get("error") or "")
