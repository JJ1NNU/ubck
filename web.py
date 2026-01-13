import streamlit as st
from groq import Groq
import folium
from streamlit_folium import st_folium
import geopandas as gpd
import random
from collections import Counter, defaultdict
from streamlit_geolocation import streamlit_geolocation
from folium import Icon, Marker
import time
import pandas as pd
import io
import re

# MODEL_NAME = "openai/gpt-oss-120b" 

st.set_page_config(layout="wide", page_title="UBCK")

# api_key = st.secrets["GROQ_API_KEY"]
# client = Groq(api_key=api_key)

# ===== 탭 생성 =====
tab2, tab3 = st.tabs(["🗺️ 조사 경로 지도", "👥 조 편성"])

# # ===== 탭 1: 기존 AI 변환기 =====
# with tab1:
#     col1, col2 = st.columns(2)

#     with col1:
#         st.subheader("📋 야장정리기 결과를 그대로 복사/붙여넣기하세요.")
#         user_input = st.text_area("엑셀에서 복사/붙여넣기한 텍스트", height=400)
#         run_button = st.button("변환 실행 ▶", use_container_width=True)

#     with col2:
#         st.subheader("✨ 관찰종 및 개체수")
#         result_container = st.empty()
        
#         if run_button and user_input:
#             try:
#                 with st.spinner("AI가 변환 중입니다..."):
#                     chat_completion = client.chat.completions.create(
#                         messages=[
#                             # 1. 시스템 프롬프트: AI의 역할과 규칙 정의 (여기를 튜닝하세요)
#                             {
#                                 "role": "system",
#                                 "content": """
#                                 당신은 “조류상 조사 결과 포맷터”이다.

#                                 입력은 엑셀에서 복사-붙여넣기한 텍스트이며, 각 행은 2열로 구성된다:
#                                 - 1열: 조류 국명(한글)
#                                 - 2열: 관찰 수(숫자 형태의 문자열)
#                                 열 구분은 탭(Tab)일 수 있고, 행 구분은 줄바꿈이다.

#                                 작업:
#                                 - 입력의 각 행을 위에서 아래 순서대로 처리한다.
#                                 - 각 행을 다음 형식의 조각으로 변환한다: {국명} <{관찰수}>
#                                 - 모든 조각을 ", " (콤마+공백)으로 연결하여 한 줄의 텍스트로 출력한다.

#                                 절대 규칙(매우 중요):
#                                 - 출력은 오직 최종 결과 한 줄만 출력한다.
#                                 - 설명, 인사, 머리말/꼬리말, 코드블록, 따옴표, 불릿, 추가 문장, 줄바꿈을 절대 포함하지 않는다.
#                                 - 입력값의 진위/타당성 검증(국명 확인, 개체 수 검증 등)을 하지 않는다. 입력에 있는 문자열을 그대로 사용한다.
#                                 - 순서를 절대 바꾸지 않는다.
#                                 - 괄호/기호는 다음만 사용한다: 각 항목의 수를 감싸는 "<"와 ">".
#                                 """
#                             },
                            
