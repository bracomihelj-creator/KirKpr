"""Preveri XML/PDF izvoz proti referenčnim vrednostim KLUG Q1/2026."""
from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET

import kirkpr_ddvo_pdf as ddvo_pdf
import kirkpr_ddvo_xml as ddvo_xml
import kirkpr_minimax_core as core

ds = core.KirkprDataset(
    header={
        "TaxPayerID": "49142275",
        "OBDOBJE_OD": "2026-01-01",
        "OBDOBJE_DO": "2026-03-31",
        "ODBDELEZ": False,
        "VRACILO": False,
    },
    kir=[
        {
            "P7": "25005",
            "P14": "5501",
        }
    ],
    kpr=[
        {
            "P8": "11574",
            "P18": "2488",
            "P19": "4",
            "P20": "6",
            "__ddv_se_odbija__": True,
        }
    ],
    source_path=Path("test"),
    source_format="test",
)

summary = core.ddvo_summary(ds)
assert summary["obligation"] == Decimal("3003"), summary

xml_path = Path(tempfile.gettempdir()) / ddvo_xml.default_ddvo_xml_name(ds)
pdf_path = Path(tempfile.gettempdir()) / ddvo_xml.default_ddvo_pdf_name(ds)
assert xml_path.name == "DDV_O_2026-Q1.xml"
assert pdf_path.name == "DDV O 2026 Q1.pdf"

kwargs = dict(
    company_name="KLUG SVETOVANJE D.O.O.",
    address="Ljubljana, Trtnikova ulica 8, 1260 Ljubljana - Polje",
    contact_name="Braco Mihelj",
    contact_phone="041653170",
)
ddvo_xml.write_ddvo_xml(ds, xml_path, **kwargs)
print("xml", xml_path, xml_path.stat().st_size)

root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
vals = {
    el.tag.split("}")[-1]: el.text
    for el in root.iter()
    if el.tag.split("}")[-1].startswith("f")
    or el.tag.split("}")[-1] in {"taxPeriodStart", "contactPersonFullName", "name", "address1"}
}
assert vals["f11"] == "25005"
assert vals["f21"] == "5501"
assert vals["f31"] == "11574"
assert vals["f41"] == "2488"
assert vals["f42"] == "4"
assert vals["f42a"] == "6"
assert vals["f51"] == "3003"
assert vals["contactPersonFullName"] == "Braco Mihelj"
assert vals["name"] == "KLUG SVETOVANJE D.O.O."
assert "TRTNIKOVA" in (vals.get("address1") or "")

ddvo_pdf.build_ddvo_pdf(ds, pdf_path, **kwargs)
print("pdf", pdf_path, pdf_path.stat().st_size)

import fitz

doc = fitz.open(pdf_path)
text = doc[0].get_text()
print("pages", doc.page_count)
assert doc.page_count == 1
assert "25.005" in text
assert "Obrazec DDV-O" in text
assert "5.501" in text
assert "3.003" in text or "3003" in text
print("OK roundtrip")
