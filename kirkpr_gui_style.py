"""Skupni Transkript-podobni videz za KIR/KPR → Minimax Studio (Cursor)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

# Paleta (Video Transkript Studio)
HEADER_PURPLE = "#5b3fd4"
HEADER_PURPLE_SOFT = "#6b4cff"
BTN_BLUE = "#2f6fed"
BTN_BLUE_HOVER = "#4f8cff"
BTN_PURPLE = "#6b4cff"
BTN_YELLOW = "#e6b84d"
BTN_GREEN = "#2f9e6b"
BTN_GREEN_HOVER = "#3cb87a"
BTN_RED = "#c44b55"
BTN_RED_HOVER = "#d55a63"
BTN_GREY = "#3a4a6a"
BTN_GREY_HOVER = "#4a5a7a"

COLORS: dict[str, str] = {
    "bg": "#0b1220",
    "panel": "#101a2f",
    "panel_alt": HEADER_PURPLE,  # glave dialogov / Header.TFrame
    "card": "#17243d",
    "header": "#2a3560",  # privzeti gumbi (slate)
    "accent": BTN_BLUE,
    "purple": HEADER_PURPLE_SOFT,
    "success": BTN_GREEN,
    "warning": BTN_YELLOW,
    "danger": BTN_RED,
    "text": "#f3f6ff",
    "muted": "#b8c0d8",
    "input": "#0d172a",
    "line": "#2a3b60",
    "header_fg": "#ffffff",
    "header_muted": "#d7d0ff",
}


class PillButton(tk.Button):
    """Barvni flat gumb (videz Transkript Studio)."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        *,
        command: Callable[[], None] | None = None,
        bg: str = BTN_BLUE,
        fg: str = "#ffffff",
        hover: str = "",
        font: tuple[str, int, str] = ("Segoe UI", 9, "bold"),
        padx: int = 12,
        pady: int = 6,
        **kwargs: Any,
    ) -> None:
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
            font=font,
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
        palette = {
            "grey": (BTN_GREY, "#ffffff", BTN_GREY_HOVER),
            "blue": (BTN_BLUE, "#ffffff", BTN_BLUE_HOVER),
            "green": (BTN_GREEN, "#ffffff", BTN_GREEN_HOVER),
            "red": (BTN_RED, "#ffffff", BTN_RED_HOVER),
            "yellow": (BTN_YELLOW, "#1a1400", "#f0c85a"),
            "purple": (BTN_PURPLE, "#ffffff", "#8566ff"),
        }
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
        bg: str,
        fg: str = COLORS["text"],
        muted: str = COLORS["muted"],
        initially_open: bool = True,
        padx: int = 6,
        pady: int = 4,
        accent: str = HEADER_PURPLE_SOFT,
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
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
            font=("Segoe UI", 10, "bold"),
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
            fg="#d7d0ff",
            font=("Segoe UI", 8, "bold"),
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
    """Vijolična glava; vrne (outer, actions_frame, meta_frame za 2. vrstico)."""
    outer = tk.Frame(parent, bg=HEADER_PURPLE, padx=pad[0], pady=pad[1])
    outer.pack(fill="x")
    row = tk.Frame(outer, bg=HEADER_PURPLE)
    row.pack(fill="x")
    title_box = tk.Frame(row, bg=HEADER_PURPLE)
    title_box.pack(side="left", fill="x", expand=True)
    tk.Label(
        title_box,
        text=title,
        bg=HEADER_PURPLE,
        fg="#ffffff",
        font=("Segoe UI", 16, "bold"),
        anchor="w",
    ).pack(anchor="w")
    if subtitle:
        tk.Label(
            title_box,
            text=subtitle,
            bg=HEADER_PURPLE,
            fg=COLORS["header_muted"],
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
    actions = tk.Frame(row, bg=HEADER_PURPLE)
    actions.pack(side="right")
    meta = tk.Frame(outer, bg=HEADER_PURPLE_SOFT, padx=10, pady=8)
    meta.pack(fill="x", pady=(10, 0))
    return outer, actions, meta


def pack_section_strip(parent: tk.Misc, title: str) -> tk.Frame:
    """Vijolična pasica + telesni trak (kot paneli v e-pošti). Vrne body frame."""
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
        font=("Segoe UI", 10, "bold"),
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
    palette = {
        "grey": (BTN_GREY, "#ffffff", BTN_GREY_HOVER),
        "blue": (BTN_BLUE, "#ffffff", BTN_BLUE_HOVER),
        "green": (BTN_GREEN, "#ffffff", BTN_GREEN_HOVER),
        "red": (BTN_RED, "#ffffff", BTN_RED_HOVER),
        "yellow": (BTN_YELLOW, "#1a1400", "#f0c85a"),
        "purple": (BTN_PURPLE, "#ffffff", "#8566ff"),
    }
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
    font: tuple[str, int, str] = ("Segoe UI", 9, "bold"),
    padding: tuple[int, int] = (14, 8),
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
        padding=padding,
        font=font,
    )
    style.map(
        name,
        background=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        lightcolor=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        darkcolor=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        bordercolor=[("pressed", hover), ("active", hover), ("disabled", disabled)],
        foreground=[("disabled", "#64708b")],
    )


