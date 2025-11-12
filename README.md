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



