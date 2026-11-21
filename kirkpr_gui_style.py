"""Skupni videz za KIR/KPR → Minimax Studio (Cursor).

Privzeto: svetla preobleka po zgledu Trops Studio 5 (barve iz ui/app.css).
Klasični temni videz (Transkript) ostane na voljo kot tema "classic".
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable

# --- Trops Studio 5.1.00 (svetla tema, :root v ui/app.css) ---
TROPS_COLORS: dict[str, str] = {
    "bg": "#f3f5f9",
    "panel": "#ffffff",
    "panel_alt": "#0f172a",
    "card": "#ffffff",
    "header": "#1e293b",
    "accent": "#4f46e5",
    "accent_2": "#6366f1",
    "accent_soft": "#eef2ff",
    "accent_text": "#3730a3",
    "purple": "#6366f1",
    "success": "#059669",
    "warning": "#b45309",
    "danger": "#dc2626",
    "text": "#0f172a",
    "muted": "#64748b",
    "input": "#ffffff",
    "line": "#e2e8f0",
    "header_fg": "#ffffff",
    "header_muted": "#cbd5e1",
    "surface_2": "#f8fafc",
    "surface_3": "#eef2f7",
    "side": "#0f172a",
    "side_2": "#1e293b",
    "side_text": "#cbd5e1",
    "side_muted": "#64748b",
    "heading_bg": "#eef2f7",
    "on_success": "#ffffff",
    "on_warning": "#ffffff",
    "on_danger": "#ffffff",
    "status_idle": "#eef2f7",
    "chip_bg": "#eef2ff",
    "chip_fg": "#475569",
    "chip_value": "#3730a3",
}

TROPS_TOKENS: dict[str, str] = {
    "HEADER_PURPLE": "#0f172a",
    "HEADER_PURPLE_SOFT": "#1e293b",
    "BTN_BLUE": "#4f46e5",
    "BTN_BLUE_HOVER": "#6366f1",
    "BTN_PURPLE": "#6366f1",
    "BTN_YELLOW": "#d97706",
    "BTN_GREEN": "#059669",
    "BTN_GREEN_HOVER": "#10b981",
    "BTN_RED": "#dc2626",
    "BTN_RED_HOVER": "#ef4444",
    "BTN_GREY": "#1e293b",
    "BTN_GREY_HOVER": "#334155",
    "YELLOW_FG": "#1a1400",
    "YELLOW_HOVER": "#f59e0b",
}

TROPS_METRICS: dict[str, Any] = {
    "rowheight": 34,
    "ui_font": 10,
    "muted_font": 9,
    "title_font": 16,
    "tab_padding": (18, 9),
    "btn_padding": (12, 7),
    "entry_padding": 7,
}

TROPS_TREE_TAGS: dict[str, dict[str, str]] = {
    "odd": {"background": "#f8fafc"},
    "tax_only": {"background": "#fffbeb", "foreground": "#b45309"},
    "self_assessment": {"background": "#eef2ff", "foreground": "#3730a3"},
    "vat_not_deducted": {"background": "#fff7ed", "foreground": "#b45309"},
    "section_start": {"background": "#eef2ff", "foreground": "#0f172a"},
    "result": {"background": "#fffbeb", "foreground": "#b45309"},
    "diff_row": {"background": "#fef2f2", "foreground": "#dc2626"},
    "api_ready": {"background": "#f0f9ff", "foreground": "#0369a1"},
    "api_ok": {"background": "#ecfdf5", "foreground": "#059669"},
    "api_error": {"background": "#fef2f2", "foreground": "#dc2626"},
    "api_sent": {"background": "#ecfdf5", "foreground": "#047857"},
    "api_missing": {"background": "#fffbeb", "foreground": "#b45309"},
    "api_exists": {"background": "#f0f9ff", "foreground": "#0369a1"},
    "match_ok": {"background": "#ecfdf5", "foreground": "#059669"},
    "match_api_only": {"background": "#fffbeb", "foreground": "#b45309"},
    "match_local_only": {"background": "#fef2f2", "foreground": "#dc2626"},
    "totals": {"background": "#eef2ff", "foreground": "#3730a3"},
    "changed": {"background": "#fffbeb", "foreground": "#b45309"},
}

# --- Klasični temni videz (pred preobleko, Transkript Studio) ---
CLASSIC_COLORS: dict[str, str] = {
    "bg": "#0b1220",
    "panel": "#101a2f",
    "panel_alt": "#5b3fd4",
    "card": "#17243d",
    "header": "#2a3560",
    "accent": "#2f6fed",
    "accent_2": "#4f8cff",
    "accent_soft": "#2a3560",
    "accent_text": "#d7d0ff",
    "purple": "#6b4cff",
    "success": "#2f9e6b",
    "warning": "#e6b84d",
    "danger": "#c44b55",
    "text": "#f3f6ff",
    "muted": "#b8c0d8",
    "input": "#0d172a",
    "line": "#2a3b60",
    "header_fg": "#ffffff",
    "header_muted": "#d7d0ff",
    "surface_2": "#101a2f",
    "surface_3": "#17243d",
    "side": "#17243d",
    "side_2": "#101a2f",
    "side_text": "#f3f6ff",
    "side_muted": "#b8c0d8",
    "heading_bg": "#243056",
    "on_success": "#07150e",
    "on_warning": "#1a1400",
    "on_danger": "#ffffff",
    "status_idle": "#20345d",
    "chip_bg": "#2a3f66",
    "chip_fg": "#c8d6f0",
    "chip_value": "#ffe08a",
}

CLASSIC_TOKENS: dict[str, str] = {
    "HEADER_PURPLE": "#5b3fd4",
    "HEADER_PURPLE_SOFT": "#6b4cff",
    "BTN_BLUE": "#2f6fed",
    "BTN_BLUE_HOVER": "#4f8cff",
    "BTN_PURPLE": "#6b4cff",
    "BTN_YELLOW": "#e6b84d",
    "BTN_GREEN": "#2f9e6b",
    "BTN_GREEN_HOVER": "#3cb87a",
    "BTN_RED": "#c44b55",
    "BTN_RED_HOVER": "#d55a63",
    "BTN_GREY": "#3a4a6a",
    "BTN_GREY_HOVER": "#4a5a7a",
    "YELLOW_FG": "#1a1400",
    "YELLOW_HOVER": "#f0c85a",
}

CLASSIC_METRICS: dict[str, Any] = {
    "rowheight": 29,
    "ui_font": 9,
    "muted_font": 9,
    "title_font": 16,
    "tab_padding": (22, 11),
    "btn_padding": (14, 8),
    "entry_padding": 7,
}

CLASSIC_TREE_TAGS: dict[str, dict[str, str]] = {
    "odd": {"background": "#101c31"},
    "tax_only": {"background": "#574a21", "foreground": "#fff1bc"},
    "self_assessment": {"background": "#2f2854", "foreground": "#eeeaff"},
    "vat_not_deducted": {"background": "#5b3717", "foreground": "#fff0c7"},
    "section_start": {"background": "#182b4b", "foreground": "#ffffff"},
    "result": {"background": "#3c3520", "foreground": "#fff1bc"},
    "diff_row": {"background": "#5b3717", "foreground": "#fff0c7"},
    "api_ready": {"background": "#10253a"},
    "api_ok": {"background": "#173c2b", "foreground": "#dcffea"},
    "api_error": {"background": "#512a31", "foreground": "#ffe6e8"},
    "api_sent": {"background": "#214638", "foreground": "#dcffea"},
    "api_missing": {"background": "#3a2f14", "foreground": "#ffe9b5"},
    "api_exists": {"background": "#1a3348", "foreground": "#d7ecff"},
    "match_ok": {"background": "#173c2b", "foreground": "#dcffea"},
    "match_api_only": {"background": "#3a2f14", "foreground": "#ffe9b5"},
    "match_local_only": {"background": "#512a31", "foreground": "#ffe6e8"},
    "totals": {"background": "#1a2740", "foreground": "#9fd4ff"},
    "changed": {"background": "#4b351b", "foreground": "#fff0c7"},
}

DEFAULT_THEME = "trops"
CLASSIC_THEME_ALIASES = {"classic", "stari", "old", "transkript", "klasicni", "klasični"}

# Modulni aliasi — veljavni po apply_theme(); privzeto Trops.
HEADER_PURPLE = TROPS_TOKENS["HEADER_PURPLE"]
HEADER_PURPLE_SOFT = TROPS_TOKENS["HEADER_PURPLE_SOFT"]
BTN_BLUE = TROPS_TOKENS["BTN_BLUE"]
BTN_BLUE_HOVER = TROPS_TOKENS["BTN_BLUE_HOVER"]
BTN_PURPLE = TROPS_TOKENS["BTN_PURPLE"]
BTN_YELLOW = TROPS_TOKENS["BTN_YELLOW"]
BTN_GREEN = TROPS_TOKENS["BTN_GREEN"]
BTN_GREEN_HOVER = TROPS_TOKENS["BTN_GREEN_HOVER"]
BTN_RED = TROPS_TOKENS["BTN_RED"]
BTN_RED_HOVER = TROPS_TOKENS["BTN_RED_HOVER"]
BTN_GREY = TROPS_TOKENS["BTN_GREY"]
BTN_GREY_HOVER = TROPS_TOKENS["BTN_GREY_HOVER"]

COLORS: dict[str, str] = dict(TROPS_COLORS)
TREE_TAG_COLORS: dict[str, dict[str, str]] = {k: dict(v) for k, v in TROPS_TREE_TAGS.items()}
METRICS: dict[str, Any] = dict(TROPS_METRICS)
_ACTIVE_THEME = DEFAULT_THEME
_FONT_FAMILY = "Segoe UI"
_FONT_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI")


def normalize_theme(name: str | None) -> str:
    """Vrni 'trops' ali 'classic'."""
    key = str(name or "").strip().casefold()
    if key in CLASSIC_THEME_ALIASES:
        return "classic"
    return "trops"


def current_theme() -> str:
    return _ACTIVE_THEME


def ui_font(size: int | None = None, weight: str = "normal") -> tuple[Any, ...]:
    """Pisava teme: Segoe UI Variable, sicer Segoe UI."""
    pt = int(METRICS["ui_font"] if size is None else size)
    if weight and weight != "normal":
        return (_FONT_FAMILY, pt, weight)
    return (_FONT_FAMILY, pt)


def resolve_ui_font_family(root: tk.Misc | None = None) -> str:
    """Izberi nameščeno družino pisave, bližjo Trops."""
    global _FONT_FAMILY
    names: set[str] = set()
    if root is not None:
        try:
            names = {str(item) for item in root.tk.call("font", "families")}
        except tk.TclError:
            names = set()
    if names:
        for candidate in _FONT_CANDIDATES:
            if candidate in names:
                _FONT_FAMILY = candidate
                return _FONT_FAMILY
    _FONT_FAMILY = "Segoe UI"
    return _FONT_FAMILY


def apply_theme(name: str | None) -> str:
    """Nastavi module-level barve in merila. Vrne normalizirano ime teme."""
    global HEADER_PURPLE, HEADER_PURPLE_SOFT
    global BTN_BLUE, BTN_BLUE_HOVER, BTN_PURPLE, BTN_YELLOW
    global BTN_GREEN, BTN_GREEN_HOVER, BTN_RED, BTN_RED_HOVER
    global BTN_GREY, BTN_GREY_HOVER, _ACTIVE_THEME

    theme = normalize_theme(name)
    tokens = TROPS_TOKENS if theme == "trops" else CLASSIC_TOKENS
    colors = TROPS_COLORS if theme == "trops" else CLASSIC_COLORS
    tags = TROPS_TREE_TAGS if theme == "trops" else CLASSIC_TREE_TAGS
    metrics = TROPS_METRICS if theme == "trops" else CLASSIC_METRICS

    HEADER_PURPLE = tokens["HEADER_PURPLE"]
    HEADER_PURPLE_SOFT = tokens["HEADER_PURPLE_SOFT"]
    BTN_BLUE = tokens["BTN_BLUE"]
    BTN_BLUE_HOVER = tokens["BTN_BLUE_HOVER"]
    BTN_PURPLE = tokens["BTN_PURPLE"]
    BTN_YELLOW = tokens["BTN_YELLOW"]
    BTN_GREEN = tokens["BTN_GREEN"]
    BTN_GREEN_HOVER = tokens["BTN_GREEN_HOVER"]
    BTN_RED = tokens["BTN_RED"]
    BTN_RED_HOVER = tokens["BTN_RED_HOVER"]
    BTN_GREY = tokens["BTN_GREY"]
    BTN_GREY_HOVER = tokens["BTN_GREY_HOVER"]

    COLORS.clear()
    COLORS.update(colors)
    TREE_TAG_COLORS.clear()
    TREE_TAG_COLORS.update({k: dict(v) for k, v in tags.items()})
    METRICS.clear()
    METRICS.update(metrics)
    _ACTIVE_THEME = theme
    return theme


def _button_palette() -> dict[str, tuple[str, str, str]]:
    tokens = TROPS_TOKENS if _ACTIVE_THEME == "trops" else CLASSIC_TOKENS
    return {
        "grey": (BTN_GREY, "#ffffff", BTN_GREY_HOVER),
        "blue": (BTN_BLUE, "#ffffff", BTN_BLUE_HOVER),
        "green": (BTN_GREEN, "#ffffff", BTN_GREEN_HOVER),
        "red": (BTN_RED, "#ffffff", BTN_RED_HOVER),
        "yellow": (BTN_YELLOW, tokens["YELLOW_FG"], tokens["YELLOW_HOVER"]),
        "purple": (BTN_PURPLE, "#ffffff", tokens["BTN_BLUE_HOVER"] if _ACTIVE_THEME == "trops" else "#8566ff"),
    }


def apply_tree_tags(tree: ttk.Treeview, *names: str) -> None:
    """Nastavi barve oznak vrstic za trenutno temo."""
    wanted: Iterable[str] = names or tuple(TREE_TAG_COLORS)
    for name in wanted:
        opts = TREE_TAG_COLORS.get(name)
        if opts:
            tree.tag_configure(name, **opts)


def text_area_kwargs() -> dict[str, str]:
    """Barve za tk.Text v dialogih."""
    return {
        "bg": COLORS["input"] if _ACTIVE_THEME == "classic" else COLORS["surface_2"],
        "fg": COLORS["text"],
        "insertbackground": COLORS["text"],
    }


class PillButton(tk.Button):
    """Barvni flat gumb (videz Transkript / Trops)."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        *,
        command: Callable[[], None] | None = None,
        bg: str | None = None,
        fg: str = "#ffffff",
        hover: str = "",
        font: tuple[Any, ...] | None = None,
        padx: int = 12,
        pady: int = 6,
        **kwargs: Any,
    ) -> None:
        bg = BTN_BLUE if bg is None else bg
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover or bg,
            activeforeground=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=font or ui_font(weight="bold"),
            padx=padx,
            pady=pady,
            cursor="hand2",
            **kwargs,
        )
        self._bg = bg
        self._hover = hover or bg
        self._fg = fg
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def set_kind(self, kind: str) -> None:
        """Preklopi barvo gumba (grey|blue|green|red|yellow|purple) — brez ttk style."""
        palette = _button_palette()
        bg, fg, hover = palette.get(kind, palette["grey"])
        self._bg = bg
        self._hover = hover
        self._fg = fg
        self.configure(bg=bg, fg=fg, activebackground=hover, activeforeground=fg)

    def _on_enter(self, _event: tk.Event | None = None) -> None:
        if str(self.cget("state")) == "disabled":
            return
        self.configure(bg=self._hover)

    def _on_leave(self, _event: tk.Event | None = None) -> None:
        self.configure(bg=self._bg)


