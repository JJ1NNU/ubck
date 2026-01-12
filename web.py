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
import re

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
    """콤마(,) 또는 줄바꿈(\n)으로 이름을 분리하고 빈 값 제거"""
    if not raw:
        return []
    # 정규식: , 또는 \n (공백 포함 가능)
    parts = re.split(r'[,\n]+', raw)
    return [p.strip() for p in parts if p.strip()]

def parse_pairs_auto(raw: str):
    """
    여러 줄 또는 콤마로 쌍들을 분리한 뒤,
    각 쌍 내부를 '-'로 분리 (예: A-B, C-D)
    """
    if not raw:
        return []
    
    pairs = []
    # 1차 분리: 줄바꿈 or 콤마로 덩어리 나누기
    chunks = re.split(r'[,\n]+', raw)
    
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or '-' not in chunk:
            continue
        
        # 2차 분리: '-' 기준으로 2개로 나눔
        parts = chunk.split('-', 1)
        if len(parts) == 2:
            a, b = parts[0].strip(), parts[1].strip()
            if a and b:
                pairs.append((a, b))
    return pairs

def try_make_teams_with_camera(k, investigators, leaders, cameras, extras, must_together, must_apart, max_tries=3000):
    # 명단 복사
    investigators = investigators[:]
    leaders = leaders[:]
    cameras = cameras[:]  # 카메라 보유자
    extras = extras[:]

    # 전체 이름 집합 (중복 체크용)
    all_names = investigators + leaders + cameras + extras
    # 카메라 보유자는 역할이 아니라 '특성'이므로, 역할(조사자/섹장/쩌리)과 중복될 수 있음 -> 여기서는 '카메라 명단'을 따로 입력받지만, 실제로는 역할군 중 하나일 것임.
    # 하지만 사용 편의상 "카메라 보유자 칸"에 쓴 사람은 우선적으로 카메라 마크를 달아줘야 함.
    # 로직: 카메라 명단에 있는 사람은, 역할 배정 시 'has_camera=True' 속성을 가짐.
    
    # 중복 체크 (역할군 간에는 중복 없어야 함. 단, 카메라 명단은 역할군과 겹칠 수 있음 -> 입력란 분리했으므로 역할군 간 중복만 체크)
    # 카메라 명단에 있는 사람이 역할군(조사/섹장/쩌리) 어디에도 없으면 -> 자동으로 쩌리로 편입? or 에러?
    # -> 편의상 "역할군 어디에도 없으면 쩌리로 추가" 처리
    
    role_union = set(investigators) | set(leaders) | set(extras)
    for cam in cameras:
        if cam not in role_union:
            extras.append(cam) # 역할 없으면 쩌리로
    
    # 다시 중복 체크
    role_all = investigators + leaders + extras
    if len(set(role_all)) != len(role_all):
        return None, "역할(조사자/섹장/쩌리) 명단 간에 중복된 이름이 있습니다. 한 명은 하나의 역할만 가능합니다."

    if len(investigators) < k:
        return None, f"조사자 후보 부족 (필요 {k}, 현재 {len(investigators)})"
    if len(leaders) < k:
        return None, f"섹장 후보 부족 (필요 {k}, 현재 {len(leaders)})"

    camera_set = set(cameras)

    for _ in range(max_tries):
        random.shuffle(investigators)
        random.shuffle(leaders)
        random.shuffle(extras)

        teams = [{"members": [], "camera_count": 0} for _ in range(k)]
        
        # 1. 조사자 배정
        inv_pick = investigators[:k]
        inv_left = investigators[k:]
        for i in range(k):
            name = inv_pick[i]
            teams[i]["members"].append({"role": "조사자", "name": name, "has_cam": name in camera_set})
        
        # 2. 섹장 배정
        # (조사자로 뽑힌 사람 제외)
        used_names = set(inv_pick)
        lead_pool = [x for x in leaders if x not in used_names]
        if len(lead_pool) < k: continue
        
        random.shuffle(lead_pool)
        lead_pick = lead_pool[:k]
        lead_left = [x for x in leaders if x not in lead_pick and x not in used_names]
        
        for i in range(k):
            name = lead_pick[i]
            teams[i]["members"].append({"role": "섹장", "name": name, "has_cam": name in camera_set})

        # 3. 쩌리 배정
        # 남은 인원 (원래 쩌리 + 탈락자들)
        all_extras = extras + inv_left + lead_left
        random.shuffle(all_extras)
        
        # **카메라 균등 분배를 위한 쩌리 배정 전략**
        # 쩌리 중 카메라 있는 사람 / 없는 사람 분리
        extra_cams = [x for x in all_extras if x in camera_set]
        extra_no_cams = [x for x in all_extras if x not in camera_set]
        
        # 현재 각 팀 카메라 수 계산
        for t in teams:
            t["camera_count"] = sum(1 for m in t["members"] if m["has_cam"])
            
        # 쩌리(카메라O) 부터, 카메라 적은 팀에 우선 배정
        for cam_person in extra_cams:
            # 카메라 수가 가장 적은 팀 찾기
            teams.sort(key=lambda t: t["camera_count"])
            target_team = teams[0] # 제일 적은 팀
            target_team["members"].append({"role": "쩌리", "name": cam_person, "has_cam": True})
            target_team["camera_count"] += 1
            
        # 쩌리(카메라X) 배정 (인원수 균형 맞추기 위해, 현재 인원 적은 팀 순?)
        # 보통은 그냥 순서대로 넣거나 랜덤. 여기서는 순서대로 넣되 인원수 균형 고려
        for no_cam_person in extra_no_cams:
            teams.sort(key=lambda t: len(t["members"])) # 인원 적은 순
            teams[0]["members"].append({"role": "쩌리", "name": no_cam_person, "has_cam": False})

        # 4. 제약조건 검사 (같이/따로)
        # 데이터 구조 변환: teams -> 기존 constraints 함수가 쓸 수 있는 형태(dict)로 변환 필요?
        # 기존 constraints 함수는 {"조사자":..., "섹장":..., "쩌리":[]} 형태를 원함.
        # 맞춰서 변환해줌.
        formatted_teams = []
        for t in teams:
            ft = {"조사자": None, "섹장": None, "쩌리": []}
            for m in t["members"]:
                if m["role"] == "조사자": ft["조사자"] = m["name"]
                elif m["role"] == "섹장": ft["섹장"] = m["name"]
                else: ft["쩌리"].append(m["name"])
            formatted_teams.append(ft)
            
        ok, reason = check_constraints(formatted_teams, must_together, must_apart)
        if ok:
            # 성공 시, 카메라 표시(📷) 붙여서 반환할 데이터 정리
            return formatted_teams, camera_set, ""

    return None, None, f"조건을 만족하는 조합을 찾지 못했습니다. (재시도 {max_tries}회)"


