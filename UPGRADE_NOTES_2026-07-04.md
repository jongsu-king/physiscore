# Physiscore 논문급 업그레이드 노트

## 10차 — UI 통일 + JV_Analysis.exe 편의 기능 완성 (2026-07-07)

**UI 전수 비교 감사 결과**: 색상은 이미 theme 토큰(#0A0A0A/#141414/#1E1E1E/#3182F6...)으로 거의
통일돼 있었고, 실제 이탈은 (a) 버튼 높이 — EQE·Abs의 38px, PL의 34px가 JV 표준(주 42/보조 40/칩 26)과
다름 → 40으로 통일, (b) 텍스트 회색 #E0E0E0 4곳 → #DDDDDD 토큰으로 통일. 상단 툴바는 analysis_shell
공용 크롬이라 원래 전 도구 동일.

**JV_Analysis.exe 편의 기능 완성** (`scripts/common/sample_naming.py` 신설):

- 우클릭 메뉴 전체 세트: Rename(F2) · **Rename to preset ▸**(전역 프리셋, config 공유) ·
  **Compose name from presets...**("ZnO / PDINN"식 조합) · Add current name to presets ·
  **Edit presets...** · **Batch rename...**(찾기/바꾸기+공통 접두어 제거+실시간 미리보기+중복 검사) ·
  **Revert to original name**(연쇄 rename 추적) · 행/표 복사. → JV·Dark JV 적용.
- **＋ Add 폴더 비교**: 여러 폴더를 겹쳐 한 번에 Process. 중복 샘플명은 ' (2)' 접미사로 분리
  (기존엔 조용히 평균됨). 코어가 단일/다중 폴더 모두 수용. → JV·Dark JV.
- **🕘 Recent 폴더** 메뉴(최근 8개, config 저장, 클릭 즉시 Process). jv/dark config 저장을
  merge-preserve로 바꿔 recent가 지워지지 않게 함.
- 검증: 프리셋 저장/중복제거, rename→조합→원복 체인, 폴더 2개 병합(ctrl1=20.0 / ctrl1 (2)=23.0
  분리 유지), Dark 다중 폴더, 전체 컴파일·import 통과. exe 스펙 hiddenimports 갱신.

## 9차 재검수 (2026-07-07)

1. **Excel 잠금(열려 있는 파일) 시 저장 무음 실패 — 중대 버그** — JV/Dark JV는 Process가 폴더의
   결과 xlsx를 자동 저장하는데, 그 파일을 Excel로 열어둔 채 다시 Process하면 PermissionError가
   조용히 삼켜져 **파일에는 이전 데이터가 그대로 남고 사용자는 갱신됐다고 착각**하게 됐음.
   → 잠겨 있으면 `<이름>_HHMMSS.xlsx`로 자동 우회 저장 + 로그에 명시, 실패 시 [ERROR] 로그.
   JV·Dark JV·EQE 세 곳 적용 (모의 잠금 테스트로 폴백 경로 검증 완료).
2. **모듈 간 참조 무결성 감사** — run_jv→AI 창(update_data 등), run_jv→JVAIIntegration,
   run_xrd→tab 접근 전수 검사: 누락 0건.

## 8차 — JV_Analysis.exe 편의 기능 전 도구 이식 (2026-07-07)

원본 JV_Analysis.exe(PySide6, 소스 복원 불가)의 편의 기능을 공용 모듈
`scripts/common/plot_interactions.py`로 재구현해 tkinter 도구 전체에 이식.

- **Dark JV legend 오류 수정**: 샘플이 많거나 이름이 길면 범례가 플롯 전체를 덮던 문제.
  전 도구 공통 `smart_legend()` — 중복 제거, 24자 초과 말줄임, 최대 10개 + "+N more",
  6개 이상이면 2열. (검증: 긴 이름 14개 샘플 → 10개 항목 2열, 잘림 정상)
- **마우스 그래프 조작 (exe와 동일)**: 휠 줌(커서 중심, Ctrl=X축만, Shift=Y축만, log축 지원),
  좌클릭 드래그 이동, 더블클릭 Auto Range.
  → JV·Dark JV·PL(줌+이동), EQE·Abs·XRD(줌만 — 좌드래그는 피팅 선택에 사용), Raman·FTIR(기존 Ctrl 줌/이동 유지).
- **그래프 우클릭 메뉴 (전 도구)**: Auto Range / Toggle Legend / Toggle Grid / Save Figure(Publication).
- **표 우클릭 메뉴**: JV·Dark JV — 이름 바꾸기(F2, 그래프·통계·박스차트·선택 상태 동기 반영, 중복 방지),
  선택 행 복사(Ctrl+C), 전체 표 복사. XRD 피크 표 — 복사.
  (검증: JV 그룹 rename이 best_performance/best_combined/box_charts/statistics 전부 반영, 중복 가드 동작)
- exe 스펙 hiddenimports에 공용 모듈 추가(함수 내부 import라 PyInstaller가 놓치는 것 방지).

## 7차 재검수 (2026-07-07)

1. **빈/비정상 입력 가드 3곳** — 형식이 안 맞는 파일을 열어 파싱 결과가 0행이 되면 Raman/FTIR `detect_peaks`와 XRD `detect_peaks_and_fit`이 numpy 예외("zero-size array...")를 사용자에게 그대로 팝업했음 → 빈 결과 반환으로 가드.
2. 무결성 스캔 — 9개 도구 전부 `AnalysisWindow` 클래스/별칭과 `__main__` 가드 정상(launcher 연동 이상 없음), spectra/app.py 정독(이상 없음).
3. 누적 회귀 테스트 재실행 — EQE Jsc(37.463), JV Voc/Jsc, Dark n, XRD 3피크+Scherrer, PL FWHM/ALS, 실측 XPS C1s 284.5 eV, AI DB "non" 안전성: 전부 통과. 물리 스위트 실행 중 deprecation 경고 0건.

## 6차 재검수 (2026-07-07)

1. **스레드-안전 로깅 (간헐 크래시/프리즈의 유력 원인)** — JV·Dark JV의 `log()`가 Process/AI 워커 스레드에서 tk 텍스트박스를 직접 조작(12개 호출 지점)했고, spectra 두 탭의 `_log`도 파이프라인 스레드에서 직접 insert + `update_idletasks()`까지 호출. tkinter는 메인 스레드 외 접근 시 무작위 크래시/프리즈가 발생함. 네 곳 모두 메인스레드 판별 후 `after()`로 마샬링하도록 수정.
2. **AI가 한국어로 답하던 잔존 경로 4곳** — run_raman/run_ftir이 컨텍스트에 `[OUTPUT: Korean]`을 주입해 core의 영어 지시를 덮어썼고, SEM 어드바이저 프롬프트 2곳도 "Respond in Korean". 전부 영어로 통일 (전 프로젝트 잔존 0 확인).
3. **matplotlib 호환성** — `boxplot(labels=...)`은 3.9에서 `tick_labels`로 개명되고 제거 예정. 신·구 버전 모두 동작하도록 폴백 처리 (mpl 3.10에서 동작 검증).
4. 라이브러리 호환 전수 스캔 — pandas 2.x 제거 API(DataFrame.append), Pillow 10 제거 API(ANTIALIAS), np.trapz 사용처: 문제 없음 확인.

## 5차 재검수 (2026-07-07)

1. **v1 exe 진입점(main gui_test3.py)의 설정 덮어쓰기** — Physiscore.spec의 실제 엔트리가 main gui_test3.py임을 확인하고, launcher와 동일한 config 통째 덮어쓰기 버그(→ cell_area_cm2 소실)를 merge-preserve로 수정.
2. **요약 블록 없는 측정 파일 처리 불가** — JV/Dark JV 파일에 장비 요약(Voc/Jsc/FF/PCE 또는 RShunt 행)이 없으면 곡선이 멀쩡해도 "No valid data found"로 중단됐음. 곡선만 있으면 샘플로 등록해 곡선 기반 분석(CurveAnalysis/다이오드 피팅)으로 처리하도록 수정 (검증: 요약 없는 파일에서 Voc=1.000/Jsc=22.0/PCE=18.5, dark n=1.845 정상 산출).
3. **spectra AI 리포트가 항상 비활성** — report.py가 프로젝트에서 안 쓰는 신SDK(google.genai, requirements에 없음)를 import해 Gemini 분기가 영영 꺼져 있었고, config 탐색 경로도 프로젝트 루트보다 한 단계 위를 보고 있었음. 표준 SDK(google.generativeai)로 포팅 + 경로 수정 + LLM 실패 시 rule-based 리포트는 계속 생성되도록 예외 격리.
4. **JV AI 어시스턴트 크래시** — 요약값이 "non"(파싱 실패/요약 없음)인 샘플이 하나라도 있으면 `float("non")`으로 해시 계산과 DB 저장이 터져 AI 리포트 전체가 실패. 안전 변환(None 저장, SQLite AVG는 NULL 무시)으로 수정 (저장·중복제거·통계 재검증).

## 4차 재검수 (2026-07-07)

1. **설정 파일 키 소실** — launcher의 설정 저장이 physisfera_config.json을 통째로 덮어써서 `cell_area_cm2`(셀 면적) 키가 설정 저장 때마다 삭제됐음 → 기존 키 보존(merge) 방식으로 수정. 도구별 config(jv/dark_jv/sem/ftir/raman)는 파일이 분리되어 상호 간섭 없음 확인.
2. **spectra PL 탭 Excel 내보내기 크래시 가능성** — 레이어 이름이 시트명이 되는데 31자 초과·특수문자(`[]:*?/\`)·중복 이름이면 openpyxl이 예외 → 정제 + 중복 자동 접미사 처리.
3. **FTIR/Raman AI 모델 조회 스레드** — 워커 스레드에서 `winfo_exists()`(tk 호출)를 사용하던 것을 제거하고 `after()` 단독 hand-off로 변경(간헐적 크래시 예방). 전체 코드 AST 스레드-안전성 스캔에서 그 외 위반 0건.
4. 미독 영역 전수 확인 — spectra peak_detect(이상 없음), EQE/PL/FTIR/SEM 내보내기 경로, XRD 범위 재피팅 호출부(새 시그니처와 호환), Origin 워크북 이름 길이, jv_ai_assistant의 processed_data 접근 키 호환성. 모두 정상.

컴파일 50/50, import 재검증 통과.

## 3차 심층 버그 사냥 (2026-07-07)

정적 분석(pyflakes: 치명 오류 0) + 실데이터 런타임 실행으로 6건 추가 수정.

1. **XPS 파이프라인이 실행 즉시 크래시** — `run_xps_pipeline`이 `PipelineConfig`에 존재하지 않는 필드 5개(xps_roi_min/max, xps_split_ev, xps_area_ratio, xps_lock_widths)를 참조. 필드 추가로 해결.
2. **실제 XPS 내보내기 CSV를 열 수 없었음** — 장비 내보내기 파일(glass-O1s.csv 등)은 숫자 데이터 앞에 메타데이터 4줄이 있어 `pd.read_csv`가 ParserError. `robust_read_csv()`(메타데이터 프리앰블 자동 스킵, 구분자 자동 감지)를 spectra 대시보드 로더 2곳 + PL 탭 로더에 적용. 실측 XPS 6개 파일 전부 로드 확인.
3. **XPS 피팅 최소 점수 요건이 실데이터를 원천 거부** — 피팅 창 최소 60/80점 요구인데 실제 지역 스캔은 0.2 eV 간격이라 창당 ~25점. 자유 파라미터 수 기반(15~20점)으로 완화. → 실데이터 결과: C1s 284.5 eV(외래탄소 문헌값), N1s 398.3 eV(PEI 아민), O1s 531.5 eV 등 물리적으로 타당.
4. **XPS 단일항/이중항 구분** — 기존 코드는 모든 피크를 이중항으로 피팅(split=0이면 동일 피크 2개 중첩이라는 비물리적 결과). split_ev=0(기본)이면 단일 Voigt, >0이면 스핀-궤도 이중항으로 분기.
5. **.TXT 대문자 확장자 무시** — JV/Dark JV 폴더 스캔이 소문자 `.txt`만 인식해 대문자 파일이 조용히 누락됐음(검증: 3개 중 2개만 처리 → 수정 후 전부 처리).
6. **requirements.txt에 openpyxl·xlrd 누락** — .xls 열기(EQE)와 Excel 저장이 새 환경에서 크래시할 수 있었음.

런타임 전수 검증: 50파일 컴파일, 28모듈 import, SEM 합성이미지 4/4 입자 분할(직경 오차 <2%), Dark JV/JV/EQE/XRD 회귀 테스트 전부 통과.

## 2차 검수 (2026-07-07, 폴더 재연결 후)

GUI 레이어 전체(run_* 10종 + launcher + spectra)를 재감사했습니다.

**물리적으로 이미 올바르게 구현되어 있음을 확인한 것들:** XRD Williamson–Hall 플롯(βcosθ=Kλ/D+4ε·sinθ, 라디안 변환·R²·기기선폭 미보정 주석까지 정확), Abs Tauc x절편 Eg + 예상 Eg 기반 최대기울기 자동 피팅, EQE 요약 카드(Jsc/Eg fit/Eg deriv/Eu)와 Auto Fit, 전 도구 AI 키 가드 및 피크 클릭 핸들러, launcher의 exe/dev 분기 실행.

**이번에 발견·수정한 문제 3건:**

1. **PL ALS 베이스라인 퇴화 (실사용 버그)** — Peak Protection 슬라이더 기본값이 0인데, ALS의 p=0이면 베이스라인이 스펙트럼의 **위쪽 포락선**이 되어 보정 후 신호가 전부 0으로 붕괴. 사용자가 기본값 그대로 Rigidity만 올리면 스펙트럼이 사라지는 현상. → core에서 p를 [0.001, 0.5]로 클램프. (검증: p=0 입력에서도 피크 보존, FWHM 40.0/40.0 정확)
2. **JV 통계 카드 의미 오류** — "평균"이 조건별 최고 소자들만의 평균이었음(통계적으로 무의미). → **전체 소자 mean±std**로 교체(논문 보고 방식), Best PCE는 유지.
3. **SEM 입도 표준편차** — 모표준편차(ddof=0) → 표본표준편차(ddof=1)로 수정.

**논문용 그림 내보내기 런타임 검증:** 다크테마 그림 → 600 dpi PNG/SVG 변환, 축·글자·범례 흑색화, 화면 그림 무손상 확인.

---

# 1차 업그레이드 (2026-07-04)

## 발견·수정된 실제 버그

1. **EQE %→분율 변환 무효 코드** (`run_eqe.py`)
   `eqe_frac = eqe if max>1 else eqe` — 조건 양쪽이 동일해서 변환이 아예 안 됨.
   `/1240/1000` 상수의 우연한 상쇄로 %입력만 맞고, 분율(0–1) 입력이면 적분 Jsc가 1000배 틀렸음.
   → 명시적 단위 판별 + `e/(hc)=1/1239.842` 기반 정확한 유도식으로 교체.

2. **AM1.5G 스펙트럼이 71점짜리 근사표** (`run_eqe.py`)
   290–990 nm, 10 nm 간격 + 990 nm 밖은 상수 외삽(0.735!) → NIR 소자 Jsc 왜곡.
   → `rawdata/am1.5g.xlsx`에서 추출한 **ASTM G173-03 전해상도 데이터(2002점, 280–4000 nm, 적분 1000.4 W/m²)**를
   `scripts/EQE/astm_g173_global.csv`로 번들. 적분은 두 그리드의 합집합에서 수행(해상도 손실 없음), 범위 밖은 0 처리.

3. **Dark JV 데이터를 소수 2자리로 반올림** (`dark_jv_core.py`)
   log 스케일(1e-5~100 mA/cm²) 데이터에서 0.005 이하 저전류 영역이 전부 파괴됐음. → 반올림 제거(전정밀 유지).

4. **XRD 피팅의 배경/중첩 처리 오류** (`xrd_core.py`)
   피크마다 국소 최소값을 따로 빼고 전 구간에 더하는 방식이라 중첩 피크 꼬리가 이중 계상되고 합성 곡선의 기준선이 어긋났음.
   → **ALS 전역 배경 + 겹치는 피크는 pseudo-Voigt로 동시 피팅**하는 방식으로 재작성.

5. **RShunt 열 인덱스 하드코딩(11)** (`dark_jv_core.py`) → 헤더 이름으로 열 탐색.

6. **박스차트 그룹당 8개 셀 제한** (`jv_core.py`) — 9번째 소자부터 통계에서 조용히 누락됐음 → 제한 제거.

7. 기타: `Intergrated` 오타, 잔여 디버그 타이틀(`|/hooks`), XRD/Raman/FTIR AI 프롬프트에 남아있던 "한국어로 답변" 지시(영문화 방침과 모순) 수정. Excel 내보내기 반올림 2→4자리(기울기 기반 저항 분석 가능하도록).

## 논문급 신규 기능

- **JV: 곡선 기반 파라미터 직접 계산** (`compute_jv_parameters`)
  장비 요약값에 의존하지 않고 J–V 곡선에서 Voc, Jsc, FF, PCE, Vmpp/Jmpp, Pmax와 **Rs(Voc 기울기), Rsh(Jsc 기울기)** [Ω·cm²]를 추출.
  Excel에 `CurveAnalysis`(장비값 교차검증용), `Statistics`(조건별 mean ± std ± best, N) 시트 추가.
- **Dark JV: 다이오드 파라미터 자동 추출** (`analyze_dark_diode`)
  ln(J)–V 슬라이딩 윈도우로 가장 선형인 구간을 자동 선택해 **ideality n, J0**, 저전압 구간에서 **Rsh_dark** 계산. GUI 표와 Excel에 표시.
- **XRD: Scherrer 결정립 크기** τ = Kλ/(β·cosθ) (K=0.9, Cu Kα, 기기 선폭 보정 옵션) + 피크별 R², pseudo-Voigt η. GUI 표에 τ(nm) 열 추가.
- **PL: 가우시안 피팅 윈도우화** — 다중 피크/배경이 있어도 주 피크만 정확히 피팅(σ 초기값도 실측 반치폭 기반).
- **전 도구 공통 그림 내보내기 논문 스타일화** — PNG 버튼이 흰 배경·검정 축/글자·안쪽 눈금·600 dpi로 저장, SVG/PDF 벡터 지원(화면 다크테마는 그대로).
- **셀 면적 설정화** — `physisfera_config.json`의 `cell_area_cm2`(기본 0.04)로 -25000 하드코딩 대체. exe 스펙에 데이터 파일 번들 추가.

## 검증 (34/34 통과)

- 50개 파일 전체 컴파일 + 24개 모듈 import + AST 미정의 self 메서드 0건 + 프로젝트 한글 0건.
- EQE: EQE=100% 적분 Jsc가 독립 계산 기준값과 37.463 mA/cm²로 일치(<0.2%), %/분율 입력 동일 결과.
- JV: 합성 단일 다이오드 곡선(Rs=2, Rsh=2000)에서 Voc/Jsc/FF/PCE 재현, Rsh 슬로프 2002 Ω·cm² 회수.
- Dark JV: n=1.85 합성 곡선 → n=1.92 회수, Rsh 5×10⁴ → 49999.
- XRD: 중첩 이중 피크(Δ2θ=0.4°) 중심 ±0.001°, FWHM 오차 <1%, Scherrer 수기 계산과 일치. 실측 peroV 데이터에서 페로브스카이트 (110)/(220) = 14.10°/28.42° 검출, 피팅 R²=0.996.
- PL: 이중 피크 스펙트럼에서 주 피크 중심 750.1/750, FWHM 오차 4%.

## 주의사항

- **exe 재빌드 필요**: `pyinstaller Physiscore.spec --noconfirm` (새 CSV·설정 번들 반영).
- **Cowork 폴더 재연결 권장**: 이 폴더의 동기화 캐시가 오래되어(폴더명 "갱신 요망" 그대로) 세션 내 파일 크기 정보가 갱신되지 않습니다. 디스크의 실제 파일은 모두 정상입니다. Cowork에서 폴더를 제거 후 다시 연결하면 해결됩니다.
- 조명 강도는 100 mW/cm²(1 sun) 가정, 다른 조건이면 `compute_jv_parameters(..., pin_mw_cm2=...)`.
