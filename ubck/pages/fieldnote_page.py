"""야장 정리 페이지."""
from __future__ import annotations

import streamlit as st

from ubck.fieldnote import format_line, merge_same_species, parse


def render() -> None:
    st.subheader("야장 정리")
    st.caption("야장정리기 결과(국명과 개체수 두 열)를 엑셀에서 복사해 붙여넣으면 "
               "'국명 <수>, 국명 <수>' 한 줄로 바꿉니다. 순서와 이름은 입력 그대로 둡니다.")
    left, right = st.columns(2)
    with left:
        raw = st.text_area("붙여넣기", height=380, key="fn_raw", placeholder="청둥오리\t120\n흰뺨검둥오리\t35\n큰고니\t8")
        merge = st.checkbox("같은 종이 여러 줄이면 합치기", key="fn_merge")
    with right:
        p = parse(raw)
        items = merge_same_species(p.items) if merge else p.items
        st.markdown(f"**결과** ({len(items)}종)")
        if items:
            st.code(format_line(items), language=None, wrap_lines=True)
            st.caption("오른쪽 위 복사 버튼으로 복사하세요.")
        if p.skipped:
            st.warning("개체수를 읽지 못해 뺀 줄:\n\n" + "\n".join(f"- {s}" for s in p.skipped))
