"""조사구역 Shapefile → 지도용 JSON 변환.

Streamlit에 의존하지 않는 순수 함수만 둔다(캐싱은 페이지 쪽에서 st.cache_data로).
좌표는 [위도, 경도] 순서(Leaflet 규약)로 내보낸다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 거리 계산용 투영 좌표계 (Korea 2000 / East Belt 2010, 부산 일대에 적합한 미터 단위)
METRIC_CRS = 5187

# 기존 web.py와 같은 팔레트 (색이 바뀌면 동아리원들이 헷갈리므로 유지)
PALETTE = ["red", "blue", "green", "purple", "orange", "darkblue", "darkgreen", "#301934", "pink"]

HAGU_POLYGON_COLOR = "blue"


@dataclass(frozen=True)
class SurveyConfig:
    name: str          # "하천" / "하구"
    line: str
    polygon: str
    point: str
    polygon_label_col: str      # 폴리곤 라벨로 쓸 열
    line_name_col: str | None   # 경로 이름(예: 하구 라인의 name)


SURVEYS: list[SurveyConfig] = [
    SurveyConfig("하천", "HacheonLine.shp", "HacheonPolygon.shp", "HacheonPoint.shp",
                 polygon_label_col="sector", line_name_col=None),
    SurveyConfig("하구", "HaguLine.shp", "HaguPolygon.shp", "HaguPoint.shp",
                 polygon_label_col="code", line_name_col="name"),
]


def normalize_sector(survey: str, value) -> str | None:
    """색/섹터 통일용 정규화. 하천6-1, 하천6-2 → 하천6 (한 섹터의 두 구간)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    if survey == "하천" and s.startswith("하천6-"):
        return "하천6"
    return s


def _read(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(path)


def _latlon(coords) -> list[list[float]]:
    return [[round(y, 6), round(x, 6)] for x, y, *_ in coords]


def _first_point(geom) -> Point | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Point":
        return geom
    if geom.geom_type == "MultiPoint":
        return geom.geoms[0]
    return geom.representative_point()


def _iter_lines(geom):
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms


def order_parts(parts: list[LineString], start: Point | None, end: Point | None) -> list[LineString]:
    """한 섹터의 경로 조각들을 시작 지점부터 이어지도록 정렬·방향 정리 (미터 좌표 입력).

    - 시작 지점이 있으면 그 지점에 가장 가까운 끝점을 가진 조각부터, 그 끝점이 앞이 되게 뒤집는다.
    - 이후 조각은 직전 조각의 끝에서 가장 가까운 끝점을 가진 조각을 탐욕적으로 이어 붙인다.
    - 시작 지점이 없고 종료 지점만 있으면 역방향으로 같은 일을 한 뒤 뒤집는다.
    """
    remaining = list(parts)
    if not remaining:
        return []
    anchor = start
    reverse_all = False
    if anchor is None and end is not None:
        anchor, reverse_all = end, True
    ordered: list[LineString] = []
    cursor = anchor
    while remaining:
        if cursor is None:
            ordered.append(remaining.pop(0))
            cursor = Point(ordered[-1].coords[-1])
            continue
        best = None
        for i, ln in enumerate(remaining):
            a, b = Point(ln.coords[0]), Point(ln.coords[-1])
            for d, flip in ((cursor.distance(a), False), (cursor.distance(b), True)):
                if best is None or d < best[0]:
                    best = (d, i, flip)
        _, i, flip = best
        ln = remaining.pop(i)
        if flip:
            ln = LineString(list(ln.coords)[::-1])
        ordered.append(ln)
        cursor = Point(ln.coords[-1])
    if reverse_all:
        ordered = [LineString(list(ln.coords)[::-1]) for ln in reversed(ordered)]
    return ordered


@dataclass
class Sector:
    id: str
    survey: str
    name: str | None
    color: str
    parts: list[list[list[float]]]              # [[lat, lon], ...] 조각들, 진행 순서
    part_labels: list[str]
    length_m: float
    start: dict | None = None                    # {"name", "latlng"}
    end: dict | None = None
    polygons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.id} {self.name}" if self.name else self.id

    def to_dict(self) -> dict:
        return {
            "id": self.id, "survey": self.survey, "name": self.name, "label": self.label,
            "color": self.color, "parts": self.parts, "partLabels": self.part_labels,
            "lengthM": round(self.length_m), "start": self.start, "end": self.end,
            "polygons": self.polygons,
        }


def _sector_sort_key(sector_id: str):
    digits = "".join(ch for ch in sector_id if ch.isdigit())
    return (int(digits) if digits else 999, sector_id)


