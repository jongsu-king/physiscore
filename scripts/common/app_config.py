"""Single source of truth for ``physisfera_config.json``.

Before this module every consumer re-derived the config location from its own
``__file__`` with a hand-counted chain of ``".."`` segments, and each one read the
file again from scratch. That had two consequences:

* the number of ``".."`` had to match the module's depth, so moving a module
  silently pointed it at the wrong directory (or at the directory *above* the
  project);
* values were captured once at import time, so editing the config while the
  application was open had no effect until the process was restarted --
  ``cell_area_cm2`` in particular scales Jsc and therefore PCE linearly.

Everything here resolves the path once, per process, and re-reads the file only
when it has actually changed on disk (mtime + size).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from typing import Any, Dict, Optional

CONFIG_FILENAME = "physisfera_config.json"

# Device area used to convert measured current [A] to current density
# [mA/cm^2]. 0.04 cm^2 is the historical default (conversion factor 25000).
DEFAULT_CELL_AREA_CM2 = 0.04

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None
_cache_stamp: Optional[tuple] = None


def project_root() -> str:
    """Directory that owns the config file.

    Source runs: the repository root (this file is ``<root>/scripts/common/``).
    Frozen runs: the directory holding the executable, so that a config written
    by the launcher's Settings dialog sits next to the .exe and survives being
    unpacked again -- ``sys._MEIPASS`` is a bundle directory, not a place for
    user-edited state.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", ".."))


def config_path() -> str:
    """Absolute path of the config file to read and write.

    ``PHYSISCORE_CONFIG`` overrides everything, which is what tests use. For a
    frozen build the file next to the executable wins; if only the bundled copy
    exists (first run after install) that one is read instead.
    """
    override = os.environ.get("PHYSISCORE_CONFIG")
    if override:
        return os.path.abspath(override)

    primary = os.path.join(project_root(), CONFIG_FILENAME)
    if getattr(sys, "frozen", False) and not os.path.exists(primary):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), CONFIG_FILENAME)
        if os.path.exists(bundled):
            return bundled
    return primary


def _stamp(path: str):
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, None, None)


def load(refresh: bool = False) -> Dict[str, Any]:
    """Return the config as a dict, ``{}`` if it is missing or unreadable.

    The result is cached and invalidated whenever the file changes on disk, so
    callers may call this on every use without paying for repeated I/O and
    without going stale after an edit.
    """
    global _cache, _cache_stamp
    path = config_path()
    stamp = _stamp(path)
    with _lock:
        if not refresh and _cache is not None and _cache_stamp == stamp:
            return _cache
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        _cache, _cache_stamp = data, stamp
        return data


def get(key: str, default: Any = None) -> Any:
    """Read one key from the config."""
    return load().get(key, default)


def update(values: Dict[str, Any]) -> str:
    """Merge ``values`` into the config and write it back atomically.

    Merge-preserving on purpose: the launcher owns ``origin_path`` and
    ``gemini_api_key``, the naming helper owns ``name_presets``, and neither may
    drop the other's keys. The write goes to a temporary file in the same
    directory and is then replaced into place, so an interrupted save cannot
    leave a truncated config behind.
    """
    global _cache, _cache_stamp
    path = config_path()
    data = dict(load(refresh=True))
    data.update(values)

    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".physisfera_config.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    with _lock:
        _cache, _cache_stamp = data, _stamp(path)
    return path


def cell_area_cm2(override: Optional[float] = None) -> float:
    """Active device area [cm^2] used for current-density conversion.

    ``override`` lets a caller pass an explicit area (a per-analysis setting or
    a test) and still go through one validation path. Non-positive or
    unparseable values fall back to the historical default rather than
    producing an infinite conversion factor.
    """
    candidate = override if override is not None else get("cell_area_cm2",
                                                          DEFAULT_CELL_AREA_CM2)
    try:
        area = float(candidate)
    except (TypeError, ValueError):
        return DEFAULT_CELL_AREA_CM2
    return area if area > 0 and area != float("inf") else DEFAULT_CELL_AREA_CM2


def current_conversion_factor(area_cm2: Optional[float] = None) -> float:
    """Multiplier taking measured current [A] to current density [mA/cm^2].

    Negative because the source-meter reports photocurrent with the opposite
    sign to the photovoltaic convention.
    """
    return -1000.0 / cell_area_cm2(area_cm2)


def origin_path() -> str:
    """Configured path to ``Origin.exe``; empty string disables Origin export."""
    return str(get("origin_path", "") or "")


def api_key() -> Optional[str]:
    """Resolve the Gemini API key: environment first, then the config file.

    A key found in the config is exported into the environment so that modules
    reached later in the call chain -- including the Google SDK's own implicit
    lookup -- see it without repeating this search.
    """
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key

    data = load()
    for name in ("gemini_api_key", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        key = data.get(name)
        if key:
            os.environ.setdefault("GEMINI_API_KEY", str(key))
            os.environ.setdefault("GOOGLE_API_KEY", str(key))
            return str(key)
    return None
