import io
import json

import pandas as pd

from ubck import storage
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


def test_person_list_roundtrip_with_absent_and_added():
    from ubck.teams.io import list_to_result, result_to_list
    df = result_to_list(sample(), [{"name": "아", "team": "1조", "role": "쩌리"}], {"다": "오후 합류"})
    assert list(df["상태"]).count("결원") == 1
    teams, absent, notes, problems = list_to_result(df, ["1조", "2조"])
    assert [t.to_dict() for t in teams] == [t.to_dict() for t in sample()]
    assert absent == [{"name": "아", "team": "1조", "role": "쩌리"}] and notes == {"다": "오후 합류"} and not problems

    # 당일 변경: 조사자 '가' 결원, '다'를 조사자로, 새 사람 '자'를 2조에 추가
    df.loc[df["이름"] == "가", "상태"] = "결원"
    df.loc[df["이름"] == "다", "역할"] = "조사자"
    df.loc[len(df)] = {"이름": "자", "조": "2조", "역할": "쩌리", "상태": "참석", "메모": ""}
    teams, absent, _, problems = list_to_result(df, ["1조", "2조"])
    assert teams[0].inv == "다" and "가" not in teams[0].everyone and "자" in teams[1].members
    assert {"name": "가", "team": "1조", "role": "조사자"} in absent and not problems


def test_person_list_reports_double_roles_and_missing_team():
    from ubck.teams.io import list_to_result
    df = pd.DataFrame([{"이름": "가", "조": "1조", "역할": "조사자", "상태": "참석"},
                       {"이름": "나", "조": "1조", "역할": "조사자", "상태": "참석"},
                       {"이름": "다", "조": None, "역할": "쩌리", "상태": "참석"},
                       {"이름": "가", "조": "2조", "역할": "쩌리", "상태": "참석"}])
    teams, _, _, problems = list_to_result(df, ["1조", "2조"])
    text = " ".join(problems)
    assert "조사자가 둘 이상" in text and "다의 조가 비어" in text and "두 번" in text
    assert teams[0].inv == "가" and "나" in teams[0].members


def test_check_result_rotation_and_revisit_warnings():
    h = build_history([[TeamResult("1조", "가", "나", ["다"])]])
    today = [TeamResult("1조", "가", "라", ["다"])]   # 가: 조사자 두 번째 + 1조 재방문, 다: 미경험인데 쩌리
    f = check_result(today, {"가", "다", "라"}, {"가", "나", "다", "라"},
                     Rules(no_revisit=True, rotate_inv=True), h, set(), {"가", "다"})
    warns = " ".join(x.text for x in f if x.level == "warn")
    assert "아직 안 해 본" in warns and "이미 1조에" in warns


def test_change_hints_suggest_vacancy_fill():
    from ubck.teams.report import change_hints
    h = build_history([])
    teams = [TeamResult("1조", None, "나", ["다", "라"]), TeamResult("2조", "마", "바", ["사", "아", "자", "차"])]
    hints = change_hints(teams, h, inv_ok={"라", "마"}, lead_ok={"나", "바"}, no_revisit=True)
    assert any("1조 조사자 후보" in x and "라(처음)" in x for x in hints)
    assert any("인원이 적은 조" in x for x in hints)


def test_day_xlsx_has_pivot_and_person_list():
    from ubck.teams.io import day_xlsx, result_to_list
    data = day_xlsx(result_to_df(sample()), result_to_list(sample(), [{"name": "아", "team": "2조", "role": "쩌리"}]), "3일차")
    xl = pd.ExcelFile(io.BytesIO(data))
    assert xl.sheet_names == ["3일차", "사람별"]
    people = xl.parse("사람별")
    assert list(people.columns) == ["이름", "조", "역할", "상태", "메모"] and (people["상태"] == "결원").sum() == 1
    # 첫 시트는 예전 가져오기 형식 그대로 읽힌다
    assert [t.name for t in read_result_xlsx(io.BytesIO(data))] == ["1조", "2조"]
