"""3.3: offline documentation and the Origin-style plot pass."""
import pytest

from scripts.common import docs_viewer as dv
from scripts.common import palette as _pal


def test_markdown_subset(tmp_path):
    md = """# Title

## 3. EQE (`scripts/EQE/eqe_core.py`)

Text with **bold**, *italic*, `code` and a [link](METHODS.md#3-eqe) and <https://example.org>.

| Quantity | Value |
|---|---:|
| Jsc | 22.0 |

- one
  - nested
- two

1. first
2. second

```bash
pytest -q
```

> note

![fig](images/a.png)
"""
    html = dv.markdown_to_html(md, "T", base=tmp_path)
    assert '<h2 id="3-eqe-scriptseqeeqe_corepy">' in html          # GitHub anchor
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html and "<code>code</code>" in html
    assert 'href="METHODS.html#3-eqe"' in html                        # .md links follow the HTML copies
    assert 'href="https://example.org"' in html
    assert "<table>" in html and 'text-align:right' in html
    assert html.count("<ul>") == 2 and "<ol>" in html               # nested list, numbered list
    assert "<pre><code" in html and "pytest -q" in html
    assert "<blockquote>" in html
    assert (tmp_path / "images" / "a.png").as_uri() in html          # images resolved to the bundled files


def test_bundled_documents_open_at_a_section(tmp_path, monkeypatch):
    monkeypatch.setattr(dv, "_out_dir", lambda: tmp_path)
    for name in dv.DOCS:
        assert dv.doc_path(name) is not None, name
    opened = []
    page = dv.open_doc("METHODS", section="3.", browser=opened.append)
    assert page is not None and page.parent == tmp_path
    assert opened[0].endswith("#" + dv.section_anchor(dv.doc_path("METHODS"), "3."))
    assert (tmp_path / "USER_GUIDE.html").exists()                    # siblings rendered for the links
    assert dv.open_doc("NO_SUCH_DOC", browser=opened.append) is None


def test_release_notes_of_this_version_are_bundled():
    from Physiscore_Launcher import APP_VERSION
    assert dv.release_notes_path(APP_VERSION) is not None


def test_origin_style_pass():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import AutoMinorLocator
    _pal.apply_mpl()
    fig, (a, b) = plt.subplots(1, 2)
    a.plot([0, 1, 2], [0, 1, 4], label="data")
    a.grid(True)                                   # a window's own grid call
    a.legend()
    twin = a.twinx()
    twin.plot([0, 1, 2], [1, 2, 3])
    b.plot([1, 2], [1, 2])
    b._physiscore_grid = True                      # switched on by the user (View -> Toggle grid)
    _pal.originize(fig)
    assert all(sp.get_linewidth() == 1.5 for sp in a.spines.values())
    assert not any(l.get_visible() for l in a.get_xgridlines())     # Origin: no grid
    assert any(l.get_visible() for l in b.get_xgridlines())         # but the user's grid stays
    assert isinstance(b.xaxis.get_minor_locator(), AutoMinorLocator)
    assert twin.yaxis.get_ticks_position() in ("right", "default")  # the twin keeps its own side
    frame = a.get_legend().get_frame()
    assert matplotlib.colors.to_hex(frame.get_edgecolor()) == "#000000"
    assert matplotlib.rcParams["axes.grid"] is False
    plt.close(fig)


def test_origin_colour_order():
    assert _pal.COLOR_SETS["origin"][:4] == ["#000000", "#FF0000", "#0000FF", "#FF00FF"]
    assert len(_pal.COLOR_SETS["colorblind"]) == 10


def test_cli_docs_list(capsys):
    import physiscore_cli
    assert physiscore_cli.main(["docs", "list"]) == 0
    assert "METHODS" in capsys.readouterr().out
