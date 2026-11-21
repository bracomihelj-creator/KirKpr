"""Force Exit / kill — tudi ko UI visi (Outlook COM).

- Gumb v programu → potrditev, nato os._exit
- Ctrl+Shift+F12 (ločen thread) → takojšnji kill ob zmrzovanju
- Kill okno (drug proces) — SAMO na zahtevo, ne ob zagonu
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

# Ctrl+Shift+F12
_HOTKEY_ID = 0x4B12
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_NOREPEAT = 0x4000
_VK_F12 = 0x7B
_WM_HOTKEY = 0x0312

_hotkey_started = False
_guardian_proc: subprocess.Popen[Any] | None = None

_GUARDIAN_PATH = Path(__file__).resolve().with_name("_kirkpr_force_exit_guardian.py")

_GUARDIAN_SCRIPT = '''\
"""Ločeno kill okno — zaženi samo, ko KIR/KPR visi."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0


def parent_alive() -> bool:
    if pid <= 0:
        return False
    # OpenProcess — zanesljivejše od os.kill(pid, 0) na Windowsu
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def do_kill() -> None:
    if not messagebox.askyesno(
        "FORCE EXIT",
        f"Ubiti KIR/KPR (PID {pid})?\n\nSamo če je program zmrznjen.",
        parent=root,
    ):
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    os._exit(0)


root = tk.Tk()
root.title("Kill switch — KIR/KPR")
root.attributes("-topmost", True)
root.resizable(False, False)
root.configure(bg="#1a1020")
tk.Label(
    root,
    text=f"Samo ob zmrzovanju\\nPID {pid}",
    bg="#1a1020",
    fg="#f0e8ff",
    font=("Segoe UI", 10),
    justify="center",
).pack(padx=14, pady=(12, 6))

btn = tk.Button(
    root,
    text="… počakaj 2 s …",
    state="disabled",
    bg="#6a3035",
    fg="#ffffff",
    font=("Segoe UI", 11, "bold"),
    padx=18,
    pady=10,
    relief="flat",
)
btn.pack(padx=14, pady=6)
tk.Label(
    root,
    text="Ctrl+Shift+F12 = takojšnji kill",
    bg="#1a1020",
    fg="#9aa0b4",
    font=("Segoe UI", 8),
).pack(padx=14, pady=(0, 12))


def arm() -> None:
    btn.configure(
        text="FORCE EXIT / KILL",
        state="normal",
        bg="#c62828",
        activebackground="#e53935",
        command=do_kill,
        cursor="hand2",
    )


def poll() -> None:
    if not parent_alive():
        try:
            root.destroy()
        except Exception:
            pass
        return
    root.after(1200, poll)


root.update_idletasks()
w, h = 240, 160
sw = root.winfo_screenwidth()
sh = root.winfo_screenheight()
root.geometry(f"{w}x{h}+{sw - w - 24}+{sh - h - 64}")
root.after(2000, arm)
poll()
root.mainloop()
'''


def force_kill_self(*, reason: str = "") -> None:
    """Takoj ubije ta proces (brez Tk cleanup) — za zmrzovanje."""
    _ = reason
    stop_guardian()
    try:
        os._exit(1)
    except SystemExit:
        raise
    except Exception:
        pass
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(os.getpid())],
            check=False,
            timeout=10,
        )
    except Exception:
        pass


def confirm_force_kill(*, parent: Any = None) -> None:
    """Gumb/meni: najprej potrditev (prepreči pomotoma ugasnitev)."""
    try:
        from tkinter import messagebox

        ok = messagebox.askyesno(
            "FORCE EXIT",
            "Takoj ubiti program?\n\n"
            "Uporabi samo, če je UI zmrznjen.\n"
            "Sicer raje Datoteka → Izhod.\n\n"
            "Da = kill (os._exit)",
            parent=parent,
        )
        if not ok:
            return
    except Exception:
        pass
    force_kill_self(reason="confirm")


def start_hotkey_watcher() -> bool:
    """Ctrl+Shift+F12 → force kill (deluje tudi ko Tk visi)."""
    global _hotkey_started
    if _hotkey_started:
        return True
    if sys.platform != "win32":
        return False

    def _run() -> None:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            mods = _MOD_CONTROL | _MOD_SHIFT | _MOD_NOREPEAT
            if not user32.RegisterHotKey(None, _HOTKEY_ID, mods, _VK_F12):
                return
            try:
                msg = wintypes.MSG()
                while True:
                    ret = int(user32.GetMessageW(ctypes.byref(msg), None, 0, 0))
                    if ret == 0 or ret == -1:
                        break
                    if msg.message == _WM_HOTKEY and int(msg.wParam) == _HOTKEY_ID:
                        vk = (int(msg.lParam) >> 16) & 0xFFFF
                        if vk == _VK_F12:
                            force_kill_self(reason="hotkey")
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                try:
                    user32.UnregisterHotKey(None, _HOTKEY_ID)
                except Exception:
                    pass
        except Exception:
            return

    threading.Thread(target=_run, name="ForceExitHotkey", daemon=True).start()
    _hotkey_started = True
    return True


def _ensure_guardian_script() -> Path:
    try:
        if not _GUARDIAN_PATH.is_file() or _GUARDIAN_PATH.read_text(encoding="utf-8") != _GUARDIAN_SCRIPT:
            _GUARDIAN_PATH.write_text(_GUARDIAN_SCRIPT, encoding="utf-8")
    except OSError:
        pass
    return _GUARDIAN_PATH


def start_guardian_window(*, parent_pid: int | None = None) -> bool:
    """Ločeno kill okno — kliči samo na zahtevo (ne ob zagonu)."""
    global _guardian_proc
    if sys.platform != "win32":
        return False
    if _guardian_proc is not None and _guardian_proc.poll() is None:
        return True
    pid = int(parent_pid or os.getpid())
    script = _ensure_guardian_script()
    if not script.is_file():
        return False
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        _guardian_proc = subprocess.Popen(
            [sys.executable, str(script), str(pid)],
            cwd=str(Path(__file__).resolve().parent),
            creationflags=creationflags,
        )
        return True
    except Exception:
        _guardian_proc = None
        return False


def stop_guardian() -> None:
    global _guardian_proc
    proc = _guardian_proc
    _guardian_proc = None
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass


def start_all() -> None:
    """Ob zagonu samo hotkey — NE odpri kill okna (sicer pomotoma ugasne)."""
    start_hotkey_watcher()


def attach_force_exit_button(
    parent: Any,
    *,
    pack_side: str = "right",
    padx: int = 8,
    dialog_parent: Any = None,
) -> Any:
    """Rdeč gumb FORCE EXIT s potrditvijo."""

    def _click() -> None:
        confirm_force_kill(parent=dialog_parent or parent)

    try:
        from kirkpr_gui_style import PillButton
    except Exception:
        import tkinter as tk

        btn = tk.Button(
            parent,
            text="FORCE EXIT",
            command=_click,
            bg="#c62828",
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
        )
        btn.pack(side=pack_side, padx=padx)
        return btn

    btn = PillButton(
        parent,
        "FORCE EXIT",
        command=_click,
        bg="#c62828",
        hover="#e53935",
        fg="#ffffff",
        padx=10,
        pady=4,
        font=("Segoe UI", 9, "bold"),
    )
    btn.pack(side=pack_side, padx=padx)
    return btn


__all__ = [
    "attach_force_exit_button",
    "confirm_force_kill",
    "force_kill_self",
    "start_all",
    "start_guardian_window",
    "start_hotkey_watcher",
    "stop_guardian",
]
