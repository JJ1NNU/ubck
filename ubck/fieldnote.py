"""야장 정리 결과(국명 ⇥ 개체수) → '국명 <수>, 국명 <수>' 한 줄 변환."""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUM = re.compile(r"^\d+(?:\.\d+)?\+?$")


@dataclass
class Parsed:
    items: list[tuple[str, str]]
    skipped: list[str]


def parse(raw: str) -> Parsed:
    """엑셀에서 복사한 2열(탭 구분)을 읽는다. 탭이 없으면 마지막 공백 뒤를 개체수로 본다.
    빈 줄은 무시하고, 개체수가 숫자가 아닌 줄은 따로 모아 돌려준다."""
    items, skipped = [], []
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("\t")]
        cells = [c for c in cells if c != ""]
        if len(cells) < 2:
            m = re.match(r"^(.*\S)\s+(\S+)$", line.strip())
            cells = [m.group(1), m.group(2)] if m else cells
        if len(cells) < 2:
            skipped.append(line.strip())
            continue
        name, count = cells[0], cells[1].replace(",", "")
        if not _NUM.match(count):
            skipped.append(line.strip())
            continue
        items.append((name, count))
    return Parsed(items, skipped)


def merge_same_species(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """같은 종이 여러 줄이면 처음 나온 자리에서 합친다."""
    order: list[str] = []
    total: dict[str, float] = {}
    for name, c in items:
        if name not in total:
            order.append(name)
            total[name] = 0
        total[name] += float(c.rstrip("+"))
    return [(n, f"{total[n]:g}") for n in order]


def format_line(items: list[tuple[str, str]]) -> str:
    return ", ".join(f"{name} <{count}>" for name, count in items)
