# -*- coding: utf-8 -*-
"""
CMR 'organometal' DB (DTU) 판독 스크립트
- ASE database(SQLite) -> 조성비 축으로 재구성한 표 + 피벗 + 그래프
"""
import os, sys, urllib.request
import pandas as pd
from ase.db import connect

URL = "https://wiki.fysik.dtu.dk/cmr-files/organometal.db"
DB  = sys.argv[1] if len(sys.argv) > 1 else "organometal.db"
OUT = "organometal_readable"

if not os.path.exists(DB):
    print(f"[1/4] 다운로드: {URL}")
    urllib.request.urlretrieve(URL, DB)

print(f"[2/4] 판독: {DB}")
rows = []
for r in connect(DB).select():
    c = r.count_atoms()                      # {'Cs':1,'Pb':1,'I':3, ...}
    nB = c.get('Pb', 0) + c.get('Sn', 0)     # B-site 개수 = 화학식 단위 수
    if nB == 0:
        continue

    # --- A-site 판별: Cs / MA(CH3NH3, N:C=1) / FA(HC(NH2)2, N:C=2) ---
    if c.get('Cs', 0):
        A = 'Cs'
    else:
        A = 'FA' if c.get('N', 0) == 2 * c.get('C', 0) else 'MA'
    B = 'Pb' if c.get('Pb', 0) else 'Sn'

    # --- 할라이드 조성비: B-site 1개당 개수 (합 = 3) ---
    nI, nBr, nCl = (c.get(x, 0) / nB for x in ('I', 'Br', 'Cl'))

    rows.append(dict(
        name=r.name, A=A, B=B,
        n_I=round(nI, 3), n_Br=round(nBr, 3), n_Cl=round(nCl, 3),
        x_I=round(nI/3, 3), x_Br=round(nBr/3, 3), x_Cl=round(nCl/3, 3),
        halide=''.join(e + ('' if n == 1 else str(int(n) if n == int(n) else n))
                       for e, n in [('I',nI),('Br',nBr),('Cl',nCl)] if n),
        symmetry=r.symmetry, space_group=r.space_group,
        Eg_direct=r.gllbsc_dir_gap, Eg_indirect=r.gllbsc_ind_gap,
        deriv_disc=r.gllbsc_disc,
        gap_type='direct' if abs(r.gllbsc_dir_gap - r.gllbsc_ind_gap) < 1e-6 else 'indirect',
        n_atoms=r.natoms, volume=round(r.volume, 2),
        energy=round(getattr(r, "energy", float("nan")), 3),
    ))

df = pd.DataFrame(rows).sort_values(['A','B','n_I','n_Br','symmetry'], ascending=[1,1,0,0,1])
print(f"      -> {len(df)} rows | A={sorted(df.A.unique())} B={sorted(df.B.unique())} "
      f"symmetry={sorted(df.symmetry.unique())}")

print("[3/4] 저장")
df.to_csv(f"{OUT}.csv", index=False, encoding='utf-8-sig')
with pd.ExcelWriter(f"{OUT}.xlsx", engine='openpyxl') as w:
    df.to_excel(w, sheet_name='full', index=False)
    for sym in df.symmetry.unique():
        d = df[df.symmetry == sym]
        (d.pivot_table(index=['A','B'], columns='halide',
                       values='Eg_indirect', aggfunc='first')
          .to_excel(w, sheet_name=f'pivot_{sym[:20]}'))

print("[4/4] 그래프")
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
syms = sorted(df.symmetry.unique())
fig, axes = plt.subplots(1, len(syms), figsize=(5*len(syms), 4.2), sharey=True, squeeze=False)
for ax, sym in zip(axes[0], syms):
    d = df[df.symmetry == sym]
    for (A, B), g in d.groupby(['A','B']):
        g = g.sort_values('n_I', ascending=False)
        ax.plot(g.n_I, g.Eg_indirect, 'o-', ms=5, lw=1.2, label=f'{A}{B}')
    ax.set(title=sym, xlabel='I per B-site  (I$_3$ → Cl$_3$)')
    ax.grid(alpha=.3); ax.invert_xaxis()
axes[0][0].set_ylabel('$E_g$ indirect, GLLB-SC+SOC  [eV]')
axes[0][-1].legend(fontsize=8, ncol=2)
plt.tight_layout(); plt.savefig(f"{OUT}_bandgap.png", dpi=150)

print(f"\n완료: {OUT}.csv / {OUT}.xlsx / {OUT}_bandgap.png")
print(df.head(8).to_string(index=False))