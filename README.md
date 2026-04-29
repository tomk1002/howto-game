# HowTo

> 게임 안의 모든 "어떻게 하는 거야?"에 대한 답을, 직접 보여주는 도구.

숙련된 유저가 시연을 녹화하면, 다른 유저는 그 파일을 받아 자기 화면 위 오버레이로 단계별로 따라할 수 있는 데스크톱 앱.

---

## 무엇을 해결하나

게임의 깊은 기술·전략은 보통 유튜브 영상으로 배우게 됩니다. 그런데 영상은:

- 일시정지하고 따라하는 게 답답함 (스크럽·반복 재생)
- 화면 비율이나 UI가 바뀌면 매핑 안 됨
- 어느 시점에 어떤 키를 눌렀는지 정확히 모름

**HowTo** 는 입력 시퀀스 + 영상 + 메타데이터를 한 패키지로 저장합니다. 받는 사람은 자기 화면 위에 항상-위 오버레이를 띄우고 — 영상은 옆에서 재생되며, 가로 타임라인이 이동하면서 각 시점에 눌러야 할 키를 시각화합니다.

---

## 사용 시나리오

| 장르 | 예시 |
|---|---|
| 격투게임 | "테켄 8 진 카자마 콤보 — 6번째 입력에서 0.2초 딜레이 있음" |
| MOBA | "LoL 야스오 Q-캔슬 정확한 타이밍 시퀀스" |
| Souls-like | "엘든링 말레키스 2페이즈 회피·반격 루틴" |
| Minecraft | "고급 자동 농장 빌드, 단계별 블록 설치 순서" |
| MMO | "FF14 검은마법사 90초 오프닝 로테이션" |
| FPS 무브 | "Apex 슈퍼글라이드 입력 + 타이밍" |

---

## 설치

### Python 환경

권장: conda env (또는 venv)

```powershell
conda create -n howto python=3.12 -y
conda activate howto
pip install -r requirements.txt
```

또는 venv:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### ffmpeg (화면 녹화에 필수)

```powershell
winget install Gyan.FFmpeg
# 새 PowerShell 창 열고
ffmpeg -version    # 정상 출력되면 완료
```

### LoL 아이콘 리소스 (선택)

LoL 챔피언 스킬·소환사 주문·아이템 아이콘을 오버레이에 띄우려면 Riot Data Dragon 에서 다운로드:

```powershell
python tools/download_ddragon.py
# 기본: 최신 버전 + ko_KR 로케일
# 옵션: --version 14.18.1  --locale en_US
```

`resources/` 에 ~20MB. 챔피언별 Q/W/E/R/패시브/초상화 + 모든 소환사 주문 + 모든 아이템 + `manifest.json`. 재실행 안전 — 이미 받은 파일은 건너뜀.

---

## 실행

```powershell
conda activate howto
python main.py
```

게임이 관리자 권한으로 실행 중이면 (대부분의 경쟁 게임), HowTo 도 **PowerShell 관리자 권한**으로 실행해야 키 입력이 캡처됩니다.

---

## 기본 워크플로

### 녹화

1. 게임을 **borderless windowed** 모드로 실행 (fullscreen exclusive 미지원)
2. HowTo 에서 **대상 창 선택** (🔄 로 목록 갱신)
3. 제목·게임·(LoL이면) 챔피언 입력
4. **F9** 또는 [녹화] → 시연 → **F9** 다시 → 정지
5. **녹화 중 창 위치 변경 금지** — 캡처 영역이 시작 시점 좌표에 고정됨

### 편집

녹화 직후 메인 창에서:

- **상단**: 영상 플레이어 (재생·시크·속도 0.25× ~ 2×)
- **중간**: 타임라인 시각화
- **하단**: 이벤트 리스트 (다중 선택 가능)
- **편집 도구바**:
  - 🗑 **선택 삭제** / Delete 키
  - ⏮ **앞쪽 자르기** / ⏭ **뒤쪽 자르기** / ↔ **구간만 남기기**
  - 🚫 **release 모두 제거** — 모든 key/mouse_release 일괄 삭제
  - 🔑 **이 키 모두 제거** — 선택 키와 같은 모든 이벤트 삭제
  - 🎨 **아이콘 지정** / **아이콘 제거** — 선택한 이벤트에만 적용 (특정 시점만 다른 아이콘)
  - ↶ **실행취소** (Ctrl+Z, 20단계)

