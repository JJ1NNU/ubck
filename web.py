import streamlit as st
from groq import Groq
import folium
from streamlit_folium import st_folium
import geopandas as gpd
import random
from collections import defaultdict

MODEL_NAME = "openai/gpt-oss-120b" 

st.set_page_config(layout="wide", page_title="UBCK")
st.title("🤖UBCK-GPT")

api_key = st.secrets["GROQ_API_KEY"]
client = Groq(api_key=api_key)

# ===== 탭 생성 =====
tab1, tab2, tab3 = st.tabs(["📋 변환기", "🗺️ 조사 경로 지도", "👥 조 편성"])

# ===== 탭 1: 기존 AI 변환기 =====
with tab1:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📋 야장정리기 결과를 그대로 복사/붙여넣기하세요.")
        user_input = st.text_area("엑셀에서 복사/붙여넣기한 텍스트", height=400)
        run_button = st.button("변환 실행 ▶", use_container_width=True)

    with col2:
        st.subheader("✨ 관찰종 및 개체수")
        result_container = st.empty()
        
        if run_button and user_input:
            try:
                with st.spinner("AI가 변환 중입니다..."):
                    chat_completion = client.chat.completions.create(
                        messages=[
                            # 1. 시스템 프롬프트: AI의 역할과 규칙 정의 (여기를 튜닝하세요)
                            {
                                "role": "system",
                                "content": """
                                당신은 “조류상 조사 결과 포맷터”이다.

                                입력은 엑셀에서 복사-붙여넣기한 텍스트이며, 각 행은 2열로 구성된다:
                                - 1열: 조류 국명(한글)
                                - 2열: 관찰 수(숫자 형태의 문자열)
                                열 구분은 탭(Tab)일 수 있고, 행 구분은 줄바꿈이다.

                                작업:
                                - 입력의 각 행을 위에서 아래 순서대로 처리한다.
                                - 각 행을 다음 형식의 조각으로 변환한다: {국명} <{관찰수}>
                                - 모든 조각을 ", " (콤마+공백)으로 연결하여 한 줄의 텍스트로 출력한다.

                                절대 규칙(매우 중요):
                                - 출력은 오직 최종 결과 한 줄만 출력한다.
                                - 설명, 인사, 머리말/꼬리말, 코드블록, 따옴표, 불릿, 추가 문장, 줄바꿈을 절대 포함하지 않는다.
                                - 입력값의 진위/타당성 검증(국명 확인, 개체 수 검증 등)을 하지 않는다. 입력에 있는 문자열을 그대로 사용한다.
                                - 순서를 절대 바꾸지 않는다.
                                - 괄호/기호는 다음만 사용한다: 각 항목의 수를 감싸는 "<"와 ">".
                                """
                            },
                            
                            # 2. 사용자 입력
                            {
                                "role": "user", 
                                "content": user_input
                            }
                        ],
                        model=MODEL_NAME,
                        temperature=0.1 
                    )
                    result_text = chat_completion.choices[0].message.content
                    result_container.text_area("결과물", value=result_text, height=400)
                    st.success("완료!")
            except Exception as e:
                st.error(f"오류 발생: {e}")

