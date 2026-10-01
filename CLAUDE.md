# CLAUDE.md — UBCK 야생조류 조사 지원 앱

이 저장소에서 일하는 Claude(와 사람)를 위한 프로젝트 맥락 문서다. 코드를 바꾸기 전에 끝까지 읽는다.

## 무엇을 위한 앱인가

- 약 100명 규모 대학 동아리(UBCK)의 **낙동강 하구 야생조류 조사**를 돕는 내부용 Streamlit 앱. 일반 공개 서비스가 아니다.
- 조사는 며칠(일차)에 걸쳐 진행되고, 매일 여러 조가 각자 맡은 **섹터**(조사 경로)를 걸으며 새를 센다.
- 쓰는 사람과 상황이 둘로 나뉜다.
  1. **현장 조사원**: 휴대폰으로 지도를 켜서 "지금 내가 섹터의 어디쯤인지, 어디로 가야 하는지, 경로에서 벗어났는지"를 확인한다. 햇빛 아래, 한 손, 느린 모바일 데이터.
  2. **운영진**: 노트북에서 명단을 관리하고 일차별로 조를 편성한다. 공평함(역할·조원·섹터가 겹치지 않게)이 최우선이고 속도는 덜 중요하다.
- 2026년 1월에 한 번 실사용했고(당시 `web.py` 한 파일), 2026년 10월에 구조를 다시 잡았다.

## 실행과 테스트

```bash
pip install -r requirements.txt
streamlit run web.py                 # 앱
python -m pytest -q                  # 테스트 (약 10초)
python -m ubck.map_view --key KEY -o map.html   # Streamlit 없이 쓰는 독립 지도 파일
```

- 배경지도 키: `.streamlit/secrets.toml`에 `VWORLD_API_KEY = "..."` (git에 올리지 않음). 없으면 OpenStreetMap으로 대체된다.
- 조 편성 저장 파일: 기본 `storage/ubck_project.json`, 환경변수 `UBCK_STORE`로 변경. git에 올리지 않음.
- 배포는 Streamlit Community Cloud를 가정한다. **그 파일 시스템은 재시작·재배포 때 지워진다.** 그래서 앱 안의 '백업·가져오기' 탭에서 프로젝트 JSON을 내려받고 다시 올리는 것이 정식 운영 방법이다.

## 구조

```
web.py                     진입점. st.navigation으로 세 페이지 연결 (배포 설정이 web.py를 가리키므로 파일명 유지)
ubck/gis.py                Shapefile → 지도용 JSON. 섹터 정규화, 경로 조각 정렬·방향 맞추기, 폴리곤-섹터 연결
ubck/map_view.py           지도 HTML 조립(템플릿에 JSON 주입), 독립 지도 파일 내보내기 CLI
ubck/assets/map.html       지도 본체. Leaflet + 순수 JS. 위치 추적·진행률·이탈 판정이 전부 브라우저 안에서 돈다
ubck/teams/model.py        Person / TeamSpec / Rules / Weights / TeamResult, 텍스트 파싱
ubck/teams/engine.py       조 편성 엔진 (담금질 탐색). docs/team-engine.md 참고
ubck/teams/history.py      이전 일차 결과 → 역할·짝꿍·조 이력 집계
ubck/teams/report.py       편성표 점검 (규칙 위반 / 누락 / 이전 일차와 겹침)
ubck/teams/io.py           편성표 ↔ DataFrame ↔ xlsx, 예전 xlsx 가져오기, 개인별 이력표
ubck/storage.py            프로젝트 JSON 저장/불러오기/스키마 보정
ubck/fieldnote.py          야장 정리(국명⇥개체수 → "국명 <수>, ..." 한 줄)
ubck/pages/*.py            Streamlit 화면 (map_page, teams_page, fieldnote_page)
data/                      QGIS에서 만든 Shapefile 6세트 (EPSG:3857)
tests/                     pytest
docs/                      설계 메모 (map.md, team-engine.md)
```

## 도메인 용어

| 용어 | 뜻 |
|---|---|
| 하천 / 하구 | 두 조사 구역 묶음. 하천은 북쪽 강 구간, 하구는 남쪽 하구·사주(도요등, 진우도 등) |
| 섹터 | 한 조가 하루에 맡는 조사 경로. `하천1`, `하구3` 같은 이름. 하천6은 `하천6-1`, `하천6-2` 두 조각(사이 약 1.8 km 이동) |
| 조사구역(폴리곤) | 관찰 범위. 하구 폴리곤은 코드(A1, G2…)로 부르고 여러 섹터에 걸칠 수 있다 |
| 조사자 | 조의 주 관찰·기록 담당. 조마다 1명. 아무나 못 한다(자격 표시) |
| 섹장 | 조 인솔·경로 담당. 조마다 1명 |
| 쩌리 | 동아리 내부 은어. 조사자·섹장이 아닌 일반 조원. UI에서도 이 말을 그대로 쓴다 |
| 카메라 | 카메라를 가진 사람. 조마다 고르게 퍼져야 한다 |
| 일차 | 조사 날짜 단위(1일차, 2일차…). 이전 일차 편성이 다음 일차 편성에 반영된다 |

