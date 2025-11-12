# 🍎 iOS App Switching Artifacts — Usage Guide

이 디렉터리는 **iOS 앱 전환(App Switcher) 아티팩트**를 분석하여 앱의 실행 타임라인과 스냅샷 이미지를 교차 검증하는 도구입니다. 이 스크립트들은 KnowledgeC.db, applicationState.db, Snapshot 파일을 기반으로 사용자 행위를 시각화하고 앱 사용 내역을 추출합니다.

---

## 📁 Folder Structure

```plaintext
iOS/
 ├─ USAGE.md                      # (이 문서)
 ├─ kc_to_sqlite.py               # KnowledgeC.db 파서
 ├─ appstate_snapshots.py         # applicationState.db + 스냅샷 매핑
 ├─ build_ios_report_by_app.py    # 앱별 HTML 리포트 생성기
 ├─ ios_ktx2png.exe               # KTX → PNG 변환기
 └─ data/                         # ⚠️ 필수 폴더
     ├─ KnowledgeC.db             # iOS 행동기록 DB
     ├─ applicationState.db       # 앱 상태 관리 DB
     └─ snapshots/                # 스냅샷(.ktx) 파일 폴더

```

✅ 중요
iOS/data/ 폴더에는 반드시

1. KnowledgeC.db
2. applicationState.db
3. 스냅샷 파일이 들어있는 폴더(snapshots/)가 존재해야 합니다.
스냅샷은 보통 SceneID:[bundle]-default 또는 SceneID:[bundle]-[SceneID] 하위에 .ktx 확장자로 존재합니다.

⚙️ Environment Setup
- Python 3.9+ 권장 
- 별도 외부 패키지 의존성 거의 없음
(kc_to_sqlite.py, appstate_snapshots.py는 표준 라이브러리/내장 모듈 위주)
- ⚠️ 대용량 스냅샷 변환 시 디스크 여유 공간을 확보하세요.
ios_ktx2png.exe는 .ktx → .png 변환 시 파일 크기가 커질 수 있습니다.

🚀 Usage Steps

터미널에서 iOS 디렉터리로 이동한 뒤 아래 순서대로 실행하세요.

① Parse KnowledgeC.db

cd iOS
python kc_to_sqlite.py


Output → data/knowledgec_parsed.sqlite

② Map applicationState.db + Snapshots
python appstate_snapshots.py


applicationState.db 내 앱 상태 정보 + 스냅샷 폴더 매핑

Output → data/appstate_snapshots.sqlite

③ Convert KTX → PNG (optional)
.\ios_ktx2png.exe "data\snapshots" "data\snapshots_png"


Converts all .ktx files to .png in the output directory

Output → data/snapshots_png/

④ Generate App Reports
python build_ios_report_by_app.py


Combines parsed DBs and snapshot info into HTML reports

Output → reports/ios_by_app/*.html

🧩 Tips for Snapshot Folders

단일 Scene 앱 → SceneID:[bundle]-default/

다중 Scene 앱 → SceneID:[bundle]-[SceneID]/

동일 앱이라도 Scene ID가 다르면 별도 폴더로 저장됨

파일명은 일반적으로 스냅샷 생성 시각(YYYYMMDD_HHMMSS.ktx)