def configure_app_style(root: tk.Misc) -> dict[str, str]:
    """Nastavi clam/ttk stile za celoten program. Vrne barvni slovar."""
    colors = dict(COLORS)
    style = ttk.Style(root)
    # clam = edini theme, kjer background na gumbih deluje zanesljivo
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.option_add("*Font", ("Segoe UI", 10))
    root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
    root.option_add("*Menu.font", ("Segoe UI", 10))
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
    style.configure("Muted.TLabel", foreground=colors["muted"], font=("Segoe UI", 9))
    style.configure("Card.TLabel", background=colors["card"], foreground=colors["text"])
    style.configure("CardMuted.TLabel", background=colors["card"], foreground=colors["muted"], font=("Segoe UI", 9))
    style.configure(
        "HeaderTitle.TLabel",
        background=HEADER_PURPLE,
        foreground="#ffffff",
        font=("Segoe UI", 18, "bold"),
    )
    style.configure(
        "HeaderSub.TLabel",
        background=HEADER_PURPLE,
        foreground=COLORS["header_muted"],
        font=("Segoe UI", 10),
    )
    style.configure("SectionTitle.TLabel", foreground=colors["text"], font=("Segoe UI", 12, "bold"))
    style.configure(
        "SummaryValue.TLabel",
        background=colors["card"],
        foreground=colors["text"],
        font=("Segoe UI", 18, "bold"),
    )
    style.configure("Status.TLabel", background=colors["panel"], foreground=colors["muted"], padding=(12, 7))

    _paint_ttk_button(style, "TButton", bg=BTN_GREY, fg=colors["text"], hover=BTN_GREY_HOVER, disabled=colors["panel"])
    _paint_ttk_button(style, "Accent.TButton", bg=BTN_BLUE, fg="#ffffff", hover=BTN_BLUE_HOVER, disabled="#29436e")
    _paint_ttk_button(style, "Purple.TButton", bg=HEADER_PURPLE_SOFT, fg="#ffffff", hover="#8566ff", disabled="#3a2f6e")
    _paint_ttk_button(style, "Success.TButton", bg=BTN_GREEN, fg="#ffffff", hover=BTN_GREEN_HOVER, disabled="#235b43")
    _paint_ttk_button(style, "Warning.TButton", bg=BTN_YELLOW, fg="#1a1400", hover="#f0c85a", disabled="#6a5a28")
    _paint_ttk_button(style, "Danger.TButton", bg=BTN_RED, fg="#ffffff", hover=BTN_RED_HOVER, disabled="#5a3035")

    style.configure(
        "TEntry",
        fieldbackground=colors["input"],
        foreground=colors["text"],
        insertcolor=colors["text"],
        bordercolor=colors["line"],
        lightcolor=colors["line"],
        darkcolor=colors["line"],
        padding=7,
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
    style.map("TCheckbutton", background=[("active", colors["panel"])])
    style.configure("Card.TCheckbutton", background=colors["card"], foreground=colors["text"])
    style.map("Card.TCheckbutton", background=[("active", colors["card"])])

    style.configure("TNotebook", background=colors["bg"], borderwidth=0, tabmargins=(0, 8, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=colors["panel"],
        foreground=colors["muted"],
        padding=(22, 11),
        font=("Segoe UI", 10, "bold"),
        lightcolor=colors["panel"],
        darkcolor=colors["panel"],
        bordercolor=colors["panel"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", HEADER_PURPLE), ("active", colors["card"])],
        lightcolor=[("selected", HEADER_PURPLE), ("active", colors["card"])],
        darkcolor=[("selected", HEADER_PURPLE), ("active", colors["card"])],
        bordercolor=[("selected", HEADER_PURPLE), ("active", colors["card"])],
        foreground=[("selected", "#ffffff"), ("active", colors["text"])],
    )
    style.configure(
        "Studio.Treeview",
        background=colors["input"],
        fieldbackground=colors["input"],
        foreground=colors["text"],
        rowheight=29,
        borderwidth=0,
        font=("Segoe UI", 9),
    )
    style.map(
        "Studio.Treeview",
        background=[("selected", BTN_BLUE)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Studio.Treeview.Heading",
        background="#243056",
        foreground=colors["text"],
        relief="flat",
        padding=(8, 8),
        font=("Segoe UI", 9, "bold"),
        lightcolor="#243056",
        darkcolor="#243056",
        bordercolor="#243056",
    )
    style.map(
        "Studio.Treeview.Heading",
        background=[("active", HEADER_PURPLE)],
        lightcolor=[("active", HEADER_PURPLE)],
        darkcolor=[("active", HEADER_PURPLE)],
    )
    style.configure("TPanedwindow", background=colors["bg"], sashwidth=6)
    style.configure(
        "TScrollbar",
        background=colors["panel"],
        troughcolor=colors["bg"],
        arrowcolor=colors["text"],
        bordercolor=colors["panel"],
        lightcolor=colors["panel"],
        darkcolor=colors["panel"],
    )
    return colors


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
    "COLORS",
    "CollapsibleSection",
    "HEADER_PURPLE",
    "HEADER_PURPLE_SOFT",
    "PillButton",
    "configure_app_style",
    "pack_purple_header",
    "pack_section_strip",
    "pill",
]
