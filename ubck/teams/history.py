"""이전 일차 편성 결과에서 이력 집계."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .model import ROLE_INV, ROLE_LEAD, TeamResult


@dataclass
class History:
    role: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))   # 이름 → {조사자: n, 섹장: n}
    pair: Counter = field(default_factory=Counter)                                   # frozenset({a,b}) → 같은 조였던 횟수
    team: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))   # 이름 → {조 이름: n}
    days: dict[str, int] = field(default_factory=Counter)                            # 이름 → 참가 일수
    n_days: int = 0

    def pair_count(self, a: str, b: str) -> int:
        return self.pair.get(frozenset((a, b)), 0)


def build_history(days: list[list[TeamResult]]) -> History:
    h = History()
    for teams in days:
        if not teams:
            continue
        h.n_days += 1
        for t in teams:
            people = t.everyone
            if t.inv:
                h.role[t.inv][ROLE_INV] += 1
            if t.lead:
                h.role[t.lead][ROLE_LEAD] += 1
            for p in people:
                h.team[p][t.name] += 1
                h.days[p] += 1
            for a, b in combinations(sorted(set(people)), 2):
                h.pair[frozenset((a, b))] += 1
    return h