# ===== 탭 2: 지도 시각화 =====
with tab2:
    st.subheader("🗺️ 조사 경로")
    
    try:
        # 프로젝트 폴더에 있는 Shapefile을 직접 로드
        # 예: GitHub 리포지토리의 /data/survey_route.shp
        gdf = gpd.read_file("data/survey_route.shp")
    
        # WGS84(위경도) 좌표계로 변환 (브이월드/웹 지도는 EPSG:4326 사용)
        if gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs(epsg=4326)
        
        # 지도 중심점 계산 (Shapefile 영역의 중심)
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        # Folium 지도 생성 (브이월드 타일 사용)
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles=None  # 기본 타일 제거
        )
        
        # 브이월드 베이스맵 추가 (Base, Satellite, Hybrid 중 선택)
        # 참고: 브이월드 API Key가 필요하면 st.secrets에서 불러오세요
        vworld_key = st.secrets.get("VWORLD_API_KEY", "YOUR_VWORLD_KEY")
        
        folium.TileLayer(
            tiles=f'http://api.vworld.kr/req/wmts/1.0.0/{vworld_key}/Base/{{z}}/{{y}}/{{x}}.png',
            attr='VWorld',
            name='브이월드 기본지도',
            overlay=False,
            control=True
        ).add_to(m)
        
        # Shapefile의 Geometry를 지도에 추가
        folium.GeoJson(
            gdf,
            name="조사 경로",
            style_function=lambda x: {
                'color': 'red',
                'weight': 3,
                'opacity': 0.8
            },
            tooltip=folium.GeoJsonTooltip(fields=list(gdf.columns[:-1]))  # geometry 제외한 속성 표시
        ).add_to(m)
        
        # 레이어 컨트롤 추가 (On/Off 토글)
        folium.LayerControl().add_to(m)
        
        # Streamlit에 지도 렌더링
        st_folium(m, width=1200, height=600)
        
        # 데이터 미리보기
        with st.expander("📊 Shapefile 속성 테이블 보기"):
            st.dataframe(gdf.drop(columns=['geometry']))

    except Exception as e:
        st.error(f"지도 로딩 실패: {e}")


# ===== 탭 3: 조 편성 =====
def parse_names(raw: str, delim: str):
    if delim == "\\n":
        parts = raw.splitlines()
    else:
        parts = raw.split(delim)
    return [p.strip() for p in parts if p.strip()]

def parse_pairs(raw: str, pair_delim: str):
    pairs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if pair_delim not in line:
            continue
        a, b = [x.strip() for x in line.split(pair_delim, 1)]
        if a and b:
            pairs.append((a, b))
    return pairs

def check_constraints(teams, must_together, must_apart):
    person_to_team = {}
    for i, t in enumerate(teams):
        members = [t["조사자"], t["섹장"]] + t["쩌리"]
        for m in members:
            person_to_team[m] = i

    for a, b in must_together:
        if a not in person_to_team or b not in person_to_team:
            return False, f"같이 팀 제약에 존재하지 않는 이름이 있습니다: {a}, {b}"
        if person_to_team[a] != person_to_team[b]:
            return False, f"같이 팀 제약 위반: {a}, {b}"

    for a, b in must_apart:
        if a not in person_to_team or b not in person_to_team:
            return False, f"다른 팀 제약에 존재하지 않는 이름이 있습니다: {a}, {b}"
        if person_to_team[a] == person_to_team[b]:
            return False, f"다른 팀 제약 위반: {a}, {b}"

    return True, ""

def try_make_teams(k, investigators, leaders, extras, must_together, must_apart, max_tries=2000):
    investigators = investigators[:]
    leaders = leaders[:]
    extras = extras[:]

    all_names = investigators + leaders + extras
    if len(set(all_names)) != len(all_names):
        return None, "후보 명단(조사자/섹장/쩌리)에 중복 이름이 있습니다. 중복을 제거해 주세요."

    if len(investigators) < k:
        return None, f"조사자 후보가 부족합니다. 필요: {k}, 현재: {len(investigators)}"
    if len(leaders) < k:
        return None, f"섹장 후보가 부족합니다. 필요: {k}, 현재: {len(leaders)}"

    for _ in range(max_tries):
        random.shuffle(investigators)
        random.shuffle(leaders)
        random.shuffle(extras)

        teams = [{"조사자": None, "섹장": None, "쩌리": []} for _ in range(k)]

        # 1) 조사자 배정
        inv_pick = investigators[:k]
        inv_leftover = investigators[k:]
        for i in range(k):
            teams[i]["조사자"] = inv_pick[i]

        # 2) 섹장 배정
        used = set(inv_pick)
        lead_pool = [x for x in leaders if x not in used]
        if len(lead_pool) < k:
            continue
        random.shuffle(lead_pool)
        lead_pick = lead_pool[:k]
        lead_leftover = [x for x in leaders if x not in lead_pick and x not in used]
        for i in range(k):
            teams[i]["섹장"] = lead_pick[i]

        # 3) 쩌리 배정
        all_extras = extras + inv_leftover + lead_leftover
        random.shuffle(all_extras)
        
        for idx, name in enumerate(all_extras):
            teams[idx % k]["쩌리"].append(name)

        ok, reason = check_constraints(teams, must_together, must_apart)
        if ok:
            return teams, ""

    return None, f"조건을 만족하는 조합을 찾지 못했습니다. (재시도 {max_tries}회)"

