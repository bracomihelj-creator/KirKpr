"""Urejljiva besedila za e-poštne {placeholders} (konto 62 ipd.)."""

from __future__ import annotations

import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Mapping

import kirkpr_minimax_core as core

TEXTS_NAME = "ddvo_placeholder_texts.json"

# Vzorci z {znesek} — uporabnik jih ureja v formi.
DEFAULT_TEXTS: dict[str, str] = {
    "konto62_v_dobro": (
        "Na eDavkih imate v dobro na kontu 62: {znesek} EUR. "
        "Ta znesek smo upoštevali pri plačilnem nalogu."
    ),
    "konto62_neplacano": (
        "Na eDavkih je na kontu 62 še neplačano (ni pokrito): {znesek} EUR. "
        "Ta znesek smo prišteli k plačilnemu nalogu."
    ),
}

PLACEHOLDER_HELP: tuple[tuple[str, str], ...] = (
    ("{nagovor}", "Kratko ime firme (prva beseda)"),
    ("{firma}", "Polno ime podjetja"),
    ("{odgovorna_oseba}", "Ena odg. oseba iz evidence"),
    ("{obdobje}", "Obdobje DDV (npr. 2026/04-06)"),
    ("{obveznost}", "Polje 51 — obveznost DDV-O"),
    ("{presezek}", "Polje 52 — presežek DDV (znesek)"),
    ("{presezek_obvestilo}", "Samodejno: presežek + vračilo DA/NE"),
    ("{preplacilo}", "Stanje konta 62 (s predznakom)"),
    ("{konto62_obvestilo}", "Samodejno: v dobro / še neplačano (spodaj)"),
    ("{placilo}", "Znesek za plačilo (51 + stanje 62)"),
    ("{placilo_block}", "HTML vrstica zneska za plačilo (prazno pri presežku)"),
    ("{priloga_obvestilo}", "Besedilo o PDF/virman priponkah"),
    ("{referenca}", "FURS referenca SI19…"),
    ("{iban}", "IBAN FURS"),
    ("{datum}", "Datum izvršitve"),
    ("{qr_block}", "UPN QR koda"),
    ("{ps_block}", "P.S. blok"),
    ("{znesek}", "Samo v vzorcih konta 62 — absolutni znesek"),
)

_BG = "#0b1220"
_PANEL = "#152238"
_EDIT_BG = "#FFF8E1"
_EDIT_FG = "#1a1400"
_PREVIEW_BG = "#E8F5E9"
_PREVIEW_FG = "#1B5E20"
_HELP_BG = "#ECEFF1"
_HELP_FG = "#263238"