def format_teams_with_camera_mark(teams, camera_set):
    """표시용 데이터프레임 생성 (카메라 📷 표시)"""
    max_jjuri = max((len(t["쩌리"]) for t in teams), default=0)
    
    def mark(name):
        return f"{name} 📷" if name in camera_set else name

    rows = []
    
    # 조사자
    rows.append(["조사자"] + [mark(t["조사자"]) for t in teams])
    # 섹장
    rows.append(["섹장"] + [mark(t["섹장"]) for t in teams])
    # 쩌리들
    for i in range(max_jjuri):
        row = [f"쩌리{i+1}"]
        for t in teams:
            if i < len(t["쩌리"]):
                row.append(mark(t["쩌리"][i]))
            else:
                row.append("")
        rows.append(row)
        
    cols = ["역할"] + [f"{i+1}조" for i in range(len(teams))]
    return pd.DataFrame(rows, columns=cols)


with tab3:
    st.subheader("👥 조 편성 (카메라 균등 분배)")
    st.info("💡 콤마(,) 또는 줄바꿈(Enter)으로 이름을 구분합니다. 카메라 보유자는 자동으로 균등하게 분산됩니다.")

    k = st.number_input("조 개수", min_value=1, value=3, step=1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        investigators_raw = st.text_area("조사자 후보", height=200, placeholder="김조사\n이조사")
    with c2:
        leaders_raw = st.text_area("섹장 후보", height=200, placeholder="박섹장, 최섹장")
    with c3:
        cameras_raw = st.text_area("📸 카메라 보유자", height=200, placeholder="여기 적힌 사람은\n가능한 조별로 찢어집니다.", help="역할(조사/섹장/쩌리)과 상관없이 카메라 가진 사람 이름을 적으세요.")
    with c4:
        extras_raw = st.text_area("쩌리 후보", height=200, placeholder="나머지 인원\n(비워둬도 됨)")

    with st.expander("🚫 제약 조건 (같이/따로)"):
        st.caption("이름 사이에 하이픈(-)을 넣어 쌍을 만드세요. 여러 쌍은 콤마나 줄바꿈으로 구분.")
        c_a, c_b = st.columns(2)
        with c_a:
            must_together_raw = st.text_area("꼭 같은 팀", placeholder="철수-영희\n민수-지수", height=100)
        with c_b:
            must_apart_raw = st.text_area("꼭 다른 팀", placeholder="사자-호랑이", height=100)

    run_team = st.button("조 편성 실행 🎲", use_container_width=True)

    if run_team:
        # 자동 파싱
        investigators = parse_names_auto(investigators_raw)
        leaders = parse_names_auto(leaders_raw)
        cameras = parse_names_auto(cameras_raw)
        extras = parse_names_auto(extras_raw)

        must_together = parse_pairs_auto(must_together_raw)
        must_apart = parse_pairs_auto(must_apart_raw)

        # 조 편성 로직 실행
        teams_data, cam_set, err = try_make_teams_with_camera(
            k=int(k),
            investigators=investigators,
            leaders=leaders,
            cameras=cameras,
            extras=extras,
            must_together=must_together,
            must_apart=must_apart
        )

        if err:
            st.error(err)
        else:
            st.success("조 편성이 완료되었습니다! (📷 표시는 카메라 보유자)")
            
            # 결과 표시
            df_display = format_teams_with_camera_mark(teams_data, cam_set)
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            # 다운로드
            excel_buffer = create_excel_buffer(df_display)
            st.download_button(
                label="📥 결과 엑셀 다운로드",
                data=excel_buffer,
                file_name="조편성_카메라분배.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
