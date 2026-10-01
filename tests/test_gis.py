import math

import pytest

from ubck.gis import load_all, normalize_sector


@pytest.fixture(scope="module")
def data():
    return load_all()


def sectors(data):
    return {s["id"]: s for sv in data["surveys"] for s in sv["sectors"]}


def test_two_surveys_with_expected_sectors(data):
    names = [sv["name"] for sv in data["surveys"]]
    assert names == ["하천", "하구"]
    ids = set(sectors(data))
    assert {"하천1", "하천6", "하천11", "하구1", "하구11"} <= ids
    assert "하천6-1" not in ids  # 6-1, 6-2는 하천6 한 섹터의 두 구간


def test_hacheon6_has_two_ordered_parts(data):
    s = sectors(data)["하천6"]
    assert s["partLabels"] == ["하천6-1", "하천6-2"]
    assert s["start"]["name"] == "대저수문"


def _m(a, b):
    ky, kx = 110574, 111320 * math.cos(math.radians(35.1))
    return math.hypot((a[0] - b[0]) * ky, (a[1] - b[1]) * kx)


def test_routes_run_from_start_point(data):
    for s in sectors(data).values():
        if s["start"]:
            assert _m(s["parts"][0][0], s["start"]["latlng"]) < 50, s["id"]


def test_hagu_polygons_know_their_sectors(data):
    hagu = data["surveys"][1]
    by = {p["label"]: p for p in hagu["polygons"]}
    assert set(by["H"]["sectors"]) == {"하구4"}
    assert "C2" in sectors(data)["하구1"]["polygons"]


def test_colors_match_previous_app(data):
    # 기존 앱과 같은 색 (처음 등장한 순서대로 팔레트 배정)
    s = sectors(data)
    assert s["하천1"]["color"] == "red" and s["하천11"]["color"] == "blue"
    assert s["하구11"]["color"] == "red" and s["하구1"]["color"] == "blue"


def test_hacheon_polygon_label_left_as_is(data):
    # 하천 폴리곤의 '하구2' 값은 확인 전까지 데이터 그대로 둔다 (CLAUDE.md 참고)
    assert data["surveys"][0]["unmatchedPolygonSectors"] == ["하구2"]


def test_normalize_sector():
    assert normalize_sector("하천", "하천6-2") == "하천6"
    assert normalize_sector("하구", "하구6-2") == "하구6-2"
    assert normalize_sector("하천", None) is None
