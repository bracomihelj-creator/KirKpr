"""Regresijski testi za KIR/KPR -> Minimax pretvornik."""

from __future__ import annotations

import csv
import base64
import io
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

from lxml import etree

import kirkpr_minimax_core as core
import kirkpr_minimax_browser as minimax_browser
import minimax_api_client as minimax_api
import convert_KIrKpr_to_minimax as minimax_gui


BASE_DIR = Path(__file__).resolve().parent
SAMPLE = BASE_DIR / "04-06-2026.json"


class AccountCodeValidationTests(unittest.TestCase):
    def test_short_numeric_account_rejected(self) -> None:
        with self.assertRaises(core.KirkprError) as ctx:
            core.validate_minimax_account_code("417")
        self.assertIn("prekratek", str(ctx.exception).casefold())
        self.assertIn("4170", str(ctx.exception))

    def test_full_account_accepted(self) -> None:
        self.assertEqual("4170", core.validate_minimax_account_code("4170 — Stroški sejmov"))
        self.assertEqual("4190", core.validate_minimax_account_code("4190"))

    def test_catalog_requires_exact_code(self) -> None:
        catalog = {"4170": "Stroški sejmov", "4190": "Storitve"}
        self.assertEqual("4170", core.validate_minimax_account_code("4170", catalog=catalog))
        with self.assertRaises(core.KirkprError) as ctx:
            core.validate_minimax_account_code("417", catalog=catalog)
        self.assertIn("4170", str(ctx.exception))

    def test_remember_account_rejects_short_code(self) -> None:
        config = core.default_config()
        row = {"P3": "PR-1", "P6": "DOB", "P7DS": "123"}
        with self.assertRaises(core.KirkprError):
            core.remember_account(config, "PR", row, "417")


class ListinaSortTests(unittest.TestCase):
    def test_listina_sort_follows_numeric_sequence(self) -> None:
        refs = [
            "26-120-000030",
            "26-120-000022",
            "26-120-000028",
            "26-120-000023",
        ]
        self.assertEqual(
            [
                "26-120-000022",
                "26-120-000023",
                "26-120-000028",
                "26-120-000030",
            ],
            sorted(refs, key=minimax_gui.listina_sort_key),
        )


class DocumentReferenceGuardTests(unittest.TestCase):
    def test_duplicate_listina_in_batch_is_rejected(self) -> None:
        client = minimax_api.MinimaxClient.__new__(minimax_api.MinimaxClient)
        seen: set[tuple[str, str]] = set()
        row = {"P3": "26-120-000022"}
        client._assert_unique_document_reference("PR", row, seen_batch=seen)
        with self.assertRaises(minimax_api.MinimaxApiError):
            client._assert_unique_document_reference("PR", row, seen_batch=seen)

    def test_existing_minimax_listina_is_rejected(self) -> None:
        client = minimax_api.MinimaxClient.__new__(minimax_api.MinimaxClient)
        row = {"P3": "26-120-000022"}
        existing = {"PR": {minimax_api.normal_invoice_reference("26-120-000022"): "Osnutek"}}
        with self.assertRaises(minimax_api.MinimaxApiError):
            client._assert_unique_document_reference("PR", row, existing_refs=existing)


class BrowserLinkTests(unittest.TestCase):
    def test_extract_received_invoice_id_from_location(self) -> None:
        location = "https://moj.minimax.si/SI/API/api/orgs/203547/receivedinvoices/68403092?id=68403092"
        self.assertEqual(
            "68403092",
            minimax_browser.extract_minimax_record_id(location, "receivedinvoices"),
        )

    def test_extract_record_id_without_query(self) -> None:
        location = "https://moj.minimax.si/SI/API/api/orgs/203547/issuedinvoices/51586221"
        self.assertEqual(
            "51586221",
            minimax_browser.extract_minimax_record_id(location, "issuedinvoices"),
        )

    def test_extract_record_id_from_location_with_companion_warning(self) -> None:
        location = "/api/orgs/203547/receivedinvoices/68403094 • spremljevalna temeljnica"
        self.assertEqual(
            "68403094",
            minimax_browser.extract_minimax_record_id(location, "receivedinvoices"),
        )

    def test_shared_session_status_does_not_export_cookies(self) -> None:
        fake = SimpleNamespace(
            playwright_profile_dir=lambda: Path(r"C:\Local\MinimaxBlagajna\PlaywrightProfile"),
            playwright_ready=lambda: True,
            playwright_logged_in=lambda **_kwargs: True,
        )
        with patch.object(minimax_browser, "_load_playwright_module", return_value=fake):
            status = minimax_browser.check_session()
        self.assertTrue(status.ready)
        self.assertTrue(status.logged_in)
        self.assertIn("PlaywrightProfile", status.profile_path)
        self.assertNotIn("cookie", status.message.casefold())

    def test_chrome_url_contains_actual_api_id_org_and_account(self) -> None:
        url = minimax_browser.received_draft_chrome_url(
            organisation_id="203547",
            received_invoice_id="68403094",
            organisation_name="KLUG d.o.o.",
            document_reference="26-120-000034",
            expense_account="4190",
            confirm=False,
            base_22="100.00",
            base_95="50",
            vat_22="22",
            vat_95="4.75",
        )
        # Na Zacetek ne sme iti Minimaxov pr_id/pgat (Sistemska napaka pred preklopom).
        self.assertNotIn("pr_id=", url)
        self.assertNotIn("pgat=", url)
        self.assertIn("kirkpr_pr=68403094", url)
        self.assertIn("kirkpr_org=203547", url)
        self.assertIn("kirkpr_konto=4190", url)
        self.assertIn("kirkpr_confirm=0", url)
        self.assertIn("kirkpr_osnova22=100.00", url)
        self.assertIn("kirkpr_osnova95=50.00", url)
        self.assertIn("kirkpr_ddv22=22.00", url)
        self.assertIn("kirkpr_ddv95=4.75", url)

    def test_chrome_open_uses_safe_default_without_confirm(self) -> None:
        with patch.object(minimax_browser.webbrowser, "open", return_value=True) as mocked:
            result = minimax_browser.open_received_draft_in_chrome(
                organisation_id="203547",
                received_invoice_id="68403094",
                organisation_name="KLUG d.o.o.",
                document_reference="26-120-000034",
                expense_account="4190",
            )
        self.assertTrue(result.ok)
        self.assertIn("brez končne potrditve", result.message)
        self.assertIn("kirkpr_confirm=0", mocked.call_args.args[0])


