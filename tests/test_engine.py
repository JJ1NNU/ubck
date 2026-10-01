import random

import pytest

from ubck.teams.engine import SolveError, solve
from ubck.teams.history import build_history
from ubck.teams.model import Person, Rules, TeamSpec, Weights, parse_fixed, parse_groups, parse_names


def club(n=60, seed=0):
    rng = random.Random(seed)
    return [Person(f"P{i:03d}", can_inv=i < 20, can_lead=15 <= i < 35, camera=i % 9 == 0,
                   attrs={"성별": rng.choice("남여"), "숙련도": rng.randint(1, 5)}) for i in range(n)]


def teams(k):
    return [TeamSpec(f"{i + 1}조") for i in range(k)]


def where(sol):
    return {n: t.name for t in sol.teams for n in t.everyone}


def test_everyone_exactly_once_even_with_overlapping_roles():
    # 예전 버그: 조사자·섹장 후보 둘 다에 있는 사람이 두 조에 들어감
    people = club()
    sol = solve(people, teams(6), time_limit=1, seed=1).solutions[0]
    names = [n for t in sol.teams for n in t.everyone]
    assert sorted(names) == sorted(p.name for p in people)
    assert all(t.inv and t.lead and t.inv != t.lead for t in sol.teams)
    assert not sol.violations


def test_sizes_balanced_and_explicit_size_respected():
    people = club(61)
    spec = teams(6)
    spec[0].size = 6
    sol = solve(people, spec, time_limit=1, seed=2).solutions[0]
    sizes = [len(t.everyone) for t in sol.teams]
    assert sizes[0] == 6
    assert max(sizes[1:]) - min(sizes[1:]) <= 1


def test_hard_rules_always_hold():
    people = club()
    rules = Rules(together=[["P040", "P041", "P042"], ["P050", "P051"]], apart=[["P001", "P002", "P003"]],
                  fixed_team={"P044": "3조"}, fixed_role={"P016": "섹장"})
    for seed in range(5):
        sol = solve(people, teams(6), rules, time_limit=0.6, seed=seed).solutions[0]
        w = where(sol)
        assert w["P040"] == w["P041"] == w["P042"]
        assert w["P050"] == w["P051"]
        assert len({w["P001"], w["P002"], w["P003"]}) == 3
        assert w["P044"] == "3조"
        assert any(t.lead == "P016" for t in sol.teams)
        assert not sol.violations


def test_history_reduces_repeats():
    people = club()
    day1 = solve(people, teams(6), time_limit=1, seed=3).solutions[0].teams
    h = build_history([day1])
    sol = solve(people, teams(6), history=h, time_limit=2, seed=4).solutions[0]
    assert sol.breakdown["역할 반복"] == 0       # 조사자 20명, 섹장 20명이라 반복 없이 가능
    assert sol.breakdown["같은 조 재배정"] == 0
    # 10명씩 6개 조. 자기 조를 피하면 새 조 하나는 나머지 5개 조에서 10명을 받으므로
    # 이전 조원끼리 최소 5쌍이 겹친다 → 6개 조 합계 30이 이론상 최솟값
    assert sol.breakdown["짝꿍 반복"] == 30


def test_attribute_balance():
    people = club(60, seed=5)
    sol = solve(people, teams(6), weights=Weights(attrs={"성별": 5}), time_limit=1.5, seed=5).solutions[0]
    male = {p.name for p in people if p.attrs["성별"] == "남"}
    counts = [sum(n in male for n in t.everyone) for t in sol.teams]
    assert max(counts) - min(counts) <= 1


def test_infeasible_inputs_explain_why():
    people = club(20)
    with pytest.raises(SolveError) as e:
        solve(people, teams(12), time_limit=0.2)
    assert any("조사자 가능 인원" in m or "부족" in m for m in e.value.messages)
    with pytest.raises(SolveError) as e:
        solve(club(), teams(3), Rules(together=[["P001", "P002"]], apart=[["P001", "P002"]]), time_limit=0.2)
    assert any("동시에" in m for m in e.value.messages)


def test_unknown_names_in_rules_are_warned_not_fatal():
    res = solve(club(), teams(6), Rules(together=[["P001", "없는사람"]]), time_limit=0.3)
    assert res.warnings and "없는사람" in res.warnings[0]


def test_parsers():
    assert parse_names("가, 나\n다\t라,,가") == ["가", "나", "다", "라"]
    assert parse_groups("철수-영희, 민수 - 지수 - 하늘\n혼자") == [["철수", "영희"], ["민수", "지수", "하늘"]]
    ft, fr, bad = parse_fixed("철수=하구3\n영희: 조사자, 이상한줄, 민수=없는조", ["하구3"])
    assert ft == {"철수": "하구3"} and fr == {"영희": "조사자"} and len(bad) == 2
