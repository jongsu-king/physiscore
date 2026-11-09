# JV_Analysis.exe 분석 리포트

## 결론 요약
- **이 exe는 소스코드를 되살릴 수 없습니다.** 이유:
  1. **PySide6(Qt6)** 로 만들어진 프로그램입니다. 지금 `scripts/JV/run_jv.py`(및 나머지 8개 툴)는 **tkinter/customtkinter** 기반이라 프레임워크 자체가 다릅니다. 코드를 복사-붙여넣기 할 수 없습니다.
  2. 핵심 로직이 **mypyc 로 C 확장(`_internal/…__mypyc.cp313-win_amd64.pyd`)** 으로 컴파일돼 있습니다. 이건 사람이 읽을 수 있는 파이썬 소스로 복원이 불가능합니다.
  3. 엔트리 스크립트(`run_jv`)는 exe 안에서 추출했지만 Python 3.13 바이트코드라, 실행 로직(계산식 등)은 위 `.pyd` 안에 있어 텍스트가 남아있지 않습니다.

- **따라서 취한 조치**: exe 자체가 이미 완성된 "업그레이드 JV"이므로, **통합 런처(Physiscore_Launcher.py)에서 J-V Curve 카드를 누르면 이 `JV_Analysis.exe`를 직접 실행**하도록 연결했습니다. Origin 경로/Gemini 키는 실행 직전 exe 폴더의 `physisfera_config.json`에 자동 복사되어 공유됩니다.

## exe에서 복원한 UI 구조 (스크린샷과 일치)
- **상단 툴바**: `📂 Open ▾`(Folder…/Text files… — 교체) · `＋ Add ▾`(Folder…/Text files… — 추가) · 경로입력칸 · `Process`(F5) · … · `Excel`(Ctrl+E) · `PNG`(Ctrl+S) · `Origin J-V` · `Origin Box`
- **보기 세그먼트**: `J-V Curve` / `Box Plots`, `Curves: Best / All devices`
- **좌측 패널**: Voc/Jsc/FF/PCE 스탯카드 · `🔍 Filter samples...` · `Devices ▾` · `All`/`Clear`/`Copy` · Sample 테이블
- **하단 축 컨트롤**: X `[-0.2]~[1.0]` V, Y `[-25.0]~[5.0]` mA/cm² · `Auto Range` · "휠=줌(Ctrl=X, Shift=Y) · 드래그=이동"
- **하단 상태바**: `Ready` … `Output` · `Log`

## exe에만 있는 고급 기능 (지금 tkinter JV보다 우위 — 복원한 메서드 169개 기준)
- **이름 일괄 변경**(BatchRenameDialog): 찾기/바꾸기, 공통 접두어 자동, 미리보기
- **프리셋 조합**(PresetComposeDialog): 예 `ZnO/PDINN` 처럼 ` / `로 이어붙이기, 토큰 제거/비우기
- **우클릭 컨텍스트 메뉴**: 이름 바꾸기(F2) · 프리셋으로 변경 · 프리셋 조합 이름 만들기 · 현재 이름을 프리셋에 추가 · 기본 이름으로 되돌리기 · 이름 일괄 변경 · 프리셋 편집 · 표 복사(Ctrl+C)
- **폴더 비교**: `＋ Add`로 여러 폴더를 겹쳐 비교(folder chips, 중복 이름 처리)
- **최근 폴더** 메뉴
- **마우스 그래프 조작**: 휠 줌(Ctrl=X축, Shift=Y축), 드래그 이동, WheelEdit(입력칸에서 휠로 값 증감)
- **디바이스 그룹핑**: 그룹/디바이스 단위 선택, 트리 펼치기/접기
- **Best/All 스코프 + J-V/Box 모드 전환**, Box range 편집·자동복원
- **리포트 Figure 생성**(J-V + Boxes), transit Excel 저장

## 만약 소스를 진짜로 되살리고 싶다면
그 exe를 **빌드한 원본 `.py` 폴더**(mypyc 컴파일 전, PySide6 소스)가 개발자 PC 어딘가에 있을 겁니다. 그 폴더를 주시면:
- 그대로 통합 런처에 편입하거나,
- 원하시면 tkinter 버전으로 이식할 수 있습니다.

exe만으로는 위 조치(직접 실행 연결)가 기술적으로 가능한 최선입니다.
