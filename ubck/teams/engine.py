"""조 편성 엔진: 제약을 지키면서 '불공평 점수'가 가장 낮은 편성을 담금질(simulated annealing)로 찾는다.

설계
- 탐색 대상은 '누가 어느 조인가'뿐이다. 조사자·섹장은 각 조 안에서 자동으로 고른다
  (자격이 있는 사람 중 그 역할을 덜 해 본 사람). 그래서 한 사람이 두 자리에 들어가는 일이 구조적으로 없다.
- '꼭 같은 조' 묶음은 한 덩어리(unit)로 움직이므로 항상 지켜진다.
- '꼭 다른 조'와 '조 고정'은 이동 단계에서 위반하는 이동을 아예 하지 않는다.
- 인원 수, 역할 자리 채우기, 역할 고정은 아주 큰 벌점(BIG)으로 다룬다. 최종 결과에 남아 있으면 위반으로 보고한다.
- 나머지(짝꿍 반복, 같은 조 반복, 역할 반복, 카메라·속성 균형)는 가중치를 곱한 벌점의 합을 줄인다.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from itertools import combinations

from .history import History
from .model import ROLE_INV, ROLE_LEAD, Person, Rules, TeamResult, TeamSpec, Weights

BIG = 10_000.0
ROTATE = 1_000.0   # 조사자 순환: 이미 해 본 사람이 조사자가 될 때 1회당 벌점 (역할 채우기보다 작고 나머지보다 훨씬 큼)


class SolveError(Exception):
    def __init__(self, messages: list[str]):
        super().__init__("\n".join(messages))
        self.messages = messages


@dataclass
class Solution:
    teams: list[TeamResult]
    cost: float
    breakdown: dict
    violations: list[str] = field(default_factory=list)


@dataclass
class SolveResult:
    solutions: list[Solution]
    warnings: list[str]
    iterations: int
    seconds: float


def _is_number(v) -> bool:
    if v is None or v == "":
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


class _Problem:
    def __init__(self, people: list[Person], teams: list[TeamSpec], rules: Rules, weights: Weights, history: History):
        self.warnings: list[str] = []
        errors: list[str] = []
        self.people = people
        self.teams = teams
        self.k = k = len(teams)
        n = len(people)
        names = [p.name for p in people]
        dup = sorted({x for x in names if names.count(x) > 1})
        if dup:
            errors.append(f"명단에 같은 이름이 여러 번 있습니다: {', '.join(dup)}")
        tnames = [t.name for t in teams]
        tdup = sorted({x for x in tnames if tnames.count(x) > 1})
        if tdup:
            errors.append(f"조 이름이 겹칩니다: {', '.join(tdup)}")
        if k < 1:
            errors.append("조를 1개 이상 만들어 주세요.")
        if errors:
            raise SolveError(errors)
        self.idx = {p.name: i for i, p in enumerate(people)}
        self.tidx = {t.name: i for i, t in enumerate(teams)}

        def known(group: list[str], what: str) -> list[str]:
            miss = [x for x in group if x not in self.idx]
            if miss:
                self.warnings.append(f"{what}에 오늘 참가하지 않는 이름이 있어 그 이름은 빼고 적용했습니다: {', '.join(miss)}")
            return [x for x in group if x in self.idx]

        # ---- 역할 고정 / 자격 ----
        fixed_role = {}
        for nm, r in rules.fixed_role.items():
            if known([nm], "역할 고정"):
                fixed_role[self.idx[nm]] = r
        self.fixed_role = fixed_role
        self.can_inv = [p.can_inv or fixed_role.get(i) == ROLE_INV for i, p in enumerate(people)]
        self.can_lead = [p.can_lead or fixed_role.get(i) == ROLE_LEAD for i, p in enumerate(people)]
        n_inv, n_lead = sum(self.can_inv), sum(self.can_lead)
        n_any = sum(1 for a, b in zip(self.can_inv, self.can_lead) if a or b)
        if n_inv < k:
            errors.append(f"조사자 가능 인원({n_inv}명)이 조 개수({k}개)보다 적습니다.")
        if n_lead < k:
            errors.append(f"섹장 가능 인원({n_lead}명)이 조 개수({k}개)보다 적습니다.")
        if n_inv >= k and n_lead >= k and n_any < 2 * k:
            errors.append(f"조사자·섹장을 서로 다른 사람으로 채우려면 둘 중 하나라도 가능한 사람이 {2 * k}명 필요한데 {n_any}명입니다.")
        if n < 2 * k:
            errors.append(f"참가 인원({n}명)이 조마다 2명(조사자+섹장)을 채우기에 부족합니다.")

        # ---- 인원 목표 ----
        explicit = {i: t.size for i, t in enumerate(teams) if t.size}
        rest = n - sum(explicit.values())
        auto = [i for i in range(k) if i not in explicit]
        self.lo = [0] * k
        self.hi = [0] * k
        if auto:
            if rest < 0:
                errors.append(f"정원을 정한 조의 합({sum(explicit.values())}명)이 참가 인원({n}명)보다 많습니다.")
            else:
                base, extra = divmod(rest, len(auto))
                for i in auto:
                    self.lo[i], self.hi[i] = base, base + (1 if extra else 0)
        elif rest != 0:
            errors.append(f"모든 조의 정원 합({sum(explicit.values())}명)이 참가 인원({n}명)과 다릅니다.")
        for i, s in explicit.items():
            self.lo[i] = self.hi[i] = s

        # ---- 같은 조 묶음 → unit ----
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for g in rules.together:
            g = known(g, "꼭 같은 조")
            for a, b in zip(g, g[1:]):
                ra, rb = find(self.idx[a]), find(self.idx[b])
                if ra != rb:
                    parent[ra] = rb
        groups: dict[int, list[int]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        self.units: list[list[int]] = list(groups.values())
        self.unit_of = [0] * n
        for u, mem in enumerate(self.units):
            for i in mem:
                self.unit_of[i] = u
        U = len(self.units)
        max_hi = max(self.hi) if self.hi else 0
        for mem in self.units:
            if len(mem) > max_hi and max_hi > 0:
                errors.append(f"꼭 같은 조 묶음({', '.join(people[i].name for i in mem)})이 한 조 정원({max_hi}명)보다 큽니다.")

        # ---- 꼭 다른 조 ----
        self.apart: list[set[int]] = [set() for _ in range(U)]
        for g in rules.apart:
            g = known(g, "꼭 다른 조")
            if len(g) > k:
                errors.append(f"꼭 다른 조 묶음({', '.join(g)})이 {len(g)}명이라 조 {k}개로는 모두 떼어 놓을 수 없습니다.")
            for a, b in combinations(g, 2):
                ua, ub = self.unit_of[self.idx[a]], self.unit_of[self.idx[b]]
                if ua == ub:
                    errors.append(f"{a}와 {b}는 '꼭 같은 조'와 '꼭 다른 조'에 동시에 들어 있습니다.")
                else:
                    self.apart[ua].add(ub)
                    self.apart[ub].add(ua)

        # ---- 조 고정 ----
        self.pin: list[int | None] = [None] * U
        for nm, tn in rules.fixed_team.items():
            if not known([nm], "조 고정"):
                continue
            if tn not in self.tidx:
                errors.append(f"{nm}을(를) 고정할 조 '{tn}'이(가) 없습니다.")
                continue
            u = self.unit_of[self.idx[nm]]
            t = self.tidx[tn]
            if self.pin[u] is not None and self.pin[u] != t:
                errors.append(f"{nm}의 묶음이 서로 다른 조에 고정되어 있습니다.")
            self.pin[u] = t
        for u in range(U):
            if self.pin[u] is not None:
                for v in self.apart[u]:
                    if self.pin[v] == self.pin[u]:
                        errors.append("같은 조에 고정된 사람들 사이에 '꼭 다른 조' 조건이 있습니다.")
        for r in (ROLE_INV, ROLE_LEAD):
            per_team: dict[int, int] = {}
            for i, rr in fixed_role.items():
                if rr == r and self.pin[self.unit_of[i]] is not None:
                    t = self.pin[self.unit_of[i]]
                    per_team[t] = per_team.get(t, 0) + 1
            if any(c > 1 for c in per_team.values()):
                errors.append(f"한 조에 '{r}' 역할 고정이 두 명 이상입니다.")
        if sum(1 for r in fixed_role.values() if r == ROLE_INV) > k or sum(1 for r in fixed_role.values() if r == ROLE_LEAD) > k:
            errors.append("역할 고정 인원이 조 개수보다 많습니다.")

        # ---- 이미 간 조(섹터) 금지 ----
        self.forbid: list[set[int]] = [set() for _ in range(U)]
        if rules.no_revisit:
            for u, mem in enumerate(self.units):
                for t, spec in enumerate(teams):
                    if any(history.team[people[i].name][spec.name] for i in mem):
                        self.forbid[u].add(t)
                if self.pin[u] is not None and self.pin[u] in self.forbid[u]:
                    self.forbid[u].discard(self.pin[u])
                    self.warnings.append(f"{', '.join(people[i].name for i in mem)}: 이미 다녀온 "
                                         f"{teams[self.pin[u]].name}에 고정되어 있어 고정을 따랐습니다.")
                if self.pin[u] is None and len(self.forbid[u]) == k:
                    who = ", ".join(people[i].name for i in mem)
                    errors.append(f"{who}은(는) 오늘의 조(섹터)를 이미 모두 다녀왔습니다. "
                                  f"그 사람을 조 고정하거나 '이미 간 섹터에 다시 배정하지 않기'를 끄세요.")
            # 묶음끼리 '꼭 다른 조'가 걸린 경우 남은 선택지가 모자라면 미리 알림
            for u in range(U):
                if self.pin[u] is None and self.apart[u]:
                    free = k - len(self.forbid[u])
                    if free == 1:
                        only = next(t for t in range(k) if t not in self.forbid[u])
                        for v in self.apart[u]:
                            if self.pin[v] == only:
                                errors.append(f"{', '.join(people[i].name for i in self.units[u])}이(가) 갈 수 있는 조는 "
                                              f"{teams[only].name}뿐인데 '꼭 다른 조' 상대가 그 조에 고정되어 있습니다.")
        if errors:
            raise SolveError(list(dict.fromkeys(errors)))

        # ---- 비용 계수 ----
        w = weights
        inv_w = ROTATE if rules.rotate_inv else w.role
        self.inv_cost = [inv_w * history.role[p.name][ROLE_INV] + w.role * 0.5 * history.role[p.name][ROLE_LEAD]
                         if self.can_inv[i] else None for i, p in enumerate(people)]
        self.lead_cost = [w.role * (history.role[p.name][ROLE_LEAD] + 0.5 * history.role[p.name][ROLE_INV]) if self.can_lead[i] else None
                          for i, p in enumerate(people)]
        self.P = [[0.0] * n for _ in range(n)]
        for a in range(n):
            for b in range(a + 1, n):
                c = history.pair_count(people[a].name, people[b].name)
                if c:
                    self.P[a][b] = self.P[b][a] = w.pair * c
        self.S = [[w.same_team * history.team[p.name][t.name] for t in teams] for p in people]
        self.cam = [1 if p.camera else 0 for p in people]
        self.cam_share = sum(self.cam) / n if n else 0
        self.w_cam = w.camera

        # 속성 균형 (범주형: 비율 맞추기 / 수치형: 평균 맞추기)
        self.cat_attrs: list[tuple[float, list[int], int]] = []   # (가중치, 사람별 범주 번호(-1=빈칸), 범주 수)
        self.cat_shares: list[list[float]] = []
        self.num_attrs: list[tuple[float, list[float | None], float, float]] = []  # (가중치, 값, 평균, 분산)
        for col, wt in (w.attrs or {}).items():
            if not wt:
                continue
            vals = [p.attrs.get(col) for p in people]
            present = [v for v in vals if v not in (None, "") and str(v).strip() != ""]
            if not present:
                continue
            if all(_is_number(v) for v in present):
                xs = [float(v) if _is_number(v) else None for v in vals]
                ys = [x for x in xs if x is not None]
                mean = sum(ys) / len(ys)
                var = sum((y - mean) ** 2 for y in ys) / len(ys)
                if var > 0:
                    self.num_attrs.append((wt, xs, mean, var))
            else:
                cats = sorted({str(v).strip() for v in present})
                code = {c: j for j, c in enumerate(cats)}
                cv = [code[str(v).strip()] if v not in (None, "") and str(v).strip() else -1 for v in vals]
                cnt = [0] * len(cats)
                for c in cv:
                    if c >= 0:
                        cnt[c] += 1
                self.cat_attrs.append((wt, cv, len(cats)))
                self.cat_shares.append([c / n for c in cnt])

    # ---------- 비용 ----------
    def roles(self, members: list[int]) -> tuple[float, int | None, int | None, int]:
        """조 안에서 조사자·섹장 고르기 → (비용, 조사자, 섹장, 위반 수)."""
        fr = self.fixed_role
        f_inv = [m for m in members if fr.get(m) == ROLE_INV]
        f_lead = [m for m in members if fr.get(m) == ROLE_LEAD]
        viol = max(0, len(f_inv) - 1) + max(0, len(f_lead) - 1)
        if f_inv:
            inv_opts = [(self.inv_cost[f_inv[0]] or 0.0, f_inv[0])]
        else:
            inv_opts = sorted((self.inv_cost[m], m) for m in members if self.inv_cost[m] is not None and m not in fr)[:2]
        if f_lead:
            lead_opts = [(self.lead_cost[f_lead[0]] or 0.0, f_lead[0])]
        else:
            lead_opts = sorted((self.lead_cost[m], m) for m in members if self.lead_cost[m] is not None and m not in fr)[:2]
        best = None
        for ci, i in inv_opts:
            for cl, l in lead_opts:
                if i != l and (best is None or ci + cl < best[0]):
                    best = (ci + cl, i, l)
        if best is None:
            if inv_opts:
                return inv_opts[0][0] + BIG, inv_opts[0][1], None, viol + 1
            if lead_opts:
                return lead_opts[0][0] + BIG, None, lead_opts[0][1], viol + 1
            return 2 * BIG, None, None, viol + 2
        return best[0] + viol * BIG, best[1], best[2], viol

    def team_cost(self, t: int, members: list[int], pairsum: float) -> float:
        m = len(members)
        c = pairsum
        dev = max(0, self.lo[t] - m, m - self.hi[t])
        c += BIG * dev
        S = self.S
        c += sum(S[i][t] for i in members)
        cam = sum(self.cam[i] for i in members)
        c += self.w_cam * (cam - m * self.cam_share) ** 2
        for (wt, cv, ncat), shares in zip(self.cat_attrs, self.cat_shares):
            cnt = [0] * ncat
            for i in members:
                if cv[i] >= 0:
                    cnt[cv[i]] += 1
            c += wt * sum((cnt[j] - m * shares[j]) ** 2 for j in range(ncat))
        for wt, xs, mean, var in self.num_attrs:
            ys = [xs[i] for i in members if xs[i] is not None]
            if ys:
                c += wt * len(ys) * ((sum(ys) / len(ys) - mean) ** 2) / var
        c += self.roles(members)[0]
        return c

    def pairsum_of(self, members: list[int]) -> float:
        P = self.P
        return sum(P[a][b] for a, b in combinations(members, 2))

    def cross(self, xs: list[int], ys: list[int]) -> float:
        P = self.P
        return sum(P[a][b] for a in xs for b in ys)


class _State:
    def __init__(self, pb: _Problem, assign: list[int]):
        self.pb = pb
        self.assign = assign[:]                      # unit → team
        self.members = [[] for _ in range(pb.k)]     # team → person idx 목록
        self.units_in = [set() for _ in range(pb.k)]
        for u, t in enumerate(assign):
            self.members[t].extend(pb.units[u])
            self.units_in[t].add(u)
        self.pairsum = [pb.pairsum_of(m) for m in self.members]
        self.cost_t = [pb.team_cost(t, self.members[t], self.pairsum[t]) for t in range(pb.k)]
        self.total = sum(self.cost_t)

    def apart_ok(self, u: int, t: int, ignore: int | None = None) -> bool:
        if t in self.pb.forbid[u]:
            return False
        ap = self.pb.apart[u]
        if not ap:
            return True
        return not any(v in ap for v in self.units_in[t] if v != ignore)

    def eval_move(self, u: int, B: int):
        pb = self.pb
        A = self.assign[u]
        um = pb.units[u]
        uset = set(um)
        a_rest = [i for i in self.members[A] if i not in uset]
        b_new = self.members[B] + um
        internal = pb.pairsum_of(um)
        ps_a = self.pairsum[A] - pb.cross(um, a_rest) - internal
        ps_b = self.pairsum[B] + pb.cross(um, self.members[B]) + internal
        ca = pb.team_cost(A, a_rest, ps_a)
        cb = pb.team_cost(B, b_new, ps_b)
        return ca + cb - self.cost_t[A] - self.cost_t[B], (A, B, a_rest, b_new, ps_a, ps_b, ca, cb)

    def eval_swap(self, u: int, v: int):
        pb = self.pb
        A, B = self.assign[u], self.assign[v]
        um, vm = pb.units[u], pb.units[v]
        us, vs = set(um), set(vm)
        a_rest = [i for i in self.members[A] if i not in us]
        b_rest = [i for i in self.members[B] if i not in vs]
        iu, iv = pb.pairsum_of(um), pb.pairsum_of(vm)
        ps_a = self.pairsum[A] - pb.cross(um, a_rest) - iu + pb.cross(vm, a_rest) + iv
        ps_b = self.pairsum[B] - pb.cross(vm, b_rest) - iv + pb.cross(um, b_rest) + iu
        a_new, b_new = a_rest + vm, b_rest + um
        ca = pb.team_cost(A, a_new, ps_a)
        cb = pb.team_cost(B, b_new, ps_b)
        return ca + cb - self.cost_t[A] - self.cost_t[B], (A, B, a_new, b_new, ps_a, ps_b, ca, cb)

    def apply(self, moved: list[tuple[int, int]], info):
        A, B, a_new, b_new, ps_a, ps_b, ca, cb = info
        for u, t in moved:
            self.units_in[self.assign[u]].discard(u)
            self.assign[u] = t
            self.units_in[t].add(u)
        self.members[A], self.members[B] = a_new, b_new
        self.pairsum[A], self.pairsum[B] = ps_a, ps_b
        self.total += ca + cb - self.cost_t[A] - self.cost_t[B]
        self.cost_t[A], self.cost_t[B] = ca, cb


def _initial(pb: _Problem, rng: random.Random) -> list[int] | None:
    U, k = len(pb.units), pb.k
    for _ in range(200):
        assign = [-1] * U
        size = [0] * k
        inv_in = [0] * k
        lead_in = [0] * k
        units_in = [set() for _ in range(k)]

        def put(u, t):
            assign[u] = t
            units_in[t].add(u)
            for i in pb.units[u]:
                size[t] += 1
                inv_in[t] += pb.can_inv[i]
                lead_in[t] += pb.can_lead[i]

        for u in range(U):
            if pb.pin[u] is not None:
                put(u, pb.pin[u])
        order = [u for u in range(U) if pb.pin[u] is None]
        rng.shuffle(order)
        # 큰 묶음, 다른 조 조건이 많은 묶음, 역할 가능자를 먼저
        order.sort(key=lambda u: (-len(pb.units[u]), -len(pb.apart[u]),
                                  -sum(pb.can_inv[i] + pb.can_lead[i] for i in pb.units[u])))
        ok = True
        for u in order:
            gives_inv = any(pb.can_inv[i] for i in pb.units[u])
            gives_lead = any(pb.can_lead[i] for i in pb.units[u])
            best, best_key = None, None
            for t in range(k):
                if t in pb.forbid[u] or any(v in pb.apart[u] for v in units_in[t]):
                    continue
                need = (gives_inv and inv_in[t] == 0) + (gives_lead and lead_in[t] == 0)
                room = pb.hi[t] - size[t] - len(pb.units[u])
                key = (room < 0, -need, size[t] / max(1, pb.hi[t]), rng.random())
                if best_key is None or key < best_key:
                    best, best_key = t, key
            if best is None:
                ok = False
                break
            put(u, best)
        if ok:
            return assign
    return None


def _breakdown(pb: _Problem, members: list[list[int]], history: History) -> tuple[list[TeamResult], dict, list[str]]:
    people = pb.people
    teams: list[TeamResult] = []
    violations: list[str] = []
    pair_rep = team_rep = role_rep = first_inv = 0
    cams = []
    for t, mem in enumerate(members):
        _, inv, lead, viol = pb.roles(mem)
        name = pb.teams[t].name
        others = [i for i in mem if i not in (inv, lead)]
        others.sort(key=lambda i: (-pb.cam[i], i))
        teams.append(TeamResult(name, people[inv].name if inv is not None else None,
                                people[lead].name if lead is not None else None,
                                [people[i].name for i in others]))
        if inv is None:
            violations.append(f"{name}: 조사자를 맡을 사람이 없습니다.")
        if lead is None:
            violations.append(f"{name}: 섹장을 맡을 사람이 없습니다.")
        if viol and inv is not None and lead is not None:
            violations.append(f"{name}: 역할 고정 조건을 모두 지키지 못했습니다.")
        if not (pb.lo[t] <= len(mem) <= pb.hi[t]):
            violations.append(f"{name}: 인원 {len(mem)}명 (목표 {pb.lo[t]}~{pb.hi[t]}명)")
        for a, b in combinations(mem, 2):
            pair_rep += history.pair_count(people[a].name, people[b].name)
        for i in mem:
            team_rep += 1 if history.team[people[i].name][name] else 0
        if inv is not None and history.role[people[inv].name][ROLE_INV]:
            role_rep += 1
        elif inv is not None:
            first_inv += 1
        if lead is not None and history.role[people[lead].name][ROLE_LEAD]:
            role_rep += 1
        cams.append(sum(pb.cam[i] for i in mem))
    sizes = [len(m) for m in members]
    bd = {
        "짝꿍 반복": pair_rep,
        "이미 간 섹터": team_rep,
        "처음 조사자": f"{first_inv}/{len(members)}조",
        "역할 반복": role_rep,
        "조별 인원": f"{min(sizes)}~{max(sizes)}명" if sizes else "-",
        "조별 카메라": f"{min(cams)}~{max(cams)}대" if cams else "-",
    }
    return teams, bd, violations


def solve(people: list[Person], teams: list[TeamSpec], rules: Rules | None = None, weights: Weights | None = None,
          history: History | None = None, time_limit: float = 8.0, n_solutions: int = 3, restarts: int | None = None,
          seed: int | None = None) -> SolveResult:
    """편성 후보를 비용이 낮은 순서로 최대 n_solutions개 돌려준다. 입력이 불가능하면 SolveError."""
    rules = rules or Rules()
    weights = weights or Weights()
    history = history or History()
    pb = _Problem(people, teams, rules, weights, history)
    rng = random.Random(seed)
    restarts = restarts or max(4, n_solutions + 2)
    t_start = time.perf_counter()
    per = time_limit / restarts
    free_units = [u for u in range(len(pb.units)) if pb.pin[u] is None]
    found: dict[tuple, tuple[float, list[list[int]]]] = {}
    iters = 0

    for r in range(restarts):
        init = _initial(pb, rng)
        if init is None:
            raise SolveError(["'꼭 다른 조'와 '이미 간 섹터 금지'를 함께 지키는 배치를 찾지 못했습니다. "
                              "'꼭 다른 조' 묶음을 줄이거나 '이미 간 섹터에 다시 배정하지 않기'를 꺼 보세요."])
        st = _State(pb, init)
        best_total, best_members = st.total, [m[:] for m in st.members]
        if len(free_units) == 0 or pb.k == 1:
            found.setdefault(_sig(best_members), (best_total, best_members))
            break

        def propose():
            u = rng.choice(free_units)
            A = st.assign[u]
            B = rng.randrange(pb.k - 1)
            if B >= A:
                B += 1
            if rng.random() < 0.35:
                if not st.apart_ok(u, B):
                    return None
                d, info = st.eval_move(u, B)
                return d, [(u, B)], info
            cands = [v for v in st.units_in[B] if pb.pin[v] is None]
            if not cands:
                return None
            v = rng.choice(cands)
            if not st.apart_ok(u, B, ignore=v) or not st.apart_ok(v, A, ignore=u):
                return None
            d, info = st.eval_swap(u, v)
            return d, [(u, B), (v, A)], info

        # 초기 온도: 무작위 이동의 '나빠지는 폭' 중앙값 (큰 벌점 제외)
        ups = []
        for _ in range(300):
            p = propose()
            if p and 0 < p[0] < BIG / 2:
                ups.append(p[0])
        ups.sort()
        T0 = ups[len(ups) // 2] if ups else 1.0
        T_end = max(T0 * 1e-3, 1e-3)
        deadline = t_start + per * (r + 1)
        r_start = time.perf_counter()
        span = max(1e-6, deadline - r_start)
        T = T0
        while True:
            if iters % 200 == 0:
                now = time.perf_counter()
                if now >= deadline:
                    break
                frac = (now - r_start) / span
                T = T0 * (T_end / T0) ** frac
            iters += 1
            p = propose()
            if p is None:
                continue
            d, moved, info = p
            if d <= 0 or rng.random() < math.exp(-d / T):
                st.apply(moved, info)
                if st.total < best_total - 1e-9:
                    best_total, best_members = st.total, [m[:] for m in st.members]
        sig = _sig(best_members)
        if sig not in found or found[sig][0] > best_total:
            found[sig] = (best_total, best_members)

    ranked = sorted(found.values(), key=lambda x: x[0])[:n_solutions]
    sols = []
    for total, members in ranked:
        tr, bd, viol = _breakdown(pb, members, history)
        sols.append(Solution(tr, round(total, 2), bd, viol))
    return SolveResult(sols, pb.warnings, iters, round(time.perf_counter() - t_start, 2))


def _sig(members: list[list[int]]) -> tuple:
    return tuple(tuple(sorted(m)) for m in members)
