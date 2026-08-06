"""Sample-name helpers shared by the file-parsing cores.

``natural_sort_key`` and the display-name normalisation below were duplicated
verbatim in the J-V and dark-J-V cores. Keeping two copies of the rules that
decide how a measurement file becomes a sample label meant a fix to one scan
type silently did not apply to the other, even though both read files exported
by the same source-meter.
"""
from __future__ import annotations

import os
import re

# "<name> 2026-01-20 18-35-48" -> the instrument appends the export timestamp
_TIMESTAMP_SUFFIX = re.compile(r"\s+\d{4}-\d{2}-\d{2}\s+\d{2}-\d{2}-\d{2}$")
# "01. sample name" -> leading export sequence number
_LEADING_INDEX = re.compile(r"^\d+\.\s+")
# "110C" -> "110°C"
_TEMPERATURE = re.compile(r"(\d+)C\b")
_NUMBER_CHUNK = re.compile(r"(\d+\.?\d*)")


def natural_sort_key(s):
    """Sort key that orders embedded numbers numerically.

    Gives 2k < 2.5k < 3k, where a plain lexicographic sort gives 2.5k < 2k < 3k.
    """
    def convert(text):
        if text.replace(".", "", 1).isdigit():
            return float(text)
        return text.lower()
    return [convert(c) for c in _NUMBER_CHUNK.split(str(s))]


def display_name_from_path(file_path: str) -> str:
    """Turn a measurement file path into the sample label shown in the UI.

    Strips the extension, the instrument's export timestamp, and the leading
    export sequence number; then applies the lab's display conventions
    (underscores as spaces, ``110C`` as ``110°C``).

    The extension is removed by exact suffix rather than by splitting on the
    last dot so that names carrying a decimal -- ``sample 2.5k`` -- keep it.
    """
    filename = os.path.basename(file_path)
    if filename.lower().endswith(".txt"):
        name = filename[:-4]
    else:
        last_dot = filename.rfind(".")
        name = filename[:last_dot] if last_dot > 0 else filename

    name = _TIMESTAMP_SUFFIX.sub("", name)
    name = re.sub(r"\.$", "", name)          # trailing dot after a cell number
    name = _LEADING_INDEX.sub("", name)
    name = name.replace("_", " ")
    return _TEMPERATURE.sub(r"\1°C", name)


def base_name(sample_name: str) -> str:
    """Condition name shared by the cells of one group: ``Ref 3`` -> ``Ref``."""
    return re.sub(r"\d+$", "", str(sample_name).strip())


def cell_number(sample_name: str) -> int:
    """Trailing cell index of a sample name; 0 when it carries none."""
    match = re.search(r"(\d+)$", str(sample_name).strip())
    return int(match.group(1)) if match else 0
