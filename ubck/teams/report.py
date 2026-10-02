"""편성 결과 점검: 규칙 위반(오류), 주의, 이전 일차와 겹침(참고), 당일 변경 도움말."""
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
                 history: History, absent: set[str] | None = None,
                 inv_qualified: set[str] | None = None) -> list[Finding]:
    absent = absent or set()
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
        out.append(Finding("error", f"명단에 없는 이름(오타일 수 있음): {', '.join(unknown)}. "
                                    "새로 온 사람이면 아래 '명단에 추가'를 누르세요."))
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

    # ---- 주의 ----
    missing = sorted(participants - set(where) - absent)
    if missing and where:
        out.append(Finding("warn", f"참가자인데 어느 조에도, 결원에도 없는 사람: {', '.join(missing)}"))
    sizes = Counter({t.name: len(t.everyone) for t in teams if t.everyone})
    if sizes and max(sizes.values()) - min(sizes.values()) > 1:
        out.append(Finding("warn", "조별 인원 차이가 2명 이상입니다: " + ", ".join(f"{k} {v}명" for k, v in sizes.items())))
    revisit_level = "warn" if rules.no_revisit else "info"
    for t in teams:
        for n in t.everyone:
            c = history.team[n][t.name]
            if c:
                out.append(Finding(revisit_level, f"{n}: 이미 {t.name}에 {c}번 다녀왔습니다."))
    if rules.rotate_inv and inv_qualified:
        waiting = sorted(n for n in where if n in inv_qualified and not history.role[n][ROLE_INV]
                         and not any(t.inv == n for t in teams))
        repeats = sorted(t.inv for t in teams if t.inv and history.role[t.inv][ROLE_INV])
        if waiting and repeats:
            out.append(Finding("warn", f"조사자를 아직 안 해 본 자격자({', '.join(waiting)})가 있는데 "
                                       f"이미 해 본 사람({', '.join(repeats)})이 조사자입니다."))

    # ---- 참고: 계획 대비 변경, 이전 일차와 겹침 ----
    added = sorted(n for n in where if n in known and n not in participants)
    if added:
        out.append(Finding("info", f"참가 계획에 없던 추가 인원: {', '.join(added)}"))
    for t in teams:
        for n, r in ((t.inv, ROLE_INV), (t.lead, ROLE_LEAD)):
            if n and history.role[n][r]:
                out.append(Finding("info", f"{n}: 이전에 {r}을(를) {history.role[n][r]}번 했습니다."))
        for a, b in combinations(sorted(set(t.everyone)), 2):
            c = history.pair_count(a, b)
            if c:
                out.append(Finding("info", f"{t.name}: {a}·{b}는 이전에 {c}번 같은 조였습니다."))
    return out


def change_hints(teams: list[TeamResult], history: History, inv_ok: set[str], lead_ok: set[str],
                 no_revisit: bool) -> list[str]:
    """결원·추가 뒤 사람이 고칠 때 참고할 제안: 빈 역할 후보, 인원이 적은 조."""
    hints: list[str] = []

    def label(n: str, role: str) -> str:
        c = history.role[n][role]
        return f"{n}({'처음' if c == 0 else f'{c}회'})"

    def order(names, role):
        return sorted(names, key=lambda n: (history.role[n][role], n))

    for t in teams:
        if not t.everyone:
            continue
        for role, ok, filled in ((ROLE_INV, inv_ok, t.inv), (ROLE_LEAD, lead_ok, t.lead)):
            if filled:
                continue
            inside = order([n for n in t.members if n in ok], role)
            if inside:
                hints.append(f"{t.name} {role} 후보(이 조 쩌리 중): " + ", ".join(label(n, role) for n in inside[:4]))
            else:
                outside = []
                for o in teams:
                    if o is t:
                        continue
                    for n in o.members:
                        if n in ok and not (no_revisit and history.team[n][t.name]):
                            outside.append((n, o.name))
                outside = sorted(outside, key=lambda x: (history.role[x[0]][role], x[0]))[:4]
                if outside:
                    hints.append(f"{t.name}에는 {role} 가능자가 없습니다. 다른 조 쩌리 중 옮길 수 있는 사람: "
                                 + ", ".join(f"{label(n, role)}·{tn}" for n, tn in outside))
                else:
                    hints.append(f"{t.name}에는 {role} 가능자가 없고, 옮겨 올 수 있는 쩌리도 없습니다.")
    sizes = sorted(((len(t.everyone), t.name) for t in teams if t.everyone))
    if sizes and sizes[-1][0] - sizes[0][0] >= 2:
        hints.append("인원이 적은 조부터: " + ", ".join(f"{nm} {sz}명" for sz, nm in sizes[:3])
                     + " / 많은 조: " + ", ".join(f"{nm} {sz}명" for sz, nm in sizes[::-1][:2]))
    return hints


def visited_text(name: str, history: History) -> str:
    """'하구3, 하구5' 처럼 그 사람이 이미 간 조(섹터)."""
    return ", ".join(sorted(history.team[name])) if history.team.get(name) else ""