class LatestReceivedInvoiceTests(unittest.TestCase):
    def test_add_attachment_posts_base64_to_exact_confirmed_pr(self) -> None:
        client = minimax_api.MinimaxClient(SimpleNamespace())  # type: ignore[arg-type]
        client.organisation_id = 203547
        expected = SimpleNamespace(status=200)
        with patch.object(client, "post", return_value=expected) as mocked:
            result = client.add_invoice_attachment(
                "PR", 68403094, filename="2026-371-racun.pdf",
                data=b"%PDF-test", mime_type="application/pdf",
            )
        self.assertIs(expected, result)
        path, payload = mocked.call_args.args
        self.assertEqual("orgs/203547/receivedinvoices/68403094/attachments", path)
        self.assertEqual("2026-371-racun.pdf", payload["AttachmentFileName"])
        self.assertEqual(base64.b64encode(b"%PDF-test").decode("ascii"), payload["AttachmentData"])

    def test_latest_confirmed_uses_highest_actual_received_id(self) -> None:
        client = minimax_api.MinimaxClient(SimpleNamespace())  # type: ignore[arg-type]
        client.organisation_id = 203547
        with patch.object(
            client,
            "received_invoices",
            return_value=[
                {"ReceivedInvoiceId": 68403091, "Status": "P"},
                {"ReceivedInvoiceId": 68403093, "Status": "P"},
                {"ReceivedInvoiceId": 68403092, "Status": "P"},
            ],
        ):
            row = client.latest_confirmed_received_invoice()
        self.assertEqual(68403093, client.received_invoice_id(row))

    def test_invoice_status_catalog_maps_ir_and_pr_by_id_and_reference(self) -> None:
        client = minimax_api.MinimaxClient(SimpleNamespace())  # type: ignore[arg-type]
        client.organisation_id = 203547

        def fake_get(path: str) -> dict:
            if "issuedinvoices?" in path:
                return {
                    "Rows": [
                        {"IssuedInvoiceId": 101, "DocumentReference": "26-360-000012", "Status": "O"},
                        {"IssuedInvoiceId": 102, "DocumentReference": "26-360-000013", "Status": "P"},
                    ],
                    "TotalRows": 2,
                }
            if "receivedinvoices?" in path:
                return {
                    "Rows": [
                        {"ReceivedInvoiceId": 201, "DocumentReference": "26-120-000021", "Status": "P"},
                        {"ReceivedInvoiceId": 202, "DocumentReference": "26-120-000021", "Status": "O"},
                    ],
                    "TotalRows": 2,
                }
            raise AssertionError(path)

        client.get = fake_get  # type: ignore[method-assign]
        catalog = client.invoice_status_catalog(date_from="2026-04-01", date_to="2026-06-30")
        self.assertEqual("Osnutek", catalog["IR"]["by_id"]["101"])
        self.assertEqual("Potrjen", catalog["IR"]["by_reference"]["26-360-000013"])
        self.assertEqual("Potrjen", catalog["PR"]["by_id"]["201"])
        self.assertEqual(
            "Osnutek",
            catalog["PR"]["by_reference"]["26-120-000021"],
            "Pri podvojeni listini zmaga zapis z višjim dejanskim ID-jem.",
        )

    def test_invoice_status_by_id_reads_nested_record(self) -> None:
        client = minimax_api.MinimaxClient(SimpleNamespace())  # type: ignore[arg-type]
        client.organisation_id = 203547
        client.get = lambda _path: {  # type: ignore[method-assign]
            "ReceivedInvoice": {
                "ReceivedInvoiceId": 68403094,
                "DocumentReference": "26-120-000021",
                "Status": "O",
            }
        }
        status, reference = client.invoice_status_by_id("PR", 68403094)
        self.assertEqual("Osnutek", status)
        self.assertEqual("26-120-000021", reference)


class GuiInvoiceStatusTests(unittest.TestCase):
    def test_gui_status_prefers_exact_api_id_over_reference(self) -> None:
        app = object.__new__(minimax_gui.ConverterApp)
        app.active_company = {"Org_ID": "203547"}
        app.minimax_client = SimpleNamespace(organisation_id=203547)
        app.minimax_invoice_status_checked = True
        app.minimax_invoice_status_org = "203547"
        app.minimax_invoice_status_catalog = {
            "IR": {"by_reference": {}, "by_id": {}},
            "PR": {
                "by_reference": {"26-120-000021": "Osnutek"},
                "by_id": {"68403094": "Potrjen"},
            },
        }
        app._sent_invoice_id = lambda _book, _row: "68403094"  # type: ignore[method-assign]
        status = app._minimax_status_for_row("PR", {"P3": "26-120-000021"})
        self.assertEqual("Potrjen", status)

    def test_gui_status_requests_api_connection_for_other_org(self) -> None:
        app = object.__new__(minimax_gui.ConverterApp)
        app.active_company = {"Org_ID": "203547"}
        app.minimax_client = SimpleNamespace(organisation_id=999999)
        app.minimax_invoice_status_checked = False
        app.minimax_invoice_status_org = ""
        status = app._minimax_status_for_row("IR", {"P3": "IR-1"})
        self.assertEqual("Poveži API", status)


def fur_payload() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8-sig"))["DDV_KIR_KPR"]


