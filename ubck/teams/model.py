"""조 편성 데이터 구조와 입력 파싱."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ROLE_INV = "조사자"
ROLE_LEAD = "섹장"
ROLE_MEMBER = "쩌리"
ROLES = (ROLE_INV, ROLE_LEAD)
CAMERA_MARK = " 📷"


@dataclass
class Person:
    name: str
    can_inv: bool = False
    can_lead: bool = False
    camera: bool = False
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamSpec:
    name: str
    size: int | None = None   # None이면 자동(균등 배분)


@dataclass
class Rules:
    together: list[list[str]] = field(default_factory=list)   # 같은 조여야 하는 묶음
    apart: list[list[str]] = field(default_factory=list)      # 서로 다른 조여야 하는 묶음(묶음 안 모든 쌍)
    fixed_team: dict[str, str] = field(default_factory=dict)  # 이름 → 조 이름
    fixed_role: dict[str, str] = field(default_factory=dict)  # 이름 → 조사자/섹장


@dataclass
class Weights:
    pair: float = 1.0        # 이전에 같은 조였던 사람끼리 또 만남
    same_team: float = 4.0   # 같은 조(=같은 섹터)에 또 배정
    role: float = 6.0        # 조사자/섹장을 이미 해 본 사람이 또 맡음
    camera: float = 3.0      # 카메라가 한 조에 몰림
    attrs: dict[str, float] = field(default_factory=dict)  # 균형 맞출 속성 열 → 가중치


@dataclass
class TeamResult:
    name: str
    inv: str | None = None
    lead: str | None = None
    members: list[str] = field(default_factory=list)  # 쩌리

    @property
    def everyone(self) -> list[str]:
        return [n for n in (self.inv, self.lead) if n] + list(self.members)

    def role_of(self, name: str) -> str:
        if name == self.inv:
            return ROLE_INV
        if name == self.lead:
            return ROLE_LEAD
        return ROLE_MEMBER

    def to_dict(self) -> dict:
        return {"name": self.name, "inv": self.inv, "lead": self.lead, "members": list(self.members)}

    @staticmethod
    def from_dict(d: dict) -> "TeamResult":
        return TeamResult(d.get("name", ""), d.get("inv") or None, d.get("lead") or None, list(d.get("members") or []))


# ---------- 텍스트 파싱 ----------
_SPLIT_NAMES = re.compile(r"[,\n\t;]+")
_SPLIT_GROUP_MEMBERS = re.compile(r"\s*[-&+/]\s*")


def clean_name(s: Any) -> str:
    """셀 값 → 이름. 카메라 표시와 공백 제거."""
    if s is None:
        return ""
    s = str(s).replace("📷", "").strip()
    return "" if s.lower() in ("nan", "none") else s


def parse_names(raw: str) -> list[str]:
    """콤마·줄바꿈·탭으로 구분된 이름 목록 (순서 유지, 중복 제거)."""
    if not raw:
        return []
    out: list[str] = []
    for p in _SPLIT_NAMES.split(raw):
        n = clean_name(p)
        if n and n not in out:
            out.append(n)
    return out


def parse_groups(raw: str) -> list[list[str]]:
    """'철수-영희-민수, 박새-오목눈이' → [['철수','영희','민수'], ['박새','오목눈이']]."""
    groups = []
    for chunk in re.split(r"[,\n;]+", raw or ""):
        names = [clean_name(x) for x in _SPLIT_GROUP_MEMBERS.split(chunk.strip()) if clean_name(x)]
        if len(names) >= 2:
            groups.append(list(dict.fromkeys(names)))
    return groups


def parse_fixed(raw: str, team_names: list[str]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """'철수=하구3, 영희=조사자' → (조 고정, 역할 고정, 해석 못 한 줄)."""
    fixed_team: dict[str, str] = {}
    fixed_role: dict[str, str] = {}
    bad: list[str] = []
    for chunk in re.split(r"[,\n;]+", raw or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^(.+?)\s*[=:]\s*(.+)$", chunk)
        if not m:
            bad.append(chunk)
            continue
        name, val = clean_name(m.group(1)), m.group(2).strip()
        if val in ROLES:
            fixed_role[name] = val
        elif val in team_names:
            fixed_team[name] = val
        else:
            bad.append(chunk)
    return fixed_team, fixed_role, bad
