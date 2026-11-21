"""UPN QR (ZBS) za plačilo DDV virmana — PNG + HTML za Outlook (cid:)."""

from __future__ import annotations

import io
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

UPNQR_TOTAL_LEN = 411
UPNQR_VERSION = 15
UPN_QR_CID = "ddvo_upn_qr"
# Marker v predogledu / belem polju (img se vstavi šele v Outlook).
UPN_QR_MARKER = "[QR koda za plačilo]"


def _clip(value: str, max_len: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:max_len]


def _amount_cents(amount: Decimal | Any) -> str:
    cents = int((Decimal(str(amount)) * 100).to_integral_value())
    if cents < 0:
        cents = 0
    if cents > 99_999_999_999:
        raise ValueError(f"Znesek izven območja UPN QR: {amount}")
    return f"{cents:011d}"


def build_upn_qr_payload(
    *,
    amount: Decimal | Any,
    payer_name: str = "",
    payer_address: str = "",
    payer_city: str = "",
    recipient_name: str,
    recipient_address: str = "",
    recipient_city: str = "",
    recipient_iban: str,
    reference: str,
    purpose_code: str = "VATX",
    purpose: str = "Placilo DDV",
    payment_date: str = "",
) -> bytes:
    """Polja 1–19 + kontrolna vsota + rezerva do 411 znakov (ISO-8859-2)."""
    iban = re.sub(r"\s+", "", str(recipient_iban or "")).upper()
    ref = re.sub(r"\s+", "", str(reference or "")).upper() or "SI99"
    placilo = _clip(payment_date, 10)
    fields = [
        "UPNQR",
        "",
        "",
        "",
        "",
        _clip(payer_name, 33),
        _clip(payer_address, 33),
        _clip(payer_city, 33),
        _clip(_amount_cents(amount), 11),
        placilo,
        "",
        _clip(str(purpose_code or "VATX").upper(), 4),
        _clip(purpose or "Placilo DDV", 42),
        "",
        _clip(iban, 34),
        _clip(ref, 26),
        _clip(recipient_name, 33),
        _clip(recipient_address, 33),
        _clip(recipient_city, 33),
    ]
    if len(fields) != 19:
        raise ValueError(f"UPN QR: pričakovanih 19 polj, dobili {len(fields)}")
    checksum = sum(len(f) for f in fields) + 19
    body = "\n".join(fields) + "\n" + f"{checksum:03d}" + "\n"
    reserve = UPNQR_TOTAL_LEN - len(body)
    if reserve < 0:
        raise ValueError(f"UPN QR predolg ({len(body)} znakov, max {UPNQR_TOTAL_LEN}).")
    payload = body + (" " * reserve)
    if len(payload) != UPNQR_TOTAL_LEN:
        raise ValueError(f"Neveljavna dolžina UPN QR: {len(payload)}")
    # ZBS zahteva ISO-8859-2; neznane znake zamenjaj z '?' (ne mešaj UTF-8).
    return payload.encode("iso-8859-2", errors="replace")