def make_furs_xml(payload: dict) -> bytes:
    root = ET.Element("DDV_KIR_KPR")
    header = ET.SubElement(root, "Glava")
    for key, value in payload["Glava"].items():
        ET.SubElement(header, key).text = str(value).lower() if isinstance(value, bool) else str(value)
    for list_name, book in (("Lista_KIR", "KIR"), ("Lista_KPR", "KPR")):
        parent = ET.SubElement(root, list_name)
        rows = payload[list_name][book]
        for row in rows:
            element = ET.SubElement(parent, book)
            for key, value in row.items():
                ET.SubElement(element, key).text = str(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def slovenian_number(value: object) -> object:
    if not isinstance(value, (int, float)):
        return value
    text = f"{value:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def csv_bytes(rows: list[dict], book: str) -> bytes:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
    writer.writeheader()
    for row in rows:
        converted = dict(row)
        numeric_range = range(7, 28) if book == "KIR" else range(8, 22)
        for index in numeric_range:
            field = f"P{index}"
            if field in converted:
                converted[field] = slovenian_number(converted[field])
        writer.writerow(converted)
    return stream.getvalue().encode("utf-8-sig")


@unittest.skipUnless(SAMPLE.is_file(), "izbirni regresijski primer 04-06-2026.json ni priložen programu")
class ParserTests(unittest.TestCase):
    def test_json_sample(self) -> None:
        dataset = core.load_dataset(SAMPLE)
        self.assertEqual("JSON", dataset.source_format)
        self.assertEqual(10, len(dataset.kir))
        self.assertEqual(20, len(dataset.kpr))
        self.assertEqual("8274.40", dataset.kir[0]["P7"])
        self.assertEqual(9, core.dataset_summary(dataset)["ir_count"])

    def test_zip_with_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "podatki.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.write(SAMPLE, "oddaja/KIR_KPR.json")
            dataset = core.load_dataset(archive_path)
            self.assertTrue(dataset.source_format.startswith("ZIP"))
            self.assertEqual((10, 20), (len(dataset.kir), len(dataset.kpr)))

    def test_zip_with_separate_slovenian_csv_files(self) -> None:
        payload = fur_payload()
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "csv_podatki.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("izdani_KIR.csv", csv_bytes(payload["Lista_KIR"]["KIR"], "KIR"))
                archive.writestr("prejeti_KPR.csv", csv_bytes(payload["Lista_KPR"]["KPR"], "KPR"))
            dataset = core.load_dataset(archive_path)
            self.assertEqual((10, 20), (len(dataset.kir), len(dataset.kpr)))
            self.assertEqual("8274.40", dataset.kir[0]["P7"])
            self.assertEqual("153.28", dataset.kpr[0]["P8"])

    def test_furs_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            xml_path = Path(temporary) / "KIR_KPR.xml"
            xml_path.write_bytes(make_furs_xml(fur_payload()))
            dataset = core.load_dataset(xml_path)
            self.assertEqual("XML", dataset.source_format)
            self.assertEqual((10, 20), (len(dataset.kir), len(dataset.kpr)))


@unittest.skipUnless(SAMPLE.is_file(), "izbirni regresijski primer 04-06-2026.json ni priložen programu")
class ExportTests(unittest.TestCase):
    def test_accounts_rules_and_xsd_export(self) -> None:
        dataset = core.load_dataset(SAMPLE)
        config = core.default_config()
        core.apply_saved_accounts(dataset, config)
        self.assertTrue(all(row["__konto__"] == "4190" for row in dataset.kpr))

        selected = dataset.kpr[0]
        core.remember_account(config, "PR", selected, "4000", supplier_rule=True)
        fresh = core.load_dataset(SAMPLE)
        core.apply_saved_accounts(fresh, config)
        same_supplier = [row for row in fresh.kpr if core.supplier_key(row) == core.supplier_key(selected)]
        self.assertTrue(same_supplier)
        self.assertTrue(all(row["__konto__"] == "4000" for row in same_supplier))

        with tempfile.TemporaryDirectory() as temporary:
            result = core.export_minimax(dataset, Path(temporary))
            self.assertEqual((9, 20, 1), (result.issued_count, result.received_count, result.tax_only_kir_count))
            self.assertTrue(result.xsd_validated)
            self.assertTrue(result.archive.is_file())
            with zipfile.ZipFile(result.archive) as archive:
                self.assertEqual(3, len(archive.namelist()))

            namespace = {"m": core.minimax_xml.NS}
            issued = etree.parse(str(result.issued_xml))
            received = etree.parse(str(result.received_xml))
            self.assertEqual(9, len(issued.xpath("//m:Temeljnica", namespaces=namespace)))
            self.assertEqual(20, len(received.xpath("//m:Temeljnica", namespaces=namespace)))
            accounts = received.xpath("//m:SifraKonta/text()", namespaces=namespace)
            self.assertIn("4190", accounts)


class MinimaxApiPayloadTests(unittest.TestCase):
    @staticmethod
    def client() -> minimax_api.MinimaxClient:
        settings = minimax_api.ApiSettings(
            api_base="https://example.invalid",
            auth_url="https://example.invalid/token",
            scope="test",
            client_id="test",
            client_secret="test",
            username="test",
            password="test",
            organisation_id="1",
            source_path=BASE_DIR / "test-settings.json",
        )
        client = minimax_api.MinimaxClient(settings)
        client.organisation_id = 1
        client._reference_by_code = lambda _resource, code: {"ID": {"EUR": 7}.get(code, 10)}  # type: ignore[method-assign]
        client._customer_reference = lambda _party: {"ID": 20}  # type: ignore[method-assign]
        client._vat_rate_reference = lambda code: {"ID": {"S": 31, "Z": 32, "0": 33, "O": 34, "N": 35}[code]}  # type: ignore[method-assign]
        client.document_numbering_catalog = lambda book="": [  # type: ignore[method-assign]
            {"id": 41 if book == "IR" else 42, "document": book, "code": book, "name": book, "default": True, "label": f"{41 if book == 'IR' else 42} — {book}"}
        ]
        client.item_catalog = lambda: [  # type: ignore[method-assign]
            {"id": 51, "code": "STORITEV", "title": "Storitve", "type": "S", "unit": "x", "revenue_account": "7601", "label": "51 — STORITEV — Storitve"}
        ]
        client.vat_accounting_type_catalog = lambda _date="": [  # type: ignore[method-assign]
            {"code": "OD", "book": "IR", "name": "Obračuna se DDV", "label": "OD — Obračuna se DDV"}
        ]
        return client

    @staticmethod
    def dataset() -> core.KirkprDataset:
        ir = {
            "ZAPST": "1", "P2": "2026-06-30", "P3": "IR-1", "P4": "2026-06-30",
            "P5": "KUPEC d.o.o.", "P6": "SI", "P6DS": "12345678", "P7": "100.00",
            "P14": "22.00", "P15": "0", "P16": "0", "__konto__": "7601",
        }
        pr = {
            "ZAPST": "1", "P2": "2026-06-30", "P3": "PR-1", "P4": "2026-06-30",
            "P5": "2026-06-30", "P6": "DOBAVITELJ d.o.o.", "P7": "SI", "P7DS": "87654321",
            "P8": "100.00", "P18": "22.00", "__konto__": "4190",
        }
        return core.KirkprDataset(
            header={"OBDOBJE_OD": "2026-06-01", "OBDOBJE_DO": "2026-06-30"},
            kir=[ir],
            kpr=[pr],
            source_path=BASE_DIR / "test.json",
            source_format="JSON",
        )

    def test_invoice_drafts_have_numbering_dates_and_amounts(self) -> None:
        client = self.client()
        dataset = self.dataset()
        issued = client.preflight_row(
            dataset,
            "IR",
            dataset.kir[0],
            mode="invoice",
            options={"numbering_ir_id": 41, "item_ir_id": 51, "due_days": 8, "vat_type_ir": "OD"},
        )
        self.assertEqual({"ID": 41}, issued["DocumentNumbering"])
        self.assertEqual("O", issued["Status"])
        self.assertEqual("2026-07-08", issued["DateDue"])
        self.assertEqual(Decimal("100.00"), sum(Decimal(str(row["Price"])) for row in issued["IssuedInvoiceRows"]))
        self.assertTrue(all(row["Item"] == {"ID": 51} for row in issued["IssuedInvoiceRows"]))
        self.assertTrue(all(row["UnitOfMeasurement"] == "x" for row in issued["IssuedInvoiceRows"]))
        self.assertTrue(all("Value" not in row for row in issued["IssuedInvoiceRows"]))
        self.assertTrue(all("VatAccountingType" not in row for row in issued["IssuedInvoiceRows"]))

        received = client.preflight_row(
            dataset,
            "PR",
            dataset.kpr[0],
            mode="invoice",
            options={"numbering_pr_id": 42, "due_days": 8},
        )
        self.assertEqual({"ID": 42}, received["DocumentNumbering"])
        self.assertEqual(122.0, received["InvoiceAmount"])
        self.assertEqual("O", received["Status"])
        self.assertIn("konto odhodka 4190", received["Notes"])
        self.assertIn("konto dobavitelja 2200", received["Notes"])
        self.assertIn("KPR neto = 100,00", received["Notes"])
        self.assertIn("osnova 22% = 100,00", received["Notes"])
        self.assertIn("DDV 22% = 22,00", received["Notes"])
        self.assertNotIn("ne sprejme odhodkovne", received["Notes"])

    def test_received_invoice_can_get_separate_draft_journal_and_vat(self) -> None:
        client = self.client()
        dataset = self.dataset()
        calls: list[tuple[str, dict]] = []

        def fake_post(path: str, payload: dict) -> minimax_api.ApiResponse:
            calls.append((path, payload))
            if path.endswith("/receivedinvoices"):
                return minimax_api.ApiResponse(201, "/api/orgs/1/receivedinvoices/701", {})
            if path.endswith("/journals"):
                return minimax_api.ApiResponse(201, "/api/orgs/1/journals/801", {})
            return minimax_api.ApiResponse(201, "", {})

        client.post = fake_post  # type: ignore[method-assign]
        client.get = lambda _path: {"JournalId": 801, "VatEntries": [{"VatEntryId": 1}]}  # type: ignore[method-assign]
        response = client.send_row(
            dataset,
            "PR",
            dataset.kpr[0],
            mode="invoice",
            options={
                "numbering_pr_id": 42,
                "due_days": 8,
                "vat_type_pr": "",
                "pr_companion_journal": True,
            },
        )

        self.assertEqual(701, response.body["ReceivedInvoiceId"])
        self.assertEqual(801, response.body["JournalId"])
        self.assertTrue(response.body["CompanionJournalCreated"])
        self.assertEqual("orgs/1/receivedinvoices", calls[0][0])
        self.assertEqual("orgs/1/journals", calls[1][0])
        self.assertEqual("O", calls[1][1]["Status"])
        self.assertNotIn("VatEntries", calls[1][1])
        self.assertIn("PR osnutek ID 701", calls[1][1]["Description"])
        self.assertEqual("orgs/1/journals/801/vat", calls[2][0])
        self.assertIn("NE POTRDI OBEH", calls[2][1]["Notes"])

    def test_journal_vat_is_posted_separately_and_verified(self) -> None:
        client = self.client()
        calls: list[tuple[str, dict]] = []

        def fake_post(path: str, payload: dict) -> minimax_api.ApiResponse:
            calls.append((path, payload))
            if path.endswith("/journals"):
                return minimax_api.ApiResponse(201, "/api/orgs/1/journals/321", {})
            return minimax_api.ApiResponse(201, "", {})

        client.post = fake_post  # type: ignore[method-assign]
        client.get = lambda _path: {"JournalId": 321, "VatEntries": [{"VatEntryId": 1}]}  # type: ignore[method-assign]
        response = client._send_journal_with_vat(
            {
                "JournalType": {"ID": 1},
                "JournalDate": "2026-06-30",
                "Description": "IR-1",
                "Status": "O",
                "JournalEntries": [{"ExternalId": "IR-1"}],
                "VatEntries": [{"VatBook": "IR", "JournalEntryExternalId": "IR-1", "VatEntryRows": []}],
            }
        )
        self.assertEqual(321, response.body["JournalId"])
        self.assertNotIn("VatEntries", calls[0][1])
        self.assertEqual("orgs/1/journals/321/vat", calls[1][0])
        self.assertEqual({"ID": 321}, calls[1][1]["Journal"])


class DdvoVirmanPaymentTests(unittest.TestCase):
    def test_payment_reduces_obligation_by_negative_saldo(self) -> None:
        calc = core.ddvo_virman_payment("1000", "-50,00")
        self.assertEqual(Decimal("1000.00"), calc["obligation"])
        self.assertEqual(Decimal("-50.00"), calc["konto62_credit"])
        self.assertEqual(Decimal("950.00"), calc["payment"])

    def test_positive_konto62_increases_payment(self) -> None:
        calc = core.ddvo_virman_payment(Decimal("1000"), Decimal("55.03"))
        self.assertEqual(Decimal("55.03"), calc["konto62_credit"])
        self.assertEqual(Decimal("1055.03"), calc["payment"])

    def test_credit_larger_than_obligation_floors_at_zero(self) -> None:
        calc = core.ddvo_virman_payment("40", "-55,03")
        self.assertEqual(Decimal("0.00"), calc["payment"])

    def test_parse_konto62_from_ekartica_text(self) -> None:
        text = (
            "62 Davek na dodano vrednost … DDV-O, VAT-RE, NKS, DKO "
            "7.179,00 7.234,03 -55,03 -55,03"
        )
        self.assertEqual(Decimal("-55.03"), core.parse_edavki_konto62_from_text(text))

    def test_parse_konto62_zero_saldo_not_breme(self) -> None:
        """Breme/Dobro sta lahko velika; pomemben je Saldo (lahko 0,00)."""
        text = (
            "62 Davek na dodano vrednost … DDV-O, VAT-RE, NKS, DKO "
            "-2.221,22 -2.221,22 0,00 0,00"
        )
        self.assertEqual(Decimal("0.00"), core.parse_edavki_konto62_from_text(text))

    def test_parse_konto62_from_diagnostic_json(self) -> None:
        payload = {
            "optional_capture": {
                "tables": [
                    {
                        "rows": [
                            ["Konto", "Naziv", "Breme", "Dobro", "Skupaj saldo", "Saldo"],
                            ["62", "DDV", "7.179,00", "7.234,03", "-55,03", "-55,03"],
                        ]
                    }
                ]
            }
        }
        self.assertEqual(
            Decimal("-55.03"),
            core.parse_edavki_konto62_from_text(json.dumps(payload)),
        )

    def test_projest_style_negative_saldo(self) -> None:
        text = (
            "62 | Davek na dodano vrednost … DDV-O, VAT-RE, NKS, DKO | "
            "51.039,18 | 52.300,79 | -1.261,61 | -1.261,61 |"
        )
        self.assertEqual(Decimal("-1261.61"), core.parse_edavki_konto62_from_text(text))
        calc = core.ddvo_virman_payment("5000", "-1.261,61")
        self.assertEqual(Decimal("3738.39"), calc["payment"])

    def test_ekartica_skupaj_footer_without_naziv_column(self) -> None:
        """Skupaj = Saldo na dan (−1.261,61); NUSZ 97 ima danes 0 → ni v analitiki."""
        payload = {
            "optional_capture": {
                "tables": [
                    {
                        "rows": [
                            [
                                "Konto",
                                "Naziv konta",
                                "Breme",
                                "Dobro",
                                "Skupaj saldo",
                                "Saldo 26.7.2026",
                                "Prikaži knjižbe",
                            ],
                            [
                                "62",
                                "Davek na dodano vrednost … DDV-O, VAT-RE, NKS, DKO",
                                "51.039,18",
                                "52.300,79",
                                "-1.261,61",
                                "-1.261,61",
                                "",
                            ],
                            [
                                "97",
                                "Nadomestilo za uporabo stavbnega zemljišča",
                                "2.120,22",
                                "1.060,08",
                                "1.060,14",
                                "0,00",
                                "",
                            ],
                            [
                                "Skupaj",
                                "93.543,62",
                                "93.745,09",
                                "-201,47",
                                "-1.261,61",
                                "",
                            ],
                        ]
                    }
                ]
            }
        }
        summary = core.parse_edavki_ekartica_summary_from_text(json.dumps(payload))
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(Decimal("-1261.61"), summary["konto62"])
        # Na dan (zadnji stolpec), ne letni Skupaj (−201,47 z NUSZ)
        self.assertEqual(Decimal("-1261.61"), summary["skupaj"])
        konti = {a["konto"] for a in summary["accounts"]}
        self.assertIn("62", konti)
        self.assertNotIn("97", konti)


class DdvoFursVirmanXmlTests(unittest.TestCase):
    def test_furs_reference_and_pain001_contains_payment_data(self) -> None:
        import kirkpr_ddvo_virman as virman

        self.assertEqual("SI19 49142275-62006", virman.furs_ddv_reference("49142275"))
        self.assertEqual("SI1949142275-62006", virman.furs_ddv_reference_sepa("49142275"))
        xml = virman.build_furs_ddv_pain001_xml(
            payer_name="KLUG d.o.o.",
            payer_iban="SI56290000055775633",
            payer_tax_id="49142275",
            amount=Decimal("3090.97"),
            payer_street="Trtnikova ulica 008",
            payer_city="1260 Ljubljana Polje",
            remittance="",
            execution_date=__import__("datetime").date(2026, 7, 31),
            period_from="2026-04-01",
            period_to="2026-06-30",
        )
        self.assertIn("SI56011008881000030", xml)
        self.assertIn("SI1949142275-62006", xml)
        self.assertNotIn("SI19 49142275-62006", xml)  # v SEPA Ref brez presledka
        self.assertIn("VATX", xml)
        self.assertIn("PREHODNI DAVČNI PODRAČUN", xml)
        self.assertIn("BACXSI22", xml)
        self.assertIn("Plačilo DDV za: 4-6.2026", xml)
        self.assertIn("<Prtry>SEPA</Prtry>", xml)
        self.assertIn("Gregorčičeva ulica 20", xml)
        self.assertRegex(xml, r"<EndToEndId>SI00\d{7}</EndToEndId>")
        self.assertNotIn("BtchBookg", xml)
        # NLB podračun 02312 — prej brez DbtrAgt → Hal@bank SAXParseException.
        self.assertEqual("LJBASI2X", virman.bic_from_iban("SI56023120017340117"))
        xml_nlb = virman.build_furs_ddv_pain001_xml(
            payer_name="GM ARHITEKTURA d.o.o.",
            payer_iban="SI56023120017340117",
            payer_tax_id="92498825",
            amount=Decimal("17492"),
            payer_street="Na jasi 016",
            payer_city="1241 Kamnik",
            execution_date=__import__("datetime").date(2026, 7, 31),
            period_from="2026-04-01",
            period_to="2026-06-30",
        )
        self.assertIn("<DbtrAgt>", xml_nlb)
        self.assertIn("LJBASI2X", xml_nlb)
        self.assertLess(xml_nlb.index("DbtrAgt"), xml_nlb.index("CdtTrfTxInf"))

    def test_write_virman_package_creates_pdf_and_xml(self) -> None:
        import kirkpr_ddvo_virman as virman

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            source_pdf = out / "source.pdf"
            source_pdf.write_bytes(b"%PDF-1.4 test")
            company = {
                "Dolgo": "KLUG SVETOVANJE D.O.O.",
                "DAVČNA": "49142275",
                "Transakcijski račun": "SI56290000055775633",
                "Email": "test@example.com",
                "NASLOV": "Ljubljana, Trtnikova ulica 8, 1260 Ljubljana - Polje",
                "Zšt": "6",
            }
            package = virman.write_virman_package(
                out,
                company=company,
                period_from="2026-04-01",
                period_to="2026-06-30",
                obligation=Decimal("1000"),
                konto62_credit=Decimal("-50"),
                payment=Decimal("950"),
                source_pdf=source_pdf,
                virman_dir=out / "Virmani",
            )
            self.assertTrue(package.pdf_path.is_file())
            self.assertTrue(package.virman_path.is_file())
            self.assertEqual(out / "Virmani", package.virman_dir)
            self.assertEqual(package.virman_path.parent, package.virman_dir)
            self.assertEqual(package.pdf_path.parent, out)
            self.assertEqual(Decimal("950.00"), package.payment)
            self.assertIn("Virman_DDV", package.virman_path.name)
            self.assertIn("DDV-O", package.pdf_path.name)
            self.assertEqual("test@example.com", package.email_to)

    def test_client_email_payment_lines_format(self) -> None:
        import kirkpr_ddvo_virman as virman

        line1, line2 = virman.format_payment_lines("3146", "-55,03", "3090.97")
        self.assertIn("v dobro na kontu 62: 55,03 EUR", line1)
        self.assertEqual("Znesek za plačilo: 3.090,97 EUR", line2)
        notice = virman.format_konto62_client_notice("-1.261,61")
        self.assertIn("v dobro na kontu 62: 1.261,61 EUR", notice)
        unpaid = virman.format_konto62_client_notice("200,00")
        self.assertIn("še neplačano", unpaid)
        self.assertEqual("", virman.format_konto62_client_notice("0"))

        import kirkpr_ddvo_placeholder_texts as placeholder_texts
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            placeholder_texts.save_texts(
                {
                    "konto62_v_dobro": "Kredit 62: {znesek} €.",
                    "konto62_neplacano": "Dolga 62: {znesek} €.",
                },
                root,
            )
            custom = placeholder_texts.format_konto62_notice_from_texts(
                "-55,03",
                html=False,
                base_dir=root,
            )
            self.assertEqual("Kredit 62: 55,03 €.", custom)

        subject, body = virman.build_ddvo_client_email(
            company_name="KLUG D.O.O.",
            period_from="2026-04-01",
            period_to="2026-06-30",
            obligation=Decimal("3146"),
            konto62_credit=Decimal("-55.03"),
            payment=Decimal("3090.97"),
            reference="SI19 49142275-62006",
        )
        self.assertIn("2026/04–06", subject)
        self.assertIn("v dobro na kontu 62", body)
        self.assertIn(line2, body)
        self.assertIn("Spoštovani/a, (KLUG).", body)
        self.assertIn("Braco MIHELJ", body)

        empty1, pay2 = virman.format_payment_lines("9709", "0", "9709")
        self.assertEqual("", empty1)
        self.assertEqual("Znesek za plačilo: 9.709,00 EUR", pay2)
        _, body0 = virman.build_ddvo_client_email(
            company_name="QUICK",
            period_from="2026-01-01",
            period_to="2026-03-31",
            obligation=Decimal("9709"),
            konto62_credit=Decimal("0"),
            payment=Decimal("9709"),
        )
        self.assertNotIn("kontu 62", body0)
        self.assertNotIn("presežek konta 62", body0)
        self.assertNotIn("preplačilo konta 62", body0)
        self.assertIn("Znesek za plačilo: 9.709,00 EUR", body0)

        manjko1, _ = virman.format_payment_lines("1000", "200,00", "1200")
        self.assertIn("še neplačano", manjko1)

    def test_presezek_email_placeholders(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl
        import kirkpr_ddvo_virman as virman
        from decimal import Decimal

        html_da = virman.format_presezek_obvestilo(Decimal("1500.50"), True)
        self.assertIn("presežek: 1.500,50 EUR", html_da)
        self.assertIn("Zahtevano je vračilo", html_da)
        html_ne = virman.format_presezek_obvestilo("1500,50", False)
        self.assertIn("DDV ostane", html_ne)
        self.assertEqual("", virman.format_presezek_obvestilo(0))

        values = email_tpl.build_placeholder_values(
            company_name="TEST d.o.o.",
            period_label="2026/06",
            obligation="0,00",
            preplacilo="0,00",
            placilo="",
            payment_amount=Decimal("0"),
            excess=Decimal("1500.50"),
            vracilo=True,
        )
        self.assertEqual("1.500,50", values["presezek"])
        self.assertIn("Zahtevano je vračilo", values["presezek_obvestilo"])
        self.assertEqual("", values["placilo_block"])
        self.assertIn("Plačilni nalog ni potreben", values["priloga_obvestilo"])
        self.assertEqual("", values["qr_block"])
        self.assertEqual("", values.get("_qr_png") or "")


class UpnQrTests(unittest.TestCase):
    def test_payload_length_and_png(self) -> None:
        import kirkpr_upn_qr as upn_qr
        from decimal import Decimal

        payload = upn_qr.build_upn_qr_payload(
            amount=Decimal("50.00"),
            payer_name="OLD TOWN 16 d.o.o.",
            payer_address="Testna 1",
            payer_city="1000 Ljubljana",
            recipient_name="PREHODNI DAVČNI PODRAČUN - PRORAČUN DRŽAVE",
            recipient_address="Gregorčičeva ulica 20",
            recipient_city="1000 Ljubljana",
            recipient_iban="SI56011008881000030",
            reference="SI19 34626298-62006",
            purpose_code="VATX",
            purpose="Placilo DDV 2026/06",
            payment_date="31.07.2026",
        )
        text = payload.decode("iso-8859-2")
        self.assertEqual(411, len(text))
        self.assertTrue(payload.startswith(b"UPNQR\n"))
        fields = text.split("\n")
        self.assertEqual("00000005000", fields[8])  # znesek 50,00 EUR
        png = upn_qr.upn_qr_png_bytes(
            amount=Decimal("3236.39"),
            payer_name="PROJEST d.o.o.",
            payer_address="Naslov 1",
            payer_city="1000 Ljubljana",
            recipient_name="PREHODNI DAVČNI PODRAČUN",
            recipient_address="Gregorčičeva ulica 20",
            recipient_city="1000 Ljubljana",
            recipient_iban="SI56011008881000030",
            reference="SI1914446669-62006",
            purpose_code="VATX",
            purpose="Placilo DDV 2026/06",
            payment_date="31.07.2026",
        )
        self.assertTrue(png.startswith(b"\x89PNG"))
        # Payload mora vsebovati pravilen znesek (3.236,39).
        pay = upn_qr.build_upn_qr_payload(
            amount=Decimal("3236.39"),
            recipient_name="PREHODNI DAVČNI PODRAČUN",
            recipient_iban="SI56011008881000030",
            reference="SI1914446669-62006",
        )
        self.assertEqual("00000323639", pay.decode("iso-8859-2").split("\n")[8])

    def test_clean_responsible_person_first_only(self) -> None:
        import kirkpr_company_registry as company_registry
        import kirkpr_ddvo_email_templates as email_tpl

        raw = (
            "Nevenka Plešec (direktor, samostojno); "
            "Miha Plešec (prokurist, samostojno); "
            "Dejan Plešec (prokurist, samostojno)"
        )
        self.assertEqual(
            company_registry.clean_responsible_person_name(raw),
            "Nevenka Plešec",
        )
        mangled = "Nevenka Plešec, ; Miha Plešec (prokurist, ; Dejan Plešec (prokurist,"
        self.assertEqual(
            company_registry.clean_responsible_person_name(mangled),
            "Nevenka Plešec",
        )
        values = email_tpl.build_placeholder_values(
            company_name="INTEGRA COLOURS, d.o.o., Ljubljana",
            period_label="2026/04–06",
            obligation="1,00",
            preplacilo="0,00",
            placilo="1,00",
            odgovorna_oseba=raw,
        )
        self.assertEqual(values["odgovorna_oseba"], "Nevenka Plešec")

    def test_placeholder_qr_block(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl
        from decimal import Decimal

        values = email_tpl.build_placeholder_values(
            company_name="OLD TOWN 16 d.o.o.",
            period_label="2026/06",
            obligation="50,00",
            preplacilo="0,00",
            placilo="50,00",
            reference="SI19 34626298-62006",
            iban="SI56011008881000030",
            datum="31.07.2026",
            payment_amount=Decimal("50.00"),
            payer_name="OLD TOWN 16 d.o.o.",
        )
        self.assertEqual("[QR koda za plačilo]", values.get("qr_block"))
        self.assertTrue(Path(values.get("_qr_png") or "").is_file())
        body = email_tpl.ensure_qr_placeholder(
            "<p>Datum izvršitve: {datum}</p>\n{ps_block}\n"
        )
        self.assertIn("{qr_block}", body)
        import kirkpr_upn_qr as upn_qr

        injected = upn_qr.inject_upn_qr_img("[QR koda za plačilo]")
        self.assertIn('src="cid:ddvo_upn_qr"', injected)


class DdvoEmailHtmlSpacingTests(unittest.TestCase):
    def test_normalize_preserves_br_after_paragraph(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        dirty = (
            "<p>Spoštovani.</p><br>\n"
            "<p>DDV</p><br><br>\n"
            "<p>Znesek</p>"
        )
        clean = email_tpl.normalize_email_html(dirty)
        self.assertIn("</p><br>", clean.replace("\n", ""))
        wrapped = email_tpl.wrap_outlook_html(dirty)
        self.assertIn("line-height:135%", wrapped.casefold())
        # WYSIWYG: brez dodatnega margin-bottom na vsak <p> (razmik = prazna vrstica).
        self.assertIn("margin:0", wrapped.casefold())
        body = wrapped.casefold().split("<body")[-1]
        self.assertIn("spoštovani.", body)
        self.assertIn("<p style=", body)

    def test_prepare_outlook_flattens_to_table_br(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        frag = email_tpl.prepare_outlook_fragment(
            "<p>A<br>\n"
            "Referenca: X<br>\n"
            "IBAN: Y</p><br>\n"
            "<p>Lep pozdrav,</p>",
            line_height="1.35",
            para_spacing_px=4,
        )
        low = frag.casefold()
        self.assertIn('<p style="', low)
        self.assertIn("line-height:135%", low)
        self.assertIn("referenca: x", low)
        self.assertIn("iban: y", low)
        # Zaporedne vrstice v enem <p> z <br> (ne vsaka v svojem <p> + spacer).
        self.assertIn("a<br>", low.replace("\n", ""))
        self.assertIn("referenca: x<br>", low.replace("\n", ""))
        self.assertIn("mso-line-height-rule:exactly", low)

    def test_apply_spacing_respects_user_controls(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        out = email_tpl.apply_spacing_to_html(
            "<p>A</p><p></p><p>B</p>",
            line_height="1.5",
            para_spacing_px=8,
        )
        self.assertIn("line-height:150%", out)
        # Prazna vrstica = <br>&nbsp; znotraj odstavka A (ne ločen velik <p>).
        compact = out.replace("\n", "").casefold()
        self.assertIn("a<br>", compact)
        self.assertIn("&nbsp;", compact)
        self.assertIn(">b</p>", compact)

    def test_collapse_empty_paragraphs_merges_spacer(self) -> None:
        import re

        import kirkpr_ddvo_email_templates as email_tpl

        src = "<p>Spoštovani.</p>\n<p></p>\n<p><strong>DDV</strong></p>\n"
        out = email_tpl.stamp_paragraph_styles(src, line_height="1.0", para_spacing_px=0)
        compact = re.sub(r"\s+", "", out).casefold()
        self.assertIn("spoštovani.<br>", compact)
        self.assertIn("&nbsp;</p>", compact)
        self.assertIn("ddv", compact)

    def test_normalize_preserves_intentional_double_br(self) -> None:
        import re

        import kirkpr_ddvo_email_templates as email_tpl

        dirty = (
            "<p>Lep pozdrav,<br><br>\n"
            "<strong>Braco MIHELJ</strong><br>\n"
            "tel.: 041.653.170<br><br>\n"
            "<strong>eMail:</strong><br>\n"
            "a@b.com</p>"
        )
        clean = email_tpl.normalize_email_html(dirty)
        compact = re.sub(r"\s+", "", clean).casefold()
        self.assertIn("leppozdrav,<br><br>", compact)
        self.assertIn("041.653.170<br><br>", compact)
        self.assertIn("bracomihelj</strong><br>", compact)

    def test_strip_br_after_paragraph_only(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        dirty = "<p>A</p><br><br>\n<p>B<br><br>\nC</p>"
        cleaned = email_tpl.strip_br_after_paragraph(dirty)
        self.assertNotIn("</p><br>", cleaned.replace("\n", ""))
        self.assertIn("<br><br>", cleaned)  # znotraj <p> ostane

    def test_preview_shows_blank_after_p_br(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        # WYSIWYG: </p><br><p> → vrstice z eno prazno med A in B
        lines = email_tpl.html_body_to_lines("<p>A</p><br>\n<p>B</p>")
        self.assertEqual(lines, ["A", "", "B"])

    def test_stamp_preserves_color_and_bold(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        src = (
            '<p>A</p>\n'
            '<p><span style="color:#C62828"><strong>Znesek</strong></span></p>\n'
        )
        out = email_tpl.stamp_paragraph_styles(src, line_height="1.5", para_spacing_px=6)
        self.assertIn('color:#C62828', out)
        self.assertIn("<strong>Znesek</strong>", out)
        self.assertIn("line-height:150%", out)
        self.assertIn("margin:0", out)
        wrapped = email_tpl.wrap_outlook_html(src, reformat=False, line_height="1.5", para_spacing_px=6)
        self.assertIn('color:#C62828', wrapped)
        self.assertIn("<!DOCTYPE html>", wrapped)

    def test_restore_placeholders_keeps_formatting(self) -> None:
        import kirkpr_ddvo_email_templates as email_tpl

        values = {
            "nagovor": "KLUG",
            "placilo": "3.090,97",
            "obdobje": "2026/04–06",
        }
        rendered = (
            '<p>Spoštovani/a, <strong>(KLUG)</strong>.</p>\n'
            '<p><span style="color:#C62828"><strong>Znesek za plačilo: 3.090,97 EUR</strong></span></p>\n'
        )
        restored = email_tpl.restore_placeholders(rendered, values)
        self.assertIn("{nagovor}", restored)
        self.assertIn("{placilo}", restored)
        self.assertIn('color:#C62828', restored)
        self.assertNotIn("KLUG", restored)
        self.assertNotIn("3.090,97", restored)

    def test_rename_copy_delete_template(self) -> None:
        import tempfile
        from pathlib import Path

        import kirkpr_ddvo_email_templates as email_tpl

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tid = email_tpl.add_template(
                title="Moja",
                subject="S {nagovor}",
                body="<p>{nagovor}</p>",
                base_dir=base,
            )
            email_tpl.rename_template(tid, "Moja nova", base_dir=base)
            self.assertEqual("Moja nova", email_tpl.get_template(tid, base_dir=base)["title"])
            cid = email_tpl.copy_template(tid, new_title="Moja kopija", base_dir=base)
            self.assertNotEqual(tid, cid)
            self.assertEqual("Moja kopija", email_tpl.get_template(cid, base_dir=base)["title"])
            email_tpl.delete_template(cid, base_dir=base)
            ids = {r["id"] for r in email_tpl.list_templates(base_dir=base)}
            self.assertNotIn(cid, ids)
            self.assertIn(tid, ids)

    def test_builtin_template_heals_without_placeholders(self) -> None:
        import tempfile
        from pathlib import Path

        import kirkpr_ddvo_email_templates as email_tpl

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / email_tpl.TEMPLATES_NAME
            path.write_text(
                '{"templates":{"ddvo_virman":{"id":"ddvo_virman","title":"x",'
                '"subject":"DDV KLUG","body":"<p>Spoštovani KLUG</p>","builtin":true}}}\n',
                encoding="utf-8",
            )
            tpl = email_tpl.get_template(email_tpl.DEFAULT_TEMPLATE_ID, base_dir=Path(tmp))
            self.assertIn("{nagovor}", tpl["body"])
            self.assertIn("{obdobje}", tpl["subject"])

    def test_parse_deferred_send_si(self) -> None:
        from datetime import datetime

        import kirkpr_ddvo_virman as virman

        self.assertIsNone(virman.parse_deferred_send_si(""))
        dt = virman.parse_deferred_send_si("31.07.2026 09:15")
        self.assertEqual(datetime(2026, 7, 31, 9, 15), dt)
        dt2 = virman.parse_deferred_send_si("31.07.2026")
        self.assertEqual(datetime(2026, 7, 31, 8, 0), dt2)
        with self.assertRaises(ValueError):
            virman.parse_deferred_send_si("2026-07-31")


class RecentSessionsTests(unittest.TestCase):
    def test_period_from_source_path_quarter(self) -> None:
        import convert_KIrKpr_to_minimax as app

        path = Path(
            r"D:\Trops\41\DDV\KIRKPR_Minimax\2026-04-01_2026-06-30\Delovne_kopije\x.json"
        )
        span = app.period_from_source_path(path)
        self.assertEqual((date(2026, 4, 1), date(2026, 6, 30)), span)

    def test_last_month_of_span_detects_wrong_june_session(self) -> None:
        import convert_KIrKpr_to_minimax as app

        span_from, span_to = date(2026, 4, 1), date(2026, 6, 30)
        self.assertTrue(
            app.is_last_month_of_span(date(2026, 6, 1), date(2026, 6, 30), span_from, span_to)
        )
        self.assertFalse(
            app.is_last_month_of_span(date(2026, 4, 1), date(2026, 6, 30), span_from, span_to)
        )
        self.assertFalse(
            app.is_last_month_of_span(date(2026, 5, 1), date(2026, 5, 31), span_from, span_to)
        )

    def test_remember_recent_session_keeps_multiple_companies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.zip"
            b = root / "b.zip"
            a.write_text("x", encoding="utf-8")
            b.write_text("y", encoding="utf-8")
            cfg: dict = {"recent_sessions": []}
            core.remember_recent_session(
                cfg,
                company_key="zst-41",
                company_label="41 KLUG",
                source=a,
                period_from="2026-04-01",
                period_to="2026-06-30",
            )
            core.remember_recent_session(
                cfg,
                company_key="zst-1",
                company_label="01 DRUGA",
                source=b,
                period_from="2026-01-01",
                period_to="2026-03-31",
            )
            self.assertEqual(2, len(cfg["recent_sessions"]))
            self.assertEqual("zst-1", cfg["recent_sessions"][0]["company_key"])
            self.assertIn("01 DRUGA", cfg["recent_sessions"][0]["label"])
            # Ponovno odprtje iste firme/vira gre na vrh, brez podvajanja.
            core.remember_recent_session(
                cfg,
                company_key="zst-41",
                company_label="41 KLUG",
                source=a,
                period_from="2026-04-01",
                period_to="2026-06-30",
            )
            self.assertEqual(2, len(cfg["recent_sessions"]))
            self.assertEqual("zst-41", cfg["recent_sessions"][0]["company_key"])
            self.assertEqual(a, core.recent_session_open_path(cfg["recent_sessions"][0]))

    def test_sqlite_sessions_crud(self) -> None:
        import kirkpr_sessions_db as sessions_db

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = sessions_db.SessionsDb(root / "test_sessions.sqlite3")
            a = root / "a.zip"
            a.write_text("x", encoding="utf-8")
            row = db.upsert(
                company_key="zst-41",
                company_label="41 KLUG",
                source=a,
                period_from="2026-04-01",
                period_to="2026-06-30",
                title="KLUG Q2",
            )
            self.assertTrue(row["id"])
            self.assertEqual("KLUG Q2", row["label"])
            listed = db.list_sessions()
            self.assertEqual(1, len(listed))
            updated = db.update_meta(int(row["id"]), title="KLUG Q2b", notes="test")
            self.assertEqual("KLUG Q2b", updated["title"])
            self.assertTrue(db.delete(int(row["id"])))
            self.assertEqual(0, len(db.list_sessions()))


class PartyDsTests(unittest.TestCase):
    def test_us_placeholder_from_address(self) -> None:
        cc, ds = core.ensure_party_ds("", "", "Anthropic, PBC, San Francisco, California")
        self.assertEqual("US", cc)
        self.assertEqual("US***", ds)

    def test_partner_code_is_not_vat(self) -> None:
        cc, ds = core.ensure_party_ds("SI", "6KKD1TCL0001", "Anthropic San Francisco California")
        self.assertEqual("US", cc)
        self.assertEqual("US***", ds)

    def test_ie_vat_kept(self) -> None:
        cc, ds = core.ensure_party_ds("", "IE6364992H", "Adobe Dublin")
        self.assertEqual("IE", cc)
        self.assertEqual("IE6364992H", ds)

    def test_si_digits(self) -> None:
        cc, ds = core.ensure_party_ds("SI", "14720078", "ITX d.o.o.")
        self.assertEqual("SI", cc)
        self.assertEqual("SI14720078", ds)

    def test_p7ds_precheck_reports_us_placeholder(self) -> None:
        issue = core.p7ds_precheck("", "", "Anthropic, PBC, San Francisco, California")
        self.assertIsNotNone(issue)
        self.assertEqual("KPR_P7DS", issue["code"])
        self.assertEqual("critical", issue["severity"])
        self.assertEqual("US***", issue["suggested"])
        self.assertIn("P7DS", issue["message"])

    def test_p7ds_precheck_partner_code_is_not_vat(self) -> None:
        issue = core.p7ds_precheck("SI", "6KKD1TCL0001", "Anthropic San Francisco")
        self.assertIsNotNone(issue)
        self.assertEqual("US***", issue["suggested"])

    def test_p7ds_precheck_real_vat_ok(self) -> None:
        self.assertIsNone(core.p7ds_precheck("", "IE6364992H", "Adobe Dublin"))
        self.assertIsNone(core.p7ds_precheck("SI", "14720078", "ITX d.o.o."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