#                             # 2. 사용자 입력
#                             {
#                                 "role": "user", 
#                                 "content": user_input
#                             }
#                         ],
#                         model=MODEL_NAME,
#                         temperature=0.1 
#                     )
#                     result_text = chat_completion.choices[0].message.content
#                     result_container.text_area("결과물", value=result_text, height=400)
#                     st.success("완료!")
#             except Exception as e:
#                 st.error(f"오류 발생: {e}")

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
            {"path": "data/HaguPolygon.shp", "type": "polygon", "layer_name": "하구 폴리곤", "sector_col": "code"},
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
    
    def make_label_html(text, color, font_size_pt=12, bold=True):
        fw = "700" if bold else "500"
        return f"""
        <div style="
            white-space: nowrap;
            display: inline-block;
            writing-mode: horizontal-tb;
            font-size: {font_size_pt}pt;
            font-weight: {fw};
            color: {color};
            background: rgba(255,255,255,0.75);
            padding: 2px 6px;
            border: 1px solid rgba(0,0,0,0.25);
            border-radius: 6px;
            text-shadow: -1px -1px 0 white, 1px -1px 0 white,
                        -1px  1px 0 white, 1px  1px 0 white;
        ">{text}</div>
        """

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
                    icon=folium.DivIcon(
                        html=make_label_html(label_text, color, font_size_pt=9, bold=False),
                        icon_size=(320, 18),
                        icon_anchor=(0, 0)
                    )
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
                    sector_col = layer_config.get("sector_col", "sector")

                    # 컬럼이 실제로 존재하는지 확인(대소문자까지)
                    if sector_col not in gdf.columns:
                        found = None
                        for c in gdf.columns:
                            if c.lower() == sector_col.lower():
                                found = c
                                break
                        sector_col = found  # 못 찾으면 None
                                        
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
                                icon=folium.DivIcon(
                                    html=make_label_html(display_name, color, font_size_pt=12, bold=True),
                                    icon_size=(300, 24),     # 충분히 넓게
                                    icon_anchor=(0, 0)
                                )
                            ).add_to(m)

                    
                    elif layer_type == "polygon":
                        if tab_config["name"] == "하구":
                            fixed_color = 'blue'

                            for idx_row, row in gdf.iterrows():
                                sector_name = row[sector_col] if sector_col else "구역 정보 없음"

                                folium.GeoJson(
                                    row['geometry'],
                                    style_function=lambda x, color=fixed_color: {
                                        'color': color,
                                        'weight': 2,
                                        'opacity': 0.9,
                                        'fillColor': 'transparent',
                                        'fillOpacity': 0.0
                                    },
                                    tooltip=f"{layer_config['layer_name']} - {sector_name}"
                                ).add_to(m)

                                centroid = row['geometry'].centroid
                                folium.Marker(
                                    location=[centroid.y, centroid.x],
                                    icon=folium.DivIcon(
                                        html=make_label_html(str(sector_name), fixed_color, font_size_pt=12, bold=True),
                                        icon_size=(300, 24),
                                        icon_anchor=(0, 0)
                                    )
                                ).add_to(m)

                        else:
                            for idx_row, row in gdf.iterrows():
                                sector_key = normalize_sector_value(
                                    tab_config["name"],
                                    row[sector_col] if sector_col else None
                                )
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
def parse_names_auto(raw: str):
    if not raw: return []
    parts = re.split(r'[,\n\t]+', raw)
    return [p.strip() for p in parts if p.strip()]

def parse_pairs_auto(raw: str):
    if not raw: return []
    pairs = []
    chunks = re.split(r'[,\n]+', raw)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or '-' not in chunk: continue
        parts = chunk.split('-', 1)
        if len(parts) == 2:
            a, b = parts[0].strip(), parts[1].strip()
            if a and b: pairs.append((a, b))
    return pairs

def create_excel_buffer(df):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='조편성', index=False)
    buffer.seek(0)
    return buffer

def check_constraints(teams, must_together, must_apart):
    person_to_team = {}
    for i, t in enumerate(teams):
        members = [t["조사자"], t["섹장"]] + t["쩌리"]
        members = [m for m in members if m]
        
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

def create_excel_buffer(df):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='조편성', index=False)
    buffer.seek(0)
    return buffer

def get_history_stats(day_idx, session_state):
    """
    Returns:
        role_counts: {이름: {'조사자': 횟수, '섹장': 횟수}}
        pair_counts: {(이름A, 이름B): 같이한 횟수}
        group_counts: {이름: {1: 횟수, 2: 횟수, ...}}  <- 조 번호 이력 추가
    """
    role_counts = defaultdict(lambda: {'조사자': 0, '섹장': 0})
    pair_counts = defaultdict(int)
    group_counts = defaultdict(lambda: defaultdict(int)) # {이름: {조번호: 횟수}}

    for d in range(1, day_idx):
        key = f"df_day_{d}"
        if key in session_state and session_state[key] is not None:
            df = session_state[key]
            
            # ['1조', '2조', '3조']
            team_cols = [c for c in df.columns if "조" in c]
            
            # 1. 역할 카운트
            for _, row in df.iterrows():
                role = row.get("역할")
                if role in ["조사자", "섹장"]:
                    for col in team_cols:
                        name = str(row[col]).replace(" 📷", "").strip()
                        if name and name != "nan" and name != "":
                            role_counts[name][role] += 1
            
            # 2. 팀 쌍 & 조 번호 카운트
            for col_idx, col in enumerate(team_cols):
                group_num = col_idx + 1
                
                members = []
                for _, row in df.iterrows():
                    name = str(row[col]).replace(" 📷", "").strip()
                    if name and name != "nan" and name != "":
                        members.append(name)
                        group_counts[name][group_num] += 1
                
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        p1, p2 = sorted((members[i], members[j]))
                        pair_counts[(p1, p2)] += 1
                        
    return role_counts, pair_counts, group_counts


