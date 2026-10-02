# UBCK 야생조류 조사 지원

동아리 낙동강 하구 야생조류 조사를 위한 내부용 Streamlit 앱입니다.

- **조사 지도**: 휴대폰에서 섹터를 고르고 '안내 시작'을 누르면 진행률, 남은 거리, 가야 할 방향을 보여 주고 경로에서 벗어나면 진동·소리로 알립니다.
- **조 편성**: 명단과 일차별 참가자를 입력하면 조를 짭니다. 이미 간 섹터에는 다시 보내지 않고, 조사자 자격자는 모두 한 번씩 조사자를 맡을 때까지 돌아가며 맡깁니다. 후보를 비교해 고르고, 당일 결원·추가는 사람별 목록에서 고칩니다.

## 실행

```bash
pip install -r requirements.txt
streamlit run web.py
```

VWorld 배경지도를 쓰려면 `.streamlit/secrets.toml`에 `VWORLD_API_KEY = "발급받은 키"`를 넣습니다.

조 편성 내용은 `storage/ubck_project.json`에 저장됩니다. Streamlit Cloud에서는 재시작 때 지워질 수 있으니 앱의 '백업·가져오기' 탭에서 파일로 받아 두세요.

개발 맥락과 규칙은 [CLAUDE.md](CLAUDE.md), 설계 메모는 [docs/](docs/)에 있습니다.
