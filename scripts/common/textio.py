"""Text exports in the encodings instrument software writes.

Most exports are UTF-8 or the Windows code page (cp949 on Korean systems),
which every reader here handles. Some Windows programs save "Unicode text",
which is UTF-16 (with or without a byte-order mark); read as UTF-8 it fails
or turns every character into two. These helpers detect UTF-16/UTF-32 by
the byte-order mark or by the pattern of zero bytes and hand the decoded
text on, so that the readers keep their own parsing.
"""
from __future__ import annotations

import codecs
import io
from typing import Union

_BOMS = ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
         (codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"))
_FALLBACKS = ("utf-8", "cp949", "latin-1")


def wide_encoding(raw: bytes) -> str:
    """'utf-16-le', 'utf-16-be', 'utf-32-le' or 'utf-32-be' when the bytes
    are a wide encoding (byte-order mark, or text whose every second byte is
    zero), else ''."""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            return "" if enc == "utf-8-sig" else enc
    head = raw[:4096]
    if len(head) < 8:
        return ""
    even, odd = head[0::2], head[1::2]
    if odd.count(0) > 0.4 * len(odd) and even.count(0) < 0.05 * len(even):
        return "utf-16-le"
    if even.count(0) > 0.4 * len(even) and odd.count(0) < 0.05 * len(odd):
        return "utf-16-be"
    return ""


def decode(raw: bytes) -> str:
    """Bytes of a text export -> str: wide encodings first, then UTF-8 (a
    byte-order mark removed), cp949 and latin-1 (which never fails)."""
    enc = wide_encoding(raw)
    if enc:
        text = raw.decode(enc, errors="replace")
        return text[1:] if text.startswith("﻿") else text
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8):]
    for e in _FALLBACKS:
        try:
            return raw.decode(e)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def read_text(path: str) -> str:
    with open(path, "rb") as fh:
        return decode(fh.read())


def csv_source(path: str) -> Union[str, io.StringIO]:
    """What to give pandas.read_csv: the path itself for an ordinary file
    (so that nothing changes for it), or the decoded text of a UTF-16/32
    file."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return path
    if wide_encoding(head):
        return io.StringIO(read_text(path))
    return path