def try_make_teams_history_aware(k, investigators, leaders, cameras, extras, must_together, must_apart, history_stats, max_tries=1000):
    role_counts, pair_counts, group_counts = history_stats
    
    inv_pool = investigators[:]
    lead_pool = leaders[:]
    cam_set = set(cameras)
    extra_pool = extras[:]
    
    # 페널티 점수 계산
    def get_team_penalty(team_idx, current_members, new_member):
        penalty = 0
        group_num = team_idx + 1
        
        # 1. 쌍 중복 페널티 (가중치 1)
        for m in current_members:
            key = tuple(sorted((m, new_member)))
            penalty += pair_counts[key] * 1 
            
        # 2. 조 중복 페널티 (이전에도 그 조였으면 감점) (가중치 10)
        prev_group_count = group_counts[new_member][group_num]
        penalty += prev_group_count * 10
        
        return penalty

    def sort_by_role_fatigue(candidates, role_name):
        return sorted(candidates, key=lambda x: (role_counts[x][role_name], random.random()))

    best_teams = None
    min_total_penalty = float('inf')

    for _ in range(max_tries):
        inv_candidates = sort_by_role_fatigue(inv_pool, '조사자')
        lead_candidates = sort_by_role_fatigue(lead_pool, '섹장')
        random.shuffle(extra_pool)

        current_teams = [{"members": [], "camera_count": 0} for _ in range(k)]
        
        # 조사자 배정
        if len(inv_candidates) < k: return None, None, "조사자 후보 부족"
        inv_picked = inv_candidates[:k]
        inv_left = inv_candidates[k:]
        
        for i in range(k):
            p = inv_picked[i]
            current_teams[i]["members"].append({"role": "조사자", "name": p})
            if p in cam_set: current_teams[i]["camera_count"] += 1

        # 섹장 배정
        used = set(inv_picked)
        valid_leaders = [p for p in lead_candidates if p not in used]
        if len(valid_leaders) < k: continue
        
        lead_picked = valid_leaders[:k]
        lead_left = [p for p in lead_candidates if p not in lead_picked and p not in used]
        
        for i in range(k):
            p = lead_picked[i]
            current_teams[i]["members"].append({"role": "섹장", "name": p})
            if p in cam_set: current_teams[i]["camera_count"] += 1

        # 쩌리 배정
        leftovers = extra_pool + inv_left + lead_left
        left_cams = [p for p in leftovers if p in cam_set]
        left_no_cams = [p for p in leftovers if p not in cam_set]
        random.shuffle(left_cams)
        random.shuffle(left_no_cams)

        def assign_extras(candidates):
            for p in candidates:
                best_team_idx = -1
                best_score = float('inf')

                team_indices = list(range(k))
                random.shuffle(team_indices)
                
                for t_idx in team_indices:
                    team = current_teams[t_idx]
                    current_names = [m['name'] for m in team['members']]

                    # 1. 인원 수 (균형 맞추기)
                    score = len(team['members']) * 1000 
                    
                    # 2. 패널티 (쌍 중복 + 조 중복 * 10)
                    penalty = get_team_penalty(t_idx, current_names, p)
                    score += penalty * 500
                    
                    # 3. 카메라 균형
                    if p in cam_set:
                        score += team['camera_count'] * 300
                        
                    if score < best_score:
                        best_score = score
                        best_team_idx = t_idx
                
                # 배정
                current_teams[best_team_idx]["members"].append({"role": "쩌리", "name": p})
                if p in cam_set: current_teams[best_team_idx]["camera_count"] += 1

        assign_extras(left_cams)
        assign_extras(left_no_cams)

        # 평가
        formatted = []
        total_penalty_score = 0
        
        for t_idx, t in enumerate(current_teams):
            ft = {"조사자": None, "섹장": None, "쩌리": []}
            names_in_team = []
            group_num = t_idx + 1
            
            for m in t["members"]:
                p_name = m["name"]
                names_in_team.append(p_name)
                if m["role"] == "조사자": ft["조사자"] = p_name
                elif m["role"] == "섹장": ft["섹장"] = p_name
                else: ft["쩌리"].append(p_name)
                
                if group_counts[p_name][group_num] > 0:
                    total_penalty_score += group_counts[p_name][group_num] * 2

            formatted.append(ft)

            for i in range(len(names_in_team)):
                for j in range(i+1, len(names_in_team)):
                    p1, p2 = sorted((names_in_team[i], names_in_team[j]))
                    total_penalty_score += pair_counts[(p1, p2)]

        ok, msg = check_constraints(formatted, must_together, must_apart)
        
        if ok:
            if total_penalty_score < min_total_penalty:
                min_total_penalty = total_penalty_score
                best_teams = formatted
                if min_total_penalty == 0: break
    
    if best_teams:
        return best_teams, cam_set, None
    else:
        return None, None, "조건을 만족하는 조합을 찾지 못했습니다."


