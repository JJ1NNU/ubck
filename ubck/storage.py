"""프로젝트(명단·일차·편성 결과) 저장.

한 개의 JSON 파일에 전부 담는다. 기본 위치는 storage/ubck_project.json (환경변수 UBCK_STORE로 변경).
Streamlit Community Cloud의 파일 시스템은 재배포·재시작 때 지워지므로, 화면의 '프로젝트 파일 내려받기'로
백업해 두고 필요할 때 다시 올리는 것을 기본 운영 방식으로 한다.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 2
ROSTER_COLUMNS = ["이름", "조사자", "섹장", "카메라", "성별", "기수", "숙련도", "메모"]
ROSTER_BOOL = ["조사자", "섹장", "카메라"]
ATTR_COLUMNS = ["성별", "기수", "숙련도"]   # 균형 맞추기에 쓸 수 있는 열

DEFAULT_WEIGHTS = {"pair": 1.0, "same_team": 4.0, "role": 6.0, "camera": 3.0}


def default_path() -> Path:
    env = os.environ.get("UBCK_STORE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "storage" / "ubck_project.json"


def empty_project() -> dict:
    return {"version": SCHEMA_VERSION, "roster": [], "days": [],
            "settings": {"weights": dict(DEFAULT_WEIGHTS), "attr_weights": {}, "time_limit": 8,
                         "no_revisit": True, "rotate_inv": True, "total_days": 5},
            "updated": None}


def new_day(label: str, prev: dict | None = None) -> dict:
    """새 일차. 이전 일차가 있으면 조 구성·참가 여부·규칙을 그대로 이어받는다."""
    day = {"id": uuid.uuid4().hex[:8], "label": label,
           "teams": [{"name": f"{i + 1}조", "size": None} for i in range(3)],
           "participants": {}, "rules": {"together": "", "apart": "", "fixed": ""}, "result": None,
           "absent": [], "notes": {}}
    if prev:
        day["teams"] = [dict(t) for t in prev.get("teams", [])]
        day["participants"] = {k: dict(v) for k, v in prev.get("participants", {}).items()}
        day["rules"] = dict(prev.get("rules", {}))
    return day


def normalize(project: dict) -> dict:
    """불러온 파일을 현재 형식으로 맞춘다(빠진 키 채우기)."""
    base = empty_project()
    if not isinstance(project, dict):
        raise ValueError("프로젝트 파일 형식이 아닙니다.")
    ver = project.get("version", 0)
    if ver > SCHEMA_VERSION:
        raise ValueError(f"더 새로운 버전(v{ver})에서 만든 파일입니다.")
    out = {**base, **{k: v for k, v in project.items() if k in base}}
    out["version"] = SCHEMA_VERSION
    out["settings"] = {**base["settings"], **(project.get("settings") or {})}
    out["settings"]["weights"] = {**DEFAULT_WEIGHTS, **(out["settings"].get("weights") or {})}
    roster = []
    for r in project.get("roster") or []:
        row = {c: r.get(c) for c in ROSTER_COLUMNS}
        row["이름"] = str(row["이름"] or "").strip()
        if not row["이름"]:
            continue
        for b in ROSTER_BOOL:
            row[b] = bool(row[b])
        roster.append(row)
    out["roster"] = roster
    days = []
    for d in project.get("days") or []:
        nd = new_day(d.get("label") or f"{len(days) + 1}일차")
        nd.update({k: d[k] for k in ("id", "teams", "participants", "rules", "result", "absent", "notes") if k in d})
        nd["absent"] = nd.get("absent") or []
        nd["notes"] = nd.get("notes") or {}
        nd["rules"] = {**{"together": "", "apart": "", "fixed": ""}, **(nd.get("rules") or {})}
        days.append(nd)
    out["days"] = days
    return out


def load(path: Path | None = None) -> dict:
    path = path or default_path()
    if not path.exists():
        return empty_project()
    return normalize(json.loads(path.read_text(encoding="utf-8")))


def dumps(project: dict) -> str:
    return json.dumps(project, ensure_ascii=False, indent=1)


def save(project: dict, path: Path | None = None) -> str:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    project["updated"] = datetime.now().isoformat(timespec="seconds")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ubck-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(dumps(project))
    os.replace(tmp, path)   # 쓰다가 끊겨도 기존 파일이 깨지지 않게
    return project["updated"]
