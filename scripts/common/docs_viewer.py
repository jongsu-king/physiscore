"""Offline documentation: the Markdown files under docs/ are bundled with every
installer; this module turns one into a self-contained HTML page (standard
library only) and opens it in the default browser, optionally at a section.

    open_doc("METHODS", section="3.")      # METHODS.md at the heading "## 3. ..."

GitHub-style heading anchors are produced, so links between the documents and
anchors such as #3-eqe-scriptseqeeqe_corepy work as on GitHub.
"""
from __future__ import annotations

import html
import os
import re
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

DOCS = {
    "USER_GUIDE": "User guide",
    "METHODS": "Methods and algorithms",
    "VALIDATION": "Validation",
    "FILE_FORMATS": "File formats",
    "INSTALL": "Installation and updates",
    "CLI": "Command line",
}


def docs_dir() -> Optional[Path]:
    """The docs folder: next to the sources, or inside a PyInstaller bundle."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "docs")
    here = Path(__file__).resolve()
    candidates += [here.parents[2] / "docs", Path(sys.executable).resolve().parent / "docs"]
    for c in candidates:
        if (c / "USER_GUIDE.md").is_file():
            return c
    return None


def doc_path(name: str) -> Optional[Path]:
    d = docs_dir()
    if d is None:
        return None
    p = d / (name if name.endswith(".md") else f"{name}.md")
    return p if p.is_file() else None


def release_notes_path(version: str) -> Optional[Path]:
    d = docs_dir()
    p = d / "release-notes" / f"{version}.md" if d else None
    return p if p is not None and p.is_file() else None


# --------------------------------------------------------------------------- Markdown
def slug(text: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces -> '-'."""
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def _inline(text: str, base: Optional[Path]) -> str:
    codes: List[str] = []

    def keep_code(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"
    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = html.escape(text, quote=False)

    def img(m):
        alt, src = m.group(1), m.group(2)
        if base is not None and not re.match(r"[a-z]+:", src):
            src = (base / src).resolve().as_uri()
        return f'<img alt="{html.escape(alt)}" src="{html.escape(src)}">'
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", img, text)

    def link(m):
        label, href = m.group(1), m.group(2)
        if href.endswith(".md") or ".md#" in href:
            href = re.sub(r"\.md(#|$)", r".html\1", href)
        return f'<a href="{html.escape(href)}">{label}</a>'
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"&lt;(https?://[^&\s]+)&gt;", r'<a href="\1">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)
    return text


def markdown_to_html(md: str, title: str = "", base: Optional[Path] = None) -> str:
    """Convert the subset of Markdown used in docs/ (headings, paragraphs, nested
    lists, tables, fenced code, block quotes, images, links, emphasis) to HTML."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i, n = 0, len(lines)
    para: List[str] = []

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(s.strip() for s in para), base) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        if line.strip().startswith("```"):
            flush_para()
            lang = line.strip()[3:].strip()
            i += 1
            block = []
            while i < n and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre><code class="{html.escape(lang)}">' + html.escape("\n".join(block)) + "</code></pre>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para()
            level, text = len(m.group(1)), m.group(2).strip()
            out.append(f'<h{level} id="{slug(text)}">{_inline(text, base)}</h{level}>')
            i += 1
            continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            flush_para()
            out.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            flush_para()
            def cells(row):
                row = row.strip().strip("|")
                return [c.strip() for c in row.split("|")]
            head = cells(line)
            aligns = []
            for c in cells(lines[i + 1]):
                aligns.append("right" if c.endswith(":") and not c.startswith(":") else
                              "center" if c.startswith(":") and c.endswith(":") else "left")
            i += 2
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            t = ["<table><thead><tr>"]
            t += [f'<th style="text-align:{aligns[k] if k < len(aligns) else "left"}">{_inline(c, base)}</th>'
                  for k, c in enumerate(head)]
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>" + "".join(
                    f'<td style="text-align:{aligns[k] if k < len(aligns) else "left"}">{_inline(c, base)}</td>'
                    for k, c in enumerate(r)) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue
        if line.startswith(">"):
            flush_para()
            quote = []
            while i < n and lines[i].startswith(">"):
                quote.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote><p>" + _inline(" ".join(quote), base) + "</p></blockquote>")
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            flush_para()
            stack: List[tuple] = []          # (indent, tag)
            while i < n and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]) or
                             (lines[i].startswith("  ") and lines[i].strip() and stack)):
                cur = lines[i]
                mm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", cur)
                if not mm:                    # continuation line of the previous item
                    out[-1] = out[-1][:-5] + " " + _inline(cur.strip(), base) + "</li>"
                    i += 1
                    continue
                indent, marker, text = len(mm.group(1)), mm.group(2), mm.group(3)
                tag = "ol" if marker[0].isdigit() else "ul"
                while stack and indent < stack[-1][0]:
                    out.append(f"</{stack.pop()[1]}>")
                if not stack or indent > stack[-1][0]:
                    out.append(f"<{tag}>")
                    stack.append((indent, tag))
                out.append(f"<li>{_inline(text, base)}</li>")
                i += 1
            while stack:
                out.append(f"</{stack.pop()[1]}>")
            continue
        if not line.strip():
            flush_para()
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para()
    body = "\n".join(out)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title or "Physiscore")}</title>
<style>
body{{font:15px/1.6 -apple-system, "Segoe UI", Arial, sans-serif; color:#1b1f24; background:#fff;
     max-width:920px; margin:0 auto; padding:24px 28px 64px}}
header{{border-bottom:1px solid #cfd4da; margin-bottom:18px; padding-bottom:8px; color:#5a6472; font-size:13px}}
h1,h2,h3,h4{{line-height:1.25; margin:1.4em 0 .5em}} h1{{font-size:26px}} h2{{font-size:20px;border-bottom:1px solid #e3e6ea;padding-bottom:4px}}
h3{{font-size:17px}} code{{font:13px Menlo, Consolas, monospace; background:#f0f1f3; padding:1px 4px}}
pre{{background:#f6f7f9; border:1px solid #e3e6ea; padding:10px 12px; overflow:auto}} pre code{{background:none; padding:0}}
table{{border-collapse:collapse; margin:12px 0; font-size:14px; display:block; overflow-x:auto}}
th,td{{border:1px solid #cfd4da; padding:5px 9px; vertical-align:top}} th{{background:#dde2e8}}
tbody tr:nth-child(even){{background:#f4f6f8}} img{{max-width:100%; border:1px solid #cfd4da}}
blockquote{{border-left:3px solid #1f5fa8; margin:10px 0; padding:2px 12px; color:#3a4350; background:#f4f6f8}}
a{{color:#1f5fa8}}
</style></head><body><header>Physiscore offline documentation · {html.escape(title)}</header>
{body}
</body></html>"""


# --------------------------------------------------------------------------- opening
def _out_dir() -> Path:
    """Per-user cache folder for the rendered pages (never inside the program)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "Physiscore"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Physiscore"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "physiscore"
    d = base / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def render(path: Path, title: str = "") -> Path:
    """Write the HTML version of ``path`` (and, for links, of its sibling documents)."""
    out = _out_dir()
    target = out / (path.stem + ".html")
    target.write_text(markdown_to_html(path.read_text(encoding="utf-8"), title or path.stem, path.parent),
                      encoding="utf-8")
    return target


def section_anchor(path: Path, prefix: str) -> str:
    """Anchor of the first heading whose text starts with ``prefix`` (e.g. '3.')."""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m and m.group(1).strip().startswith(prefix):
            return slug(m.group(1).strip())
    return ""


def open_doc(name: str, section: Optional[str] = None, browser=webbrowser.open) -> Optional[Path]:
    """Render docs/<name>.md (and the other documents, so links work) and open it.
    Returns the HTML file, or None when the documentation is not bundled."""
    path = doc_path(name)
    if path is None:
        return None
    for other in DOCS:
        p = doc_path(other)
        if p is not None and p != path:
            try:
                render(p, DOCS.get(other, other))
            except Exception:
                pass
    html_file = render(path, DOCS.get(path.stem, path.stem))
    url = html_file.resolve().as_uri()
    if section:
        anchor = section_anchor(path, section)
        if anchor:
            url += "#" + anchor
    browser(url)
    return html_file


def open_release_notes(version: str, browser=webbrowser.open) -> Optional[Path]:
    path = release_notes_path(version)
    if path is None:
        return None
    out = _out_dir() / f"release-notes-{version}.html"
    out.write_text(markdown_to_html(path.read_text(encoding="utf-8"), f"What's new in {version}", path.parent),
                   encoding="utf-8")
    browser(out.resolve().as_uri())
    return out