def format_teams_expanded(teams):
    # ===== 수정: 행/열 변경 + 쩌리를 한 명당 한 행 =====
    import pandas as pd
    
    rows = []
    for i, t in enumerate(teams, start=1):
        if not t["쩌리"]:  # 쩌리가 없으면
            rows.append({
                "조": f"{i}조",
                "조사자": t["조사자"],
                "섹장": t["섹장"],
                "쩌리": ""
            })
        else:  # 쩌리가 여러 명이면 각 명마다 행 생성
            for j, jjuri in enumerate(t["쩌리"]):
                if j == 0:  # 첫 번째 쩌리 (조사자/섹장과 같은 행)
                    rows.append({
                        "조": f"{i}조",
                        "조사자": t["조사자"],
                        "섹장": t["섹장"],
                        "쩌리": jjuri
                    })
                else:  # 나머지 쩌리들 (별도 행, 조 칼럼만 공란)
                    rows.append({
                        "조": "",
                        "조사자": "",
                        "섹장": "",
                        "쩌리": jjuri
                    })
    
    return pd.DataFrame(rows)

def teams_to_excel(teams):
    # ===== 엑셀 파일 생성 (바이너리) =====
    import pandas as pd
    from io import BytesIO
    
    df = format_teams_expanded(teams)
    
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="조편성")
    
    buffer.seek(0)
    return buffer.getvalue()

with tab3:
    st.subheader("👥 조 편성 (조사자/섹장/쩌리)")
    st.info("💡 조사자/섹장 후보 중 선정되지 않은 인원은 자동으로 쩌리로 편입됩니다.")

    k = st.number_input("조 개수", min_value=1, value=3, step=1)

    delim = st.text_input("이름 구분자 (예: ,  또는  \\n)", value="\\n")

    c1, c2, c3 = st.columns(3)
    with c1:
        investigators_raw = st.text_area("조사자 후보 (이름들)", height=180, placeholder="한 줄에 한 명 또는 ,로 구분")
    with c2:
        leaders_raw = st.text_area("섹장 후보 (이름들)", height=180)
    with c3:
        extras_raw = st.text_area("쩌리 후보 (이름들)", height=180, help="여기는 비워둬도 됩니다. 조사자/섹장 탈락자가 자동으로 쩌리가 됩니다.")

    st.markdown("### 제약조건(선택)")
    pair_delim = st.text_input("같이/다른 팀 '쌍' 구분자", value="-")
    must_together_raw = st.text_area("꼭 같은 팀 (한 줄에: A-B)", height=120)
    must_apart_raw = st.text_area("꼭 떨어져야 함 (한 줄에: A-B)", height=120)

    run_team = st.button("조 편성 생성(랜덤) 🎲", use_container_width=True)

    if run_team:
        investigators = parse_names(investigators_raw, delim)
        leaders = parse_names(leaders_raw, delim)
        extras = parse_names(extras_raw, delim)

        must_together = parse_pairs(must_together_raw, pair_delim)
        must_apart = parse_pairs(must_apart_raw, pair_delim)

        teams, err = try_make_teams(
            k=int(k),
            investigators=investigators,
            leaders=leaders,
            extras=extras,
            must_together=must_together,
            must_apart=must_apart,
            max_tries=3000
        )

        if err:
            st.error(err)
        else:
            df = format_teams_expanded(teams)
            
            # 표 표시
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # ===== 수정: 엑셀 다운로드 버튼 =====
            excel_data = teams_to_excel(teams)
            st.download_button(
                label="📥 엑셀 파일로 다운로드",
                data=excel_data,
                file_name="조편성.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            st.markdown("💡 위 엑셀 파일을 다운로드하여 원하는 곳에 붙여넣기할 수 있습니다.")
