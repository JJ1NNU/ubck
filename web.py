import streamlit as st
from groq import Groq
import folium
from streamlit_folium import st_folium
import geopandas as gpd
import random
from collections import defaultdict
from streamlit_geolocation import streamlit_geolocation
from folium import Icon, Marker
import time
import pandas as pd
import io

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

    # GPS 위치 가져오기
    col_gps1, col_gps2 = st.columns([1, 4])
    with col_gps1:
        gps_button = st.button("📍 내 위치", use_container_width=True)

    location = streamlit_geolocation()

    # 2개 메인 탭 생성 (하천/하구)
    subtabs = st.tabs(["하천", "하구"])
    
    # 각 탭별 Shapefile 설정
    tab_configs = [
    {
        "name": "하천",
        "files": [
            {"path": "data/HacheonLine.shp", "type": "line", "layer_name": "하천 라인", "sector_col": "sector"},
            {"path": "data/HacheonPolygon.shp", "type": "polygon", "layer_name": "하천 폴리곤", "sector_col": "sector"},
            {"path": "data/HacheonPoint.shp", "type": "point", "layer_name": "하천 포인트", "sector_col": "sector"}
        ]
    },
    {
        "name": "하구",
        "files": [
            {"path": "data/HaguLine.shp", "type": "line", "layer_name": "하구 라인", "sector_col": "sector"},
            {"path": "data/HaguPolygon.shp", "type": "polygon", "layer_name": "하구 폴리곤", "sector_col": "sector"},
            {"path": "data/HaguPoint.shp", "type": "point", "layer_name": "하구 포인트", "sector_col": "sector"}
        ]
    }
]

    # 구역별 색상 할당
    def get_color_for_sector(sector_value, all_sectors):
        colors = ['red', 'blue', 'green', 'purple', 'orange','darkblue', 'darkgreen', '#301934', 'pink']
        try:
            idx = list(all_sectors).index(sector_value)
            return colors[idx % len(colors)]
        except:
            return 'blue'
        
    def normalize_sector_value(tab_name: str, sector_value: str):
        """색상/표시 통일을 위한 sector 정규화."""
        if sector_value is None:
            return None
        s = str(sector_value).strip()

        # 하천 라인의 하천6-1, 하천6-2를 하천6으로 통일
        if tab_name == "하천" and s.startswith("하천6-"):
            return "하천6"

        return s

    def build_sector_color_map(tab_name: str, gdfs: dict):
        """
        탭(하천/하구) 단위로 sector->color 매핑을 1회 생성.
        - 하구 polygon은 색 고정이므로, 매핑에는 굳이 포함하지 않아도 됨(포함해도 무방).
        """
        seen = set()
        ordered = []

        # line -> polygon -> point 순서로 “처음 등장한 sector”를 수집
        for lt in ["line", "polygon", "point"]:
            if lt not in gdfs:
                continue
            gdf = gdfs[lt]["gdf"]

            if "sector" not in gdf.columns:
                continue

            for v in gdf["sector"].tolist():
                key = normalize_sector_value(tab_name, v)
                if key is None:
                    continue
                if key not in seen:
                    seen.add(key)
                    ordered.append(key)

        # colors는 기존 그대로 사용
        sector_color_map = {}
        for i, key in enumerate(ordered):
            sector_color_map[key] = get_color_for_sector(key, ordered)  # 기존 함수 그대로 사용

        return sector_color_map

    def add_point_geometry_to_map(geom, m, color, popup_text=None, tooltip_text=None, label_text=None):
        if geom is None:
            return

        def _add_one_point(pt):
            folium.CircleMarker(
                location=[pt.y, pt.x],
                radius=7,
                color=color,
                weight=3,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                popup=popup_text,
                tooltip=tooltip_text,
            ).add_to(m)

            # 지도 위 텍스트 라벨(시작/종료 + location) [web:165]
            if label_text:
                folium.Marker(
                    location=[pt.y, pt.x],
                    icon=folium.DivIcon(html=f"""
                        <div style="font-size: 10pt; color: {color}; font-weight: bold;
                            text-shadow: -1px -1px 0 white, 1px -1px 0 white,
                                        -1px 1px 0 white, 1px 1px 0 white;">
                            {label_text}
                        </div>
                    """)
                ).add_to(m)

        gtype = getattr(geom, "geom_type", "")

        if gtype == "Point":
            _add_one_point(geom)

        elif gtype == "MultiPoint":
            for p in geom.geoms:
                _add_one_point(p)

        else:
            folium.GeoJson(geom).add_to(m)


    # 각 메인 탭 처리
    for tab_idx, (subtab, tab_config) in enumerate(zip(subtabs, tab_configs)):
        with subtab:
            # 폴리곤 on/off 토글
            show_polygon = st.checkbox(f"{tab_config['name']} 폴리곤 표시", value=True, key=f"polygon_toggle_{tab_idx}")
            
            try:
                # 모든 파일 로드
                gdfs = {}
                all_bounds = []
                
                for file_config in tab_config["files"]:
                    gdf = gpd.read_file(file_config["path"])
                    if gdf.crs != "EPSG:4326":
                        gdf = gdf.to_crs(epsg=4326)
                    gdfs[file_config["type"]] = {"gdf": gdf, "config": file_config}
                    all_bounds.append(gdf.total_bounds)
                
                sector_color_map = build_sector_color_map(tab_config["name"], gdfs)

                # 전체 영역의 중심점 계산
                if all_bounds:
                    min_x = min(b[0] for b in all_bounds)
                    min_y = min(b[1] for b in all_bounds)
                    max_x = max(b[2] for b in all_bounds)
                    max_y = max(b[3] for b in all_bounds)
                    default_center_lat = (min_y + max_y) / 2
                    default_center_lon = (min_x + max_x) / 2
                else:
                    default_center_lat, default_center_lon = 37.5, 127.0
                
                # GPS 위치 설정
                if gps_button and location and location.get("latitude"):
                    center_lat = location["latitude"]
                    center_lon = location["longitude"]
                    zoom = 16
                elif location and location.get("latitude"):
                    center_lat = location["latitude"]
                    center_lon = location["longitude"]
                    zoom = 15
                else:
                    center_lat = default_center_lat
                    center_lon = default_center_lon
                    zoom = 13
                
                # Folium 지도 생성
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=zoom,
                    tiles=None
                )
                
                # 브이월드 배경지도
                vworld_key = st.secrets["VWORLD_API_KEY"]
                folium.TileLayer(
                    tiles=f'https://api.vworld.kr/req/wmts/1.0.0/{vworld_key}/Base/{{z}}/{{y}}/{{x}}.png',
                    attr='VWorld',
                    name='배경지도',
                    overlay=False,
                    control=True
                ).add_to(m)
                
                # 각 레이어 추가 (라인 -> 폴리곤 -> 포인트 순서)
                for layer_type in ["line", "polygon", "point"]:
                    if layer_type not in gdfs:
                        continue
                    
                    # 폴리곤이고 토글이 꺼져있으면 스킵
                    if layer_type == "polygon" and not show_polygon:
                        continue
                    
                    gdf = gdfs[layer_type]["gdf"]
                    layer_config = gdfs[layer_type]["config"]
                    
                    # Sector 컬럼 찾기
                    sector_col = "sector"
                                        
                    # 레이어별 처리
                    if layer_type == "line":
                        for idx_row, row in gdf.iterrows():
                            # 색상 키(정규화 sector)
                            raw_sector = row[sector_col] if sector_col else None
                            sector_key = normalize_sector_value(tab_config["name"], raw_sector)
                            color = sector_color_map.get(sector_key, "blue")

                            # 표시용 이름(하구 라인은 name, 하천 라인은 sector_key)
                            if tab_config["name"] == "하구" and "name" in gdf.columns and pd.notna(row.get("name")):
                                display_name = str(row["name"])
                            else:
                                display_name = sector_key if sector_key else "구역 정보 없음"

                            folium.GeoJson(
                                row['geometry'],
                                style_function=lambda x, color=color: {
                                    'color': color,
                                    'weight': 4,
                                    'opacity': 0.8
                                },
                                tooltip=f"{layer_config['layer_name']} - {display_name}"
                            ).add_to(m)

                            centroid = row['geometry'].centroid
                            folium.Marker(
                                location=[centroid.y, centroid.x],
                                icon=folium.DivIcon(html=f"""
                                    <div style="font-size: 12pt; color: {color}; font-weight: bold;
                                        text-shadow: -1px -1px 0 white, 1px -1px 0 white,
                                                    -1px 1px 0 white, 1px 1px 0 white;">
                                        {display_name}
                                    </div>
                                """)
                            ).add_to(m)

                    
                    # 기존 폴리곤 처리 부분을 아래로 교체
                    elif layer_type == "polygon":
                        # 하구 폴리곤은 blue로 고정
                        if tab_config["name"] == "하구":
                            fixed_color = 'blue'
                            
                            for idx_row, row in gdf.iterrows():
                                sector_name = row[sector_col] if sector_col else "구역 정보 없음"
                                
                                folium.GeoJson(
                                    row['geometry'],
                                    style_function=lambda x, color=fixed_color: {
                                        'fillColor': color,
                                        'color': color,
                                        'weight': 2,
                                        'fillOpacity': 0.3,
                                        'opacity': 0.8
                                    },
                                    tooltip=f"{layer_config['layer_name']} - {sector_name}"
                                ).add_to(m)
                                
                                # 라벨도 blue로
                                centroid = row['geometry'].centroid
                                folium.Marker(
                                    location=[centroid.y, centroid.x],
                                    icon=folium.DivIcon(html=f"""
                                        <div style="font-size: 10pt; color: {fixed_color}; font-weight: bold; 
                                            text-shadow: -1px -1px 0 white, 1px -1px 0 white, 
                                            -1px 1px 0 white, 1px 1px 0 white;">
                                            [{sector_name}]
                                        </div>
                                    """)
                                ).add_to(m)
                        
                        else:
                            for idx_row, row in gdf.iterrows():
                                sector_key = normalize_sector_value(tab_config["name"], row[sector_col] if sector_col else None)
                                color = sector_color_map.get(sector_key, "blue")    
                                
                                folium.GeoJson(
                                    row['geometry'],
                                    style_function=lambda x, color=color: {
                                        'fillColor': color,
                                        'color': color,
                                        'weight': 2,
                                        'fillOpacity': 0.3,
                                        'opacity': 0.8
                                    },
                                    tooltip=f"{layer_config['layer_name']} - {sector_key}"
                                ).add_to(m)
                                
                                centroid = row['geometry'].centroid
                                folium.Marker(
                                    location=[centroid.y, centroid.x],
                                    icon=folium.DivIcon(html=f"""
                                        <div style="font-size: 10pt; color: {color}; font-weight: bold; 
                                            text-shadow: -1px -1px 0 white, 1px -1px 0 white, 
                                            -1px 1px 0 white, 1px 1px 0 white;">
                                            [{sector_key}]
                                        </div>
                                    """)
                                ).add_to(m)
                    
                    elif layer_type == "point":
                        for _, row in gdf.iterrows():
                            raw_sector = row[sector_col] if sector_col else None
                            sector_key = normalize_sector_value(tab_config["name"], raw_sector)
                            color = sector_color_map.get(sector_key, "blue")

                            # 시작/종료 + 지점명 라벨
                            se = str(row["startend"]).strip() if "startend" in gdf.columns and pd.notna(row["startend"]) else ""
                            loc = str(row["location"]).strip() if "location" in gdf.columns and pd.notna(row["location"]) else ""
                            label_text = f"{se}: {loc}" if se and loc else (loc if loc else None)

                            add_point_geometry_to_map(
                                row["geometry"],
                                m,
                                color=color,
                                popup_text=f"{layer_config['layer_name']} - {sector_key}",
                                tooltip_text=f"{layer_config['layer_name']} - {sector_key}",
                                label_text=label_text
                            )
                            
                
                # 내 위치 마커
                if location and location.get("latitude"):
                    folium.Marker(
                        location=[location["latitude"], location["longitude"]],
                        popup="📍 현재 위치",
                        tooltip="내 위치",
                        icon=folium.Icon(color='red', icon='user', prefix='fa')
                    ).add_to(m)
                    
                    if location.get("accuracy"):
                        folium.Circle(
                            location=[location["latitude"], location["longitude"]],
                            radius=location["accuracy"],
                            color='red',
                            fill=True,
                            fillOpacity=0.1,
                            popup=f"오차범위: {location['accuracy']:.0f}m"
                        ).add_to(m)
                
                folium.LayerControl().add_to(m)
                
                # 지도 렌더링 (모바일 친화)
                st_folium(m, use_container_width=True, height=420, key=f"map_{tab_idx}")
                
                # GPS 정보 표시
                if location and location.get("latitude"):
                    st.success(f"📍 현재 위치: 위도 {location['latitude']:.6f}, 경도 {location['longitude']:.6f}")
                    st.info(f"정확도: ±{location.get('accuracy', 0):.0f}m")
                else:
                    st.warning("위치 권한을 허용하면 내 위치가 지도에 표시됩니다.")
                
                # 실시간 추적
                if location and location.get("latitude"):
                    time.sleep(0.1)
                    st.rerun()
            
            except Exception as e:
                st.error(f"{tab_config['name']} 지도 로딩 실패: {e}")



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

        # 3) 쩌리
        all_extras = extras + inv_leftover + lead_leftover
        random.shuffle(all_extras)
        
        for idx, name in enumerate(all_extras):
            teams[idx % k]["쩌리"].append(name)

        ok, reason = check_constraints(teams, must_together, must_apart)
        if ok:
            return teams, ""

    return None, f"조건을 만족하는 조합을 찾지 못했습니다. (재시도 {max_tries}회)"

