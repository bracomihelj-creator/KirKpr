from pathlib import Path
import tempfile

import kirkpr_ddvo_pdf as pdf
import kirkpr_ddvo_xml as xml
import kirkpr_minimax_core as core

ds = core.KirkprDataset(
    header={
        "TaxPayerID": "49142275",
        "OBDOBJE_OD": "2026-01-01",
        "OBDOBJE_DO": "2026-03-31",
        "ODBDELEZ": False,
        "VRACILO": False,
    },
    kir=[{"P7": "25005", "P14": "5501"}],
    kpr=[{"P8": "11574", "P18": "2488", "P19": "4", "P20": "6", "__ddv_se_odbija__": True}],
    source_path=Path("t"),
    source_format="t",
)
kwargs = dict(
    company_name="KLUG SVETOVANJE D.O.O.",
    address="Ljubljana, Trtnikova ulica 8, 1260 Ljubljana - Polje",
    contact_name="Braco Mihelj",
    contact_phone="041653170",
)
raw = xml.build_ddvo_xml_bytes(ds, **kwargs).decode("utf-8")
assert "DDV_O_11.7-display-sl.xslt" in raw
assert "xml-stylesheet" in raw

out = Path(tempfile.gettempdir()) / "DDV O 2026 Q1 edavki.pdf"
pdf.build_ddvo_pdf(ds, out, also_write_html=True, **kwargs)
assert out.is_file() and out.stat().st_size > 10000
html = out.with_suffix(".html").read_text(encoding="utf-8")
assert "tablesignbullet" in html
assert "Obrazec DDV-O" in html
assert "25.005" in html
assert "b8ccce" in html or "#b8ccce" in html

import fitz

doc = fitz.open(out)
text = doc[0].get_text()
assert doc.page_count == 1
assert "Obrazec DDV-O" in text
assert "25.005" in text
assert "e-DDV_O_11.7" in text or "DDV_O_11.7" in text
print("OK", out, out.stat().st_size, "pages", doc.page_count)
