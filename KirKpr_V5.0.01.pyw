# -*- coding: utf-8 -*-
"""KirKpr 5.0.01 — zagon WebView2 brez konzole (kot Trops_Studio_V5.1.00.pyw)."""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "KIRKPR_zagon_napaka.log"


def _log(message: str) -> None:
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (stamp, message))
    except OSError:
        pass


def _fatal(message: str) -> int:
    _log(message)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("KirKpr 5.0.01", message)
        root.destroy()
    except Exception:
        pass
    return 1


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        import webview  # noqa: F401
    except Exception:
        return _fatal(
            "Manjka knjižnica pywebview.\n\n"
            "Namestitev: py -3.10 -m pip install pywebview\n\n"
            + traceback.format_exc()[-2000:]
        )
    try:
        from host_webview import desktop

        return int(desktop() or 0)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code:
            return _fatal(str(code))
        return 0
    except Exception:
        return _fatal("Zagon ni uspel:\n\n" + traceback.format_exc()[-2000:])


if __name__ == "__main__":
    raise SystemExit(main())