def format_teams_horizontal_table(teams):
    """
    각 열이 한 조가 되도록 행/렬 변경.
    쩌리가 여러 명이면 각 칸에 한 명씩.
    """
    # 쩌리의 최대 명수 구하기
    max_jjuri = max((len(t["쩌리"]) for t in teams), default=0)
    
    # 행 구성: 역할별 (조사자, 섹장, 쩌리 1, 쩌리 2, ...)
    rows_data = []
    
    # 1행: 조사자
    row_investigator = ["조사자"] + [t["조사자"] for t in teams]
    rows_data.append(row_investigator)
    
    # 2행: 섹장
    row_leader = ["섹장"] + [t["섹장"] for t in teams]
    rows_data.append(row_leader)
    
    # 3행~: 쩌리 (한 행에 한 명씩)
    for jjuri_idx in range(max_jjuri):
        row_jjuri = [f"쩌리{jjuri_idx + 1}"]
        for t in teams:
            if jjuri_idx < len(t["쩌리"]):
                row_jjuri.append(t["쩌리"][jjuri_idx])
            else:
                row_jjuri.append("")  # 빈 칸
        rows_data.append(row_jjuri)
    
    # 컬럼명: 조역할, 1조, 2조, ...
    columns = ["역할"] + [f"{i}조" for i in range(1, len(teams) + 1)]
    
    df = pd.DataFrame(rows_data, columns=columns)
    return df

def create_excel_buffer(df):
    """DataFrame을 메모리상 Excel 파일로 변환"""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='조편성', index=False)
    buffer.seek(0)
    return buffer

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
    must_together_raw = st.text_area("꼭 같은 팀 (여러 쌍 가능: 구분자가 - 라면 한 줄에 A-B)", height=120)
    must_apart_raw = st.text_area("꼭 다른 팀 (여러 쌍 가능: 구분자가 - 라면 한 줄에 A-B)", height=120)

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
            df = format_teams_horizontal_table(teams)
            
            # 표 형식으로 표시
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Excel 다운로드 버튼
            excel_buffer = create_excel_buffer(df)
            st.download_button(
                label="📥 Excel 파일 다운로드 (.xlsx)",
                data=excel_buffer,
                file_name="조편성_결과.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 복사/붙여넣기용 탭 형식 텍스트
            st.markdown("### 복사/붙여넣기 (엑셀용)")
            st.info("아래 텍스트를 Ctrl+C로 복사 후 엑셀에 바로 붙여넣기 가능합니다.")
            
            # DataFrame을 탭 구분 텍스트로 변환
            tsv_text = df.to_csv(sep='\t', index=False)
            st.text_area("", value=tsv_text, height=150, disabled=True)
