# MobileAppSwitchForensics

An automated forensic analysis tool for **iOS and Android app switching artifacts**.  
This project aims to assist forensic investigators and researchers in **cross-verifying user activity** through artifacts generated when applications transition between foreground and background states.

---

## 📘 Overview
MobileAppSwitchForensics parses and correlates multiple artifacts to reconstruct user behavior timelines related to app transitions.

### Supported Platforms & Artifacts
- **Android**
  - `usagestats` (XML / protobuf)
  - `recent_tasks` (XML)
  - `snapshots` (screenshot cache)
- **iOS**
  - `KnowledgeC.db`
  - `applicationState.db`
  - `snapshot` (.ktx → .png)

### Output
- Structured SQLite databases (`*_parsed.sqlite`)
- HTML visualization reports (per app or per timeline)

---

### Third-Party Components Notice

This project includes the following external component:

- **ios_ktx2png.exe**  
  - Source: [GitHub - ydkhatri/MacForensics (IOS_KTX_TO_PNG)](https://github.com/ydkhatri/MacForensics/blob/master/IOS_KTX_TO_PNG/ios_ktx2png.py)  
  - Author: Yogesh Khatri  
  - License: MIT License  
  - Description: A tool originally written to convert iOS KTX snapshot files to PNG. Modified/packaged here for use in this project.


This project includes selected modules derived from the following open-source projects:

- **ALEAPP / iLEAPP Components (Android)**
  - ALEAPP (Android Logs, Events, And Protobuf Parser)
  - Source: https://github.com/abrignoni/ALEAPP
  - Authors: Alexis Brignoni, Yogesh Khatri
  - License: MIT License

The following files in this project originate from (or are modified versions of) ALEAPP/iLEAPP modules:

```
scripts/ilapfuncs.py
scripts/filetype.py
scripts/lavafuncs.py
scripts/artifact_report.py
protobuf/usagestatsservice_pb2.py
protobuf/usagestatsservice_v2_pb2.py
protobuf/configuration_pb2.py
protobuf/privacy_pb2.py
protobuf/window_configuration_pb2.py
(and other dependent protobuf modules required for Android UsageStats decoding)
```

Description:
These modules were originally created to parse Android artifacts in ALEAPP.
For this project, they are selectively included and adapted to support automated analysis of Android app-switching artifacts (UsageStats, Recent Tasks, Snapshots).
All modifications remain under the original MIT License.