def format_teams_for_editor(teams, camera_set):
    max_jjuri = max((len(t["쩌리"]) for t in teams), default=0)
    def mark(name):
        if not name: return ""
        return f"{name} 📷" if name in camera_set else name

    rows = []
    rows.append(["조사자"] + [mark(t["조사자"]) for t in teams])
    rows.append(["섹장"] + [mark(t["섹장"]) for t in teams])
    for i in range(max_jjuri):
        row = [f"쩌리{i+1}"]
        for t in teams:
            if i < len(t["쩌리"]): row.append(mark(t["쩌리"][i]))
            else: row.append("")
        rows.append(row)
        
    cols = ["역할"] + [f"{i+1}조" for i in range(len(teams))]
    return pd.DataFrame(rows, columns=cols)

def get_warnings(df, day_idx, session_state):
    warnings = []
    if df is None or df.empty: return warnings
    
    role_counts, pair_counts, group_counts = get_history_stats(day_idx, session_state)
    
    team_cols = [c for c in df.columns if "조" in c]
    
    for _, row in df.iterrows():
        role = row.get("역할")
        for col_idx, col in enumerate(team_cols):
            name_raw = str(row[col])
            name = name_raw.replace(" 📷", "").strip()
            
            if not name or name == "nan" or name == "":
                continue
            
            # 1. 역할 중복 경고
            if role in ["조사자", "섹장"]:
                prev_count = role_counts[name][role]
                if prev_count > 0:
                    warnings.append(f"⚠️ **{name}**: 과거에 이미 '{role}' 역할을 {prev_count}번 수행했습니다.")
            
            # 2. 조 번호 중복 경고
            group_num = col_idx + 1 
            prev_group_cnt = group_counts[name][group_num]
            if prev_group_cnt > 0:
                warnings.append(f"🔢 **{name}**: 과거에 이미 {group_num}조에 {prev_group_cnt}번 배정됐습니다.")

    # 3. 팀원 중복 경고
    for col in team_cols:
        members = []
        for _, row in df.iterrows():
            name = str(row[col]).replace(" 📷", "").strip()
            if name and name != "nan": members.append(name)
        
        for i in range(len(members)):
            for j in range(i+1, len(members)):
                p1, p2 = sorted((members[i], members[j]))
                count = pair_counts[(p1, p2)]
                if count > 0:
                    warnings.append(f"👥 **{col}**: ({p1}, {p2}) 조합은 이전에 {count}번 같은 조였습니다.")
                    
    return list(dict.fromkeys(warnings))

