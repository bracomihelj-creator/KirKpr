"""Poti in imena za izvoz virmanov (plačilnih nalogov) v TROPS strukturo."""
from __future__ import annotations

import json
import re
from pathlib import Path

_DEFAULT_TROPS_ROOT = Path(r"D:\TROPS")
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def _zst_folder_name(zst: int) -> str:
    """Ime mape TROPS: 01, 02, … (min. 2 cifri)."""
    return str(int(zst)).zfill(2)


def trops_root() -> Path:
    """Koren TROPS (iz EvidencaFirm config ali privzeto D:\\TROPS)."""
    try:
        from db.connection import load_config

        cfg = load_config()
        ev_path = str((cfg.get("minimax") or {}).get("evidenca_config") or "").strip()
        if ev_path:
            data = json.loads(Path(ev_path).read_text(encoding="utf-8"))
            root = str((data.get("trops") or {}).get("root") or "").strip()
            if root:
                return Path(root)
    except Exception:
        pass
    return _DEFAULT_TROPS_ROOT


def trops_dir_for_zst(popa_id: int | str) -> Path:
    """D:\\TROPS\\03 ali obstoječa mapa (03 / 3)."""
    try:
        zst = int(popa_id)
    except (TypeError, ValueError):
        zst = 0
    if zst < 1:
        return trops_root() / "00"
    root = trops_root()
    padded = _zst_folder_name(zst)
    for name in (padded, str(zst)):
        path = root / name
        if path.is_dir():
            return path
    return root / padded


def virman_dir_for_zst(popa_id: int | str) -> Path:
    """D:\\TROPS\\{ZŠT}\\virmani — ustvari, če ne obstaja."""
    path = trops_dir_for_zst(popa_id) / "virmani"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clients_with_virman_history() -> set[int]:
    """Stranke, ki že imajo vsaj eno datoteko v TROPS/{ZŠT}/virmani/."""
    try:
        from db.repo import list_clients  # opcijsko (Fakturiranje) — pri KIR/KPR ni
    except Exception:
        return set()
    out: set[int] = set()
    for client in list_clients(active_only=False):
        try:
            zst = int(client.popa_id or 0)
        except (TypeError, ValueError):
            continue
        if zst < 1:
            continue
        vdir = trops_dir_for_zst(zst) / "virmani"
        if not vdir.is_dir():
            continue
        try:
            if any(vdir.iterdir()):
                out.add(int(client.client_id))
        except OSError:
            continue
    return out


def _sanitize_filename_part(text: str, *, max_len: int = 80) -> str:
    raw = _INVALID_CHARS.sub("", str(text or "")).strip()
    raw = re.sub(r"\s+", " ", raw)
    return raw[:max_len] if raw else "?"


def virman_export_path(
    popa_id: int | str,
    firm_name: str,
    supplier_name: str,
    invoice_ref: str,
    *,
    suffix: str = ".xml",
) -> Path:
    """
    Celotna pot izvoza: D:\\TROPS\\{ZŠT}\\virmani\\<Firma> - <Dobavitelj> - <št>.xml
  """
    firm = _sanitize_filename_part(firm_name)
    supplier = _sanitize_filename_part(supplier_name or "QuickMB")
    inv = _sanitize_filename_part(invoice_ref or "racun")
    name = f"{firm} - {supplier} - {inv}{suffix}"
    return virman_dir_for_zst(popa_id) / name
