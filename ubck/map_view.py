"""지도 HTML 조립. 지도는 브라우저 안에서만 동작한다(위치 계산·이탈 판정 포함, 서버 재실행 없음)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gis import load_all

TEMPLATE = Path(__file__).resolve().parent / "assets" / "map.html"
PLACEHOLDER = "/*__UBCK_DATA__*/null"


def build_map_html(data: dict, vworld_key: str | None = None, initial_sector: str | None = None,
                   defaults: dict | None = None) -> str:
    payload = dict(data)
    payload["vworldKey"] = vworld_key or None
    payload["initialSector"] = initial_sector
    payload["defaults"] = defaults or {}
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise RuntimeError("map.html 템플릿에 데이터 자리표시자가 없습니다.")
    return html.replace(PLACEHOLDER, js, 1)


def main() -> None:
    """독립 실행형 지도 파일 만들기: python -m ubck.map_view --key VWORLD_KEY -o map.html

    Streamlit 없이 어느 정적 호스팅(https 필수)에 올려도 동작한다. 키는 파일 안에 그대로 들어가므로
    VWorld 키를 해당 도메인으로 제한해 두고 공개 저장소에는 올리지 않는다.
    """
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--key", default=None, help="VWorld API 키 (없으면 OpenStreetMap 배경)")
    ap.add_argument("-o", "--out", default="map.html")
    args = ap.parse_args()
    Path(args.out).write_text(build_map_html(load_all(), args.key), encoding="utf-8")
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
