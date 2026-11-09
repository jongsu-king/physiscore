[2026-07-02 정리] 이 폴더의 파일들은 현재 어떤 코드에서도 import되지 않는 구버전 복사본입니다.

- abs_core.py     : scripts/Abs/abs_core.py 였음. run_abs.py가 사용하지 않는 옛 단독 구현 (675줄)
- eqe_core.py     : scripts/EQE/eqe_core.py 였음. run_eqe.py가 사용하지 않는 옛 단독 구현 (1,136줄)
- sem_app_old.py  : scripts/SEM/app.py.py 였음. run_sem.py로 대체된 옛 SEM GUI (468줄)

필요 시 다시 꺼내 쓸 수 있도록 삭제하지 않고 보관합니다.

[2026-11-09] Moved here with the 3.0.0 release; nothing imports or builds them:
- main gui_test3.py, Physiscore.spec, Physiscore_v2.spec, build_exe.bat, build_exe_v2.bat:
  the pre-2.1 Windows-only exe entry point and its PyInstaller specs. The installers
  for every platform are built from packaging/physiscore.spec by .github/workflows/release.yml.
- db read.py: a one-off reader for the DTU CMR organometal database, unrelated to the suite.
- JV_Analysis_exe_분석리포트.md: notes on the external JV_Analysis.exe (its conveniences
  were re-implemented in scripts/common/plot_interactions.py and sample_naming.py).
