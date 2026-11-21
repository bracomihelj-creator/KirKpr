# -*- coding: utf-8 -*-
"""KirKpr 4.0.3 — zagon brez konzole (kot Trops_Studio_V5.1.00.pyw)."""
from __future__ import annotations

import os
import runpy
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "convert_KIrKpr_to_minimax.py"
LOG = ROOT / "KIRKPR_zagon_napaka.log"


def _log(message: str) -> None:
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def _fatal(message: str) -> int:
    _log(message)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("KirKpr 4.0.3", message)
        root.destroy()
    except Exception:
        pass
    return 1


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if not APP.is_file():
        return _fatal(f"Manjka glavni program:\n{APP}")
    try:
        import lxml  # noqa: F401
        import tkinter  # noqa: F401
    except Exception:
        return _fatal(
            "Python 3 s knjižnico lxml (in tkinter) ni na voljo.\n\n"
            "Namestitev: python -m pip install -r requirements_KIrKpr_to_minimax.txt\n\n"
            + traceback.format_exc()[-2000:]
        )
    try:
        sys.argv = [str(APP), *sys.argv[1:]]
        runpy.run_path(str(APP), run_name="__main__")
        return 0
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