def load_survey(cfg: SurveyConfig, data_dir: Path = DATA_DIR) -> dict:
    """한 조사(하천/하구)의 섹터·폴리곤·지점을 JSON 친화 dict로."""
    lines = _read(data_dir / cfg.line)
    polys = _read(data_dir / cfg.polygon)
    points = _read(data_dir / cfg.point)

    # 색 매핑: line → polygon → point 순으로 처음 등장한 섹터에 팔레트를 차례로 배정 (기존 동작 유지)
    order: list[str] = []
    for gdf in (lines, polys, points):
        if "sector" not in gdf.columns:
            continue
        for v in gdf["sector"].tolist():
            key = normalize_sector(cfg.name, v)
            if key and key not in order:
                order.append(key)
    color_of = {k: PALETTE[i % len(PALETTE)] for i, k in enumerate(order)}

    lines_m = lines.to_crs(METRIC_CRS)
    points_m = points.to_crs(METRIC_CRS)
    lines_ll = lines.to_crs(4326)
    points_ll = points.to_crs(4326)
    polys_ll = polys.to_crs(4326)

    # 시작/종료 지점
    endpoints: dict[str, dict[str, dict]] = {}
    for idx, row in points_ll.iterrows():
        key = normalize_sector(cfg.name, row.get("sector"))
        se = str(row.get("startend") or "").strip()
        if not key or se not in ("시작", "종료"):
            continue
        p_ll = _first_point(row.geometry)
        p_m = _first_point(points_m.loc[idx].geometry)
        if p_ll is None:
            continue
        loc = row.get("location")
        endpoints.setdefault(key, {})[se] = {
            "name": str(loc).strip() if pd.notna(loc) else se,
            "latlng": [round(p_ll.y, 6), round(p_ll.x, 6)],
            "_m": p_m,
        }

    # 경로(라인) 묶기
    grouped: dict[str, list[tuple[str, LineString]]] = {}
    names: dict[str, str] = {}
    for idx, row in lines_m.iterrows():
        key = normalize_sector(cfg.name, row.get("sector"))
        if not key:
            continue
        raw = str(row.get("sector")).strip()
        for ln in _iter_lines(row.geometry):
            grouped.setdefault(key, []).append((raw, ln))
        if cfg.line_name_col and cfg.line_name_col in lines_m.columns:
            nm = row.get(cfg.line_name_col)
            if pd.notna(nm) and str(nm).strip():
                names[key] = str(nm).strip()

    sectors: list[Sector] = []
    for key in sorted(grouped, key=_sector_sort_key):
        raw_parts = grouped[key]
        st_pt = endpoints.get(key, {}).get("시작", {}).get("_m")
        en_pt = endpoints.get(key, {}).get("종료", {}).get("_m")
        ordered_m = order_parts([ln for _, ln in raw_parts], st_pt, en_pt)
        # 정렬된 조각을 위경도로 변환
        series = gpd.GeoSeries(ordered_m, crs=METRIC_CRS).to_crs(4326)
        parts_ll = [_latlon(g.coords) for g in series]
        # 조각 라벨: 원본 sector 값(하천6-1 등). 뒤집힌 조각은 id가 바뀌므로 길이로 매칭
        part_labels = []
        for ln in ordered_m:
            match = next((raw for raw, orig in raw_parts if abs(orig.length - ln.length) < 1e-6), key)
            part_labels.append(match)
        ep = endpoints.get(key, {})
        sectors.append(Sector(
            id=key, survey=cfg.name, name=names.get(key),
            color=color_of.get(key, "blue"),
            parts=parts_ll, part_labels=part_labels,
            length_m=sum(ln.length for ln in ordered_m),
            start={k: v for k, v in ep["시작"].items() if k != "_m"} if "시작" in ep else None,
            end={k: v for k, v in ep["종료"].items() if k != "_m"} if "종료" in ep else None,
        ))

    # 폴리곤
    polygons = []
    sec_cols = [c for c in polys_ll.columns if c.startswith("sec") and c[3:].isdigit()]
    sector_ids = {s.id for s in sectors}
    for _, row in polys_ll.iterrows():
        label_val = row.get(cfg.polygon_label_col)
        label = str(label_val).strip() if pd.notna(label_val) else "구역 정보 없음"
        members: list[str] = []
        if sec_cols:  # 하구: sec1..sec11 = 해당 섹터 조사 범위에 포함되는지(1/0)
            for c in sec_cols:
                v = row.get(c)
                if pd.notna(v) and float(v) >= 1:
                    members.append(f"{cfg.name}{c[3:]}")
        else:
            key = normalize_sector(cfg.name, row.get("sector"))
            if key:
                members.append(key)
        if cfg.name == "하구":
            color = HAGU_POLYGON_COLOR
        else:
            key = normalize_sector(cfg.name, row.get("sector"))
            color = color_of.get(key, "blue")
        geom = row.geometry
        rings = []
        for poly in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]):
            rings.append([_latlon(poly.exterior.coords)] + [_latlon(r.coords) for r in poly.interiors])
        polygons.append({"label": label, "color": color, "sectors": members, "rings": rings,
                         "filled": cfg.name != "하구"})
        for m in members:
            for s in sectors:
                if s.id == m and label not in s.polygons:
                    s.polygons.append(label)
    unknown = sorted({m for p in polygons for m in p["sectors"]} - sector_ids)

    bounds = lines_ll.total_bounds  # minx, miny, maxx, maxy
    return {
        "name": cfg.name,
        "sectors": [s.to_dict() for s in sectors],
        "polygons": polygons,
        "bounds": [[round(float(bounds[1]), 6), round(float(bounds[0]), 6)], [round(float(bounds[3]), 6), round(float(bounds[2]), 6)]],
        "unmatchedPolygonSectors": unknown,
    }


def load_all(data_dir: Path = DATA_DIR) -> dict:
    surveys = [load_survey(cfg, data_dir) for cfg in SURVEYS]
    return {"surveys": surveys}


def sector_ids(data: dict) -> list[str]:
    return [s["id"] for sv in data["surveys"] for s in sv["sectors"]]
