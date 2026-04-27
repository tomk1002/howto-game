# combo-trainer

게임 콤보·기술 시연을 입력 시퀀스로 녹화하고, 재생·시각화·공유할 수 있는 데스크톱 앱.

## 비전

장기적으로는 **유저가 만드는 인터랙티브 게임 튜토리얼 플랫폼** 으로 확장. 첫 단계는 콤보 녹화·재생.

## 스택

- Python 3.10+
- PyQt6 (UI)
- pynput (글로벌 입력 캡처)

## 설치 / 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

## MVP 기능

- 글로벌 단축키 (기본 F9) 로 녹화 시작/정지
- 키보드·마우스 입력을 타임스탬프와 함께 기록 (마우스 이동은 노이즈가 커서 클릭/스크롤만)
- 타임라인 위젯으로 시각화
- JSON 파일로 저장/불러오기
- 게임 위에 입력을 주입하지 않음 (안티치트 회피, 시각화만)

## 데이터 포맷

```json
{
  "version": 1,
  "title": "",
  "game": "",
  "tags": [],
  "duration_ms": 1234,
  "created_at": "2026-04-27T10:00:00Z",
  "events": [
    { "t_ms": 0, "type": "key_press", "key": "Q" },
    { "t_ms": 100, "type": "key_release", "key": "Q" }
  ]
}
```

미래에 `steps`, `annotations`, `audio_track`, `video_track` 등 확장.

## 로드맵

- [x] M0: 프로젝트 스캐폴드
- [ ] M1: 입력 녹화 + 타임라인 시각화 + 저장/불러오기
- [ ] M2: 재생 (시각화 커서, 입력 주입 없음)
- [ ] M3: 스텝 마커 추가 (녹화 중 단계 구분)
- [ ] M4: 화면·마이크 옵션 동시 녹화
- [ ] M5: 게임 위 투명 오버레이 재생 (안티치트 호환 영역만)
- [ ] M6: 공유 플랫폼 (웹 업로드/검색/다운로드)
