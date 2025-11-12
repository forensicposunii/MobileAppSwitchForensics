# 🤖 Android App Switching Artifacts — Usage Guide

이 디렉터리는 Android 앱 전환(App Switcher) 아티팩트를 자동으로 분석하여 앱의 사용 타임라인과 최근 작업 스냅샷을 교차검증하는 도구입니다.

📂 Folder Structure & Required Files

```
Android/
 ├─ USAGE.md
 ├─ usagestats_to_sqlite.py         # UsageStats XML → SQLite 변환기
 ├─ recentactivity.py               # RecentTasks XML 파서
 ├─ build_recenttasks_sqlite.py     # RecentTasks → SQLite 정리기
 ├─ build_android_eventlog_report.py# 리포트 생성기 (HTML)
 ├─ data/                           # ⚠️ 필수: 아래 폴더들 포함
 │   ├─ usagestats/                 # UsageStats XML 파일들이 들어있는 폴더
 │   ├─ recent_tasks/               # RecentTasks XML이 들어있는 폴더
 │   └─ snapshots/                  # 앱 전환 시 캡처된 썸네일 이미지 폴더
 └─ protobuf/                       # ALEAPP 기반 Protobuf 파서 모듈들 (*.py)
```

⚠️ 중요:
Android/data/ 폴더는 반드시 다음 세 가지 하위 폴더를 포함해야 합니다:

```
1️⃣ usagestats/ → UsageStatsService에서 추출된 XML 파일
2️⃣ recent_tasks/ → /system_ce/0/recent_tasks/ 내부 XML들
3️⃣ snapshots/ → /system_ce/0/snapshots/ 내부의 스냅샷 이미지들
```

⚙️ Environment Setup

- Python 3.9 이상 권장
- 필요한 경우, 루트 폴더에서 가상환경 생성:
```
python -m venv .venv_aus
.\.venv_aus\Scripts\activate
pip install protobuf
```
protobuf 라이브러리가 없을 경우 google 모듈 에러가 발생할 수 있습니다.
반드시 venv 내에서 설치 후 실행하세요.
