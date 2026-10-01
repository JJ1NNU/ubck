"""조 편성 페이지."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ubck import storage
from ubck.storage import ATTR_COLUMNS, ROSTER_BOOL, ROSTER_COLUMNS
from ubck.teams.engine import SolveError, solve
from ubck.teams.history import build_history
from ubck.teams.io import (day_xlsx, df_to_result, empty_df, fairness_df, project_xlsx, read_result_xlsx,
                           result_to_df)
from ubck.teams.model import (CAMERA_MARK, Person, Rules, TeamResult, TeamSpec, Weights, parse_fixed, parse_groups,
                              parse_names)
from ubck.teams.report import check_result

PART_COLS = ["이름", "참가", "조사자", "섹장", "카메라"]


# ---------------------------------------------------------------- 상태
def _project() -> dict:
    if "project" not in st.session_state:
        try:
            st.session_state.project = storage.load()
        except Exception as e:  # 파일이 깨졌을 때도 화면은 뜨게
            st.session_state.project = storage.empty_project()
            st.session_state.load_error = str(e)
    return st.session_state.project


def _save() -> None:
    try:
        st.session_state.saved_at = storage.save(st.session_state.project)
    except OSError as e:
        st.session_state.save_error = str(e)


def _ver(name: str) -> int:
    return st.session_state.setdefault("_ver", {}).get(name, 0)


def _bump(name: str) -> None:
    v = st.session_state.setdefault("_ver", {})
    v[name] = v.get(name, 0) + 1


def _stable_df(name: str, build) -> pd.DataFrame:
    """data_editor 입력 표는 버전이 바뀔 때만 새로 만든다.
    (편집 결과를 다시 입력으로 넣으면 수정이 사라지거나 두 번 적용되는 Streamlit 특성 때문)"""
    store = st.session_state.setdefault("_base", {})
    key = (name, _ver(name))
    if key not in store:
        store[key] = build()
    return store[key]


def _records(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        out.append({k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()})
    return out


@st.cache_data(show_spinner=False)
def _sector_names() -> dict[str, list[str]]:
    from ubck.gis import load_all
    return {sv["name"]: [s["id"] for s in sv["sectors"]] for sv in load_all()["surveys"]}


# ---------------------------------------------------------------- 명단
def _roster_tab(project: dict) -> None:
    roster = project["roster"]
    n = len(roster)
    st.caption("동아리원 전체 명단입니다. 일차마다 참가 여부와 역할 가능 여부는 따로 바꿀 수 있습니다. "
               "엑셀에서 여러 칸을 복사해 표에 바로 붙여넣을 수 있습니다.")
    c = st.columns(4)
    c[0].metric("전체", f"{n}명")
    c[1].metric("조사자 가능", sum(1 for r in roster if r.get("조사자")))
    c[2].metric("섹장 가능", sum(1 for r in roster if r.get("섹장")))
    c[3].metric("카메라", sum(1 for r in roster if r.get("카메라")))

    base = _stable_df("roster", lambda: pd.DataFrame(roster, columns=ROSTER_COLUMNS))
    edited = st.data_editor(
        base, key=f"roster_editor_{_ver('roster')}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "이름": st.column_config.TextColumn("이름", required=True),
            "조사자": st.column_config.CheckboxColumn("조사자 가능", default=False),
            "섹장": st.column_config.CheckboxColumn("섹장 가능", default=False),
            "카메라": st.column_config.CheckboxColumn("카메라", default=False),
            "성별": st.column_config.TextColumn("성별", help="균형 맞추기에 쓸 수 있습니다(선택)."),
            "기수": st.column_config.TextColumn("기수", help="학번·기수 등. 균형 맞추기에 쓸 수 있습니다(선택)."),
            "숙련도": st.column_config.NumberColumn("숙련도", min_value=1, max_value=5, step=1,
                                                 help="1~5. 조별 평균을 비슷하게 맞출 수 있습니다(선택)."),
            "메모": st.column_config.TextColumn("메모"),
        },
    )
    rows = []
    for r in _records(edited):
        name = str(r.get("이름") or "").strip()
        if not name:
            continue
        r["이름"] = name
        for b in ROSTER_BOOL:
            r[b] = bool(r.get(b))
        rows.append(r)
    names = [r["이름"] for r in rows]
    dup = sorted({x for x in names if names.count(x) > 1})
    if dup:
        st.error(f"같은 이름이 두 번 있습니다: {', '.join(dup)}. 동명이인은 '김민수A'처럼 구분해 주세요.")
    if rows != roster:
        project["roster"] = rows
        _save()

    with st.expander("이름 목록 붙여넣어 한꺼번에 추가·표시하기"):
        st.caption("예전처럼 '조사자 후보' 목록을 붙여넣고 '조사자 가능'에 체크하면, 없는 사람은 추가되고 "
                   "있는 사람은 표시만 켜집니다.")
        txt = st.text_area("이름 (콤마, 줄바꿈, 탭으로 구분)", key="bulk_names", height=120)
        cc = st.columns(4)
        f_inv = cc[0].checkbox("조사자 가능", key="bulk_inv")
        f_lead = cc[1].checkbox("섹장 가능", key="bulk_lead")
        f_cam = cc[2].checkbox("카메라", key="bulk_cam")
        if cc[3].button("명단에 반영", key="bulk_go", width="stretch"):
            names_in = parse_names(txt)
            by = {r["이름"]: r for r in project["roster"]}
            added = 0
            for nm in names_in:
                if nm not in by:
                    by[nm] = {c: None for c in ROSTER_COLUMNS} | {"이름": nm, "조사자": False, "섹장": False, "카메라": False}
                    project["roster"].append(by[nm])
                    added += 1
                if f_inv:
                    by[nm]["조사자"] = True
                if f_lead:
                    by[nm]["섹장"] = True
                if f_cam:
                    by[nm]["카메라"] = True
            _save()
            _bump("roster")
            st.session_state.flash = f"{len(names_in)}명 반영 (새로 추가 {added}명)"
            st.rerun()


# ---------------------------------------------------------------- 일차
def _sync_participants(day: dict, roster: list[dict]) -> bool:
    parts = day.setdefault("participants", {})
    changed = False
    names = [r["이름"] for r in roster]
    for r in roster:
        if r["이름"] not in parts:
            parts[r["이름"]] = {"참가": True, "조사자": r["조사자"], "섹장": r["섹장"], "카메라": r["카메라"]}
            changed = True
    for nm in list(parts):
        if nm not in names:
            del parts[nm]
            changed = True
    return changed


def _day_tab(project: dict) -> None:
    days = project["days"]
    roster = project["roster"]
    if not roster:
        st.info("먼저 '명단' 탭에서 동아리원을 입력해 주세요.")
        return
    top = st.columns([3, 1, 1])
    if days:
        labels = [d["label"] for d in days]
        cur = st.session_state.get("day_idx", len(days) - 1)
        cur = min(cur, len(days) - 1)
        idx = top[0].radio("일차", range(len(days)), index=cur, format_func=lambda i: labels[i],
                           horizontal=True, key=f"day_radio_{len(days)}_{_ver('days')}")
        st.session_state.day_idx = idx
    if top[1].button("새 일차 추가", width="stretch", help="이전 일차의 조 구성·참가 여부·규칙을 이어받습니다."):
        prev = days[-1] if days else None
        days.append(storage.new_day(f"{len(days) + 1}일차", prev))
        st.session_state.day_idx = len(days) - 1
        _bump("days")
        _save()
        st.rerun()
    if not days:
        st.info("'새 일차 추가'를 눌러 1일차를 만드세요.")
        return
    day = days[idx]
    with top[2].popover("이 일차 삭제", width="stretch"):
        st.write(f"{day['label']}을(를) 삭제합니다. 편성 결과도 함께 지워집니다.")
        if st.button("삭제", key=f"del_{day['id']}", type="primary"):
            days.pop(idx)
            st.session_state.day_idx = max(0, idx - 1)
            _bump("days")
            _save()
            st.rerun()

    if _sync_participants(day, roster):
        _save()
    did = day["id"]
    history = build_history([[TeamResult.from_dict(t) for t in d["result"]] for d in days[:idx] if d.get("result")])

    label = st.text_input("일차 이름", day["label"], key=f"label_{did}")
    if label.strip() and label != day["label"]:
        day["label"] = label.strip()
        _save()
    done_before = sum(1 for d in days[:idx] if d.get("result"))
    st.caption(f"이전 일차 중 편성 결과가 있는 {done_before}개 일차의 이력을 반영해 겹침을 줄입니다.")

    # ---- 1. 조 구성
    st.markdown("#### 1. 조 구성")
    tc = st.columns([1, 1, 1, 2])
    k = tc[0].number_input("조 개수", 1, 40, len(day["teams"]) or 1, key=f"k_{did}_{_ver('teams' + did)}")
    if k != len(day["teams"]):
        day["teams"] = day["teams"][:k] + [{"name": f"{i + 1}조", "size": None} for i in range(len(day["teams"]), k)]
        _bump("teams" + did)
        _save()
        st.rerun()
    sectors = _sector_names()
    for col, sv in zip(tc[1:3], sectors):
        if col.button(f"{sv} 섹터 이름으로", key=f"preset_{sv}_{did}", width="stretch",
                      help=f"{', '.join(sectors[sv])}"):
            day["teams"] = [{"name": s, "size": None} for s in sectors[sv]]
            _bump("teams" + did)
            _save()
            st.rerun()
    tc[3].caption("조 이름을 조사 섹터 이름으로 해 두면 '같은 섹터에 또 배정'을 피할 수 있습니다. "
                  "정원을 비워 두면 남은 인원을 고르게 나눕니다.")
    tbase = _stable_df("teams" + did, lambda: pd.DataFrame(
        [{"조 이름": t["name"], "정원": t.get("size")} for t in day["teams"]]))
    tedit = st.data_editor(tbase, key=f"teams_ed_{did}_{_ver('teams' + did)}", hide_index=True, width="stretch",
                           num_rows="fixed",
                           column_config={"조 이름": st.column_config.TextColumn(required=True),
                                          "정원": st.column_config.NumberColumn(min_value=2, max_value=60, step=1,
                                                                              help="비우면 자동")})
    new_teams = []
    for i, r in enumerate(_records(tedit)):
        nm = str(r.get("조 이름") or "").strip() or f"{i + 1}조"
        size = r.get("정원")
        new_teams.append({"name": nm, "size": int(size) if size else None})
    if new_teams != day["teams"]:
        day["teams"] = new_teams
        _save()
    tnames = [t["name"] for t in day["teams"]]
    if len(set(tnames)) != len(tnames):
        st.error("조 이름이 겹칩니다. 서로 다르게 바꿔 주세요.")

    # ---- 2. 참가자
    st.markdown("#### 2. 오늘 참가자")
    parts = day["participants"]
    pname = f"parts{did}_{abs(hash(tuple(r['이름'] for r in roster)))}"
    pbase = _stable_df(pname, lambda: pd.DataFrame(
        [{"이름": r["이름"], **{c: parts[r["이름"]][c] for c in PART_COLS[1:]}} for r in roster], columns=PART_COLS))
    pc = st.columns([1, 1, 3])
    if pc[0].button("모두 참가로", key=f"allin_{did}", width="stretch"):
        for v in parts.values():
            v["참가"] = True
        _bump(pname)
        _save()
        st.rerun()
    if pc[1].button("명단 기준으로 되돌리기", key=f"reset_{did}", width="stretch",
                    help="조사자·섹장·카메라 표시를 '명단' 탭 값으로 되돌립니다."):
        for r in roster:
            parts[r["이름"]].update({"조사자": r["조사자"], "섹장": r["섹장"], "카메라": r["카메라"]})
        _bump(pname)
        _save()
        st.rerun()
    pedit = st.data_editor(pbase, key=f"parts_ed_{pname}_{_ver(pname)}",
                           hide_index=True, width="stretch", num_rows="fixed", disabled=["이름"], height=320,
                           column_config={c: st.column_config.CheckboxColumn(c) for c in PART_COLS[1:]})
    for r in _records(pedit):
        cur = parts.get(r["이름"])
        newv = {c: bool(r.get(c)) for c in PART_COLS[1:]}
        if cur is not None and cur != newv:
            parts[r["이름"]] = newv
            day["_dirty"] = True
    if day.pop("_dirty", False):
        _save()
    present = [nm for nm, v in parts.items() if v["참가"]]
    m = st.columns(4)
    m[0].metric("참가", f"{len(present)}명")
    m[1].metric("조사자 가능", sum(1 for nm in present if parts[nm]["조사자"]))
    m[2].metric("섹장 가능", sum(1 for nm in present if parts[nm]["섹장"]))
    m[3].metric("카메라", sum(1 for nm in present if parts[nm]["카메라"]))

    # ---- 3. 규칙
    st.markdown("#### 3. 조건")
    rules_raw = day["rules"]
    rc = st.columns(3)
    together = rc[0].text_area("꼭 같은 조", rules_raw["together"], key=f"tog_{did}", height=110,
                               placeholder="철수-영희\n민수-지수-하늘", help="한 줄(또는 콤마)에 한 묶음. 이름은 - 로 잇습니다. 세 명 이상도 됩니다.")
    apart = rc[1].text_area("꼭 다른 조", rules_raw["apart"], key=f"apart_{did}", height=110,
                            placeholder="강아지-고양이\n사자-호랑이-표범", help="한 묶음 안의 모든 사람이 서로 다른 조가 됩니다.")
    fixed = rc[2].text_area("고정", rules_raw["fixed"], key=f"fixed_{did}", height=110,
                            placeholder=f"철수={tnames[0] if tnames else '1조'}\n영희=조사자",
                            help="이름=조 이름 → 그 조로 고정. 이름=조사자 / 이름=섹장 → 그 역할을 꼭 맡김.")
    new_rules = {"together": together, "apart": apart, "fixed": fixed}
    if new_rules != rules_raw:
        day["rules"] = new_rules
        _save()
    fixed_team, fixed_role, bad = parse_fixed(fixed, tnames)
    rules = Rules(parse_groups(together), parse_groups(apart), fixed_team, fixed_role)
    if bad:
        st.warning(f"'고정'에서 이해하지 못한 줄: {', '.join(bad)} (조 이름이나 '조사자'/'섹장'인지 확인)")
    known = {r["이름"] for r in roster}
    typo = sorted({n for g in rules.together + rules.apart for n in g} | set(fixed_team) | set(fixed_role))
    typo = [n for n in typo if n not in known]
    if typo:
        st.warning(f"명단에 없는 이름: {', '.join(typo)}")

    # ---- 4. 실행
    st.markdown("#### 4. 편성")
    settings = project["settings"]
    with st.expander("무엇을 얼마나 중요하게 볼지 (가중치)와 탐색 시간"):
        w = settings["weights"]
        wc = st.columns(4)
        nw = {
            "pair": wc[0].slider("같은 사람과 또 만나기", 0.0, 10.0, float(w["pair"]), 0.5, key="w_pair",
                                 help="이전에 같은 조였던 두 사람이 또 같은 조가 될 때마다 더하는 벌점"),
            "same_team": wc[1].slider("같은 조(섹터) 또 배정", 0.0, 10.0, float(w["same_team"]), 0.5, key="w_team"),
            "role": wc[2].slider("조사자·섹장 또 맡기", 0.0, 10.0, float(w["role"]), 0.5, key="w_role"),
            "camera": wc[3].slider("카메라 몰림", 0.0, 10.0, float(w["camera"]), 0.5, key="w_cam"),
        }
        attr_avail = [c for c in ATTR_COLUMNS if any(r.get(c) not in (None, "") for r in roster)]
        aw = settings.get("attr_weights", {})
        chosen = st.multiselect("고르게 섞을 속성", attr_avail, default=[a for a in aw if a in attr_avail],
                                key="attr_sel", help="명단에 값이 있는 열만 보입니다. 성별·기수는 비율을, 숙련도는 평균을 맞춥니다.")
        new_aw = {}
        if chosen:
            ac = st.columns(len(chosen))
            for col, a in zip(ac, chosen):
                new_aw[a] = col.slider(f"{a} 균형", 0.5, 10.0, float(aw.get(a, 2.0)), 0.5, key=f"aw_{a}")
        sc = st.columns(2)
        tl = sc[0].slider("탐색 시간(초)", 2, 60, int(settings.get("time_limit", 8)), key="time_limit",
                          help="길수록 더 좋은 편성을 찾을 가능성이 높습니다.")
        ncand = sc[1].slider("보여 줄 후보 수", 1, 5, int(settings.get("n_candidates", 3)), key="n_cand")
        new_settings = {**settings, "weights": nw, "attr_weights": new_aw, "time_limit": tl, "n_candidates": ncand}
        if new_settings != settings:
            project["settings"] = new_settings
            _save()
    settings = project["settings"]

    if st.button(f"{day['label']} 조 편성 실행", type="primary", width="stretch", key=f"run_{did}"):
        people = []
        attr_by = {r["이름"]: r for r in roster}
        for nm in present:
            v = parts[nm]
            people.append(Person(nm, v["조사자"], v["섹장"], v["카메라"],
                                 {a: attr_by[nm].get(a) for a in ATTR_COLUMNS}))
        teams = [TeamSpec(t["name"], t.get("size")) for t in day["teams"]]
        wts = Weights(**settings["weights"], attrs=settings.get("attr_weights", {}))
        try:
            with st.spinner(f"{settings['time_limit']}초 동안 더 나은 편성을 찾는 중…"):
                res = solve(people, teams, rules, wts, history, time_limit=settings["time_limit"],
                            n_solutions=settings.get("n_candidates", 3))
            st.session_state.setdefault("cands", {})[did] = res
        except SolveError as e:
            st.session_state.setdefault("cands", {}).pop(did, None)
            st.error("편성할 수 없습니다.\n\n" + "\n".join(f"- {m}" for m in e.messages))

    res = st.session_state.get("cands", {}).get(did)
    cams = {nm for nm, v in parts.items() if v["카메라"]}
    if res:
        for wmsg in res.warnings:
            st.warning(wmsg)
        st.caption(f"{res.seconds}초 동안 {res.iterations:,}가지 바꿔 보기를 시도했습니다. 점수가 낮을수록 좋습니다.")
        ctabs = st.tabs([f"후보 {i + 1} (점수 {s.cost:g})" for i, s in enumerate(res.solutions)])
        for i, (ct, sol) in enumerate(zip(ctabs, res.solutions)):
            with ct:
                bc = st.columns(len(sol.breakdown))
                for col, (kk, vv) in zip(bc, sol.breakdown.items()):
                    col.metric(kk, vv)
                for v in sol.violations:
                    st.error(v)
                st.dataframe(result_to_df(sol.teams, cams), hide_index=True, width="stretch")
                if st.button("이 후보로 확정", key=f"pick_{did}_{i}", type="primary"):
                    day["result"] = [t.to_dict() for t in sol.teams]
                    _bump("res" + did)
                    st.session_state["cands"].pop(did, None)
                    _save()
                    st.session_state.flash = f"{day['label']} 편성을 확정했습니다. 아래 표에서 직접 고칠 수 있습니다."
                    st.rerun()
        if day.get("result"):
            st.caption("확정하면 아래의 현재 편성 결과를 덮어씁니다.")

    # ---- 5. 결과
    st.markdown("#### 5. 편성 결과")
    result = [TeamResult.from_dict(t) for t in day["result"]] if day.get("result") else None
    rbase = _stable_df("res" + did, lambda: result_to_df(result, cams) if result else empty_df(tnames))
    st.caption("칸을 눌러 이름을 고치거나 붙여넣을 수 있습니다. 행 추가도 됩니다. 수정 내용은 바로 저장됩니다.")
    redit = st.data_editor(rbase, key=f"res_ed_{did}_{_ver('res' + did)}", hide_index=True, width="stretch",
                           num_rows="dynamic", disabled=["역할"] if result else False)
    edited = [t for t in df_to_result(redit)]
    has_any = any(t.everyone for t in edited)
    new_result = [t.to_dict() for t in edited] if has_any else None
    if new_result != day.get("result"):
        day["result"] = new_result
        _save()
    if has_any:
        findings = check_result(edited, set(present), known, rules, history)
        errs = [f for f in findings if f.level == "error"]
        warns = [f for f in findings if f.level == "warn"]
        infos = [f for f in findings if f.level == "info"]
        for f in errs:
            st.error(f.text)
        for f in warns:
            st.warning(f.text)
        if infos:
            with st.expander(f"이전 일차와 겹치는 점 {len(infos)}건"):
                for f in infos:
                    st.write(f.text)
        elif not errs and not warns:
            st.success("규칙 위반이나 이전 일차와의 겹침이 없습니다.")
        dc = st.columns([2, 1])
        dc[0].download_button(f"{day['label']} 결과 엑셀로 받기", day_xlsx(result_to_df(edited, cams), day["label"]),
                              file_name=f"조편성_{day['label']}.xlsx", key=f"dl_{did}", width="stretch",
                              mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with dc[1].popover("결과 비우기", width="stretch"):
            if st.button("편성 결과 지우기", key=f"clr_{did}", type="primary"):
                day["result"] = None
                _bump("res" + did)
                _save()
                st.rerun()


# ---------------------------------------------------------------- 이력
def _history_tab(project: dict) -> None:
    done = [d for d in project["days"] if d.get("result")]
    if not done:
        st.info("편성 결과가 있는 일차가 아직 없습니다.")
        return
    st.caption(f"편성 결과가 있는 {len(done)}개 일차를 합친 사람별 이력입니다. 표 머리글을 눌러 정렬할 수 있습니다.")
    df = fairness_df(project)
    st.dataframe(df, hide_index=True, width="stretch", height=480)
    st.download_button("전체 일차와 개인별 이력을 엑셀 한 파일로 받기", project_xlsx(project),
                       file_name="UBCK_조편성_전체.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- 백업
def _backup_tab(project: dict) -> None:
    st.markdown("**프로젝트 파일 백업**")
    st.caption("명단·일차·편성 결과·가중치가 모두 들어 있는 파일입니다. 서버를 다시 시작하면 저장 내용이 지워질 수 있으니 "
               "조 편성을 확정할 때마다 받아 두세요.")
    st.download_button("프로젝트 파일 받기 (.json)", storage.dumps(project).encode("utf-8"),
                       file_name="ubck_project.json", mime="application/json", width="stretch")
    up = st.file_uploader("프로젝트 파일 올리기 (현재 내용을 바꿉니다)", type=["json"], key="up_json")
    if up is not None and st.button("올린 파일로 바꾸기", type="primary"):
        try:
            st.session_state.project = storage.normalize(json.loads(up.getvalue().decode("utf-8")))
            for k in ("_base", "_ver", "cands"):
                st.session_state.pop(k, None)
            _save()
            st.session_state.flash = "프로젝트 파일을 불러왔습니다."
            st.rerun()
        except (ValueError, json.JSONDecodeError) as e:
            st.error(f"불러올 수 없는 파일입니다: {e}")

    st.divider()
    st.markdown("**예전 조 편성 엑셀 가져오기**")
    st.caption("예전 사이트에서 받은 '조편성_n일차.xlsx'를 올리면 일차로 추가하고, 명단에 없는 사람은 명단에 추가합니다. "
               "조사자·섹장 칸에 있던 사람은 그 역할 가능으로, 📷 표시는 카메라로 표시합니다. 파일 이름 순서대로 추가됩니다.")
    files = st.file_uploader("엑셀 파일 (여러 개 가능)", type=["xlsx"], accept_multiple_files=True, key="up_xlsx")
    if files and st.button("일차로 추가", type="primary"):
        by = {r["이름"]: r for r in project["roster"]}
        added_days = 0
        for f in sorted(files, key=lambda x: x.name):
            raw = pd.read_excel(f, sheet_name=0, dtype=str).fillna("")
            cams = {str(v).replace("📷", "").strip() for v in raw.values.ravel() if "📷" in str(v)}
            f.seek(0)
            teams = read_result_xlsx(f)
            if not teams:
                st.warning(f"{f.name}: 편성 내용을 찾지 못했습니다.")
                continue
            for t in teams:
                for nm in t.everyone:
                    if nm not in by:
                        by[nm] = {c: None for c in ROSTER_COLUMNS} | {"이름": nm, "조사자": False, "섹장": False, "카메라": False}
                        project["roster"].append(by[nm])
                    if nm == t.inv:
                        by[nm]["조사자"] = True
                    if nm == t.lead:
                        by[nm]["섹장"] = True
                    if nm in cams:
                        by[nm]["카메라"] = True
            label = f.name.rsplit(".", 1)[0].replace("조편성_", "")
            d = storage.new_day(label, project["days"][-1] if project["days"] else None)
            d["teams"] = [{"name": t.name, "size": None} for t in teams]
            d["result"] = [t.to_dict() for t in teams]
            d["participants"] = {}
            project["days"].append(d)
            _sync_participants(d, project["roster"])
            present = {n for t in teams for n in t.everyone}
            for nm, v in d["participants"].items():
                v["참가"] = nm in present
            added_days += 1
        _bump("roster")
        _bump("days")
        _save()
        st.session_state.flash = f"{added_days}개 일차를 가져왔습니다."
        st.rerun()

    st.divider()
    st.caption(f"저장 위치: `{storage.default_path()}`")
    if st.button("저장된 파일에서 다시 불러오기", help="다른 사람이 같은 서버에서 고친 내용을 보려면 누르세요."):
        st.session_state.project = storage.load()
        for k in ("_base", "_ver", "cands"):
            st.session_state.pop(k, None)
        st.rerun()


# ---------------------------------------------------------------- 진입점
def render() -> None:
    project = _project()
    st.subheader("조 편성")
    if st.session_state.get("load_error"):
        st.error(f"저장된 파일을 읽지 못해 빈 프로젝트로 시작했습니다: {st.session_state.load_error}")
    if st.session_state.get("save_error"):
        st.error(f"저장하지 못했습니다: {st.session_state.pop('save_error')}. '백업' 탭에서 파일로 받아 두세요.")
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    tabs = st.tabs(["명단", "일차별 편성", "누적 이력", "백업·가져오기"])
    with tabs[0]:
        _roster_tab(project)
    with tabs[1]:
        _day_tab(project)
    with tabs[2]:
        _history_tab(project)
    with tabs[3]:
        _backup_tab(project)
    if st.session_state.get("saved_at"):
        st.caption(f"마지막 저장 {st.session_state.saved_at}")
