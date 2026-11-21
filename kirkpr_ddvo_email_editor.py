"""WYSIWYG urejevalnik e-pošte za DDV + virman (HTML samo v ozadju)."""

from __future__ import annotations

import html as html_lib
import re
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

import kirkpr_ddvo_email_presets as email_presets
import kirkpr_ddvo_email_templates as email_tpl
import kirkpr_ddvo_virman as ddvo_virman
from kirkpr_gui_style import (
    BTN_BLUE as _BTN_BLUE,
    BTN_BLUE_HOVER as _BTN_BLUE_HOVER,
    BTN_GREY as _BTN_GREY,
    BTN_GREEN as _BTN_GREEN,
    BTN_PURPLE as _BTN_PURPLE,
    BTN_RED as _BTN_RED,
    BTN_YELLOW as _BTN_YELLOW,
    HEADER_PURPLE as _HEADER_PURPLE,
    CollapsibleSection,
    PillButton,
)

HTML_COLORS = (
    ("Modra", "#1565C0"),
    ("Rdeča", "#C62828"),
    ("Zelena", "#2E7D32"),
    ("Oranžna", "#EF6C00"),
    ("Siva", "#616161"),
    ("Črna", "#111111"),
)

HTML_FONTS = (
    ("Calibri", "Calibri, Arial, sans-serif"),
    ("Segoe UI", "Segoe UI, Arial, sans-serif"),
    ("Arial", "Arial, Helvetica, sans-serif"),
    ("Times New Roman", "'Times New Roman', Times, serif"),
    ("Consolas", "Consolas, monospace"),
)

HTML_SIZES = (
    ("Majhna", "10pt"),
    ("Običajna", "11pt"),
    ("Velika", "14pt"),
    ("Zelo velika", "18pt"),
)

INSERT_VARS = (
    "{nagovor}",
    "{firma}",
    "{odgovorna_oseba}",
    "{obdobje}",
    "{obveznost}",
    "{presezek}",
    "{presezek_obvestilo}",
    "{preplacilo}",
    "{konto62_obvestilo}",
    "{placilo}",
    "{placilo_block}",
    "{priloga_obvestilo}",
    "{referenca}",
    "{iban}",
    "{datum}",
    "{qr_block}",
    "{ps_block}",
)

_PREVIEW_BG = "#FFFFFF"
_PREVIEW_FG = "#111111"
_DEFAULT_GEOMETRY = "980x820"
_TAG_RE = re.compile(
    r"(</?(?:strong|span|div|br|em|b|i|u|s|p)(?:\s[^>]*)?/?>)"
    r"|(&nbsp;|&amp;|&lt;|&gt;|&quot;|&#39;)",
    re.I,
)
_COLOR_RE = re.compile(r"color\s*:\s*(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)", re.I)
_FONT_RE = re.compile(
    r"font-family\s*:\s*([^;]+).*?font-size\s*:\s*([0-9.]+pt)"
    r"|font-size\s*:\s*([0-9.]+pt).*?font-family\s*:\s*([^;]+)",
    re.I,
)


def _ensure_editor_tags(widget: tk.Text) -> None:
    widget.tag_configure("b", font=("Calibri", 11, "bold"))
    widget.tag_configure("i", font=("Calibri", 11, "italic"))
    widget.tag_configure("u", underline=True)
    widget.tag_configure("s", overstrike=True)


def load_html_into_editor(widget: tk.Text, html: str) -> None:
    """HTML → bel WYSIWYG urejevalnik (brez prikaza surovega HTML)."""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    for name in list(widget.tag_names()):
        if str(name) in {"b", "i", "u", "s"} or str(name).startswith(("c_", "f_")):
            try:
                widget.tag_delete(name)
            except tk.TclError:
                pass
    _ensure_editor_tags(widget)
    raw = str(html or "")
    lines = email_tpl.html_body_to_lines(raw)
    for i, line in enumerate(lines):
        if i:
            widget.insert("end", "\n")
        if not line.strip() or line.strip() == "&nbsp;":
            continue
        _insert_html_line(widget, line)
    # Če HTML parser ni vstaviti ničesar, a telo obstaja → vsaj golo besedilo.
    if not widget.get("1.0", "end-1c").strip() and raw.strip():
        plain = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
        plain = re.sub(r"</p\s*>", "\n", plain, flags=re.I)
        plain = re.sub(r"<[^>]+>", "", plain)
        plain = html_lib.unescape(plain).strip()
        if plain:
            widget.insert("1.0", plain)
    widget.edit_modified(False)


def _insert_html_line(widget: tk.Text, src: str) -> None:
    bold = italic = under = strike = 0
    color_stack: list[str] = []
    font_stack: list[tuple[str, str]] = []
    pos = 0

    def _ins(text: str) -> None:
        if not text:
            return
        tags: list[str] = []
        if bold:
            tags.append("b")
        if italic:
            tags.append("i")
        if under:
            tags.append("u")
        if strike:
            tags.append("s")
        color = next((c for c in reversed(color_stack) if c), "")
        if color:
            tag = f"c_{color}"
            if tag not in widget.tag_names():
                widget.tag_configure(tag, foreground=color)
            tags.append(tag)
        font = next((f for f in reversed(font_stack) if f[0]), ("", ""))
        if font[0]:
            fam = font[0].split(",")[0].strip().strip("'\"")
            size_pt = font[1] or "11pt"
            try:
                size_n = int(float(size_pt.replace("pt", "").strip()))
            except ValueError:
                size_n = 11
            tag = f"f_{fam}_{size_n}"
            if tag not in widget.tag_names():
                weight = "bold" if bold else "normal"
                slant = "italic" if italic else "roman"
                widget.tag_configure(tag, font=(fam, size_n, weight if not italic else f"{weight} {slant}".strip()))
                # Tk: use bold italic as style string
                style = []
                if bold:
                    style.append("bold")
                if italic:
                    style.append("italic")
                widget.tag_configure(tag, font=(fam, size_n, " ".join(style) if style else "normal"))
            tags.append(tag)
        widget.insert("end", text, tuple(tags) if tags else ())

    for match in _TAG_RE.finditer(src):
        if match.start() > pos:
            chunk = src[pos : match.start()]
            if chunk:
                _ins(html_lib.unescape(chunk))
        token = match.group(0)
        pos = match.end()
        if token.startswith("&"):
            _ins(html_lib.unescape(token))
            continue
        low = token.casefold()
        if low.startswith("<br"):
            widget.insert("end", "\n")
        elif low.startswith("<strong") or re.match(r"<b(\s|>|/)", low):
            bold += 1
        elif low.startswith("</strong") or low.startswith("</b"):
            bold = max(0, bold - 1)
        elif low.startswith("<em") or re.match(r"<i(\s|>|/)", low):
            italic += 1
        elif low.startswith("</em") or low.startswith("</i"):
            italic = max(0, italic - 1)
        elif low.startswith("<u"):
            under += 1
        elif low.startswith("</u"):
            under = max(0, under - 1)
        elif low.startswith("<span"):
            cm = _COLOR_RE.search(token)
            color_stack.append(cm.group(1) if cm else "")
            fm = _FONT_RE.search(token)
            if fm:
                if fm.group(1):
                    font_stack.append((fm.group(1).strip(), (fm.group(2) or "11pt").strip()))
                else:
                    font_stack.append((fm.group(4).strip(), (fm.group(3) or "11pt").strip()))
            else:
                font_stack.append(("", ""))
        elif low.startswith("</span"):
            if color_stack:
                color_stack.pop()
            if font_stack:
                font_stack.pop()
        elif re.match(r"<s(\s|>|/)", low):
            strike += 1
        elif low.startswith("</s"):
            strike = max(0, strike - 1)
    if pos < len(src):
        rest = re.sub(r"<[^>]+>", "", src[pos:])
        if rest:
            _ins(html_lib.unescape(rest))


def _line_to_html_chunks(widget: tk.Text, line_no: int, line_text: str) -> str:
    """Ena vrstica belga polja → HTML (barve/krepko), brez <p>."""
    html_chunks: list[str] = []
    i = 0
    n = len(line_text)
    while i < n:
        idx = f"{line_no}.{i}"
        tags = {str(t) for t in widget.tag_names(idx)}
        j = i + 1
        while j < n and {str(t) for t in widget.tag_names(f"{line_no}.{j}")} == tags:
            j += 1
        chunk = html_lib.escape(line_text[i:j])
        color = next((t[2:] for t in tags if t.startswith("c_")), "")
        font_tag = next((t for t in tags if t.startswith("f_")), "")
        if color:
            chunk = f'<span style="color:{color}">{chunk}</span>'
        if font_tag:
            bits = font_tag.split("_")
            if len(bits) >= 3:
                fam = bits[1]
                size = bits[-1]
                chunk = (
                    f'<span style="font-family:{fam},Arial,sans-serif;'
                    f'font-size:{size}pt">{chunk}</span>'
                )
        if "s" in tags:
            chunk = f"<s>{chunk}</s>"
        if "u" in tags:
            chunk = f"<u>{chunk}</u>"
        if "i" in tags:
            chunk = f"<em>{chunk}</em>"
        if "b" in tags:
            chunk = f"<strong>{chunk}</strong>"
        html_chunks.append(chunk)
        i = j
    return "".join(html_chunks)


def richtext_to_html(widget: tk.Text) -> str:
    """Bel WYSIWYG → HTML (enako kot na ekranu).

    Zaporedne neprazne vrstice = en ``<p>`` z ``<br>`` (kot v Outlooku).
    Prazna vrstica = ločilo odstavkov (ena ``<p></p>``).
    Vdelana UPN QR slika → marker ``[QR koda za plačilo]`` (ob pošiljanju → cid).
    """
    import kirkpr_upn_qr as upn_qr

    try:
        last_line = int(widget.index("end-1c").split(".")[0])
    except (tk.TclError, ValueError):
        return "<p></p>\n"
    parts: list[str] = []
    run: list[str] = []
    blank_run = 0

    def _flush_run() -> None:
        nonlocal run
        if not run:
            return
        parts.append("<p>" + "<br>\n".join(run) + "</p>")
        run = []

    for line_no in range(1, last_line + 1):
        line_start = f"{line_no}.0"
        line_end = f"{line_no}.end"
        line_text = widget.get(line_start, line_end)
        try:
            has_img = bool(widget.dump(line_start, line_end, image=True))
        except tk.TclError:
            has_img = False
        if has_img and not line_text.strip():
            blank_run = 0
            run.append(upn_qr.UPN_QR_MARKER)
            continue
        if not line_text.strip():
            blank_run += 1
            if blank_run == 1:
                _flush_run()
                parts.append("<p></p>")
            continue
        blank_run = 0
        chunk = _line_to_html_chunks(widget, line_no, line_text)
        if has_img and upn_qr.UPN_QR_MARKER not in chunk:
            chunk = f"{chunk}<br>\n{upn_qr.UPN_QR_MARKER}" if chunk else upn_qr.UPN_QR_MARKER
        run.append(chunk)
    _flush_run()
    return email_tpl.normalize_email_html("\n".join(parts))


