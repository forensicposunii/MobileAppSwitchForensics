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

---

✅ 중요
iOS/data/ 폴더에는 반드시

1. KnowledgeC.db
2. applicationState.db
3. 스냅샷 파일이 들어있는 폴더(snapshots/)가 존재해야 합니다.
스냅샷은 보통 SceneID:[bundle]-default 또는 SceneID:[bundle]-[SceneID] 하위에 .ktx 확장자로 존재합니다.
---
⚙️ Environment Setup
- Python 3.9+ 권장 
- 별도 외부 패키지 의존성 거의 없음
(kc_to_sqlite.py, appstate_snapshots.py는 표준 라이브러리/내장 모듈 위주)
- ⚠️ 대용량 스냅샷 변환 시 디스크 여유 공간을 확보하세요.
ios_ktx2png.exe는 .ktx → .png 변환 시 파일 크기가 커질 수 있습니다.

---
🚀 Usage Steps

터미널에서 iOS 디렉터리로 이동한 뒤 아래와 같이 명령어를 입력하여 사용하면 됩니다.

```
python build_ios_report_by_app.py --dir .
```

Output:
iOS/ios_by_app.html

---

## External Component Notice

This project includes a binary tool derived from an external open-source project:

- **ios_ktx2png.exe**  
  - **Source:** [GitHub - ydkhatri/MacForensics (IOS_KTX_TO_PNG)](https://github.com/ydkhatri/MacForensics/blob/master/IOS_KTX_TO_PNG/ios_ktx2png.py)  
  - **Author:** Yogesh Khatri  
  - **License:** MIT License  
  - **Description:**  
    This executable is based on the original `ios_ktx2png.py` script from the *MacForensics* repository.  
    It is used to decode and convert iOS snapshot files (`.ktx`, Apple-modified KTX format) into standard `.png` images for forensic analysis and visualization.