def texts_path(base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else Path(core.config_path()).parent
    return root / TEXTS_NAME


def default_texts() -> dict[str, str]:
    return dict(DEFAULT_TEXTS)


def load_texts(base_dir: Path | None = None) -> dict[str, str]:
    path = texts_path(base_dir)
    data = default_texts()
    if not path.is_file():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return data
    if not isinstance(raw, Mapping):
        return data
    for key in DEFAULT_TEXTS:
        value = str(raw.get(key) or "").strip()
        if value:
            data[key] = value
    return data


def save_texts(texts: Mapping[str, str], base_dir: Path | None = None) -> Path:
    path = texts_path(base_dir)
    payload = default_texts()
    for key in DEFAULT_TEXTS:
        value = str(texts.get(key) or "").strip()
        if value:
            payload[key] = value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _si_money(amount: Any) -> str:
    value = abs(core.decimal_value(amount))
    text = f"{value:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def render_template(template: str, *, znesek: str) -> str:
    text = str(template or "")
    return text.replace("{znesek}", znesek)


def collect_editor_texts(editors: Mapping[str, tk.Text]) -> dict[str, str]:
    return {
        key: editors[key].get("1.0", "end-1c").strip() or DEFAULT_TEXTS[key]
        for key in DEFAULT_TEXTS
    }


def format_konto62_notice_from_texts(
    konto62: Any,
    *,
    html: bool = False,
    texts: Mapping[str, str] | None = None,
    base_dir: Path | None = None,
) -> str:
    """Sestavi {konto62_obvestilo} iz uporabniških vzorcev."""
    saldo = core.edavki_konto62_saldo(konto62)
    if saldo == 0:
        return ""
    cfg = dict(texts) if texts is not None else load_texts(base_dir)
    znesek = _si_money(saldo)
    if saldo < 0:
        body = render_template(cfg.get("konto62_v_dobro") or DEFAULT_TEXTS["konto62_v_dobro"], znesek=znesek)
        color = "#1565C0"
    else:
        body = render_template(
            cfg.get("konto62_neplacano") or DEFAULT_TEXTS["konto62_neplacano"],
            znesek=znesek,
        )
        color = "#C62828"
    body = re.sub(r"\s+", " ", body).strip()
    if not body:
        return ""
    if html:
        esc = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return f'<p><strong><span style="color:{color}">{esc}</span></strong></p>'
    return body


def open_placeholder_texts_form(
    parent: tk.Misc,
    *,
    base_dir: Path | None = None,
    on_change: Callable[[dict[str, str]], None] | None = None,
) -> dict[str, str] | None:
    """Forma: urejanje vzorcev za {konto62_obvestilo}. Vrne shranjene tekste ali None.

    on_change — ob tipkanju (živ predogled v starševskem urejevalniku).
    """
    result: dict[str, str] | None = None
    current = load_texts(base_dir)

    win = tk.Toplevel(parent)
    win.title("Besedila e-pošte — postavke {…}")
    win.transient(parent)
    win.grab_set()
    win.minsize(700, 580)
    try:
        win.configure(bg=_BG)
    except tk.TclError:
        pass

    outer = tk.Frame(win, bg=_BG, padx=14, pady=14)
    outer.pack(fill="both", expand=True)

    tk.Label(
        outer,
        text="V predlogi e-pošte vstaviš {konto62_obvestilo}. "
        "Tu urejaš, kaj se zapiše, ko je stanje 62 ≠ 0. "
        "Uporabi {znesek} za znesek. Spremembe se takoj vidijo v predogledu spodaj.",
        wraplength=660,
        justify="left",
        bg=_BG,
        fg="#E8EEF8",
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(0, 10))

    help_box = tk.LabelFrame(
        outer,
        text=" Kaj pomenijo {…} v predlogi ",
        bg=_PANEL,
        fg="#B0BEC5",
        padx=8,
        pady=6,
        font=("Segoe UI", 9, "bold"),
    )
    help_box.pack(fill="x", pady=(0, 10))
    help_text = tk.Text(
        help_box,
        height=6,
        wrap="word",
        font=("Consolas", 9),
        bg=_HELP_BG,
        fg=_HELP_FG,
        relief="flat",
        padx=8,
        pady=6,
        highlightthickness=0,
    )
    help_text.pack(fill="x")
    for key, desc in PLACEHOLDER_HELP:
        help_text.insert("end", f"{key:<22} {desc}\n")
    help_text.configure(state="disabled")

    editors: dict[str, tk.Text] = {}

    for key, label, accent in (
        ("konto62_v_dobro", "Konto 62 — v dobro (−)  → {konto62_obvestilo}", "#1565C0"),
        ("konto62_neplacano", "Konto 62 — še neplačano (+)  → {konto62_obvestilo}", "#C62828"),
    ):
        box = tk.LabelFrame(
            outer,
            text=f" {label} ",
            bg=_PANEL,
            fg=accent,
            padx=8,
            pady=6,
            font=("Segoe UI", 9, "bold"),
        )
        box.pack(fill="both", expand=True, pady=(0, 8))
        txt = tk.Text(
            box,
            height=3,
            wrap="word",
            font=("Segoe UI", 11),
            bg=_EDIT_BG,
            fg=_EDIT_FG,
            insertbackground=_EDIT_FG,
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=accent,
            highlightcolor=accent,
        )
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", current.get(key) or DEFAULT_TEXTS[key])
        editors[key] = txt

    prev_box = tk.LabelFrame(
        outer,
        text=" Predogled (takoj ob tipkanju) ",
        bg=_PANEL,
        fg="#2E7D32",
        padx=8,
        pady=6,
        font=("Segoe UI", 9, "bold"),
    )
    prev_box.pack(fill="x", pady=(0, 8))
    prev_text = tk.Text(
        prev_box,
        height=4,
        wrap="word",
        font=("Segoe UI", 10),
        bg=_PREVIEW_BG,
        fg=_PREVIEW_FG,
        relief="flat",
        padx=10,
        pady=8,
        highlightthickness=0,
    )
    prev_text.pack(fill="x")

    def _current_payload() -> dict[str, str]:
        return collect_editor_texts(editors)

    def _preview(*_a: Any) -> None:
        payload = _current_payload()
        sample_neg = render_template(payload["konto62_v_dobro"], znesek="1.261,61")
        sample_pos = render_template(payload["konto62_neplacano"], znesek="200,00")
        prev_text.configure(state="normal")
        prev_text.delete("1.0", "end")
        prev_text.insert("end", f"(−) v dobro:\n{sample_neg}\n\n(+) še neplačano:\n{sample_pos}")
        prev_text.configure(state="disabled")
        if on_change is not None:
            try:
                on_change(payload)
            except Exception:
                pass

    for txt in editors.values():
        txt.bind("<KeyRelease>", _preview)
        txt.bind("<<Modified>>", _preview)
        txt.bind("<FocusOut>", _preview)
    _preview()

    btns = tk.Frame(outer, bg=_BG)
    btns.pack(fill="x", pady=(8, 0))

    def _defaults() -> None:
        for key, txt in editors.items():
            txt.delete("1.0", "end")
            txt.insert("1.0", DEFAULT_TEXTS[key])
        _preview()

    def _cancel() -> None:
        win.destroy()

    def _save() -> None:
        nonlocal result
        payload = _current_payload()
        for key, text in payload.items():
            if "{znesek}" not in text:
                if not messagebox.askyesno(
                    "Manjka {znesek}",
                    f"V »{key}« ni {{znesek}}.\nShrani vseeno?",
                    parent=win,
                ):
                    return
        try:
            save_texts(payload, base_dir)
        except OSError as exc:
            messagebox.showerror("Shranjevanje", str(exc), parent=win)
            return
        result = payload
        win.destroy()

    tk.Button(
        btns,
        text="Privzeto",
        command=_defaults,
        bg="#455A64",
        fg="white",
        relief="flat",
        padx=12,
        pady=6,
    ).pack(side="left")
    tk.Button(
        btns,
        text="Prekliči",
        command=_cancel,
        bg="#C62828",
        fg="white",
        relief="flat",
        padx=12,
        pady=6,
    ).pack(side="right")
    tk.Button(
        btns,
        text="Shrani",
        command=_save,
        bg="#2E7D32",
        fg="white",
        relief="flat",
        padx=14,
        pady=6,
    ).pack(side="right", padx=(0, 8))

    win.bind("<Escape>", lambda _e: _cancel())
    win.update_idletasks()
    w, h = max(720, win.winfo_reqwidth()), max(600, win.winfo_reqheight())
    try:
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        py = parent.winfo_rooty() + max(40, (parent.winfo_height() - h) // 3)
        win.geometry(f"{w}x{h}+{px}+{py}")
    except tk.TclError:
        win.geometry(f"{w}x{h}")
    parent.wait_window(win)
    return result


__all__ = [
    "DEFAULT_TEXTS",
    "PLACEHOLDER_HELP",
    "collect_editor_texts",
    "default_texts",
    "format_konto62_notice_from_texts",
    "load_texts",
    "open_placeholder_texts_form",
    "render_template",
    "save_texts",
    "texts_path",
]