이벤트 행 클릭 → 영상이 그 시각으로 자동 시크.

### 영상 크롭

🖼 **크롭 설정** → 다이얼로그가 영상을 무한 루프 재생, 그 위에서 드래그로 영역 선택 → 적용. 저장 시 ffmpeg가 그 영역만 재인코딩.

### 키 → 아이콘 매핑

🔧 **키 아이콘 매핑…** → 녹화에 등장한 모든 고유 키 목록 → 각 키에 사용할 이미지 지정 (resources/ 또는 외부 파일). 챔피언 자동 매핑 위에 덮어씀.

### 오버레이 재생

🎯 **오버레이 재생** → 두 창이 항상-위로 띄워짐:

1. **영상 오버레이창** — 영상 재생, 무한 루프
2. **시퀀스 오버레이창** — 가로 타임라인 strip + 실시간 사용자 입력 트래커
   - 시간이 흐르면서 step 박스가 좌→우로 활성화
   - 박스가 가로로 겹치면 **자동 레인 스태킹** (피아노롤처럼 위로 쌓임)
   - 사용자가 실제로 누른 키는 아래쪽 행에 마커로 표시 (의도 vs 실측 비교)

두 창은 **시간 동기** — 영상이 시간 소스, 시퀀스 step 하이라이트가 영상 위치를 따라 자동 진행. 영상 재생 시작 + 끝에서 자동 루프.

두 창 모두 **헤더 드래그로 이동**, **모서리 드래그로 리사이즈**.

### 아이콘 우선순위

오버레이 step 박스는 다음 순서로 아이콘을 결정:

1. **이벤트별 아이콘** (특정 시점 override)
2. **키별 매핑** (사용자 지정)
3. **챔피언 자동 매핑** (Q/W/E/R, LoL일 때)
4. **텍스트 키캡** (글자 라벨)

---

## 디자인 원칙

1. **안티치트 호환성 우선** — 입력을 게임에 주입하지 않고 "보여주기"만 함
2. **확장 가능한 포맷** — 같은 파일이 콤보·튜토리얼·풀 가이드까지 커버
3. **게임 비종속** — Windows OS 레벨에서 동작, 게임별 통합 0
4. **공유 친화** — `.json` + `.mp4` 페어. 상대경로 우선 저장으로 폴더 통째 옮겨도 동작

---

## 데이터 포맷

```json
{
  "version": 1,
  "title": "Akali Combo",
  "game": "League of Legends",
  "champion_id": "Akali",
  "tags": ["mid", "mechanic"],
  "duration_ms": 5271,
  "created_at": "2026-04-27T05:00:00Z",
  "key_icons": {
    "Q": "resources/champion/spells/AkaliQ.png",
    "F": "resources/summoner/SummonerFlash.png"
  },
  "video_file": "AkaliCombo.mp4",
  "video_meta": {
    "fps": 30,
    "codec": "libx264",
    "window_title": "League of Legends (TM) Client",
    "capture_bounds": [643, 344, 2554, 1434],
    "crop_applied": [320, 180, 1920, 1080]
  },
  "events": [
    { "t_ms": 0,    "type": "key_press",   "key": "q" },
    { "t_ms": 80,   "type": "mouse_press", "button": "Button.right", "x": 960, "y": 540 },
    { "t_ms": 240,  "type": "key_release", "key": "q" },
    { "t_ms": 500,  "type": "key_press",   "key": "r",
      "icon": "resources/champion/spells/AkaliR.png" }
  ]
}
```

- `key_icons` — 키 → 이미지 경로 매핑 (PROJECT_ROOT 기준 상대경로 우선)
- 각 이벤트의 `icon` — 그 시점만 적용되는 개별 아이콘
- `video_meta.crop_applied` — 저장 시 ffmpeg crop 으로 영역 잘렸으면 기록