class DdvoEmailEditorDialog(tk.Toplevel):
    """WYSIWYG e-pošta: urejanje v belem polju (kot Outlook), HTML v ozadju."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        to_addr: str = "",
        subject: str = "",
        body_html: str = "",
        attachments: list[Path] | None = None,
        placeholder_values: dict[str, str] | None = None,
        template_id: str = email_tpl.DEFAULT_TEMPLATE_ID,
        colors: dict[str, str] | None = None,
        geometry: str = "",
        on_geometry: Callable[[str], None] | None = None,
        on_result: Callable[[dict[str, str] | None], None] | None = None,
        on_template_id: Callable[[str], None] | None = None,
        on_settings: Callable[[dict[str, Any]], None] | None = None,
        from_smtp: str = "",
        deferred_send: str = "",
        read_receipt: bool = True,
        delivery_receipt: bool = True,
        send_channel: str = "smtp",
        cc_addr: str = "",
        bcc_addr: str = "",
    ) -> None:
        super().__init__(parent)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.title("Virman — e-pošta DDV (HTML predloga)")
        bg = (colors or {}).get("bg", "#0b1220")
        panel = (colors or {}).get("panel", "#121a2a")
        text_fg = (colors or {}).get("text", "#e8eef8")
        muted = (colors or {}).get("muted", "#9aa7bd")
        entry_bg = (colors or {}).get("entry", "#0f1724")
        self._bg = bg
        self._panel = panel
        self._text_fg = text_fg
        self._muted = muted
        self.configure(bg=bg)
        geo = str(geometry or "").strip() or _DEFAULT_GEOMETRY
        try:
            self.geometry(geo)
        except tk.TclError:
            self.geometry(_DEFAULT_GEOMETRY)
        self.minsize(960, 780)
        self._on_result = on_result
        self._on_geometry = on_geometry
        self._on_template_id = on_template_id
        self._on_settings = on_settings
        self._result: dict[str, str] | None = None
        self._placeholder_values = dict(placeholder_values or {})
        self._attachments = list(attachments or [])
        self._templates = email_tpl.load_templates()
        self._template_id = email_tpl.resolve_template_id(
            str(template_id or ""),
            email_tpl.get_active_template_id(),
        )
        self._dirty = False
        self._loading_template = False
        self._autosave_after: Any = None
        self._view_mode = "vzorec"  # vzorec = {placeholders}; predogled = s podatki firme
        self._combo_ids: list[str] = []
        self._presets = email_presets.load_presets()
        self._preset_id = email_presets.get_active_preset_id()
        # Fallbacki iz klicatelja (samo če vzorec nima polja).
        self._fallback_read_receipt = bool(read_receipt)
        self._fallback_delivery_receipt = bool(delivery_receipt)
        self._fallback_deferred_send = str(deferred_send or "")
        self._fallback_cc = str(cc_addr or "").strip() or "info@quickmb.com"
        self._fallback_bcc = str(bcc_addr or "").strip()
        chan_init = str(send_channel or "smtp").strip().casefold()
        if chan_init not in ("smtp", "outlook"):
            chan_init = "smtp"
        self._channel_init = chan_init
        # Outlook COM nikoli ob odprtju — zmrzne UI, če Outlook visi.
        self._outlook_live_cache: list[str] | None = None
        self._qr_photo: Any = None  # PhotoImage ref (GC)

        # VZOREC z diska = edini vir (belo telo + Od + razmiki) — zgornja Konfiguracija ne prepiše.
        tpl = email_tpl.get_template(self._template_id)
        tpl_subj = str(tpl.get("subject") or "").strip()
        tpl_body = str(tpl.get("body") or "").strip()
        self._source_subject = tpl_subj or str(subject or "").strip()
        self._source_body = tpl_body or str(body_html or "").strip()
        if self._source_body and not any(
            t in self._source_body.casefold() for t in ("<p", "<div", "<br", "<strong", "<span")
        ):
            self._source_body = email_tpl.plain_to_html(self._source_body)
        subject0 = self._source_subject
        body0 = self._source_body
        # Od iz vzorca (ne iz stale configa / presetov).
        from_smtp = str(tpl.get("from_smtp") or from_smtp or ddvo_virman.DEFAULT_OUTLOOK_FROM)

        self._build_menubar()

        # --- Glava (Transkript-stil) ---
        header = tk.Frame(self, bg=_HEADER_PURPLE, padx=14, pady=10)
        header.pack(side="top", fill="x")
        tk.Label(
            header,
            text="✉️  Virman — e-pošta DDV",
            bg=_HEADER_PURPLE,
            fg="#ffffff",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        self.var_config_label = tk.StringVar(value="")
        self.btn_config = PillButton(
            header,
            text="⚙ Konfiguracija: Privzeto",
            command=self._show_config_menu,
            bg=_BTN_BLUE,
            hover=_BTN_BLUE_HOVER,
            padx=14,
            pady=5,
        )
        self.btn_config.pack(side="right")
        self._refresh_config_label()

        # --- Spodnji gumbi VEDNO vidni ---
        btns = tk.Frame(self, bg=panel, padx=14, pady=10)
        btns.pack(side="bottom", fill="x")
        PillButton(
            btns,
            "Shrani konfiguracijo",
            command=self._save_email_configuration,
            bg=_BTN_BLUE,
            hover=_BTN_BLUE_HOVER,
            padx=14,
            pady=7,
        ).pack(side="left")
        PillButton(
            btns, "Shrani kot novo…", command=self._save_as_new, bg=_BTN_YELLOW, fg="#1a1400", hover="#f0c85a"
        ).pack(side="left", padx=(8, 0))
        try:
            import kirkpr_force_exit as force_exit

            force_exit.attach_force_exit_button(btns, pack_side="right", padx=(8, 0))
        except Exception:
            pass
        PillButton(btns, "Prekliči", command=self._cancel, bg=_BTN_RED, hover="#d55a63").pack(side="right")
        self.btn_send = PillButton(
            btns,
            "✉ Pošlji SMTP",
            command=self._accept,
            bg=_BTN_GREEN,
            hover="#3cb87a",
            padx=16,
            pady=7,
        )
        self.btn_send.pack(side="right", padx=(0, 8))
        # Kot DDV-O Oddaje: TEST → samo info@quickmb.com, zadeva [TEST], brez KP/SKP.
        PillButton(
            btns,
            "TEST",
            command=self._accept_test,
            bg=_BTN_YELLOW,
            fg="#1a1400",
            hover="#f0c85a",
            padx=12,
            pady=7,
        ).pack(side="right", padx=(0, 8))

        outer = tk.Frame(self, bg=bg, padx=12, pady=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        tk.Label(outer, text="Predloga", bg=bg, fg=muted).grid(row=0, column=0, sticky="w", pady=2)
        tpl_row = tk.Frame(outer, bg=bg)
        tpl_row.grid(row=0, column=1, sticky="ew", pady=2)
        self.var_template = tk.StringVar()
        self.cmb_template = ttk.Combobox(tpl_row, textvariable=self.var_template, state="readonly")
        self.cmb_template.pack(side="left", fill="x", expand=True)
        self.cmb_template.bind("<<ComboboxSelected>>", self._on_template_selected)
        PillButton(
            tpl_row, "Naloži", command=self._load_selected_template, bg=_BTN_GREEN, hover="#3cb87a",
            padx=8, pady=2, font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(6, 0))
        PillButton(
            tpl_row, "Odpri…", command=self._open_template_picker, bg=_BTN_BLUE, hover=_BTN_BLUE_HOVER,
            padx=8, pady=2, font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(4, 0))
        PillButton(
            tpl_row, "Preimenuj", command=self._rename_template, bg=_BTN_GREY, hover="#4a5a7a", padx=8, pady=2,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(4, 0))
        PillButton(
            tpl_row, "Kopiraj", command=self._copy_template, bg=_BTN_YELLOW, fg="#1a1400", hover="#f0c85a",
            padx=8, pady=2, font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(4, 0))
        PillButton(
            tpl_row, "Briši", command=self._delete_template, bg=_BTN_RED, hover="#d55a63", padx=8, pady=2,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(4, 0))
        self._refresh_template_combo(select_id=self._template_id)

        # Povzetek vzorca: Od + zadeva + dolžina (vedno viden)
        self.var_vzorec_info = tk.StringVar(value="")
        tk.Label(
            outer,
            textvariable=self.var_vzorec_info,
            bg=bg,
            fg=muted,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=780,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        tk.Label(outer, text="Za (e-pošta)", bg=bg, fg=muted).grid(row=2, column=0, sticky="w", pady=2)
        self.var_to = tk.StringVar(value=ddvo_virman.normalize_outlook_recipients(to_addr or ""))
        ttk.Entry(outer, textvariable=self.var_to).grid(row=2, column=1, sticky="ew", pady=2)

        # KP = kopija (CC), SKP = skrita kopija (BCC) — kot Outlook / Oddaje.
        default_cc = str(
            cc_addr
            or getattr(self, "_fallback_cc", "")
            or "info@quickmb.com"
        ).strip()
        tk.Label(outer, text="KP / CC", bg=bg, fg=muted).grid(row=3, column=0, sticky="w", pady=2)
        self.var_cc = tk.StringVar(value=ddvo_virman.normalize_outlook_recipients(default_cc))
        ttk.Entry(outer, textvariable=self.var_cc).grid(row=3, column=1, sticky="ew", pady=2)
        self.var_cc.trace_add("write", lambda *_: self._mark_dirty())

        default_bcc = str(bcc_addr or getattr(self, "_fallback_bcc", "") or "").strip()
        tk.Label(outer, text="SKP / BCC", bg=bg, fg=muted).grid(row=4, column=0, sticky="w", pady=2)
        self.var_bcc = tk.StringVar(value=ddvo_virman.normalize_outlook_recipients(default_bcc))
        ttk.Entry(outer, textvariable=self.var_bcc).grid(row=4, column=1, sticky="ew", pady=2)
        self.var_bcc.trace_add("write", lambda *_: self._mark_dirty())

        # Od (pošiljatelj) — VEDNO viden; privzeto iz VZORCA, ne iz starega configa.
        tk.Label(outer, text="Od (račun)", bg=bg, fg=muted).grid(row=5, column=0, sticky="w", pady=2)
        from0 = str(
            tpl.get("from_smtp") or from_smtp or ddvo_virman.DEFAULT_OUTLOOK_FROM
        ).strip()
        from_choices = self._outlook_from_choices()
        if from0 not in from_choices:
            if from0.casefold() == "info@quickmb.com" and "info@quickmb.si" in from_choices:
                from0 = "info@quickmb.si"
            elif from0.casefold() == "info@quickmb.si" and "info@quickmb.com" in from_choices:
                from0 = "info@quickmb.com"
            elif from0 not in from_choices:
                # Ostani na želenem — uporabnik ga vidi, tudi če Outlook še ni odgovoril
                if from0 and from0 not in from_choices:
                    from_choices = [from0, *from_choices]
                else:
                    from0 = from_choices[0] if from_choices else ddvo_virman.DEFAULT_OUTLOOK_FROM
        self.var_from = tk.StringVar(value=from0)
        from_row = tk.Frame(outer, bg=bg)
        from_row.grid(row=5, column=1, sticky="ew", pady=2)
        self.cmb_from = ttk.Combobox(
            from_row,
            textvariable=self.var_from,
            values=from_choices,
            width=36,
            state="readonly",
        )
        self.cmb_from.pack(side="left")
        PillButton(
            from_row,
            "Osveži",
            command=self._refresh_from_accounts,
            bg=_BTN_GREY,
            hover="#4a5a7a",
            padx=8,
            pady=2,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(8, 0))
        self.var_from_hint = tk.StringVar(value="")
        tk.Label(from_row, textvariable=self.var_from_hint, bg=bg, fg=muted).pack(side="left", padx=(10, 0))
        # Ne kličemo _update_from_hint tukaj — var_channel še ni; naredimo po kanalu.

        def _from_changed(*_a: Any) -> None:
            self._update_from_hint()
            self._mark_dirty()

        self.var_from.trace_add("write", _from_changed)

        # Kanal: SMTP (privzeto) ali Outlook — Outlook odloženo pogosto »ni poslano«.
        self.var_channel = tk.StringVar(value=self._channel_init)
        tk.Label(outer, text="Kanal", bg=bg, fg=muted).grid(row=6, column=0, sticky="w", pady=2)
        chan_row = tk.Frame(outer, bg=bg)
        chan_row.grid(row=6, column=1, sticky="ew", pady=2)
        ttk.Radiobutton(
            chan_row,
            text="SMTP (Gmail) — takoj",
            value="smtp",
            variable=self.var_channel,
            command=self._on_channel_changed,
        ).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(
            chan_row,
            text="Outlook",
            value="outlook",
            variable=self.var_channel,
            command=self._on_channel_changed,
        ).pack(side="left", padx=(0, 10))
        self.var_channel_hint = tk.StringVar(value="")
        tk.Label(chan_row, textvariable=self.var_channel_hint, bg=bg, fg=muted).pack(side="left")
        # Hint za Od — brez Outlook COM (sicer zmrzne).
        self._update_from_hint()

        tk.Label(outer, text="Ime predloge", bg=bg, fg=muted).grid(row=7, column=0, sticky="w", pady=2)
        self.var_title = tk.StringVar(value=str(tpl.get("title") or "DDV + virman"))
        ttk.Entry(outer, textvariable=self.var_title).grid(row=7, column=1, sticky="ew", pady=2)
        self.var_title.trace_add("write", lambda *_: self._mark_dirty())

        tk.Label(outer, text="Zadeva", bg=bg, fg=muted).grid(row=8, column=0, sticky="w", pady=2)
        self.var_subject = tk.StringVar(value=subject0)
        ttk.Entry(outer, textvariable=self.var_subject).grid(row=8, column=1, sticky="ew", pady=2)
        self.var_subject.trace_add("write", lambda *_: self._mark_dirty())

        # Priponke: chk DDV-O / virman (ostale datoteke ostanejo vedno).
        self._attach_pdf_path: Path | None = None
        self._attach_virman_path: Path | None = None
        self._attach_extra: list[Path] = []
        for raw in self._attachments:
            path = Path(raw)
            if not path.is_file():
                continue
            name = path.name.casefold()
            if path.suffix.casefold() == ".pdf" and self._attach_pdf_path is None:
                self._attach_pdf_path = path
            elif (
                self._attach_virman_path is None
                and (
                    path.suffix.casefold() == ".xml"
                    or "virman" in name
                    or "pain" in name
                )
            ):
                self._attach_virman_path = path
            else:
                self._attach_extra.append(path)

        attach_fr = tk.Frame(outer, bg=bg)
        attach_fr.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        tk.Label(attach_fr, text="Priponke", bg=bg, fg=muted).pack(side="left", padx=(0, 10))
        self.var_attach_pdf = tk.BooleanVar(value=self._attach_pdf_path is not None)
        self.var_attach_virman = tk.BooleanVar(value=self._attach_virman_path is not None)
        pdf_label = (
            f"DDV-O ({self._attach_pdf_path.name})"
            if self._attach_pdf_path is not None
            else "DDV-O (ni datoteke)"
        )
        vir_label = (
            f"Virman ({self._attach_virman_path.name})"
            if self._attach_virman_path is not None
            else "Virman (ni datoteke)"
        )
        cb_pdf = ttk.Checkbutton(attach_fr, text=pdf_label, variable=self.var_attach_pdf)
        cb_pdf.pack(side="left", padx=(0, 14))
        if self._attach_pdf_path is None:
            self.var_attach_pdf.set(False)
            cb_pdf.state(["disabled"])
        cb_vir = ttk.Checkbutton(attach_fr, text=vir_label, variable=self.var_attach_virman)
        cb_vir.pack(side="left", padx=(0, 14))
        if self._attach_virman_path is None:
            self.var_attach_virman.set(False)
            cb_vir.state(["disabled"])
        if self._attach_extra:
            extra_names = ", ".join(p.name for p in self._attach_extra[:4])
            more = f" (+{len(self._attach_extra) - 4})" if len(self._attach_extra) > 4 else ""
            tk.Label(
                attach_fr,
                text=f"+ {extra_names}{more}",
                bg=bg,
                fg=muted,
            ).pack(side="left")
        self.var_qr_hint = tk.StringVar(value="")
        tk.Label(attach_fr, textvariable=self.var_qr_hint, bg=bg, fg=muted).pack(side="left", padx=(12, 0))
        self._refresh_qr_hint()

        # Outlook: odloženo / potrdila — privzeto BREZ odložitve (sicer ostane v Outbox).
        send_sec = CollapsibleSection(
            outer,
            "Outlook pošiljanje (potrdila / odloženo)",
            bg=panel,
            fg=text_fg,
            muted=muted,
            initially_open=False,
        )
        send_sec.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        self._send_sec = send_sec
        send_fr = send_sec.body
        send_fr.columnconfigure(1, weight=1)

        self.var_delivery_receipt = tk.BooleanVar(value=bool(delivery_receipt))
        self.var_read_receipt = tk.BooleanVar(value=bool(read_receipt))
        ttk.Checkbutton(
            send_fr,
            text="Potrdilo o prejemu (dostavljeno) — Outlook te obvesti",
            variable=self.var_delivery_receipt,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(
            send_fr,
            text="Potrdilo o odprtju (prejeto/prebrano)",
            variable=self.var_read_receipt,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

        # Nikoli samodejno odloži — shranjen čas je samo predlog v polju.
        self.var_defer = tk.BooleanVar(value=False)
        defer_row = tk.Frame(send_fr, bg=panel)
        defer_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Checkbutton(
            defer_row,
            text="Odloži pošiljanje (Outlook Outbox)",
            variable=self.var_defer,
            command=self._toggle_defer,
        ).pack(side="left")
        default_defer = str(deferred_send or "").strip()
        if not default_defer:
            tomorrow = datetime.now() + timedelta(days=1)
            default_defer = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0).strftime(
                "%d.%m.%Y %H:%M"
            )
        self.var_defer_at = tk.StringVar(value=default_defer)
        self.ent_defer = ttk.Entry(defer_row, textvariable=self.var_defer_at, width=18)
        self.ent_defer.pack(side="left", padx=(8, 0))
        tk.Label(defer_row, text="(dd.mm.llll UU:MM)", bg=panel, fg=muted).pack(side="left", padx=(6, 0))
        self._toggle_defer()
        # NE kličemo _on_channel_changed tukaj — še ni txt_html / Oblikovanje (sicer
        # _mark_dirty → AttributeError in belo telo se nikoli ne naredi).

        fmt_sec = CollapsibleSection(
            outer,
            "Oblikovanje (kot Transkript)",
            bg=panel,
            fg=text_fg,
            muted=muted,
            initially_open=True,
        )
        fmt_sec.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        fmt = fmt_sec.body
        fr = tk.Frame(fmt, bg=panel)
        fr.pack(fill="x")
        PillButton(fr, "B", command=self._wrap_bold, bg=_BTN_BLUE, hover=_BTN_BLUE_HOVER, padx=8, pady=3).pack(
            side="left", padx=(0, 2)
        )
        PillButton(fr, "I", command=self._wrap_italic, bg=_BTN_BLUE, hover=_BTN_BLUE_HOVER, padx=8, pady=3).pack(
            side="left", padx=(0, 2)
        )
        PillButton(fr, "U", command=self._wrap_underline, bg=_BTN_BLUE, hover=_BTN_BLUE_HOVER, padx=8, pady=3).pack(
            side="left", padx=(0, 2)
        )
        PillButton(fr, "S", command=self._wrap_strike, bg=_BTN_GREY, hover="#4a5a7a", padx=8, pady=3).pack(
            side="left", padx=(0, 6)
        )
        PillButton(fr, "Odstavek", command=self._wrap_paragraph, bg=_BTN_GREY, hover="#4a5a7a", padx=10, pady=3).pack(
            side="left", padx=(0, 4)
        )
        PillButton(fr, "Nova vrstica", command=self._insert_br, bg=_BTN_GREY, hover="#4a5a7a", padx=10, pady=3).pack(
            side="left", padx=(0, 4)
        )
        PillButton(
            fr, "Prazna vrstica", command=self._insert_blank_line, bg=_BTN_GREY, hover="#4a5a7a", padx=10, pady=3
        ).pack(side="left", padx=(0, 8))

        tk.Label(fr, text="Barva:", bg=panel, fg=muted).pack(side="left", padx=(4, 2))
        self.var_color = tk.StringVar(value=HTML_COLORS[0][0])
        ttk.Combobox(
            fr,
            textvariable=self.var_color,
            values=[n for n, _ in HTML_COLORS],
            width=9,
            state="readonly",
        ).pack(side="left", padx=(0, 4))
        PillButton(fr, "Obarvaj", command=self._wrap_color, bg=_BTN_PURPLE, hover="#8566ff", padx=10, pady=3).pack(
            side="left", padx=(0, 8)
        )

        fr2 = tk.Frame(fmt, bg=panel)
        fr2.pack(fill="x", pady=(6, 0))
        tk.Label(fr2, text="Pisava:", bg=panel, fg=muted).pack(side="left")
        self.var_font = tk.StringVar(value=HTML_FONTS[0][0])
        ttk.Combobox(
            fr2,
            textvariable=self.var_font,
            values=[n for n, _ in HTML_FONTS],
            width=16,
            state="readonly",
        ).pack(side="left", padx=(4, 8))
        tk.Label(fr2, text="Velikost:", bg=panel, fg=muted).pack(side="left")
        self.var_size = tk.StringVar(value=HTML_SIZES[1][0])
        ttk.Combobox(
            fr2,
            textvariable=self.var_size,
            values=[n for n, _ in HTML_SIZES],
            width=12,
            state="readonly",
        ).pack(side="left", padx=(4, 4))
        PillButton(fr2, "Uporabi font", command=self._wrap_font, bg=_BTN_BLUE, hover=_BTN_BLUE_HOVER, padx=10, pady=3).pack(
            side="left", padx=(0, 8)
        )

        # Transkript: Vrstica / Odstavek / Tesno
        fr_sp = tk.Frame(fmt, bg=panel)
        fr_sp.pack(fill="x", pady=(8, 0))
        tk.Label(fr_sp, text="Vrstica", bg=panel, fg=muted).pack(side="left")
        self.var_line_height = tk.StringVar(value="1.35")
        ttk.Combobox(
            fr_sp,
            textvariable=self.var_line_height,
            values=("1.0", "1.15", "1.35", "1.5", "1.75", "2.0"),
            width=6,
            state="readonly",
        ).pack(side="left", padx=(4, 10))
        tk.Label(fr_sp, text="Odstavek", bg=panel, fg=muted).pack(side="left")
        self.var_para_spacing = tk.StringVar(value="4 px")
        ttk.Combobox(
            fr_sp,
            textvariable=self.var_para_spacing,
            values=("0 px", "2 px", "4 px", "6 px", "8 px", "12 px", "16 px"),
            width=7,
            state="readonly",
        ).pack(side="left", padx=(4, 10))
        def _spacing_changed(*_a: Any) -> None:
            self._apply_editor_spacing()
            self._mark_dirty()

        self.var_line_height.trace_add("write", _spacing_changed)
        self.var_para_spacing.trace_add("write", _spacing_changed)
        PillButton(fr_sp, "↕ Tesno", command=self._apply_tighten, bg=_BTN_YELLOW, fg="#1a1400", hover="#f0c85a", padx=10, pady=3).pack(
            side="left", padx=(0, 6)
        )
        PillButton(
            fr_sp, "Uporabi razmike", command=self._apply_spacing, bg=_BTN_BLUE, hover=_BTN_BLUE_HOVER, padx=10, pady=3
        ).pack(side="left", padx=(0, 6))
        PillButton(fr_sp, "✍️ Podpis", command=self._insert_signature, bg=_BTN_PURPLE, hover="#8566ff", padx=10, pady=3).pack(
            side="left"
        )

        fr3 = tk.Frame(fmt, bg=panel)
        fr3.pack(fill="x", pady=(6, 0))
        tk.Label(fr3, text="Vstavi:", bg=panel, fg=muted).pack(side="left")
        for var_key in INSERT_VARS:
            PillButton(
                fr3,
                var_key,
                command=lambda k=var_key: self._insert_var(k),
                bg=_BTN_GREY,
                hover="#4a5a7a",
                padx=6,
                pady=2,
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=2)
        PillButton(
            fr3,
            "Besedila {…}",
            command=self._edit_placeholder_texts,
            bg=_BTN_YELLOW,
            fg="#1a1400",
            hover="#f0c85a",
            padx=10,
            pady=2,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(10, 0))

        # Presežek (52): kljukica vračilo — kot DDV-O Oddaje 1.0.64/65
        has_excess = bool(str(self._placeholder_values.get("presezek") or "").strip())
        self.var_vracilo = tk.BooleanVar(
            value=str(self._placeholder_values.get("vracilo") or "").strip().casefold()
            in {"da", "1", "true", "yes"}
        )
        fr_vr = tk.Frame(fmt, bg=panel)
        fr_vr.pack(fill="x", pady=(8, 0))
        self.chk_vracilo = tk.Checkbutton(
            fr_vr,
            text="Zahtevam vračilo presežka (polje 04) — vpliva na {presezek_obvestilo} in f04 PDF",
            variable=self.var_vracilo,
            command=self._on_vracilo_toggle,
            bg=panel,
            fg=text_fg,
            activebackground=panel,
            activeforeground=text_fg,
            selectcolor=entry_bg,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.chk_vracilo.pack(side="left", fill="x")
        if not has_excess:
            self.chk_vracilo.configure(state="disabled")
            self.var_vracilo.set(False)

        # Bel WYSIWYG — to je edino mesto urejanja (HTML je v ozadju).
        edit_fr = tk.LabelFrame(
            outer,
            text="Besedilo e-pošte (urejaj tukaj — enako gre v Outlook / SMTP)",
            bg=panel,
            fg=text_fg,
            padx=4,
            pady=4,
        )
        edit_fr.grid(row=12, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        # Teža na vrstici 12 = belo telo (NE na Oblikovanje).
        outer.rowconfigure(12, weight=1)
        edit_fr.rowconfigure(1, weight=1)
        edit_fr.columnconfigure(0, weight=1)

        self.var_preview_subj = tk.StringVar(value="")
        mode_row = tk.Frame(edit_fr, bg=_PREVIEW_BG)
        mode_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        mode_row.columnconfigure(0, weight=1)
        tk.Label(
            mode_row,
            textvariable=self.var_preview_subj,
            bg=_PREVIEW_BG,
            fg=_PREVIEW_FG,
            font=("Calibri", 10, "bold"),
            anchor="w",
            padx=10,
            pady=6,
        ).pack(side="left", fill="x", expand=True)
        self.btn_mode_vzorec = PillButton(
            mode_row,
            "Vzorec {…}",
            command=self._show_vzorec_mode,
            bg=_BTN_BLUE,
            hover=_BTN_BLUE_HOVER,
            padx=10,
            pady=3,
            font=("Segoe UI", 8, "bold"),
        )
        self.btn_mode_vzorec.pack(side="right", padx=(0, 8), pady=4)
        self.btn_mode_predogled = PillButton(
            mode_row,
            "Predogled s podatki",
            command=self._show_predogled_mode,
            bg=_BTN_GREY,
            hover="#4a5a7a",
            padx=10,
            pady=3,
            font=("Segoe UI", 8, "bold"),
        )
        self.btn_mode_predogled.pack(side="right", padx=(0, 4), pady=4)

        self.txt_html = tk.Text(
            edit_fr,
            wrap="word",
            height=18,
            font=("Calibri", 11),
            bg=_PREVIEW_BG,
            fg=_PREVIEW_FG,
            insertbackground=_PREVIEW_FG,
            selectbackground="#c5d8f7",
            relief="solid",
            borderwidth=1,
            padx=12,
            pady=10,
            undo=True,
            spacing1=0,
            spacing2=2,
            spacing3=4,
        )
        sb = ttk.Scrollbar(edit_fr, orient="vertical", command=self.txt_html.yview)
        self.txt_html.configure(yscrollcommand=sb.set)
        self.txt_html.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        _ensure_editor_tags(self.txt_html)
        load_html_into_editor(self.txt_html, body0)
        self.txt_html.bind("<<Modified>>", self._on_text_modified)
        self.txt_html.bind("<KeyRelease>", lambda _e: self._mark_dirty())
        self.txt_html.bind("<FocusOut>", lambda _e: self._autosave_now(), add="+")
        status_row = tk.Frame(edit_fr, bg=panel)
        status_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.var_save_status = tk.StringVar(value="✓ belo telo z diska")
        tk.Label(
            status_row,
            textvariable=self.var_save_status,
            bg=panel,
            fg="#7dcea0",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(side="left")
        self.var_editor_hint = tk.StringVar(
            value="Spremembe se samodejno shranijo · tudi Shrani / Outlook"
        )
        tk.Label(
            status_row,
            textvariable=self.var_editor_hint,
            bg=panel,
            fg=muted,
            font=("Segoe UI", 8),
            anchor="e",
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Configure>", self._on_configure_geometry, add="+")
        # SAMO vzorec z diska — preset/Konfiguracija NE prepiše belega telesa / Od / razmikov.
        self._apply_vzorec_fields(email_tpl.get_template(self._template_id))
        self._update_mode_buttons()
        self._refresh_subject_label()
        # Ob odprtju z DDV podatki: takoj prikaži zapolnjeno e-pošto (ne {obdobje}).
        if self._placeholder_values:
            self.after(60, self._show_predogled_mode)
        self.after(80, self._on_channel_changed)
        self.after(40, lambda: self.txt_html.focus_set())

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Shrani konfiguracijo", command=self._save_email_configuration)
        m_file.add_command(label="Shrani kot novo…", command=self._save_as_new)
        m_file.add_separator()
        m_file.add_command(label="Zapri", command=self._cancel)
        menubar.add_cascade(label="Datoteka", menu=m_file)

        m_tpl = tk.Menu(menubar, tearoff=0)
        m_tpl.add_command(label="Odpri…", command=self._open_template_picker)
        m_tpl.add_command(label="Preimenuj…", command=self._rename_template)
        m_tpl.add_command(label="Kopiraj…", command=self._copy_template)
        m_tpl.add_command(label="Briši…", command=self._delete_template)
        m_tpl.add_separator()
        m_tpl.add_command(label="Obnovi privzeti vzorec…", command=self._restore_default_template)
        menubar.add_cascade(label="Predloga", menu=m_tpl)

        self._menu_config = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Konfiguracija", menu=self._menu_config)
        self._rebuild_config_menu()

        m_fmt = tk.Menu(menubar, tearoff=0)
        m_fmt.add_command(label="Uporabi razmike", command=self._apply_spacing)
        m_fmt.add_command(label="↕ Tesno (1.35 / 4 px)", command=self._apply_tighten)
        m_fmt.add_command(label="✍️ Vstavi podpis", command=self._insert_signature)
        menubar.add_cascade(label="Oblikovanje", menu=m_fmt)

        self.config(menu=menubar)

    def _rebuild_config_menu(self) -> None:
        menu = self._menu_config
        menu.delete(0, "end")
        choose = tk.Menu(menu, tearoff=0)
        for row in email_presets.list_presets():
            tid = str(row.get("id") or "")
            name = str(row.get("name") or tid)
            mark = "✓ " if tid == self._preset_id else "   "
            choose.add_command(
                label=f"{mark}{name}",
                command=lambda i=tid: self._apply_preset(i),
            )
        menu.add_cascade(label="Izberi…", menu=choose)
        menu.add_separator()
        menu.add_command(label="Shrani trenutno konfiguracijo", command=self._save_current_preset)
        menu.add_command(label="Shrani kot novo…", command=self._save_preset_as)
        menu.add_command(label="Izbriši aktivno…", command=self._delete_active_preset)

    def _preset_display_name(self, preset_id: str = "") -> str:
        tid = str(preset_id or self._preset_id or email_presets.DEFAULT_PRESET_ID)
        row = email_presets.get_preset(tid)
        return str(row.get("name") or tid)

    def _refresh_config_label(self) -> None:
        name = self._preset_display_name()
        label = f"⚙ Konfiguracija: {name}"
        self.var_config_label.set(label)
        try:
            self.btn_config.configure(text=label)
        except (tk.TclError, AttributeError):
            pass

    def _show_config_menu(self) -> None:
        """Popup meni kot Transkript gumb Konfiguracija."""
        self._rebuild_config_menu()
        menu = tk.Menu(self, tearoff=0)
        for row in email_presets.list_presets():
            tid = str(row.get("id") or "")
            name = str(row.get("name") or tid)
            mark = "✓ " if tid == self._preset_id else "   "
            menu.add_command(label=f"{mark}{name}", command=lambda i=tid: self._apply_preset(i))
        menu.add_separator()
        menu.add_command(label="Shrani trenutno…", command=self._save_current_preset)
        menu.add_command(label="Shrani kot novo…", command=self._save_preset_as)
        menu.add_command(label="Izbriši aktivno…", command=self._delete_active_preset)
        try:
            menu.tk_popup(self.btn_config.winfo_rootx(), self.btn_config.winfo_rooty() + self.btn_config.winfo_height())
        finally:
            menu.grab_release()

    def _apply_preset(self, preset_id: str, *, quiet: bool = False, keep_from: bool = False) -> None:
        row = email_presets.get_preset(preset_id)
        self._preset_id = str(row.get("id") or email_presets.DEFAULT_PRESET_ID)
        email_presets.set_active_preset_id(self._preset_id)
        from_smtp = str(row.get("from_smtp") or ddvo_virman.DEFAULT_OUTLOOK_FROM).strip()
        choices = self._outlook_from_choices() if hasattr(self, "cmb_from") else list(ddvo_virman.OUTLOOK_FROM_ACCOUNTS)
        if from_smtp not in choices:
            # Dovolimo alias .si/.com
            if from_smtp.casefold() == "info@quickmb.com" and "info@quickmb.si" in choices:
                from_smtp = "info@quickmb.si"
            elif from_smtp not in choices:
                from_smtp = choices[0] if choices else ddvo_virman.DEFAULT_OUTLOOK_FROM
        if hasattr(self, "var_from") and not keep_from:
            self.var_from.set(from_smtp)
            self._update_from_hint()
        lh = str(row.get("line_height") or "1.35").strip() or "1.35"
        if hasattr(self, "var_line_height"):
            self.var_line_height.set(lh)
        try:
            px = int(row.get("para_spacing_px") or 4)
        except (TypeError, ValueError):
            px = 4
        if hasattr(self, "var_para_spacing"):
            self.var_para_spacing.set(f"{max(0, min(48, px))} px")
        if hasattr(self, "txt_html"):
            self._apply_editor_spacing()
        if hasattr(self, "var_read_receipt"):
            self.var_read_receipt.set(bool(row.get("read_receipt", True)))
        if hasattr(self, "var_delivery_receipt"):
            self.var_delivery_receipt.set(bool(row.get("delivery_receipt", True)))
        if hasattr(self, "var_defer"):
            self.var_defer.set(bool(row.get("defer_send", False)))
            self._toggle_defer()
        self._refresh_config_label()
        try:
            self._rebuild_config_menu()
        except (tk.TclError, AttributeError):
            pass
        # Preset spremeni samo Od/razmike v UI — belo telo ostane; ob shrani gre v vzorec.
        if hasattr(self, "var_save_status"):
            self.var_save_status.set("● Od/razmiki spremenjeni — shranjujem v vzorec…")
        self._mark_dirty()

    def _current_preset_payload(self) -> dict[str, Any]:
        lh, px = self._spacing_values()
        return {
            "from_smtp": self.var_from.get().strip() or ddvo_virman.DEFAULT_OUTLOOK_FROM,
            "line_height": lh,
            "para_spacing_px": px,
            "read_receipt": bool(self.var_read_receipt.get()),
            "delivery_receipt": bool(self.var_delivery_receipt.get()),
            "defer_send": bool(self.var_defer.get()),
        }

    def _notify_settings_saved(self, *, template_id: str, from_smtp: str, lh: str, px: int) -> None:
        if not self._on_settings:
            return
        try:
            self._on_settings(
                {
                    "template_id": template_id,
                    "from_smtp": from_smtp,
                    "line_height": lh,
                    "para_spacing_px": px,
                    "read_receipt": bool(self.var_read_receipt.get()),
                    "delivery_receipt": bool(self.var_delivery_receipt.get()),
                    "defer_send": bool(self.var_defer.get()),
                    "to": self.var_to.get().strip(),
                    "title": self.var_title.get().strip(),
                }
            )
        except Exception:
            pass

    def _save_current_preset(self) -> None:
        name = self._preset_display_name()
        payload = self._current_preset_payload()
        tid = email_presets.save_preset(
            self._preset_id,
            name=name,
            **payload,
        )
        self._preset_id = tid
        email_presets.set_active_preset_id(tid)
        self._refresh_config_label()
        self._rebuild_config_menu()
        messagebox.showinfo("Konfiguracija", f"Shranjeno: {name}", parent=self)

    def _save_preset_as(self) -> None:
        name = simpledialog.askstring(
            "Nova konfiguracija",
            "Ime konfiguracije (npr. Gmail tesno):",
            parent=self,
            initialvalue=self._preset_display_name(),
        )
        if not name or not str(name).strip():
            return
        payload = self._current_preset_payload()
        tid = email_presets.save_preset(
            str(name).strip(),
            name=str(name).strip(),
            **payload,
        )
        self._preset_id = tid
        email_presets.set_active_preset_id(tid)
        self._refresh_config_label()
        self._rebuild_config_menu()
        messagebox.showinfo("Konfiguracija", f"Nova konfiguracija: {name}", parent=self)

    def _delete_active_preset(self) -> None:
        if self._preset_id == email_presets.DEFAULT_PRESET_ID:
            messagebox.showwarning("Konfiguracija", "Privzete konfiguracije ni mogoče izbrisati.", parent=self)
            return
        name = self._preset_display_name()
        if not messagebox.askyesno("Konfiguracija", f"Izbrisati «{name}»?", parent=self):
            return
        if email_presets.delete_preset(self._preset_id):
            self._apply_preset(email_presets.DEFAULT_PRESET_ID, quiet=True)
            messagebox.showinfo("Konfiguracija", f"Izbrisano: {name}", parent=self)

    def _on_configure_geometry(self, _event: tk.Event | None = None) -> None:
        if self._on_geometry and self.state() == "normal":
            try:
                self._on_geometry(self.geometry())
            except tk.TclError:
                pass

    def _persist_geometry(self) -> None:
        if self._on_geometry:
            try:
                self._on_geometry(self.geometry())
            except tk.TclError:
                pass

    def _toggle_defer(self) -> None:
        state = "normal" if self.var_defer.get() else "disabled"
        try:
            self.ent_defer.configure(state=state)
        except tk.TclError:
            pass

    def _on_channel_changed(self) -> None:
        channel = str(self.var_channel.get() or "smtp").casefold()
        if channel == "smtp":
            self.var_defer.set(False)
            self._toggle_defer()
            try:
                import kirkpr_ddvo_smtp as ddvo_smtp

                path = ddvo_smtp.smtp_secret_path()
                self.var_channel_hint.set(
                    f"✓ geslo OK · {ddvo_smtp.SENDER_EMAIL} → klikni ✉ Pošlji SMTP"
                    if path
                    else "✗ ni smtp_secret.bin"
                )
            except Exception as exc:
                self.var_channel_hint.set(f"✗ {exc}")
            if hasattr(self, "btn_send"):
                self.btn_send.configure(text="✉ Pošlji SMTP")
            if hasattr(self, "_send_sec"):
                try:
                    self._send_sec.set_open(False)
                except Exception:
                    pass
        else:
            self.var_channel_hint.set("Osveži = Outlook računi · potrdila spodaj")
            if hasattr(self, "btn_send"):
                self.btn_send.configure(text="✉ Pošlji Outlook")
            if hasattr(self, "_send_sec"):
                try:
                    self._send_sec.set_open(True)
                except Exception:
                    pass
        self._update_from_hint()
        # Ne _mark_dirty med gradnjo / prvim sync — samo hinti.

    def _refresh_qr_hint(self) -> None:
        import kirkpr_upn_qr as upn_qr

        png = str(self._placeholder_values.get("_qr_png") or "").strip()
        if png and Path(png).is_file():
            self.var_qr_hint.set("✓ UPN QR PNG (vdelava ob pošiljanju)")
        elif upn_qr.UPN_QR_MARKER in str(self._placeholder_values.get("qr_block") or ""):
            self.var_qr_hint.set("✗ UPN QR PNG manjka — v telesu ostane marker")
        elif str(self._placeholder_values.get("placilo") or "").strip():
            self.var_qr_hint.set("✗ UPN QR ni pripravljen")
        else:
            self.var_qr_hint.set("")

    def _static_from_choices(self) -> list[str]:
        rows: list[str] = []
        for addr in ddvo_virman.OUTLOOK_FROM_ACCOUNTS:
            if addr not in rows:
                rows.append(addr)
        return rows or [ddvo_virman.DEFAULT_OUTLOOK_FROM]

    def _outlook_from_choices(self, *, probe_live: bool = False) -> list[str]:
        """Combobox: znani računi; Outlook COM samo ob izrecnem Osveži."""
        rows = self._static_from_choices()
        if not probe_live:
            if self._outlook_live_cache:
                for addr in self._outlook_live_cache:
                    if addr and addr not in rows:
                        rows.append(addr)
            return rows
        try:
            live = ddvo_virman.list_outlook_account_addresses()
            self._outlook_live_cache = list(live)
            for addr in live:
                if addr and addr not in rows:
                    rows.append(addr)
        except Exception:
            pass
        return rows or [ddvo_virman.DEFAULT_OUTLOOK_FROM]

    def _refresh_from_accounts(self) -> None:
        self.var_from_hint.set("… berem Outlook …")
        self.update_idletasks()
        choices = self._outlook_from_choices(probe_live=True)
        current = self.var_from.get().strip()
        try:
            self.cmb_from.configure(values=choices)
        except tk.TclError:
            return
        if current not in choices and choices:
            self.var_from.set(choices[0])
        self._update_from_hint()
        live = self._outlook_live_cache or []
        messagebox.showinfo(
            "Outlook računi",
            "Računi v Outlooku:\n"
            + ("\n".join(f"• {a}" for a in live) if live else "• (ni najdenih — preveri Outlook)")
            + "\n\nIzberi enega v polju Od (račun).",
            parent=self,
        )

    def _from_account_in_outlook(self, wanted: str = "") -> bool:
        addr = (wanted or self.var_from.get() or "").strip()
        if not addr:
            return False
        live_list = self._outlook_live_cache
        if live_list is None:
            return True  # ne blokiraj — uporabnik naj Osveži, če želi preveriti
        live = {a.casefold() for a in live_list}
        if not live:
            return False
        if addr.casefold() in live:
            return True
        if addr.casefold() == "info@quickmb.com" and "info@quickmb.si" in live:
            return True
        if addr.casefold() == "info@quickmb.si" and "info@quickmb.com" in live:
            return True
        return False

    def _update_from_hint(self) -> None:
        if not hasattr(self, "var_from_hint"):
            return
        wanted = (self.var_from.get() or "").strip()
        if not wanted:
            self.var_from_hint.set("")
            return
        channel = "smtp"
        if hasattr(self, "var_channel"):
            channel = str(self.var_channel.get() or "smtp").casefold()
        elif getattr(self, "_channel_init", "smtp") == "outlook":
            channel = "outlook"
        if channel == "smtp":
            self.var_from_hint.set("Reply-To (pošlje Gmail SMTP)")
            return
        if self._outlook_live_cache is None:
            self.var_from_hint.set("Outlook — klikni Osveži za preverbo")
            return
        if not self._outlook_live_cache:
            self.var_from_hint.set("(Outlook računov ni bilo mogoče prebrati)")
            return
        ok = self._from_account_in_outlook(wanted)
        self.var_from_hint.set("✓ v Outlooku" if ok else "✗ ni v Outlooku — Od: ne bo deloval")

    def _on_text_modified(self, _event: tk.Event | None = None) -> None:
        if getattr(self, "_loading_template", False):
            try:
                self.txt_html.edit_modified(False)
            except tk.TclError:
                pass
            return
        try:
            if self.txt_html.edit_modified():
                self.txt_html.edit_modified(False)
                self._mark_dirty()
        except tk.TclError:
            pass

    def _mark_dirty(self, *_args: Any) -> None:
        if getattr(self, "_loading_template", False):
            return
        self._dirty = True
        if hasattr(self, "var_save_status"):
            self.var_save_status.set("● neshranjeno — shranjujem…")
        if hasattr(self, "var_preview_subj"):
            self._refresh_subject_label()
        if hasattr(self, "txt_html"):
            self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        """Po tipkanju kmalu shrani belo telo na disk (brez premika kurzorja)."""
        if getattr(self, "_autosave_after", None):
            try:
                self.after_cancel(self._autosave_after)
            except (tk.TclError, ValueError):
                pass
            self._autosave_after = None
        self._autosave_after = self.after(700, self._autosave_now)

    def _autosave_now(self) -> None:
        self._autosave_after = None
        if getattr(self, "_loading_template", False):
            return
        if not self._dirty:
            return
        ok = self._save_template(quiet=True, reload_editor=False)
        if hasattr(self, "var_save_status"):
            if ok:
                self.var_save_status.set("✓ shranjeno na disk")
            else:
                self.var_save_status.set("✗ shranjevanje ni uspelo")

    def _refresh_template_combo(self, select_id: str = "") -> None:
        self._templates = email_tpl.load_templates()
        rows = email_tpl.list_templates()
        # Indeks → id (zanesljivo; ne zanašaj se samo na naslov).
        self._combo_ids: list[str] = []
        self._label_to_id: dict[str, str] = {}
        display_labels: list[str] = []
        seen: dict[str, int] = {}
        for r in rows:
            tid = str(r["id"])
            base = str(r.get("title") or tid).strip() or tid
            count = seen.get(base, 0)
            seen[base] = count + 1
            label = base if count == 0 else f"{base} [{tid}]"
            display_labels.append(label)
            self._combo_ids.append(tid)
            self._label_to_id[label] = tid
        self.cmb_template.configure(values=display_labels)
        tid = email_tpl.resolve_template_id(select_id or self._template_id)
        try:
            idx = self._combo_ids.index(tid)
        except ValueError:
            idx = 0 if self._combo_ids else -1
        if idx >= 0:
            self.cmb_template.current(idx)
            self.var_template.set(display_labels[idx])
            self._template_id = self._combo_ids[idx]
        elif display_labels:
            self.var_template.set(display_labels[0])
            self._template_id = self._combo_ids[0]

    def _selected_combo_template_id(self) -> str:
        """Id iz spustnega seznama — najprej .get() (zanesljivo na Windowsu)."""
        label = ""
        try:
            label = str(self.cmb_template.get() or "").strip()
        except tk.TclError:
            label = ""
        if not label:
            label = str(self.var_template.get() or "").strip()
        if label and label in self._label_to_id:
            return self._label_to_id[label]
        try:
            idx = int(self.cmb_template.current())
        except (TypeError, ValueError, tk.TclError):
            idx = -1
        if 0 <= idx < len(getattr(self, "_combo_ids", [])):
            return self._combo_ids[idx]
        # Delno ujemanje naslova
        for lbl, tid in self._label_to_id.items():
            if lbl == label or label in lbl or lbl in label:
                return tid
        return email_tpl.resolve_template_id(self._template_id)

    def _refresh_vzorec_info(self, tpl: dict[str, Any] | None = None, *, loaded: bool = False) -> None:
        if not hasattr(self, "var_vzorec_info"):
            return
        row = tpl or email_tpl.get_template(self._template_id)
        title = str(row.get("title") or self._template_id)
        prefix = "✓ NALOŽENO " if loaded else "Vzorec "
        self.var_vzorec_info.set(f"{prefix}«{title}»  ·  {email_tpl.template_summary_line(row)}")

    def _switch_to_template(self, tid: str, *, ask_save: bool = True, announce: bool = False) -> None:
        """Zamenjaj vzorec — NIKOLI tiho ne prepisuj drugega vzorca."""
        tid = email_tpl.resolve_template_id(tid)
        if not tid:
            return
        if ask_save and self._dirty and tid != self._template_id:
            answer = messagebox.askyesnocancel(
                "Vzorec",
                "Trenutni vzorec ima spremembe.\n\n"
                "Da = shrani trenutnega, nato odpri izbranega\n"
                "Ne = zavrzi spremembe in odpri izbranega\n"
                "Prekliči = ostani",
                parent=self,
            )
            if answer is None:
                self._refresh_template_combo(select_id=self._template_id)
                return
            if answer:
                if not self._save_template(quiet=True):
                    self._refresh_template_combo(select_id=self._template_id)
                    return
        self._load_template_into_editor(tid, force=True, announce=announce)

    def _load_selected_template(self) -> None:
        """Gumb Naloži — vedno naloži izbrano iz spustnega seznama."""
        tid = self._selected_combo_template_id()
        if not tid:
            messagebox.showwarning("Vzorec", "Izberi predlogo v spustnem seznamu.", parent=self)
            return
        self._switch_to_template(tid, ask_save=True, announce=True)

    def _on_template_selected(self, _event: Any = None) -> None:
        if getattr(self, "_loading_template", False):
            return
        tid = self._selected_combo_template_id()
        if not tid:
            return
        self._switch_to_template(tid, ask_save=True, announce=False)

    def _activate_template(self, tid: str) -> None:
        tid = email_tpl.set_active_template_id(tid)
        self._template_id = tid
        if self._on_template_id:
            try:
                self._on_template_id(tid)
            except Exception:
                pass

    def _set_from_smtp(self, address: str) -> None:
        addr = str(address or "").strip() or ddvo_virman.DEFAULT_OUTLOOK_FROM
        choices = list(self.cmb_from.cget("values") or ())
        if addr not in choices:
            if addr.casefold() == "info@quickmb.com" and "info@quickmb.si" in choices:
                addr = "info@quickmb.si"
            elif addr.casefold() == "info@quickmb.si" and "info@quickmb.com" in choices:
                addr = "info@quickmb.com"
            else:
                self.cmb_from.configure(values=[addr, *choices])
        self.var_from.set(addr)
        self._update_from_hint()

    def _apply_vzorec_fields(self, tpl: dict[str, Any]) -> None:
        """Naloži Od + razmike + potrdila iz vzorca (belo telo se naloži ločeno)."""
        self._set_from_smtp(str(tpl.get("from_smtp") or ddvo_virman.DEFAULT_OUTLOOK_FROM))
        lh = str(tpl.get("line_height") or "1.35").strip() or "1.35"
        try:
            px = int(tpl.get("para_spacing_px") or 4)
        except (TypeError, ValueError):
            px = 4
        if hasattr(self, "var_line_height"):
            self.var_line_height.set(lh)
        if hasattr(self, "var_para_spacing"):
            self.var_para_spacing.set(f"{max(0, min(48, px))} px")
        if hasattr(self, "txt_html"):
            self._apply_editor_spacing()
        if hasattr(self, "var_read_receipt"):
            if "read_receipt" in tpl:
                self.var_read_receipt.set(bool(tpl.get("read_receipt")))
            else:
                self.var_read_receipt.set(self._fallback_read_receipt)
        if hasattr(self, "var_delivery_receipt"):
            if "delivery_receipt" in tpl:
                self.var_delivery_receipt.set(bool(tpl.get("delivery_receipt")))
            else:
                self.var_delivery_receipt.set(self._fallback_delivery_receipt)
        if hasattr(self, "var_defer"):
            # Nikoli samodejno odloži iz starega configa — samo izrecna kljukica v vzorcu + Outlook.
            want_defer = bool(tpl.get("defer_send")) if "defer_send" in tpl else False
            if str(getattr(self, "var_channel", tk.StringVar(value="smtp")).get() or "").casefold() == "smtp":
                want_defer = False
            self.var_defer.set(want_defer)
            if want_defer and hasattr(self, "var_defer_at") and self._fallback_deferred_send.strip():
                if not str(self.var_defer_at.get() or "").strip():
                    self.var_defer_at.set(self._fallback_deferred_send)
            self._toggle_defer()
        self._refresh_vzorec_info(tpl)

    def _pattern_subject_body(self) -> tuple[str, str]:
        """Trenutno besedilo kot vzorec s {placeholders} (neodvisno od načina prikaza)."""
        if self._view_mode == "vzorec":
            subject = self.var_subject.get().strip()
            body = self._html().strip()
        else:
            subject = email_tpl.restore_placeholders(
                self.var_subject.get().strip(),
                self._placeholder_values,
            )
            body = email_tpl.restore_placeholders(
                self._html().strip(),
                self._placeholder_values,
            )
        # Varnost: še enkrat restore, če so ostanki zneskov.
        subject = email_tpl.restore_placeholders(subject, self._placeholder_values)
        body = email_tpl.restore_placeholders(body, self._placeholder_values)
        return subject, body

    def _update_mode_buttons(self) -> None:
        if not hasattr(self, "btn_mode_vzorec"):
            return
        if self._view_mode == "vzorec":
            self.btn_mode_vzorec.configure(bg=_BTN_BLUE)
            self.btn_mode_predogled.configure(bg=_BTN_GREY)
            if hasattr(self, "var_editor_hint"):
                self.var_editor_hint.set(
                    "Način VZOREC: v belem polju so {nagovor}, {referenca}, {iban}… — to se shrani kot predloga"
                )
        else:
            self.btn_mode_vzorec.configure(bg=_BTN_GREY)
            self.btn_mode_predogled.configure(bg=_BTN_GREEN)
            if hasattr(self, "var_editor_hint"):
                self.var_editor_hint.set(
                    "Način PREDOGLED: zapolnjeni podatki firme (samo za ogled) — pred shranjevanjem se vrnejo v {…}"
                )

    def _show_vzorec_mode(self) -> None:
        """Belo polje = shranljiv vzorec z {placeholders}."""
        if getattr(self, "_loading_template", False):
            return
        if self._view_mode == "vzorec":
            self._update_mode_buttons()
            self._refresh_subject_label()
            return
        subject, body = self._pattern_subject_body()
        self._source_subject = subject
        self._source_body = body
        self._view_mode = "vzorec"
        self._qr_photo = None
        self._loading_template = True
        try:
            self.var_subject.set(subject)
            load_html_into_editor(self.txt_html, body)
            self.txt_html.edit_modified(False)
        finally:
            self._loading_template = False
        self._update_mode_buttons()
        self._refresh_subject_label()
        self.txt_html.focus_set()

    def _embed_qr_preview_in_editor(self) -> None:
        """V predogledu zamenjaj [QR koda za plačilo] z dejansko PNG sliko."""
        import kirkpr_upn_qr as upn_qr

        if not hasattr(self, "txt_html"):
            return
        self._qr_photo = None
        png = str(self._placeholder_values.get("_qr_png") or "").strip()
        if not png or not Path(png).is_file():
            return
        marker = upn_qr.UPN_QR_MARKER
        try:
            start = self.txt_html.search(marker, "1.0", stopindex="end")
        except tk.TclError:
            start = ""
        if not start:
            return
        end = f"{start}+{len(marker)}c"
        try:
            from PIL import Image, ImageTk

            img = Image.open(png)
            # Predogled ~180 px (kot cid v e-pošti)
            resample = getattr(Image, "Resampling", Image).LANCZOS
            img.thumbnail((180, 180), resample)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            try:
                photo = tk.PhotoImage(file=png)
                # Če je prevelika — subsample
                w = int(photo.width())
                if w > 200:
                    factor = max(1, (w + 179) // 180)
                    photo = photo.subsample(factor, factor)
            except Exception:
                return
        self._qr_photo = photo
        try:
            self.txt_html.delete(start, end)
            self.txt_html.image_create(start, image=photo, padx=4, pady=6)
            self.txt_html.edit_modified(False)
        except tk.TclError:
            self._qr_photo = None

    def _show_predogled_mode(self) -> None:
        """Belo polje = predogled s trenutnimi podatki (KLUG, zneski…)."""
        if getattr(self, "_loading_template", False):
            return
        if not self._placeholder_values:
            messagebox.showinfo(
                "Predogled",
                "Ni podatkov firme/obdobja za predogled.\n"
                "Odpri e-pošto prek gumba E-pošta virman… z naloženim DDV-O.",
                parent=self,
            )
            return
        subject, body = self._pattern_subject_body()
        self._source_subject = subject
        self._source_body = body
        self._view_mode = "predogled"
        self._loading_template = True
        try:
            self.var_subject.set(email_tpl.render_placeholders(subject, self._placeholder_values))
            load_html_into_editor(
                self.txt_html,
                email_tpl.render_placeholders(body, self._placeholder_values),
            )
            self._embed_qr_preview_in_editor()
            self.txt_html.edit_modified(False)
        finally:
            self._loading_template = False
        self._update_mode_buttons()
        self._refresh_subject_label()
        self._refresh_qr_hint()
        self.txt_html.focus_set()

    def _load_template_into_editor(self, tid: str, *, force: bool = True, announce: bool = False) -> None:
        """Naloži vzorec z diska: Od + zadeva + besedilo z {placeholders} v belo polje."""
        tid = email_tpl.resolve_template_id(tid)
        tpl = email_tpl.get_template(tid)
        body_html = str(tpl.get("body") or "")
        subj_raw = str(tpl.get("subject") or "")
        if not body_html.strip():
            messagebox.showwarning(
                "Predloga",
                f"Predloga «{tpl.get('title') or tid}» nima besedila.",
                parent=self,
            )
            return
        self._activate_template(tid)
        self._source_subject = subj_raw
        self._source_body = body_html
        self._view_mode = "vzorec"
        self._loading_template = True
        try:
            self.var_title.set(str(tpl.get("title") or tid))
            self.var_subject.set(subj_raw)
            load_html_into_editor(self.txt_html, body_html)
            self._apply_vzorec_fields(tpl)
            self._refresh_vzorec_info(tpl, loaded=True)
            self._dirty = False
            try:
                self.txt_html.edit_modified(False)
            except tk.TclError:
                pass
            self._update_mode_buttons()
            self._refresh_subject_label()
            self._refresh_template_combo(select_id=tid)
            try:
                self.txt_html.see("1.0")
                self.txt_html.focus_set()
            except tk.TclError:
                pass
            shown = self.txt_html.get("1.0", "end-1c").strip()
            if force and body_html.strip() and not shown:
                messagebox.showerror(
                    "Predloga",
                    "Predloga je na disku, a belo polje ostaja prazno.",
                    parent=self,
                )
            elif announce:
                title = str(tpl.get("title") or tid)
                messagebox.showinfo(
                    "Vzorec naložen",
                    (
                        f"«{title}»\n\n"
                        f"Od: {tpl.get('from_smtp') or '—'}\n"
                        f"Zadeva (vzorec): {subj_raw}\n"
                        f"Začetek: {email_tpl.template_body_preview(tpl)}\n\n"
                        "V belem polju so {placeholders} (npr. {{referenca}}, {{iban}}).\n"
                        "Za številke firme: gumb »Predogled s podatki«."
                    ),
                    parent=self,
                )
        finally:
            self._loading_template = False

    def _open_template_picker(self) -> None:
        """Seznam shranjenih predlog — izberi in odpri."""
        rows = email_tpl.list_templates()
        if not rows:
            messagebox.showinfo("Predloga", "Ni shranjenih predlog.", parent=self)
            return
        win = tk.Toplevel(self)
        win.title("Odpri predlogo")
        win.transient(self)
        win.grab_set()
        win.configure(bg=self._bg)
        win.geometry("520x400")
        tk.Label(
            win,
            text="Shranjene predloge — dvoklik ali Odpri",
            bg=self._bg,
            fg=self._text_fg,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 6))
        fr = tk.Frame(win, bg=self._panel)
        fr.pack(fill="both", expand=True, padx=12, pady=4)
        lb = tk.Listbox(
            fr,
            font=("Segoe UI", 10),
            bg="#ffffff",
            fg="#111111",
            selectmode="browse",
            activestyle="dotbox",
        )
        sb = ttk.Scrollbar(fr, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        id_by_index: list[str] = []
        active = email_tpl.get_active_template_id()
        select_idx = 0
        for i, r in enumerate(rows):
            tid = str(r["id"])
            title = str(r.get("title") or tid)
            mark = "★ " if tid == active else "   "
            builtin = " (privzeto)" if tid == email_tpl.DEFAULT_TEMPLATE_ID else ""
            lb.insert("end", f"{mark}{title}{builtin}")
            lb.insert("end", f"      {email_tpl.template_summary_line(r)}")
            id_by_index.append(tid)
            id_by_index.append(tid)
            if tid == self._template_id or tid == active:
                select_idx = len(id_by_index) - 2
        if id_by_index:
            lb.selection_set(select_idx)
            lb.see(select_idx)

        def _do_open(_event: Any = None) -> None:
            sel = lb.curselection()
            if not sel:
                return
            tid = id_by_index[int(sel[0])]
            win.destroy()
            self.after(10, lambda t=tid: self._switch_to_template(t, ask_save=True, announce=True))

        lb.bind("<Double-Button-1>", _do_open)
        btns = tk.Frame(win, bg=self._bg)
        btns.pack(fill="x", padx=12, pady=10)
        PillButton(btns, "Odpri", command=_do_open, bg=_BTN_GREEN, hover="#3cb87a").pack(side="right")
        PillButton(btns, "Prekliči", command=win.destroy, bg=_BTN_GREY, hover="#4a5a7a").pack(
            side="right", padx=(0, 8)
        )

    def _rename_template(self) -> None:
        current = self.var_title.get().strip() or self.var_template.get().strip()
        new_name = simpledialog.askstring(
            "Preimenuj predlogo",
            "Novo ime predloge:",
            initialvalue=current,
            parent=self,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Predloga", "Ime ne sme biti prazno.", parent=self)
            return
        try:
            tid = email_tpl.rename_template(self._template_id, new_name)
        except ValueError as exc:
            messagebox.showerror("Predloga", str(exc), parent=self)
            return
        self._activate_template(tid)
        self.var_title.set(new_name)
        self._refresh_template_combo(select_id=tid)
        messagebox.showinfo("Predloga", f"Predloga preimenovana v «{new_name}».", parent=self)

    def _copy_template(self) -> None:
        current = self.var_title.get().strip() or self.var_template.get().strip()
        new_name = simpledialog.askstring(
            "Kopiraj predlogo",
            "Ime kopije:",
            initialvalue=f"{current} (kopija)",
            parent=self,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Predloga", "Ime ne sme biti prazno.", parent=self)
            return
        # Kopiraj trenutni vzorec (z {placeholders}).
        subject, body = self._pattern_subject_body()
        lh, px = self._spacing_values()
        try:
            tid = email_tpl.copy_template(
                self._template_id,
                new_title=new_name,
                subject=subject or None,
                body=body or None,
                from_smtp=self.var_from.get().strip() or ddvo_virman.DEFAULT_OUTLOOK_FROM,
                line_height=lh,
                para_spacing_px=px,
            )
        except ValueError as exc:
            messagebox.showerror("Predloga", str(exc), parent=self)
            return
        self._load_template_into_editor(tid, force=True, announce=True)
        messagebox.showinfo(
            "Predloga",
            f"Kopija «{new_name}» je ustvarjena in odprta.\n"
            f"{email_tpl.template_summary_line(email_tpl.get_template(tid))}",
            parent=self,
        )

    def _delete_template(self) -> None:
        tid = self._template_id
        title = self.var_title.get().strip() or tid
        if tid == email_tpl.DEFAULT_TEMPLATE_ID:
            if not messagebox.askyesno(
                "Briši / obnovi",
                f"«{title}» je vgrajena predloga — ne morem je izbrisati.\n\n"
                "Obnovim privzeti vzorec s {placeholders}?",
                parent=self,
            ):
                return
            self._restore_default_template(confirm=False)
            return
        if not messagebox.askyesno(
            "Briši predlogo",
            f"Res zbrišem predlogo «{title}»?\nTega ni mogoče razveljaviti.",
            parent=self,
        ):
            return
        try:
            next_id = email_tpl.delete_template(tid)
        except ValueError as exc:
            messagebox.showerror("Predloga", str(exc), parent=self)
            return
        self._refresh_template_combo(select_id=next_id)
        self._load_template_into_editor(next_id)
        messagebox.showinfo("Predloga", f"Predloga «{title}» je izbrisana.", parent=self)

    def _restore_default_template(self, *, confirm: bool = True) -> None:
        if confirm and not messagebox.askyesno(
            "Obnovi privzeti vzorec",
            "Obnovim vgrajeni vzorec s {placeholders}?\n"
            "(Trenutna shranjena predloga bo prepisana.)",
            parent=self,
        ):
            return
        dflt = email_tpl.default_templates()[email_tpl.DEFAULT_TEMPLATE_ID]
        tid = email_tpl.save_template(
            email_tpl.DEFAULT_TEMPLATE_ID,
            title=str(dflt.get("title") or "DDV + virman"),
            subject=str(dflt.get("subject") or ""),
            body=str(dflt.get("body") or ""),
        )
        self._refresh_template_combo(select_id=tid)
        self._load_template_into_editor(tid)
        messagebox.showinfo("Predloga", "Privzeti vzorec je obnovljen.", parent=self)

    def _html(self) -> str:
        return richtext_to_html(self.txt_html)

    def _set_html(self, body: str) -> None:
        load_html_into_editor(self.txt_html, body)

    def _selection_range(self) -> tuple[str, str] | None:
        try:
            return self.txt_html.index("sel.first"), self.txt_html.index("sel.last")
        except tk.TclError:
            return None

    def _toggle_tag(self, tag: str) -> None:
        self.txt_html.focus_set()
        sel = self._selection_range()
        if not sel:
            messagebox.showinfo("Oblikovanje", "Najprej označi besedilo v belem polju.", parent=self)
            return
        start, end = sel
        _ensure_editor_tags(self.txt_html)
        # Če je tag že na začetku izbora → odstrani, sicer dodaj.
        if tag in self.txt_html.tag_names(start):
            self.txt_html.tag_remove(tag, start, end)
        else:
            self.txt_html.tag_add(tag, start, end)
        self._dirty = True

    def _wrap_bold(self) -> None:
        self._toggle_tag("b")

    def _wrap_italic(self) -> None:
        self._toggle_tag("i")

    def _wrap_underline(self) -> None:
        self._toggle_tag("u")

    def _wrap_strike(self) -> None:
        self._toggle_tag("s")

    def _wrap_paragraph(self) -> None:
        """Nova vrstica pred/za izborom (odstavek)."""
        self.txt_html.focus_set()
        sel = self._selection_range()
        if sel:
            start, end = sel
            self.txt_html.insert(end, "\n")
            self.txt_html.insert(start, "\n")
        else:
            self.txt_html.insert("insert", "\n")
        self._dirty = True

    def _spacing_values(self) -> tuple[str, int]:
        lh = (self.var_line_height.get() or "1.35").strip() or "1.35"
        raw = (self.var_para_spacing.get() or "4").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        try:
            px = int(digits or "4")
        except ValueError:
            px = 4
        return lh, max(0, min(48, px))

    def _apply_editor_spacing(self) -> None:
        """Vizuaini razmik v belem polju (Outlook dobi enako ob pošiljanju)."""
        lh, px = self._spacing_values()
        try:
            factor = float(lh.replace(",", "."))
        except ValueError:
            factor = 1.35
        # Tk spacing3 ≈ razmik med odstavki; spacing2 ≈ med vrsticami.
        self.txt_html.configure(
            spacing1=0,
            spacing2=max(0, int(round((factor - 1.0) * 8))),
            spacing3=max(0, px),
        )

    def _apply_spacing(self) -> None:
        self._apply_editor_spacing()
        self._dirty = True

    def _apply_tighten(self) -> None:
        self.var_line_height.set("1.35")
        self.var_para_spacing.set("4 px")
        self._apply_spacing()

    def _insert_signature(self) -> None:
        text = self.txt_html.get("1.0", "end-1c")
        if "Braco MIHELJ" in text and "info@quickmb.com" in text:
            messagebox.showinfo("Podpis", "Podpis je že v besedilu.", parent=self)
            return
        block = (
            "\n\n"
            "Lep pozdrav,\n"
            "Braco MIHELJ\n"
            "tel.: 041.653.170\n"
            "eMail:\n"
            "braco.mihelj@gmail.com\n"
            "bracom@windowslive.com\n"
            "info@quickmb.com"
        )
        self.txt_html.focus_set()
        start = self.txt_html.index("end-1c")
        self.txt_html.insert("end", block)
        # Krepko ime
        try:
            idx = self.txt_html.search("Braco MIHELJ", start, "end")
            if idx:
                self.txt_html.tag_add("b", idx, f"{idx}+12c")
        except tk.TclError:
            pass
        self._dirty = True

    def _wrap_color(self) -> None:
        self.txt_html.focus_set()
        sel = self._selection_range()
        if not sel:
            messagebox.showinfo("Barva", "Najprej označi besedilo v belem polju, nato Obarvaj.", parent=self)
            return
        start, end = sel
        name = self.var_color.get()
        hex_c = next((h for n, h in HTML_COLORS if n == name), "#1565C0")
        for t in list(self.txt_html.tag_names()):
            if str(t).startswith("c_"):
                self.txt_html.tag_remove(t, start, end)
        tag = f"c_{hex_c}"
        self.txt_html.tag_configure(tag, foreground=hex_c)
        self.txt_html.tag_add(tag, start, end)
        self._dirty = True

    def _wrap_font(self) -> None:
        self.txt_html.focus_set()
        sel = self._selection_range()
        if not sel:
            messagebox.showinfo("Pisava", "Najprej označi besedilo v belem polju.", parent=self)
            return
        start, end = sel
        font_name = self.var_font.get()
        size_name = self.var_size.get()
        size = next((s for n, s in HTML_SIZES if n == size_name), "11pt")
        try:
            size_n = int(float(str(size).replace("pt", "").strip()))
        except ValueError:
            size_n = 11
        fam = font_name.split(",")[0].strip()
        for t in list(self.txt_html.tag_names()):
            if str(t).startswith("f_"):
                self.txt_html.tag_remove(t, start, end)
        tag = f"f_{fam}_{size_n}"
        self.txt_html.tag_configure(tag, font=(fam, size_n))
        self.txt_html.tag_add(tag, start, end)
        self._dirty = True

    def _insert_br(self) -> None:
        self.txt_html.focus_set()
        self.txt_html.insert("insert", "\n")
        self._dirty = True

    def _insert_blank_line(self) -> None:
        self.txt_html.focus_set()
        self.txt_html.insert("insert", "\n\n")
        self._dirty = True

    def _on_vracilo_toggle(self) -> None:
        """Osveži {presezek_obvestilo} ob kljukici vračilo (kot Oddaje 1.0.65)."""
        excess_raw = self._placeholder_values.get("_excess") or self._placeholder_values.get("presezek") or "0"
        try:
            notice = ddvo_virman.format_presezek_obvestilo(excess_raw, bool(self.var_vracilo.get()))
        except Exception:
            notice = ""
        self._placeholder_values["presezek_obvestilo"] = notice
        self._placeholder_values["vracilo"] = "Da" if self.var_vracilo.get() else "Ne"
        self._placeholder_values["_vracilo"] = "1" if self.var_vracilo.get() else "0"
        # Osveži predogled, če je aktiven.
        if self._view_mode == "predogled":
            subject, body = self._pattern_subject_body()
            self._reload_editor_with_placeholders(subject, body, show_predogled=True)
        else:
            self._refresh_subject_label()
        if hasattr(self, "var_save_status"):
            self.var_save_status.set(
                "✓ vračilo DA — {presezek_obvestilo} osveženo"
                if self.var_vracilo.get()
                else "✓ vračilo NE — {presezek_obvestilo} osveženo"
            )

    def _insert_var(self, key: str) -> None:
        self.txt_html.focus_set()
        self.txt_html.insert("insert", key)
        self._dirty = True

    def _edit_placeholder_texts(self) -> None:
        """Uredi vzorce za samodejne {placeholders} (konto 62 …)."""
        import kirkpr_ddvo_placeholder_texts as placeholder_texts

        # Shrani vzorec PRED spremembo vrednosti (restore potrebuje stare tekste).
        pattern_subject, pattern_body = self._pattern_subject_body()
        self._source_subject = pattern_subject
        self._source_body = pattern_body

        def _set_notice(texts: dict[str, str] | None = None) -> None:
            try:
                raw = self._placeholder_values.get("preplacilo") or "0"
                if texts is not None:
                    notice = placeholder_texts.format_konto62_notice_from_texts(
                        raw,
                        html=True,
                        texts=texts,
                    )
                else:
                    import kirkpr_ddvo_virman as ddvo_virman

                    notice = ddvo_virman.format_konto62_client_notice(raw, html=True)
            except Exception:
                notice = ""
            self._placeholder_values["konto62_obvestilo"] = notice

        saved = placeholder_texts.open_placeholder_texts_form(
            self,
            on_change=_set_notice,
        )
        if saved is not None:
            _set_notice(saved)
        else:
            _set_notice(None)
        self._reload_editor_with_placeholders(
            pattern_subject,
            pattern_body,
            show_predogled=True,
        )
        if hasattr(self, "var_save_status"):
            self.var_save_status.set(
                "✓ besedila {…} osvežena" if saved is not None else "besedila {…} — preklicano"
            )

    def _reload_editor_with_placeholders(
        self,
        subject_pattern: str,
        body_pattern: str,
        *,
        show_predogled: bool = True,
    ) -> None:
        """Takoj prepiše belo polje (vzorec ali predogled s podatki)."""
        if getattr(self, "_loading_template", False):
            return
        self._source_subject = subject_pattern
        self._source_body = body_pattern
        self._loading_template = True
        try:
            if show_predogled and self._placeholder_values:
                self._view_mode = "predogled"
                self.var_subject.set(
                    email_tpl.render_placeholders(subject_pattern, self._placeholder_values)
                )
                load_html_into_editor(
                    self.txt_html,
                    email_tpl.render_placeholders(body_pattern, self._placeholder_values),
                )
                self._embed_qr_preview_in_editor()
            else:
                self._view_mode = "vzorec"
                self._qr_photo = None
                self.var_subject.set(subject_pattern)
                load_html_into_editor(self.txt_html, body_pattern)
            self.txt_html.edit_modified(False)
        finally:
            self._loading_template = False
        self._update_mode_buttons()
        self._refresh_subject_label()
        try:
            self.txt_html.update_idletasks()
        except tk.TclError:
            pass

    def _rendered(self) -> tuple[str, str]:
        """Zadeva + telo za Outlook (vedno zapolnjeno s podatki)."""
        subject, body = self._pattern_subject_body()
        values = self._placeholder_values
        return (
            email_tpl.render_placeholders(subject, values),
            email_tpl.render_placeholders(body, values),
        )

    def _refresh_subject_label(self) -> None:
        if not hasattr(self, "var_preview_subj"):
            return
        pattern_subj, _ = self._pattern_subject_body() if hasattr(self, "txt_html") else (
            self._source_subject,
            "",
        )
        rendered = email_tpl.render_placeholders(pattern_subj, self._placeholder_values)
        if self._view_mode == "vzorec":
            self.var_preview_subj.set(
                f"VZOREC  ·  zadeva: {pattern_subj or '—'}  ·  s podatki bi bilo: {rendered or '—'}"
            )
        else:
            self.var_preview_subj.set(f"PREDOGLED  ·  Zadeva: {rendered or '—'}")
        self._update_mode_buttons()

    def _update_preview(self) -> None:
        self._refresh_subject_label()

    def _save_template(self, *, quiet: bool = False, reload_editor: bool = False) -> bool:
        """Shrani VSE iz urejevalnika: belo telo + Od + zadeva + razmiki + potrdila.

        Belo telo je vir resnice (ne glede na zgornjo Konfiguracijo).
        reload_editor=False: kurzor/vsebina ostaneta (privzeto).
        """
        title = self.var_title.get().strip() or self._template_id
        subject, body = self._pattern_subject_body()
        if not subject or not body:
            messagebox.showwarning(
                "Predloga",
                "Zadeva in besedilo ne smeta biti prazna — ni shranjeno.",
                parent=self,
            )
            return False
        if "{" not in body and self._placeholder_values:
            if not quiet and not messagebox.askyesno(
                "Vzorec",
                "V besedilu ni {placeholders} (npr. {nagovor}, {placilo}).\n"
                "Res shrani tako (brez vzorca za druge firme)?",
                parent=self,
            ):
                return False
        lh, px = self._spacing_values()
        from_smtp = self.var_from.get().strip() or ddvo_virman.DEFAULT_OUTLOOK_FROM
        read_r = bool(self.var_read_receipt.get())
        deliv_r = bool(self.var_delivery_receipt.get())
        defer_s = bool(self.var_defer.get())
        # Med shranjevanjem combo ne sme prepisati belega polja.
        self._loading_template = True
        try:
            try:
                tid = email_tpl.save_template(
                    self._template_id or email_tpl.DEFAULT_TEMPLATE_ID,
                    title=title,
                    subject=subject,
                    body=body,
                    from_smtp=from_smtp,
                    line_height=lh,
                    para_spacing_px=px,
                    read_receipt=read_r,
                    delivery_receipt=deliv_r,
                    defer_send=defer_s,
                )
            except OSError as exc:
                messagebox.showerror(
                    "Predloga — shranjevanje",
                    f"Belo telo / nastavitve NISO shranjene.\n\n{exc}\n\n"
                    f"Datoteka: {email_tpl.templates_path()}",
                    parent=self,
                )
                return False
            # Preset = zrcalo trenutnega urejevalnika (ne obratno).
            try:
                self._preset_id = email_presets.save_preset(
                    self._preset_id,
                    name=self._preset_display_name(),
                    **self._current_preset_payload(),
                )
                email_presets.set_active_preset_id(self._preset_id)
            except OSError:
                pass
            self._activate_template(tid)
            self._source_subject = subject
            self._source_body = body
            self._refresh_template_combo(select_id=tid)
            check = email_tpl.get_template(tid)
            self._refresh_vzorec_info(check, loaded=True)
            if reload_editor:
                self._view_mode = "vzorec"
                self.var_subject.set(subject)
                load_html_into_editor(self.txt_html, body)
                try:
                    self.txt_html.edit_modified(False)
                except tk.TclError:
                    pass
            self._dirty = False
            self._persist_geometry()
            self._update_mode_buttons()
            self._refresh_subject_label()
            self._notify_settings_saved(template_id=tid, from_smtp=from_smtp, lh=lh, px=px)
            if hasattr(self, "var_save_status"):
                self.var_save_status.set(f"✓ shranjeno ({len(body)} znakov HTML)")
            # Potrdi, da je belo telo na disku enako.
            disk_body = str(check.get("body") or "")
            if email_tpl.normalize_email_html(disk_body) != email_tpl.normalize_email_html(body):
                messagebox.showerror(
                    "Shrani",
                    "Preverjanje: belo telo na disku se ne ujema z urejevalnikom.",
                    parent=self,
                )
                return False
        finally:
            self._loading_template = False
        if not quiet:
            messagebox.showinfo(
                "Shranjeno",
                f"«{title}»\n"
                f"Od: {from_smtp}\n"
                f"Zadeva: {subject}\n"
                f"Belo telo: {len(body)} znakov\n"
                f"Razmik: {lh} / {px}px\n\n"
                f"{email_tpl.templates_path()}",
                parent=self,
            )
        return True

    def _save_email_configuration(self) -> None:
        """En klik: belo telo + vsi parametri → disk (vzorec + preset + config)."""
        if not self._save_template(quiet=False, reload_editor=False):
            return
        self._refresh_config_label()
        try:
            self._rebuild_config_menu()
        except (tk.TclError, AttributeError):
            pass

    def _save_as_new(self) -> None:
        suggested = (self.var_title.get().strip() or "DDV virman") + " (nova)"
        title = simpledialog.askstring(
            "Shrani kot novo",
            "Ime nove predloge:",
            initialvalue=suggested,
            parent=self,
        )
        if title is None:
            return
        title = title.strip() or "DDV virman"
        subject, body = self._pattern_subject_body()
        if not subject or not body:
            messagebox.showwarning("Predloga", "Zadeva in besedilo ne smeta biti prazna.", parent=self)
            return
        lh, px = self._spacing_values()
        tid = email_tpl.add_template(
            title=title,
            subject=subject,
            body=body,
            from_smtp=self.var_from.get().strip() or ddvo_virman.DEFAULT_OUTLOOK_FROM,
            line_height=lh,
            para_spacing_px=px,
        )
        self._activate_template(tid)
        self._source_subject = subject
        self._source_body = body
        self.var_title.set(title)
        self._refresh_template_combo(select_id=tid)
        self._refresh_vzorec_info(email_tpl.get_template(tid))
        self._dirty = False
        # Shrani tudi trenutno Od/razmike k aktivni konfiguraciji
        payload = self._current_preset_payload()
        try:
            email_presets.save_preset(
                self._preset_id,
                name=self._preset_display_name(),
                **payload,
            )
            email_presets.set_active_preset_id(self._preset_id)
        except OSError:
            pass
        self._persist_geometry()
        self._update_preview()
        messagebox.showinfo(
            "Konfiguracija",
            f"Nova predloga «{title}» je shranjena.\n{email_tpl.templates_path()}",
            parent=self,
        )

    def _accept_test(self) -> None:
        """TEST kot Oddaje: samo info@quickmb.com, zadeva [TEST], brez KP/SKP."""
        channel = str(self.var_channel.get() or "smtp").strip().casefold()
        if channel not in ("smtp", "outlook"):
            channel = "smtp"
        chan_label = "SMTP" if channel == "smtp" else "Outlook"
        ok = messagebox.askyesno(
            "TEST e-pošta",
            f"TEST ({chan_label}): poslati SAMO na info@quickmb.com?\n\n"
            "• zadeva = [TEST] …\n"
            "• brez stranke, brez KP/CC in SKP/BCC\n"
            "• enaka oblika in priponke kot v belem polju\n\n"
            "Da = pošlji TEST\nNe = ostani v urejevalniku",
            parent=self,
        )
        if not ok:
            return
        self._finish_send(test=True)

    def _accept(self) -> None:
        """Pošlji stranki: shrani vzorec, nato Outlook ali SMTP."""
        self._finish_send(test=False)

    def _finish_send(self, *, test: bool = False) -> None:
        """Sestavi rezultat pošiljanja (test=True → samo info@, [TEST])."""
        # Vedno zahtevaj potrdilo o prejemu (dostava) — uporabnik želi biti obveščen.
        self.var_delivery_receipt.set(True)
        to_addr = ddvo_virman.normalize_outlook_recipients(self.var_to.get())
        self.var_to.set(to_addr)
        cc_addr = ddvo_virman.normalize_outlook_recipients(self.var_cc.get())
        self.var_cc.set(cc_addr)
        bcc_addr = ddvo_virman.normalize_outlook_recipients(self.var_bcc.get())
        self.var_bcc.set(bcc_addr)
        from_smtp = self.var_from.get().strip() or ddvo_virman.DEFAULT_OUTLOOK_FROM
        channel = str(self.var_channel.get() or "smtp").strip().casefold()
        if channel not in ("smtp", "outlook"):
            channel = "smtp"
        if (
            not test
            and channel == "outlook"
            and self._outlook_live_cache is not None
            and not self._from_account_in_outlook(from_smtp)
        ):
            live = self._outlook_live_cache or []
            avail = "\n".join(f"• {a}" for a in live) if live else "• (ni računov — Osveži)"
            cont = messagebox.askyesno(
                "Od (račun)",
                f"Račun «{from_smtp}» ni med Outlook računi.\n\n"
                f"Razpoložljivi:\n{avail}\n\n"
                "Da = vseeno odpri Outlook (Od: bo verjetno napačen)\n"
                "Ne = ostani tukaj in izberi pravi račun",
                parent=self,
            )
            if not cont:
                return
        if channel == "smtp":
            try:
                import kirkpr_ddvo_smtp as ddvo_smtp

                path = ddvo_smtp.smtp_secret_path()
                ok_smtp, info = (True, str(path)) if path else (False, "Ni smtp_secret.bin")
            except Exception as exc:
                ok_smtp, info = False, str(exc)
            if not ok_smtp:
                messagebox.showerror(
                    "SMTP",
                    f"SMTP ni pripravljen:\n{info}\n\n"
                    "Ustvari smtp_secret.bin (Gmail App Password) v Minimax_forward\\server.",
                    parent=self,
                )
                return
        if not test and not to_addr.strip():
            messagebox.showwarning("E-pošta", "Manjka prejemnik (Za).", parent=self)
            return
        # Shrani vzorec (placeholders) na disk.
        if not self._save_template(quiet=True):
            return
        try:
            payload = self._current_preset_payload()
            email_presets.save_preset(
                self._preset_id,
                name=self._preset_display_name(),
                **payload,
            )
            email_presets.set_active_preset_id(self._preset_id)
        except OSError:
            pass
        lh, px = self._spacing_values()
        # Pošiljanje = TOČNO belo polje (ne znova iz predloge — sicer druga oblika!).
        if self._view_mode == "predogled":
            subject = self.var_subject.get().strip()
            body = self._html().strip()
        else:
            subject = email_tpl.render_placeholders(
                self.var_subject.get().strip(), self._placeholder_values
            )
            body = email_tpl.render_placeholders(
                self._html().strip(), self._placeholder_values
            )
        # Če je še kaj {placeholder}, zapolni (npr. vzorec).
        if self._placeholder_values:
            if "{" in subject:
                subject = email_tpl.render_placeholders(subject, self._placeholder_values)
            if "{" in body:
                body = email_tpl.render_placeholders(body, self._placeholder_values)
        if not subject.strip() or not body.strip():
            messagebox.showwarning("E-pošta", "Zadeva in telo ne smeta biti prazna.", parent=self)
            return
        defer_at = ""
        if (not test) and channel == "outlook" and self.var_defer.get():
            try:
                dt = ddvo_virman.parse_deferred_send_si(self.var_defer_at.get())
            except ValueError as exc:
                messagebox.showwarning("Odloženo pošiljanje", str(exc), parent=self)
                return
            if dt is None:
                messagebox.showwarning(
                    "Odloženo pošiljanje",
                    "Vnesi datum/čas (dd.mm.llll UU:MM).",
                    parent=self,
                )
                return
            if dt <= datetime.now():
                messagebox.showwarning(
                    "Odloženo pošiljanje",
                    "Čas odložitve mora biti v prihodnosti.",
                    parent=self,
                )
                return
            defer_at = dt.strftime("%d.%m.%Y %H:%M")
            cont_defer = messagebox.askyesno(
                "Odloženo pošiljanje",
                f"Outlook bo sporočilo držal v Outbox do {defer_at}.\n"
                "Do takrat NI poslano.\n\n"
                "Da = odloži\nNe = ostani v urejevalniku",
                parent=self,
            )
            if not cont_defer:
                return
        import kirkpr_upn_qr as upn_qr

        qr_png = str(self._placeholder_values.get("_qr_png") or "").strip()
        if qr_png and not Path(qr_png).is_file():
            qr_png = ""
        if upn_qr.UPN_QR_MARKER in body and not qr_png:
            messagebox.showwarning(
                "UPN QR",
                "V telesu je [QR koda za plačilo], a PNG datoteka manjka.\n"
                "Zapri urejevalnik in znova odpri e-pošto (preračun QR),\n"
                "ali pošlji brez QR (marker ostane kot besedilo).",
                parent=self,
            )
        if test:
            to_addr = "info@quickmb.com"
            cc_addr = ""
            bcc_addr = ""
            defer_at = ""
            if not subject.casefold().startswith("[test]"):
                subject = f"[TEST] {subject}"
        self._persist_geometry()
        self._result = {
            "to": to_addr,
            "cc": cc_addr,
            "bcc": bcc_addr,
            "subject": subject,
            "body": body,
            "html": "1",
            "template_id": self._template_id,
            "from_smtp": from_smtp,
            "channel": channel,
            "deferred_send": defer_at,
            "read_receipt": "1" if self.var_read_receipt.get() else "0",
            "delivery_receipt": "1" if self.var_delivery_receipt.get() else "0",
            "attach_pdf": "1" if self.var_attach_pdf.get() and self._attach_pdf_path else "0",
            "attach_virman": "1" if self.var_attach_virman.get() and self._attach_virman_path else "0",
            "line_height": lh,
            "para_spacing_px": str(px),
            "saved": "1",
            "vracilo": "1" if getattr(self, "var_vracilo", None) and self.var_vracilo.get() else "0",
            "test": "1" if test else "0",
        }
        if qr_png:
            self._result["_qr_png"] = qr_png
        if self._on_result:
            self._on_result(self._result)
        self.destroy()

    def _cancel(self) -> None:
        self._persist_geometry()
        if self._dirty:
            answer = messagebox.askyesnocancel(
                "Neshranjene spremembe",
                "Predloga ima spremembe.\n\n"
                "Da = shrani predlogo\n"
                "Ne = zapri brez shranjevanja\n"
                "Prekliči = ostani v urejevalniku",
                parent=self,
            )
            if answer is None:
                return
            if answer and not self._save_template(quiet=True):
                return
        self._result = None
        if self._on_result:
            self._on_result(None)
        self.destroy()

    def result(self) -> dict[str, str] | None:
        return self._result


def open_ddvo_email_editor(
    parent: tk.Misc,
    **kwargs: Any,
) -> dict[str, str] | None:
    """Modalni HTML urejevalnik; vrne {to, subject, body, html} ali None."""
    holder: dict[str, Any] = {"value": None}

    def _capture(value: dict[str, str] | None) -> None:
        holder["value"] = value

    dialog = DdvoEmailEditorDialog(parent, on_result=_capture, **kwargs)
    parent.wait_window(dialog)
    return holder["value"]


__all__ = ["DdvoEmailEditorDialog", "open_ddvo_email_editor"]