## 데이터 메모

- 라인: `sector`(하구 라인은 `name`도 있음). 모든 경로는 '시작' 지점에서 '종료' 지점 방향으로 그려져 있음을 확인했다(gis.order_parts가 방향을 다시 맞추므로 뒤집혀 들어와도 된다).
- 포인트: `sector`, `startend`(시작/종료), `location`(지명). 모두 점 1개짜리 MultiPoint.
- 하구 폴리곤: `code`와 `sec1`~`sec11`(그 섹터 조사 범위에 들어가면 1). 지도에서 섹터를 고르면 해당 폴리곤을 강조하는 데 쓴다.
- 하구2, 하구5, 하구7은 시작≈종료인 순환 경로다. 진행률 계산은 직전 진행 위치에 가까운 후보를 고르는 방식으로 처리한다.
- **알려진 미확인 사항:** `HacheonPolygon`의 한 행 `sector` 값이 `하구2`다(하천2의 오타로 보이지만 사용자가 확인 전까지 **그대로 두라고 함**). 그래서 그 폴리곤은 하천2 라인과 색이 다르고, `unmatchedPolygonSectors`에 `하구2`로 나온다. 고치지 말 것.
- 색 팔레트는 예전 앱과 같게 유지한다(동아리원들이 색으로 섹터를 기억한다). `gis.PALETTE`와 배정 순서를 바꾸지 말 것.

## 설계 결정과 이유

**지도**
- 지도 전체를 브라우저 안의 Leaflet 페이지 하나로 만들고 `st.iframe`(구버전은 components.html)으로 넣는다. 위치가 바뀔 때 서버를 재실행하지 않으므로 모바일 데이터에서도 빠르고, 지도 확대·이동 상태가 유지된다. 예전 folium + streamlit-geolocation 방식은 위치 갱신·지도 이동마다 서버 재실행과 Shapefile 재로딩이 일어났다.
- Streamlit iframe은 `allow`에 geolocation, wake-lock, fullscreen이 들어 있다(확인함).
- 위치는 기기 밖으로 보내지 않는다. 이 원칙을 깨는 기능(다른 조원 위치 공유 등)은 사용자와 먼저 상의한다.
- 이탈 판정 규칙과 한계는 docs/map.md.

**조 편성**
- 엔진은 '누가 어느 조인가'만 탐색하고 조사자·섹장은 조 안에서 자동 선택한다 → 한 사람이 두 자리에 들어가는 예전 버그가 구조적으로 불가능.
- '꼭 같은 조'는 한 덩어리로 움직여 항상 지켜지고, '꼭 다른 조'·'조 고정'은 위반하는 이동을 하지 않는다. 인원·역할 채우기·역할 고정은 큰 벌점(BIG)으로 다룬다.
- 품질 확인: 100명/10개 조, 60명/6개 조에서 2일차 짝꿍 반복이 이론상 최솟값(자기 조 이름을 피하면 생기는 비둘기집 하한)과 같게 나온다. 테스트 `test_history_reduces_repeats`가 이를 고정한다.
- `st.data_editor`는 **입력 표를 버전이 바뀔 때만 새로 만든다**(teams_page `_stable_df`). 편집 결과를 다음 실행의 입력으로 다시 넣으면 수정이 사라지거나 두 번 적용된다. 예전 앱의 "Enter로는 반영이 안 돼요" 문제의 원인이었다. 표를 코드에서 바꿨다면 `_bump(이름)`으로 버전을 올린다.

## 작업 규칙

- UI 문구는 한국어, 짧고 구체적으로. 버튼은 결과를 말한다("조 편성 실행", "이 후보로 확정"). 오류는 무엇이 잘못됐고 어떻게 고치는지 말한다.
- 조원 이름 같은 실제 명단은 저장소에 넣지 않는다(storage/는 .gitignore).
- 엔진·파싱·GIS를 바꾸면 테스트를 같이 고친다. 지도 JS를 바꾸면 Playwright 등으로 모바일 폭(390px)에서 화면을 확인한다(테스트 훅: `window.__ubck.onFix(lat, lng, acc)`, `select(id)`, `startGuide()`, `state()`).
- 커밋 메시지는 한국어로, 무엇을 왜 바꿨는지.

## 열린 질문 / 다음 할 일

- 하천 폴리곤 `하구2` 값이 오타인지 사용자 확인 필요.
- 조 편성 추가 제약 중 무엇을 넣을지 사용자가 고르는 중 → docs/team-engine.md '확장 아이디어'.
- Streamlit Cloud 휘발 문제를 근본적으로 없애려면 Google Sheets/Supabase 같은 외부 저장소 연결이 필요하다(아직 안 함).
- iPhone Safari는 iframe 안 전체 화면을 지원하지 않는다. 현장에서 불편하면 `python -m ubck.map_view`로 만든 독립 지도 파일을 GitHub Pages 등(https)에 올리는 방안이 있다.
