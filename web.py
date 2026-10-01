"""UBCK 야생조류 조사 지원 앱 (Streamlit 진입점).

실행: streamlit run web.py
"""
import streamlit as st

from ubck.pages import fieldnote_page, map_page, teams_page

st.set_page_config(page_title="UBCK", page_icon="🐦", layout="wide")

pages = [
    st.Page(map_page.render, title="조사 지도", icon="🗺️", url_path="map", default=True),
    st.Page(teams_page.render, title="조 편성", icon="👥", url_path="teams"),
    st.Page(fieldnote_page.render, title="야장 정리", icon="📋", url_path="fieldnote"),
]
st.navigation(pages, position="top").run()