class CollapsibleSection(tk.Frame):
    """Panel s klikom na naslov: ▼ razširi / ▶ skrči."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        bg: str | None = None,
        fg: str | None = None,
        muted: str | None = None,
        initially_open: bool = True,
        padx: int = 6,
        pady: int = 4,
        accent: str | None = None,
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
        bg = COLORS["bg"] if bg is None else bg
        fg = COLORS["text"] if fg is None else fg
        muted = COLORS["muted"] if muted is None else muted
        accent = HEADER_PURPLE_SOFT if accent is None else accent
        super().__init__(parent, bg=bg, highlightbackground=accent, highlightthickness=1)
        self._title = title
        self._open = bool(initially_open)
        self._on_toggle = on_toggle
        header = tk.Frame(self, bg=accent, cursor="hand2")
        header.pack(fill="x")
        self._hdr_lbl = tk.Label(
            header,
            text=self._header_text(),
            bg=accent,
            fg="#ffffff",
            font=ui_font(10, "bold"),
            anchor="w",
            cursor="hand2",
            padx=10,
            pady=6,
        )
        self._hdr_lbl.pack(side="left", fill="x", expand=True)
        hint = tk.Label(
            header,
            text="skrči / razširi  ▶",
            bg=accent,
            fg=COLORS["header_muted"],
            font=ui_font(8, "bold"),
            cursor="hand2",
            padx=10,
            pady=6,
        )
        hint.pack(side="right")
        self._hint = hint
        self._bind_header_click(header)
        self.body = tk.Frame(self, bg=bg, padx=padx, pady=pady)
        if self._open:
            self.body.pack(fill="x", expand=False)

    def _bind_header_click(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._on_header_click)
        for child in widget.winfo_children():
            self._bind_header_click(child)

    def _on_header_click(self, _event: tk.Event | None = None) -> None:
        self.toggle()

    def _header_text(self) -> str:
        return f"{'▼' if self._open else '▶'}  {self._title}"

    def toggle(self) -> None:
        self.set_open(not self._open)

    def set_open(self, open_: bool) -> None:
        """Nastavi odprto/zaprto."""
        want = bool(open_)
        if want == self._open:
            return
        self._open = want
        self._hdr_lbl.configure(text=self._header_text())
        self._hint.configure(text="skrči / razširi  ▼" if self._open else "skrči / razširi  ▶")
        if self._open:
            self.body.pack(fill="x", expand=False)
        else:
            self.body.pack_forget()
        if self._on_toggle is not None:
            self._on_toggle(self._open)


def pack_purple_header(
    parent: tk.Misc,
    title: str,
    *,
    subtitle: str = "",
    pad: tuple[int, int] = (18, 14),
) -> tuple[tk.Frame, tk.Frame, tk.Frame]:
    """Glava (Trops: temna #0f172a, classic: vijolična); vrne (outer, actions, meta)."""
    header_bg = HEADER_PURPLE
    outer = tk.Frame(parent, bg=header_bg, padx=pad[0], pady=pad[1])
    outer.pack(fill="x")
    row = tk.Frame(outer, bg=header_bg)
    row.pack(fill="x")
    title_box = tk.Frame(row, bg=header_bg)
    title_box.pack(side="left", fill="x", expand=True)
    tk.Label(
        title_box,
        text=title,
        bg=header_bg,
        fg="#ffffff",
        font=ui_font(int(METRICS["title_font"]), "bold"),
        anchor="w",
    ).pack(anchor="w")
    if subtitle:
        tk.Label(
            title_box,
            text=subtitle,
            bg=header_bg,
            fg=COLORS["header_muted"],
            font=ui_font(),
            anchor="w",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
    actions = tk.Frame(row, bg=header_bg)
    actions.pack(side="right")
    meta = tk.Frame(outer, bg=HEADER_PURPLE_SOFT, padx=10, pady=8)
    meta.pack(fill="x", pady=(10, 0))
    return outer, actions, meta


def pack_section_strip(parent: tk.Misc, title: str) -> tk.Frame:
    """Pasica + telesni trak. Vrne body frame."""
    outer = tk.Frame(
        parent,
        bg=COLORS["card"],
        highlightbackground=HEADER_PURPLE_SOFT,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=(10, 0))
    hdr = tk.Frame(outer, bg=HEADER_PURPLE_SOFT)
    hdr.pack(fill="x")
    tk.Label(
        hdr,
        text=title,
        bg=HEADER_PURPLE_SOFT,
        fg="#ffffff",
        font=ui_font(10, "bold"),
        anchor="w",
        padx=12,
        pady=5,
    ).pack(side="left")
    body = tk.Frame(outer, bg=COLORS["card"], padx=12, pady=8)
    body.pack(fill="x")
    return body


def pill(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    *,
    kind: str = "grey",
    padx: int = 12,
    pady: int = 5,
    **kwargs: Any,
) -> PillButton:
    """Hitra izdelava barvnega gumba: grey|blue|green|red|yellow|purple."""
    palette = _button_palette()
    bg, fg, hover = palette.get(kind, palette["grey"])
    return PillButton(
        parent,
        text,
        command=command,
        bg=bg,
        fg=fg,
        hover=hover,
        padx=padx,
        pady=pady,
        **kwargs,
    )


def _paint_ttk_button(
    style: ttk.Style,
    name: str,
    *,
    bg: str,
    fg: str,
    hover: str,
    disabled: str,
    font: tuple[Any, ...] | None = None,
    padding: tuple[int, int] | None = None,
) -> None:
    """Windows clam: lightcolor/darkcolor/bordercolor = dejanska barva gumba."""
    style.configure(
        name,
        background=bg,
        foreground=fg,
        lightcolor=bg,
        darkcolor=bg,
        bordercolor=bg,
        focuscolor=bg,
        relief="flat",
        borderwidth=0,
        padding=padding or tuple(METRICS["btn_padding"]),
        font=font or ui_font(weight="bold"),
    )
    style.map(
        name,
        background=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        lightcolor=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        darkcolor=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        bordercolor=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        foreground=[("disabled", COLORS["muted"])],
    )


def configure_app_style(root: tk.Misc, theme: str | None = None) -> dict[str, str]:
    """Nastavi clam/ttk stile za celoten program. Vrne barvni slovar."""
    apply_theme(theme if theme is not None else _ACTIVE_THEME)
    resolve_ui_font_family(root)
    colors = dict(COLORS)
    metrics = METRICS
    style = ttk.Style(root)
    # clam = edini theme, kjer background na gumbih deluje zanesljivo
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.option_add("*Font", ui_font())
    root.option_add("*TCombobox*Listbox.font", ui_font())
    root.option_add("*Menu.font", ui_font())
    root.option_add("*Menu.background", colors["panel"])
    root.option_add("*Menu.foreground", colors["text"])
    root.option_add("*Menu.activeBackground", HEADER_PURPLE)
    root.option_add("*Menu.activeForeground", "#ffffff")

    style.configure(".", background=colors["bg"], foreground=colors["text"])
    style.configure("TFrame", background=colors["bg"])
    style.configure("Panel.TFrame", background=colors["panel"])
    style.configure("Panel.TLabel", background=colors["panel"], foreground=colors["text"])
    style.configure("Card.TFrame", background=colors["card"])
    style.configure("Header.TFrame", background=HEADER_PURPLE)
    style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
    style.configure("Muted.TLabel", foreground=colors["muted"], font=ui_font(int(metrics["muted_font"])))
    style.configure("Card.TLabel", background=colors["card"], foreground=colors["text"])
    style.configure(
        "CardMuted.TLabel",
        background=colors["card"],
        foreground=colors["muted"],
        font=ui_font(int(metrics["muted_font"])),
    )
    style.configure(
        "HeaderTitle.TLabel",
        background=HEADER_PURPLE,
        foreground="#ffffff",
        font=ui_font(int(metrics["title_font"]) + 2, "bold"),
    )
    style.configure(
        "HeaderSub.TLabel",
        background=HEADER_PURPLE,
        foreground=colors["header_muted"],
        font=ui_font(),
    )
    style.configure("SectionTitle.TLabel", foreground=colors["text"], font=ui_font(12, "bold"))
    style.configure(
        "SummaryValue.TLabel",
        background=colors["card"],
        foreground=colors["text"],
        font=ui_font(18, "bold"),
    )
    style.configure("Status.TLabel", background=colors["panel"], foreground=colors["muted"], padding=(12, 7))

    disabled_btn = colors["surface_3"]
    _paint_ttk_button(style, "TButton", bg=BTN_GREY, fg="#ffffff", hover=BTN_GREY_HOVER, disabled=disabled_btn)
    _paint_ttk_button(style, "Accent.TButton", bg=BTN_BLUE, fg="#ffffff", hover=BTN_BLUE_HOVER, disabled=disabled_btn)
    _paint_ttk_button(
        style,
        "Purple.TButton",
        bg=HEADER_PURPLE_SOFT if _ACTIVE_THEME == "classic" else colors["accent_2"],
        fg="#ffffff",
        hover="#8566ff" if _ACTIVE_THEME == "classic" else colors["accent"],
        disabled=disabled_btn,
    )
    _paint_ttk_button(style, "Success.TButton", bg=BTN_GREEN, fg="#ffffff", hover=BTN_GREEN_HOVER, disabled=disabled_btn)
    yellow_tokens = TROPS_TOKENS if _ACTIVE_THEME == "trops" else CLASSIC_TOKENS
    _paint_ttk_button(
        style,
        "Warning.TButton",
        bg=BTN_YELLOW,
        fg=yellow_tokens["YELLOW_FG"],
        hover=yellow_tokens["YELLOW_HOVER"],
        disabled=disabled_btn,
    )
    _paint_ttk_button(style, "Danger.TButton", bg=BTN_RED, fg="#ffffff", hover=BTN_RED_HOVER, disabled=disabled_btn)

    style.configure(
        "TEntry",
        fieldbackground=colors["input"],
        foreground=colors["text"],
        insertcolor=colors["text"],
        bordercolor=colors["line"],
        lightcolor=colors["line"],
        darkcolor=colors["line"],
        padding=int(metrics["entry_padding"]),
    )
    style.configure(
        "TCombobox",
        fieldbackground=colors["input"],
        background=BTN_GREY,
        foreground=colors["text"],
        arrowcolor=colors["text"],
        bordercolor=colors["line"],
        lightcolor=colors["line"],
        darkcolor=colors["line"],
        padding=6,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", colors["input"])],
        foreground=[("readonly", colors["text"])],
        background=[("readonly", BTN_GREY), ("active", BTN_GREY_HOVER)],
    )
    style.configure("TCheckbutton", background=colors["panel"], foreground=colors["text"])
    style.map("TCheckbutton", background=[("active", colors["panel"])], foreground=[("active", colors["text"])])
    style.configure("Card.TCheckbutton", background=colors["card"], foreground=colors["text"])
    style.map("Card.TCheckbutton", background=[("active", colors["card"])])

    style.configure("TNotebook", background=colors["bg"], borderwidth=0, tabmargins=(0, 8, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=colors["surface_3"] if _ACTIVE_THEME == "trops" else colors["panel"],
        foreground=colors["muted"],
        padding=tuple(metrics["tab_padding"]),
        font=ui_font(weight="bold"),
        lightcolor=colors["line"] if _ACTIVE_THEME == "trops" else colors["panel"],
        darkcolor=colors["line"] if _ACTIVE_THEME == "trops" else colors["panel"],
        bordercolor=colors["line"] if _ACTIVE_THEME == "trops" else colors["panel"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", HEADER_PURPLE if _ACTIVE_THEME == "classic" else colors["accent"]), ("active", colors["card"])],
        lightcolor=[("selected", HEADER_PURPLE if _ACTIVE_THEME == "classic" else colors["accent"]), ("active", colors["card"])],
        darkcolor=[("selected", HEADER_PURPLE if _ACTIVE_THEME == "classic" else colors["accent"]), ("active", colors["card"])],
        bordercolor=[("selected", HEADER_PURPLE if _ACTIVE_THEME == "classic" else colors["accent"]), ("active", colors["card"])],
        foreground=[("selected", "#ffffff"), ("active", colors["text"])],
    )
    style.configure(
        "Studio.Treeview",
        background=colors["input"] if _ACTIVE_THEME == "classic" else colors["surface_2"],
        fieldbackground=colors["input"] if _ACTIVE_THEME == "classic" else colors["surface_2"],
        foreground=colors["text"],
        rowheight=int(metrics["rowheight"]),
        borderwidth=0,
        font=ui_font(),
    )
    style.map(
        "Studio.Treeview",
        background=[("selected", colors["accent"])],
        foreground=[("selected", "#ffffff")],
    )
    heading_bg = colors["heading_bg"]
    style.configure(
        "Studio.Treeview.Heading",
        background=heading_bg,
        foreground=colors["text"],
        relief="flat",
        padding=(8, 8),
        font=ui_font(weight="bold"),
        lightcolor=heading_bg,
        darkcolor=heading_bg,
        bordercolor=heading_bg,
    )
    style.map(
        "Studio.Treeview.Heading",
        background=[("active", colors["accent"])],
        lightcolor=[("active", colors["accent"])],
        darkcolor=[("active", colors["accent"])],
        foreground=[("active", "#ffffff")],
    )

    # Levi panel (Trops: temna vrstica #0f172a; classic: enak kartici).
    style.configure("Sidebar.TFrame", background=colors["side"])
    style.configure("Sidebar.TLabel", background=colors["side"], foreground=colors["side_text"])
    style.configure(
        "SidebarMuted.TLabel",
        background=colors["side"],
        foreground=colors["side_muted"],
        font=ui_font(int(metrics["muted_font"])),
    )
    style.configure(
        "Sidebar.Treeview",
        background=colors["side"],
        fieldbackground=colors["side"],
        foreground=colors["side_text"],
        rowheight=int(metrics["rowheight"]),
        borderwidth=0,
        font=ui_font(),
    )
    style.map(
        "Sidebar.Treeview",
        background=[("selected", colors["accent"])],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Sidebar.Treeview.Heading",
        background=colors["side_2"],
        foreground=colors["side_text"],
        relief="flat",
        padding=(8, 8),
        font=ui_font(weight="bold"),
        lightcolor=colors["side_2"],
        darkcolor=colors["side_2"],
        bordercolor=colors["side_2"],
    )
    style.map(
        "Sidebar.Treeview.Heading",
        background=[("active", colors["accent"])],
        lightcolor=[("active", colors["accent"])],
        darkcolor=[("active", colors["accent"])],
        foreground=[("active", "#ffffff")],
    )

    style.configure("TPanedwindow", background=colors["bg"], sashwidth=6)
    style.configure(
        "TScrollbar",
        background=colors["surface_3"] if _ACTIVE_THEME == "trops" else colors["panel"],
        troughcolor=colors["bg"],
        arrowcolor=colors["muted"],
        bordercolor=colors["line"],
        lightcolor=colors["surface_3"] if _ACTIVE_THEME == "trops" else colors["panel"],
        darkcolor=colors["surface_3"] if _ACTIVE_THEME == "trops" else colors["panel"],
    )
    return colors


# Ob uvozu velja Trops, dokler configure_app_style/apply_theme ne nastavi drugače.
apply_theme(DEFAULT_THEME)

__all__ = [
    "BTN_BLUE",
    "BTN_BLUE_HOVER",
    "BTN_GREEN",
    "BTN_GREEN_HOVER",
    "BTN_GREY",
    "BTN_GREY_HOVER",
    "BTN_PURPLE",
    "BTN_RED",
    "BTN_RED_HOVER",
    "BTN_YELLOW",
    "CLASSIC_COLORS",
    "COLORS",
    "CollapsibleSection",
    "DEFAULT_THEME",
    "HEADER_PURPLE",
    "HEADER_PURPLE_SOFT",
    "PillButton",
    "TROPS_COLORS",
    "apply_theme",
    "apply_tree_tags",
    "configure_app_style",
    "current_theme",
    "normalize_theme",
    "pack_purple_header",
    "pack_section_strip",
    "pill",
    "text_area_kwargs",
    "ui_font",
]
