"""Text exports saved as UTF-16 ("Unicode text" of Windows programs) or with
Korean headers in cp949 are read like UTF-8 files by every reader (3.6.0).
Before 3.6.0 a UTF-16 file failed in the curve tools, XRD, Raman, FTIR, PL,
XPS and the J-V readers."""
import os

import numpy as np
import pandas as pd
import pytest

from conftest import measurement_columns, write_measurement
from scripts.common import curve_batch as cb
from scripts.common import textio

ENCODINGS = ("utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "cp949")


def _write(folder, kind, enc, header_suffix=""):
    cols, pre, sep = measurement_columns(kind)
    if header_suffix:
        cols = {k + header_suffix: v for k, v in cols.items()}
    path = os.path.join(str(folder), f"{kind}_{enc}.csv")
    text = pre + pd.DataFrame(cols).to_csv(index=False, sep=sep)
    with open(path, "wb") as fh:
        fh.write(text.encode(enc))
    return path


@pytest.mark.parametrize("enc,expect", [("utf-16", "utf-16-le"), ("utf-16-le", "utf-16-le"), ("utf-16-be", "utf-16-be"),
                                        ("utf-32", "utf-32-le"), ("utf-8", ""), ("utf-8-sig", ""), ("cp949", "")])
def test_wide_encoding_detection(enc, expect):
    raw = "파장 (nm),강도\n400.0,1.25\n401.0,1.30\n".encode(enc)
    assert textio.wide_encoding(raw) == expect
    assert textio.decode(raw).startswith("파장 (nm)")


def test_plain_files_are_passed_to_pandas_unchanged(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    assert textio.csv_source(str(p)) == str(p)
    q = tmp_path / "b.csv"
    q.write_bytes("x,y\n1,2\n3,4\n".encode("utf-16"))
    assert pd.read_csv(textio.csv_source(str(q))).shape == (2, 2)


@pytest.mark.parametrize("enc", ENCODINGS)
@pytest.mark.parametrize("tool", ["trpl", "eis", "cv", "stability", "sclc"])
def test_curve_tools_read_every_encoding(tmp_path, tool, enc):
    ref = write_measurement(tmp_path, tool, f"ref_{tool}.csv")
    other = _write(tmp_path, tool, enc, header_suffix=" 값" if enc == "cp949" else "")
    p = cb.parameters(tool, {"area_cm2": 0.1} if tool in cb.AREA_FROM_SETTINGS else {})
    a, b = cb.load(tool, ref, p), cb.load(tool, other, p)
    for key in a:
        if not key.startswith("_"):
            np.testing.assert_allclose(np.asarray(b[key], float), np.asarray(a[key], float))


@pytest.mark.parametrize("enc", ENCODINGS)
def test_spectrum_readers_read_every_encoding(tmp_path, enc):
    from scripts.FTIR import ftir_core
    from scripts.PL import pl_core
    from scripts.Raman import raman_core
    from scripts.XRD import xrd_core
    from spectra.core.utils import robust_read_csv
    x_ref, y_ref = xrd_core.load_data(write_measurement(tmp_path, "xrd", "ref.xy"))
    x, y = xrd_core.load_data(_write(tmp_path, "xrd", enc))
    np.testing.assert_allclose(x, x_ref)
    np.testing.assert_allclose(y, y_ref)
    for kind, loader in (("raman", raman_core.load_data), ("ftir", ftir_core.load_data)):
        ref = loader(write_measurement(tmp_path, kind, f"ref_{kind}.csv"))[0]
        got = loader(_write(tmp_path, kind, enc))[0]
        np.testing.assert_allclose(got["wavenumbers"], ref["wavenumbers"])
        np.testing.assert_allclose(got["intensities"], ref["intensities"])
    ref_df, _ = pl_core.load_data_preview(write_measurement(tmp_path, "pl", "ref_pl.csv"))
    got_df, _ = pl_core.load_data_preview(_write(tmp_path, "pl", enc))
    np.testing.assert_allclose(got_df.to_numpy(float), ref_df.to_numpy(float))
    ref_x = robust_read_csv(write_measurement(tmp_path, "xps", "ref_xps.csv"))
    got_x = robust_read_csv(_write(tmp_path, "xps", enc))
    np.testing.assert_allclose(got_x.to_numpy(float), ref_x.to_numpy(float))


@pytest.mark.parametrize("enc", ("utf-16", "utf-16-le", "cp949"))
def test_source_meter_jv_file_in_a_wide_encoding(tmp_path, enc, jv_sweep):
    from conftest import single_diode_jv
    from scripts.JV import jv_core
    v = jv_sweep
    j = single_diode_jv(v)                              # mA/cm2
    lines = ["Keithley 2400 export", "Vmeas\tImeas"] + [f"{a:.4f}\t{-b * 0.1e-3:.6e}" for a, b in zip(v, j)]
    ref, other = tmp_path / "ref.txt", tmp_path / f"cell_{enc}.txt"
    ref.write_text("\n".join(lines) + "\n", encoding="utf-8")
    other.write_bytes(("\n".join(lines) + "\n").encode(enc))
    va, ja = jv_core.read_jv_curve(str(ref), area_cm2=0.1)
    vb, jb = jv_core.read_jv_curve(str(other), area_cm2=0.1)
    assert len(va) > 10
    np.testing.assert_allclose(vb, va)
    np.testing.assert_allclose(jb, ja)
