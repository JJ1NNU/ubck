import io
import json

import pandas as pd

from ubck import storage
from ubck.fieldnote import format_line, merge_same_species, parse
from ubck.teams.history import build_history
from ubck.teams.io import df_to_result, fairness_df, project_xlsx, read_result_xlsx, result_to_df
from ubck.teams.model import Rules, TeamResult
from ubck.teams.report import check_result


def sample():
    return [TeamResult("1조", "가", "나", ["다", "라"]), TeamResult("2조", "마", "바", ["사"])]


def test_table_roundtrip_with_camera_marks():
    df = result_to_df(sample(), cameras={"다"})
    assert df.loc[2, "1조"] == "다 📷"
    back = df_to_result(df)
    assert [t.to_dict() for t in back] == [t.to_dict() for t in sample()]


def test_reads_old_app_xlsx():
    # 예전 web.py가 내려주던 형식: 역할 | 1조 | 2조 ..., 행은 조사자/섹장/쩌리n
    old = pd.DataFrame([["조사자", "가 📷", "마"], ["섹장", "나", "바"], ["쩌리1", "다", "사"], ["쩌리2", "라", ""]],
                       columns=["역할", "1조", "2조"])
    buf = io.BytesIO()
    old.to_excel(buf, sheet_name="조편성", index=False)
    buf.seek(0)
    got = read_result_xlsx(buf)
    assert [t.to_dict() for t in got] == [t.to_dict() for t in sample()]


def test_check_result_finds_duplicates_and_rule_breaks():
    teams = [TeamResult("1조", "가", "나", ["다", "가"]), TeamResult("2조", None, "바", ["사", "모름"])]
    known = {"가", "나", "다", "라", "바", "사"}
    f = check_result(teams, {"가", "나", "다", "라", "바", "사"}, known,
                     Rules(together=[["다", "사"]]), build_history([]))
    texts = " ".join(x.text for x in f)
    assert "여러 곳" in texts and "조사자 칸" in texts and "모름" in texts and "꼭 같은 조" in texts and "라" in texts


def test_storage_roundtrip_and_backfill(tmp_path):
    p = storage.empty_project()
    p["roster"] = [{"이름": "가", "조사자": 1}]
    d = storage.new_day("1일차")
    d["result"] = [t.to_dict() for t in sample()]
    p["days"].append(d)
    path = tmp_path / "x.json"
    storage.save(p, path)
    q = storage.load(path)
    assert q["roster"][0]["조사자"] is True and q["roster"][0]["섹장"] is False
    assert q["days"][0]["result"][0]["inv"] == "가"
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == storage.SCHEMA_VERSION


def test_new_day_inherits_previous():
    a = storage.new_day("1일차")
    a["teams"] = [{"name": "하구1", "size": None}]
    a["rules"]["apart"] = "가-나"
    b = storage.new_day("2일차", a)
    assert b["teams"] == a["teams"] and b["rules"]["apart"] == "가-나" and b["result"] is None
    b["teams"][0]["name"] = "바뀜"
    assert a["teams"][0]["name"] == "하구1"   # 깊은 복사


def test_fairness_and_project_export():
    p = storage.empty_project()
    p["roster"] = [{"이름": n, "조사자": False, "섹장": False, "카메라": False} for n in "가나다라마바사"]
    for i in range(2):
        d = storage.new_day(f"{i + 1}일차")
        d["result"] = [t.to_dict() for t in sample()]
        p["days"].append(d)
    df = fairness_df(p)
    row = df[df["이름"] == "가"].iloc[0]
    assert row["조사자"] == 2 and row["참가 일수"] == 2 and "나(2회)" in row["2번 이상 같은 조"]
    xl = pd.ExcelFile(io.BytesIO(project_xlsx(p)))
    assert xl.sheet_names[:2] == ["1일차", "2일차"] and "개인별 이력" in xl.sheet_names


def test_fieldnote():
    p = parse("청둥오리\t120\n\n흰뺨검둥오리\t35\n큰고니 8\n알수없음\t많음\n청둥오리\t5")
    assert format_line(p.items) == "청둥오리 <120>, 흰뺨검둥오리 <35>, 큰고니 <8>, 청둥오리 <5>"
    assert p.skipped == ["알수없음\t많음".strip()]
    assert format_line(merge_same_species(p.items)).startswith("청둥오리 <125>")
