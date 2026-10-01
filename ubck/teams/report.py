"""편성 결과 점검: 규칙 위반(오류)과 이력상 반복(알림)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from .history import History
from .model import ROLE_INV, ROLE_LEAD, Rules, TeamResult


@dataclass
class Finding:
    level: str   # "error" | "warn" | "info"
    text: str


def check_result(teams: list[TeamResult], participants: set[str], known: set[str], rules: Rules,
                 history: History) -> list[Finding]:
    out: list[Finding] = []
    where: dict[str, list[str]] = {}
    for t in teams:
        for n in t.everyone:
            where.setdefault(n, []).append(t.name)

    # ---- 오류: 바로 고쳐야 하는 것 ----
    for n, ts in where.items():
        if len(ts) > 1:
            out.append(Finding("error", f"{n}이(가) 여러 곳에 들어 있습니다: {', '.join(ts)}"))
    for t in teams:
        if t.everyone and not t.inv:
            out.append(Finding("error", f"{t.name}: 조사자 칸이 비어 있습니다."))
        if t.everyone and not t.lead:
            out.append(Finding("error", f"{t.name}: 섹장 칸이 비어 있습니다."))
    unknown = [n for n in where if n not in known]
    if unknown:
        out.append(Finding("error", f"명단에 없는 이름(오타일 수 있음): {', '.join(unknown)}"))
    team_of = {n: ts[0] for n, ts in where.items()}
    for g in rules.together:
        placed = {team_of[n] for n in g if n in team_of}
        if len(placed) > 1:
            out.append(Finding("error", f"꼭 같은 조 위반: {', '.join(g)}"))
    for g in rules.apart:
        for a, b in combinations(g, 2):
            if a in team_of and team_of.get(a) == team_of.get(b):
                out.append(Finding("error", f"꼭 다른 조 위반: {a}, {b} ({team_of[a]})"))
    for n, tn in rules.fixed_team.items():
        if n in team_of and team_of[n] != tn:
            out.append(Finding("error", f"조 고정 위반: {n}은(는) {tn} 고정인데 {team_of[n]}에 있습니다."))
    for n, r in rules.fixed_role.items():
        t = next((t for t in teams if n in t.everyone), None)
        if t and t.role_of(n) != r:
            out.append(Finding("error", f"역할 고정 위반: {n}은(는) {r} 고정인데 {t.role_of(n)}입니다."))

    # ---- 주의: 참가자 누락 ----
    missing = sorted(participants - set(where))
    if missing and where:
        out.append(Finding("warn", f"오늘 참가자인데 어느 조에도 없는 사람: {', '.join(missing)}"))
    absent = sorted(n for n in where if n in known and n not in participants)
    if absent:
        out.append(Finding("warn", f"오늘 불참으로 표시된 사람이 편성되어 있습니다: {', '.join(absent)}"))
    sizes = Counter({t.name: len(t.everyone) for t in teams if t.everyone})
    if sizes and max(sizes.values()) - min(sizes.values()) > 1:
        out.append(Finding("warn", "조별 인원 차이가 2명 이상입니다: " + ", ".join(f"{k} {v}명" for k, v in sizes.items())))

    # ---- 참고: 이전 일차와 겹침 ----
    for t in teams:
        for n, r in ((t.inv, ROLE_INV), (t.lead, ROLE_LEAD)):
            if n and history.role[n][r]:
                out.append(Finding("info", f"{n}: 이전에 {r}을(를) {history.role[n][r]}번 했습니다."))
        for n in t.everyone:
            c = history.team[n][t.name]
            if c:
                out.append(Finding("info", f"{n}: 이전에 {t.name}에 {c}번 배정됐습니다."))
        for a, b in combinations(sorted(set(t.everyone)), 2):
            c = history.pair_count(a, b)
            if c:
                out.append(Finding("info", f"{t.name}: {a}·{b}는 이전에 {c}번 같은 조였습니다."))
    return out
