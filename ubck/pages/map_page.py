"""지도 페이지."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from ubck.gis import load_all
from ubck.map_view import build_map_html


@st.cache_data(show_spinner="조사구역 지도를 불러오는 중…")
def _map_data() -> dict:
    return load_all()


def _vworld_key() -> str | None:
    try:
        return st.secrets.get("VWORLD_API_KEY") or None
    except Exception:  # secrets.toml이 아예 없을 때
        return None


def render() -> None:
    # 모바일에서 지도가 화면을 최대한 쓰도록 여백 축소
    st.markdown(
        """<style>
        .block-container {padding-top: 3.2rem; padding-bottom: 0.5rem; padding-left: .5rem; padding-right: .5rem;}
        iframe[title="st.iframe"], iframe {border-radius: 10px;}
        </style>""",
        unsafe_allow_html=True,
    )
    height = st.session_state.get("map_height", 680)
    key = _vworld_key()
    html = build_map_html(_map_data(), key)
    if hasattr(st, "iframe"):          # Streamlit 1.5x 이후
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)

    with st.expander("지도 사용법과 설정"):
        st.markdown(
            """
- **섹터 선택**: 위쪽 목록에서 오늘 맡은 섹터를 고르면 그 경로만 강조되고, 진행 방향 화살표와 출발·도착 지점이 표시됩니다. 경로 선을 눌러도 선택됩니다.
- **내 위치 보기**: 한 번만 위치를 확인합니다. 섹터를 골라 두었다면 가야 할 곳이 함께 보이게 지도를 맞춥니다.
- **안내 시작**: 위치를 계속 따라가며 진행률, 경로상 남은 거리, 가야 할 방향을 보여 줍니다. 경로에서 기준 거리(기본 50 m) 이상 두 번 연속 벗어나면 빨간 경고와 함께 진동·소리로 알립니다.
  - 출발 지점에 도착하기 전에는 이탈 경고를 하지 않고 출발 지점까지의 방향만 안내합니다.
  - GPS 오차가 클 때는 이탈 판정을 잠시 보류합니다.
- **화면은 켜 두세요.** 화면이 꺼지거나 다른 앱으로 넘어가면 브라우저가 위치 갱신을 멈춥니다. 안내 중에는 화면 꺼짐 방지를 요청합니다(지원 기기만).
- 위치는 휴대폰 안에서만 계산되며 서버로 보내거나 저장하지 않습니다.
            """
        )
        st.slider("지도 높이(px)", 420, 1100, height, step=20, key="map_height",
                  help="휴대폰 화면에 맞게 조절하세요. 브라우저에 저장되지는 않습니다.")
        if not key:
            st.info("VWorld 키가 설정되지 않아 OpenStreetMap 배경지도를 씁니다. "
                    "`.streamlit/secrets.toml`에 `VWORLD_API_KEY`를 넣으면 VWorld 일반지도·항공사진을 씁니다.")
