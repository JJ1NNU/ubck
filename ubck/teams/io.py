"""편성 결과 ↔ 표(DataFrame) ↔ 엑셀."""
from __future__ import annotations

import io
import re

import pandas as pd

from .history import build_history
from .model import CAMERA_MARK, ROLE_INV, ROLE_LEAD, ROLE_MEMBER, TeamResult, clean_name

ROLE_COL = "역할"


def result_to_df(teams: list[TeamResult], cameras: set[str] | None = None) -> pd.DataFrame:
    cameras = cameras or set()

    def mark(n):
        return f"{n}{CAMERA_MARK}" if n and n in cameras else (n or "")

    rows = [[ROLE_INV] + [mark(t.inv) for t in teams], [ROLE_LEAD] + [mark(t.lead) for t in teams]]
    depth = max((len(t.members) for t in teams), default=0)
    for i in range(depth):
        rows.append([f"{ROLE_MEMBER}{i + 1}"] + [mark(t.members[i]) if i < len(t.members) else "" for t in teams])
    return pd.DataFrame(rows, columns=[ROLE_COL] + [t.name for t in teams])


def empty_df(team_names: list[str], depth: int = 3) -> pd.DataFrame:
    return result_to_df([TeamResult(n, None, None, [""] * depth) for n in team_names])


def df_to_result(df: pd.DataFrame) -> list[TeamResult]:
    """표 → 조 목록. 역할 칸이 '조사자'/'섹장'이면 그 역할, 나머지는 쩌리."""
    if df is None or df.empty:
        return []
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    role_col = ROLE_COL if ROLE_COL in df.columns else df.columns[0]
    teams = []
    for col in [c for c in df.columns if c != role_col and not c.startswith("Unnamed")]:
        t = TeamResult(col)
        for _, row in df.iterrows():
            name = clean_name(row[col])
            if not name:
                continue
            role = str(row[role_col]).strip()
            if role == ROLE_INV and not t.inv:
                t.inv = name
            elif role == ROLE_LEAD and not t.lead:
                t.lead = name
            else:
                t.members.append(name)
        teams.append(t)
    return teams


def read_result_xlsx(file) -> list[TeamResult]:
    """예전 웹앱에서 내려받은 '조편성_n일차.xlsx'(역할 열 + 조별 열)도 그대로 읽는다."""
    df = pd.read_excel(file, sheet_name=0, dtype=str).fillna("")
    return [t for t in df_to_result(df) if t.everyone]


def _sheet_name(label: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]\*\?/\\:]", "_", label)[:31] or "sheet"
    name, i = base, 2
    while name in used:
        suffix = f"({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


def day_xlsx(df: pd.DataFrame, label: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=_sheet_name(label, set()), index=False)
    return buf.getvalue()


def fairness_df(project: dict) -> pd.DataFrame:
    """사람별 누적 이력: 참가 일수, 역할 횟수, 조 이력, 가장 자주 겹친 사람."""
    days = [d for d in project["days"] if d.get("result")]
    results = [[TeamResult.from_dict(t) for t in d["result"]] for d in days]
    h = build_history(results)
    names = [r["이름"] for r in project["roster"]]
    for teams in results:
        for t in teams:
            for n in t.everyone:
                if n not in names:
                    names.append(n)
    rows = []
    for n in names:
        trail = []
        for d, teams in zip(days, results):
            hit = next((t for t in teams if n in t.everyone), None)
            if hit:
                role = hit.role_of(n)
                trail.append(f"{d['label']}:{hit.name}" + ("" if role == ROLE_MEMBER else f"({role})"))
        partners = {}
        for key, c in h.pair.items():
            if n in key:
                other = next(iter(key - {n}))
                partners[other] = c
        top = sorted(partners.items(), key=lambda x: (-x[1], x[0]))
        repeat = [f"{o}({c}회)" for o, c in top if c >= 2][:3]
        rows.append({"이름": n, "참가 일수": h.days.get(n, 0), "조사자": h.role[n][ROLE_INV], "섹장": h.role[n][ROLE_LEAD],
                     "만난 사람 수": len(partners), "2번 이상 같은 조": ", ".join(repeat), "이력": "  ".join(trail)})
    return pd.DataFrame(rows)


def project_xlsx(project: dict) -> bytes:
    """전체 일차 + 개인별 이력 + 명단을 한 파일로."""
    buf = io.BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        cams = {r["이름"] for r in project["roster"] if r.get("카메라")}
        for d in project["days"]:
            if d.get("result"):
                df = result_to_df([TeamResult.from_dict(t) for t in d["result"]], cams)
                df.to_excel(w, sheet_name=_sheet_name(d["label"], used), index=False)
        fairness_df(project).to_excel(w, sheet_name=_sheet_name("개인별 이력", used), index=False)
        pd.DataFrame(project["roster"]).to_excel(w, sheet_name=_sheet_name("명단", used), index=False)
    return buf.getvalue()
