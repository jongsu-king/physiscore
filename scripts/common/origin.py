"""Shared OriginPro (COM) connection helper.

Six modules carried their own near-identical copy of this function, differing
only in log wording and in whether they waited 30 s or 60 s for a launched
Origin to register itself. Each copy also swallowed *every* exception from the
wait loop with a bare ``except:``, which catches ``KeyboardInterrupt`` too --
so a user pressing Ctrl-C during a minute-long wait was ignored.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable, Optional

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:            # non-Windows, or pywin32 not installed
    win32com = None
    WIN32COM_AVAILABLE = False

# Origin's single-instance automation server ProgID.
_PROGID = "Origin.ApplicationSI"


def _log(log_callback: Optional[Callable[[str], None]], message: str) -> None:
    if log_callback:
        log_callback(message)


def _dispatch() -> Optional[Any]:
    """Attach to a running Origin and make it visible, or return None."""
    try:
        origin = win32com.client.Dispatch(_PROGID)
        origin.Visible = 1
        return origin
    except Exception:
        return None


def connect_to_origin(origin_exe_path: str = "",
                      log_callback: Optional[Callable[[str], None]] = None,
                      timeout_s: int = 60) -> Optional[Any]:
    """Return a live Origin automation object, or None.

    Attaches to a running instance first; failing that, launches
    ``origin_exe_path`` and polls once a second until Origin has registered its
    automation server or ``timeout_s`` elapses.
    """
    if not WIN32COM_AVAILABLE:
        _log(log_callback, "pywin32 not installed - Origin export unavailable")
        return None

    origin = _dispatch()
    if origin is not None:
        _log(log_callback, "Connected to existing Origin")
        return origin

    if not origin_exe_path or not os.path.exists(origin_exe_path):
        _log(log_callback, f"Origin path not found: {origin_exe_path}")
        return None

    _log(log_callback, f"Launching Origin: {origin_exe_path}")
    try:
        subprocess.Popen([origin_exe_path])
    except Exception as e:
        _log(log_callback, f"Origin launch error: {e}")
        return None

    for elapsed in range(int(timeout_s)):
        time.sleep(1)
        origin = _dispatch()
        if origin is not None:
            _log(log_callback, "New Origin instance started")
            return origin
        if elapsed and elapsed % 5 == 0:
            _log(log_callback, "Waiting for Origin...")

    _log(log_callback, "Timeout: Origin connection failed")
    return None