장기 확장 슬롯: `steps[]` (단계 마커) · `annotations[]` (화살표·텍스트) · `audio_track` (내레이션) · `branches[]` (조건부 경로).

---

## 로드맵

| 단계 | 내용 | 상태 |
|---|---|---|
| **M0** | 프로젝트 스캐폴드 | ✅ |
| **M1** | 입력 녹화 + 타임라인 + 저장/불러오기 | ✅ |
| **M2** | 영상 동기 편집기 (플레이어 + 타임라인 + 이벤트 리스트) | ✅ |
| **M3** | 편집 도구 (트림·삭제·필터·undo) | ✅ |
| **M4** | 화면 녹화 — gdigrab 데스크톱 캡처 + 창 크롭 | ✅ |
| **M5** | 항상-위 오버레이 재생 (시퀀스 + 영상 동기) | ✅ |
| **M6** | LoL 아이콘 통합 (DDragon · 챔피언 · 키 매핑 · 이벤트 매핑) | ✅ |
| **M7** | 영상 크롭 도구 | ✅ |
| **M8** | 단계 마커 (녹화 중 구간 구분) | ⏳ |
| **M9** | 마이크 내레이션 동시 녹음 | ⏳ |
| **M10** | 화면 OCR 기반 자동 단계 진행 | ⏳ |
| **M11** | 공유 플랫폼 (웹 업로드·검색·다운로드) | ⏳ |

---

## 기술 스택

- **Python 3.10+** (3.12 권장)
- **PyQt6 + QtMultimedia** — UI, 영상 재생, QGraphicsView 크롭 캔버스
- **pynput** — 글로벌 키보드·마우스 캡처
- **pywin32** — 윈도우 enumeration · DWM 프레임 바운드
- **ffmpeg (외부 바이너리)** — gdigrab 화면 캡처, 크롭 재인코딩

---

## 안티치트 정책

본 도구는 다음 원칙을 따릅니다:

- 게임 프로세스에 **주입하지 않음** (DLL 인젝션 X)
- 게임 메모리 **읽지 않음**
- 입력을 게임에 **전송하지 않음** (시각화만)
- OS 레벨 입력 캡처 (Raw Input · `SetWindowsHookEx`) 만 사용
- 화면 캡처는 데스크톱 컴포지트 GDI 캡처 (게임 후킹 X)

Vanguard·Easy Anti-Cheat·BattlEye 등의 일반적인 거부 사유에서 벗어나도록 설계됩니다. 단, Vanguard 같은 일부 커널 레벨 안티치트는 키보드 훅을 강제 unhook 하므로 LoL 같은 환경에선 입력 캡처가 제한될 수 있습니다.

---

## 폴더 구조

```
HowTo/
├── main.py
├── howto/
│   ├── app.py              # 메인 윈도우 + 편집기
│   ├── recorder.py         # 글로벌 입력 캡처 (pynput)
│   ├── screen_recorder.py  # ffmpeg gdigrab 래퍼 + 크롭 재인코딩
│   ├── crop_dialog.py      # 영상 위 드래그 크롭 (QGraphicsView)
│   ├── windows.py          # 윈도우 enumeration + DWM 바운드
│   ├── timeline.py         # 메인 편집기 타임라인 위젯
│   ├── event_list.py       # 이벤트 표 (다중 선택)
│   ├── player.py           # 시퀀스 오버레이창 (가로 strip + 입력 트래커)
│   ├── video_overlay.py    # 영상 오버레이창 (frameless QVideoWidget)
│   ├── frameless.py        # edge resize 헬퍼
│   ├── key_mapping_dialog.py  # 키 → 아이콘 매핑 다이얼로그
│   ├── resources_loader.py # DDragon manifest 로더 + 경로 헬퍼
│   └── storage.py          # JSON IO
├── tools/
│   └── download_ddragon.py # 리소스 다운로더
├── resources/              # gitignored — DDragon 자산
├── recordings/             # gitignored — 녹화 임시 파일
└── data/                   # gitignored
```