# 메인 UI
with tab3:
    st.subheader("👥 조 편성")
    st.info("각 날짜 탭을 순서대로 진행하세요. 이전 날짜의 편성 결과가 다음 날짜의 알고리즘에 반영되어 중복을 최소화합니다.  \n조사자/섹장을 이미 했던 사람은 최대한 쩌리로 가며, 같은 조에 또다시 배정되는 일을 최소화합니다.  \n콤마(,), Enter, Tab 으로 사람을 구분합니다. 후보 입력 칸이나 아래 표 모두 '엑셀에서 그대로 북사/붙여넣기'를 허용합니다.")

    days = st.tabs([f"{i}일차" for i in range(1, 6)])

    for i, day_tab in enumerate(days):
        day_num = i + 1
        with day_tab:
            st.markdown(f"### 📅 {day_num}일차")
            
            key_df = f"df_day_{day_num}"
            key_input_inv = f"input_inv_{day_num}"
            key_input_lead = f"input_lead_{day_num}"
            key_input_cam = f"input_cam_{day_num}"
            key_input_extra = f"input_extra_{day_num}"
            
            if day_num > 1:
                prev_inv = st.session_state.get(f"input_inv_{day_num-1}", "")
                prev_lead = st.session_state.get(f"input_lead_{day_num-1}", "")
                prev_cam = st.session_state.get(f"input_cam_{day_num-1}", "")
                prev_extra = st.session_state.get(f"input_extra_{day_num-1}", "")
            else:
                prev_inv, prev_lead, prev_cam, prev_extra = "", "", "", ""

            col_cfg1, col_cfg2 = st.columns([1, 3])
            with col_cfg1:
                k_val = st.number_input(f"{day_num}일차 조 개수", min_value=1, value=3, key=f"k_{day_num}")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                inv_txt = st.text_area("조사자 후보", value=prev_inv, height=150, key=key_input_inv, placeholder="김조사\n이조사")
            with c2:
                lead_txt = st.text_area("섹장 후보", value=prev_lead, height=150, key=key_input_lead. placeholder="김섹장, 이섹장")
            with c3:
                extra_txt = st.text_area("쩌리 후보", value=prev_extra, height=150, key=key_input_extra)
            with c4:
                cam_txt = st.text_area("📸 카메라", value=prev_cam, height=150, key=key_input_cam, placeholder="여기 적힌 사람은\n가능한 조별로 찢어집니다.", help="역할(조사/섹장/쩌리)과 상관없이 카메라가 있는 사람들 이름을 모두 적으세요.")

            with st.expander("🚫 제약 조건"):
                ca, cb = st.columns(2)
                with ca: must_together_txt = st.text_area("꼭 같은 팀 (A-B)", height=70, key=f"together_{day_num}", placeholder="철수-영희\n박새-오목눈이")
                with cb: must_apart_txt = st.text_area("꼭 다른 팀 (A-B)", height=70, key=f"apart_{day_num}", placeholder="강아지-고양이, 사자-호랑이")

            if st.button(f"🚀 {day_num}일차 조 편성 실행", key=f"btn_{day_num}", use_container_width=True):
                invs = parse_names_auto(inv_txt)
                leads = parse_names_auto(lead_txt)
                cams = parse_names_auto(cam_txt)
                extras = parse_names_auto(extra_txt)
                mt = parse_pairs_auto(must_together_txt)
                ma = parse_pairs_auto(must_apart_txt)
                
                history_stats = get_history_stats(day_num, st.session_state)
                
                teams_struct, cam_set, err = try_make_teams_history_aware(
                    k=int(k_val), investigators=invs, leaders=leads, cameras=cams, extras=extras,
                    must_together=mt, must_apart=ma, history_stats=history_stats
                )
                
                if err:
                    st.error(err)
                else:
                    df_res = format_teams_for_editor(teams_struct, cam_set)
                    st.session_state[key_df] = df_res
                    st.rerun()

            st.divider()
            
            if key_df not in st.session_state:
                empty_cols = ["역할"] + [f"{i+1}조" for i in range(k_val)]
                empty_data = [["조사자"] + [""]*k_val, ["섹장"] + [""]*k_val] + [[f"쩌리{r+1}"] + [""]*k_val for r in range(3)]
                st.session_state[key_df] = pd.DataFrame(empty_data, columns=empty_cols)

            st.markdown(f"### 📝 {day_num}일차 조 편성")
            st.caption("아래 표를 클릭하여 직접 이름을 수정하거나 복사/붙여넣기 할 수 있습니다.")
            st.caption("셀을 수정하고 Tab을 누르거나 셀을 옮기면 수정이 적용됩니다. Enter로는 반영이 안돼요!!")
            st.caption("조 이름은 xlsx 다운로드 후 수정해주세요.")
            
            edited_df = st.data_editor(
                st.session_state[key_df],
                key=f"editor_{day_num}",
                num_rows="dynamic",
                use_container_width=True,
                height=300
            )
            
            st.session_state[key_df] = edited_df

            warnings = get_warnings(edited_df, day_num, st.session_state)
            if warnings:
                with st.container():
                    st.warning(f"⚠️ {len(warnings)}건의 중복 알림이 있습니다:")
                    for w in warnings:
                        st.write(w)
            else:
                if not edited_df.empty:
                    st.success("✅ 중복되는 역할이나 팀 구성이 없습니다 (또는 1일차입니다).")

            csv_buffer = create_excel_buffer(edited_df)
            st.download_button(
                label=f"💾 {day_num}일차 조 편성 결과 다운로드 (.xlsx)",
                data=csv_buffer,
                file_name=f"조편성_{day_num}일차.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"down_{day_num}"
            )
