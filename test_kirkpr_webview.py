# -*- coding: utf-8 -*-
"""Kadenski testi za WebView2 most (brez zagona GUI in brez vpisa v pravo konfiguracijo)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import kirkpr_minimax_core as core
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

    def test_version_is_5_0_01(self) -> None:
        self.assertEqual("5.0.01", APP_VERSION)
        boot = self.svc.boot()
        self.assertTrue(boot["ok"])
        self.assertEqual("5.0.01", boot["version"])
        self.assertFalse(boot["has_data"])

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


if __name__ == "__main__":
    unittest.main()