def upn_qr_png_bytes(
    *,
    amount: Decimal | Any,
    payer_name: str = "",
    payer_address: str = "",
    payer_city: str = "",
    recipient_name: str,
    recipient_address: str = "",
    recipient_city: str = "",
    recipient_iban: str,
    reference: str,
    purpose_code: str = "VATX",
    purpose: str = "Placilo DDV",
    payment_date: str = "",
    box_size: int = 4,
    border: int = 3,
) -> bytes:
    """PNG bajti UPN QR po ZBS: verzija 15, ECC M, ISO-8859-2 + ECI 000004.

    Pomembno: en sam BYTE tok (brez optimize-chunkov) — sicer banke
    pogosto ne preberejo zneska.
    """
    payload = build_upn_qr_payload(
        amount=amount,
        payer_name=payer_name,
        payer_address=payer_address,
        payer_city=payer_city,
        recipient_name=recipient_name,
        recipient_address=recipient_address,
        recipient_city=recipient_city,
        recipient_iban=recipient_iban,
        reference=reference,
        purpose_code=purpose_code,
        purpose=purpose,
        payment_date=payment_date,
    )
    text = payload.decode("iso-8859-2")
    scale = max(2, int(box_size))
    quiet = max(3, int(border))  # ZBS: min. 3 moduli belega roba

    try:
        import segno

        qr = segno.make(
            text,
            error="m",
            version=UPNQR_VERSION,
            encoding="iso-8859-2",
            eci=True,
            boost_error=False,
        )
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=scale, border=quiet)
        return buf.getvalue()
    except Exception:
        pass

    # Fallback: qrcode — obvezno optimize=0 + čisti BYTE način.
    import qrcode
    from qrcode.util import MODE_8BIT_BYTE, QRData

    qr = qrcode.QRCode(
        version=UPNQR_VERSION,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=scale,
        border=quiet,
    )
    qr.data_list.append(QRData(payload, mode=MODE_8BIT_BYTE, check_data=False))
    qr.make(fit=False)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def write_upn_qr_png(
    path: Path | str,
    **kwargs: Any,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(upn_qr_png_bytes(**kwargs))
    return target


def write_temp_upn_qr_png(**kwargs: Any) -> Path:
    fd, name = tempfile.mkstemp(prefix="ddvo_upn_qr_", suffix=".png")
    Path(name).write_bytes(upn_qr_png_bytes(**kwargs))
    try:
        import os

        os.close(fd)
    except OSError:
        pass
    return Path(name)


def upn_qr_cache_dir() -> Path:
    """Trajna mapa za UPN QR PNG (temp se lahko zbriše pred Outlook/SMTP)."""
    base = Path(__file__).resolve().parent / "upn_qr_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_cache_upn_qr_png(*, cache_key: str = "", **kwargs: Any) -> Path:
    """Zapiši UPN QR v upn_qr_cache (stabilno ime = prepiše prejšnji za isto obdobje)."""
    import re

    key = re.sub(r"[^\w\-]+", "_", str(cache_key or "qr").strip())[:72] or "qr"
    target = upn_qr_cache_dir() / f"UPN_QR_{key}.png"
    return write_upn_qr_png(target, **kwargs)


def qr_img_html(*, cid: str = UPN_QR_CID, size: int = 180) -> str:
    return (
        f'<p><img src="cid:{cid}" width="{int(size)}" height="{int(size)}" '
        f'alt="UPN QR za plačilo" style="display:block;border:0;outline:none;"></p>'
    )


def inject_upn_qr_img(body: str, *, cid: str = UPN_QR_CID, size: int = 180) -> str:
    """Zamenjaj marker / {qr_block} z <img src=\"cid:…\">."""
    text = str(body or "")
    img = qr_img_html(cid=cid, size=size)
    if UPN_QR_MARKER in text:
        return text.replace(UPN_QR_MARKER, img, 1)
    if "{qr_block}" in text:
        return text.replace("{qr_block}", img, 1)
    return text


def ensure_qr_placeholder(body: str) -> str:
    """Vstavi {qr_block} v predlogo, če še ni (za obstoječe shranjene vzorce)."""
    text = str(body or "")
    if "{qr_block}" in text or "{qr}" in text:
        return text
    needle = "Datum izvršitve: {datum}</p>"
    if needle in text:
        return text.replace(needle, needle + "\n{qr_block}\n", 1)
    if "{ps_block}" in text:
        return text.replace("{ps_block}", "{qr_block}\n{ps_block}", 1)
    low = text.casefold()
    for marker in ("<p>lep pozdrav", "lep pozdrav,"):
        idx = low.find(marker)
        if idx >= 0:
            return text[:idx] + "{qr_block}\n" + text[idx:]
    if text.strip():
        return text.rstrip() + "\n{qr_block}\n"
    return "{qr_block}\n"


__all__ = [
    "UPNQR_TOTAL_LEN",
    "UPNQR_VERSION",
    "UPN_QR_CID",
    "UPN_QR_MARKER",
    "build_upn_qr_payload",
    "ensure_qr_placeholder",
    "inject_upn_qr_img",
    "qr_img_html",
    "upn_qr_cache_dir",
    "upn_qr_png_bytes",
    "write_cache_upn_qr_png",
    "write_temp_upn_qr_png",
    "write_upn_qr_png",
]
