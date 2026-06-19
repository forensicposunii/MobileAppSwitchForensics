
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Android Forensic Report — Application별
RecentTasks + Snapshots(있으면) + UsageStats(RESUMED/PAUSED/STOPPED) 보고서 생성
- 스냅샷 보유 앱 우선 정렬
- 분(minute) 단위 일치: 파란색
- 앱별 가장 최근 분 불일치: 최신 UsageStats 행과 최신 RecentTasks 행을 빨간색
"""
import argparse, os, re, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_RCT = SCRIPT_DIR / "RecentTasks.db"
DEFAULT_DB_USG = SCRIPT_DIR / "data" / "usagestats_parsed.sqlite"
DEFAULT_SNAP_DIR = SCRIPT_DIR / "data" / "snapshots"
DEFAULT_HTML    = SCRIPT_DIR / "android_report_by_app.html"


def _exists(p: Path) -> bool:
    return p.exists() and (p.is_file() or p.is_dir())


def _extract_package(real_activity: str) -> str:
    if not real_activity:
        return None
    s = str(real_activity).strip()
    # ComponentInfo{pkg/cls}
    m = re.search(r'\{([A-Za-z0-9._]+)/', s)
    if m: return m.group(1)
    # pkg/.Class  OR  pkg/Class
    m = re.match(r'([A-Za-z0-9._]+)[/ ]', s)
    if m: return m.group(1)
    # pure package
    m = re.match(r'^([A-Za-z0-9._]+)$', s)
    if m: return m.group(1)
    # fallback
    m = re.search(r'([A-Za-z0-9._]+)\.', s)
    return m.group(1) if m else None


def read_recenttasks(db_path: Path) -> pd.DataFrame:
    if not _exists(db_path):
        print(f"[WARN] RecentTasks DB 없음: {db_path}")
        return pd.DataFrame(columns=["task_id","real_activity","last_time_moved","last_time_moved_utc","snapshot_file","package"])
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT task_id, real_activity, last_time_moved, last_time_moved_utc, snapshot_file
    FROM recent_tasks
    ORDER BY CAST(last_time_moved AS INTEGER) DESC;
    """
    df = pd.read_sql_query(q, con)
    con.close()
    df["package"] = df["real_activity"].apply(_extract_package)
    return df


def read_usagestats(db_path: Path) -> pd.DataFrame:
    if not _exists(db_path):
        print(f"[WARN] UsageStats DB 없음: {db_path}")
        return pd.DataFrame(columns=["last_time_kst","package","types","classs","source"])
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT
        datetime(lastime/1000,'unixepoch','+9 hours') AS last_time_kst,
        package, types, classs, source
    FROM data
    WHERE usage_type='event-log'
      AND (
        types='ACTIVITY_RESUMED' OR
        types='ACTIVITY_PAUSED'  OR
        types='ACTIVITY_PAUSE'   OR
        types='ACTIVITY_STOPPED'
      )
    ORDER BY lastime DESC;
    """
    df = pd.read_sql_query(q, con)
    con.close()
    return df


def index_snapshots(snap_dir: Path):
    """재귀적으로 스냅샷 파일 인덱스 생성 (키: 파일명 소문자)"""
    mapping = {}
    if not _exists(snap_dir):
        return mapping
    for p in snap_dir.rglob("*"):
        if p.is_file():
            mapping[p.name.lower()] = p
    return mapping


def _minute_key_from_usg(s: str) -> str:
    """UsageStats 'YYYY-MM-DD HH:MM:SS' -> 'YYYY-MM-DD HH:MM'"""
    if not s:
        return ""
    s = str(s).replace("T", " ").strip()
    return s[:16]


def _minute_key_from_rct_utc_to_kst(s: str) -> str:
    """RecentTasks UTC 문자열을 KST로 변환 후 'YYYY-MM-DD HH:MM' 반환"""
    if not s:
        return ""
    try:
        try:
            dt = datetime.fromisoformat(str(s))
        except Exception:
            dt = datetime.fromisoformat(str(s).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        return kst.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(s).replace("T"," ")[:16]


def build_html(df_rct, df_usg, snap_dir: Path, out_path: Path):
    """
    - 스냅샷 우선 정렬
    - UsageStats subset + RecentTasks
    - 분(minute) 일치=파랑, 최신 불일치=빨강
    """
    # 패키지 결측은 'android' 그룹으로 묶기
    df_rct2 = df_rct.copy()
    df_usg2 = df_usg.copy()
    df_rct2["pkg2"] = df_rct2["package"].fillna("android").astype(str)
    df_usg2["pkg2"] = df_usg2["package"].fillna("android").astype(str)

    # 스냅샷 인덱스
    snap_index = index_snapshots(snap_dir)

    # 스냅샷 보유 점수 계산
    def _snapshot_score_for_pkg(pkg: str) -> int:
        sub_r = df_rct2[df_rct2["pkg2"] == pkg]
        if sub_r.empty:
            return 0
        exts = [".jpg",".png",".webp",".jpeg"]
        score = 0
        for _, r in sub_r.iterrows():
            sf = str(r.get("snapshot_file","") or "").strip().lower()
            if sf and sf in snap_index:
                score += 1
                continue
            tid = str(r.get("task_id","") or "")
            digits = "".join(ch for ch in tid if ch.isdigit())
            candidates = []
            if sf:
                candidates.append(sf)
            if digits:
                candidates += [f"{digits}{e}" for e in exts] + [f"{digits}_reduced{e}" for e in exts]
            found = False
            for cand in candidates:
                if cand in snap_index:
                    found = True
                    break
                for key in snap_index.keys():
                    if key.endswith(cand):
                        found = True
                        break
                if found:
                    break
            if found:
                score += 1
        return score

    # 정렬용 앱 목록
    pkgs_all = sorted(set(df_rct2["pkg2"].unique()).union(set(df_usg2["pkg2"].unique())))
    pkgs = sorted(pkgs_all, key=lambda x: (-_snapshot_score_for_pkg(x), x or ""))

    def esc(s):
        return (str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") if s is not None else "")

    html = [f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Android Forensic Report — Application별</title>
<style>
body {{font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:20px;}}
h1 {{font-size:24px;margin-bottom:10px;}}
h2 {{margin-top:40px;color:#0a58ca;}}
.snapshots {{display:flex;flex-wrap:wrap;gap:12px;}}
.snapshots figure {{text-align:center;width:240px;}}
.snapshots img {{max-width:100%;border:1px solid #aaa;}}
table {{font-size:12px;border-collapse:collapse;width:100%;}}
th,td {{border:1px solid #999;padding:3px 6px;white-space:nowrap;}}
th {{background:#f0f0f0;}}
.blue td {{ color:#06c; font-weight:600; }}
.red  td {{ color:#c00; font-weight:600; }}
</style>
</head>
<body>
<h1>📱 Android Forensic Report — Application별</h1>
<p>기준 폴더: {esc(str(out_path.parent))}</p>
"""]

    exts = [".jpg",".png",".webp",".jpeg"]
    for pkg in pkgs:
        html.append(f'<h2 id="{pkg}">{pkg}</h2>')

        # 앱별 서브셋 준비
        sub_r = df_rct2[df_rct2["pkg2"] == pkg]
        sub_u = df_usg2[df_usg2["pkg2"] == pkg]

        # 분 단위 키 세트
        usg_minutes = [(_minute_key_from_usg(x), i) for i, x in enumerate(sub_u["last_time_kst"].dropna().astype(str).tolist())]
        rct_minutes = [(_minute_key_from_rct_utc_to_kst(x), i) for i, x in enumerate(sub_r["last_time_moved_utc"].dropna().astype(str).tolist())]
        usg_min_set = set(m for m, _ in usg_minutes if m)
        rct_min_set = set(m for m, _ in rct_minutes if m)
        intersect_minutes = usg_min_set & rct_min_set
        most_recent_usg_min = max(usg_min_set) if usg_min_set else ""
        most_recent_rct_min = max(rct_min_set) if rct_min_set else ""

        # --- UsageStats subset ---
        if not sub_u.empty:
            html.append("<h3>UsageStats — ACTIVITY_RESUMED / PAUSED / STOPPED</h3>")
            html.append("<table><thead><tr><th>last_time (KST)</th><th>types</th><th>class</th><th>source</th></tr></thead><tbody>")
            for _, r in sub_u.sort_values(by="last_time_kst", ascending=False).iterrows():
                mk = _minute_key_from_usg(r.get('last_time_kst'))
                row_cls = ""
                if mk:
                    if mk in intersect_minutes:
                        row_cls = " class='blue'"
                    elif most_recent_usg_min and most_recent_rct_min and (mk == most_recent_usg_min) and (most_recent_usg_min != most_recent_rct_min):
                        row_cls = " class='red'"
                html.append(f"<tr{row_cls}>"
                            f"<td>{esc(r.get('last_time_kst'))}</td>"
                            f"<td>{esc(r.get('types'))}</td>"
                            f"<td>{esc(r.get('classs'))}</td>"
                            f"<td>{esc(r.get('source'))}</td>"
                            "</tr>")
            html.append("</tbody></table>")

        # --- RecentTasks ---
        if sub_r.empty and sub_u.empty:
            html.append("<p><i>해당 앱에 대한 RecentTasks/UsageStats 데이터가 없습니다.</i></p>")
            continue

        if not sub_r.empty:
            html.append("<h3>RecentTasks (with Snapshot)</h3>")
            html.append("<table><thead><tr><th>last_time_moved (UTC)</th><th>task_id</th><th>real_activity</th><th>snapshot_file</th></tr></thead><tbody>")
            for _, r in sub_r.iterrows():
                mk = _minute_key_from_rct_utc_to_kst(r.get('last_time_moved_utc'))
                row_cls = ""
                if mk:
                    if mk in intersect_minutes:
                        row_cls = " class='blue'"
                    elif most_recent_usg_min and most_recent_rct_min and (mk == most_recent_rct_min) and (most_recent_usg_min != most_recent_rct_min):
                        row_cls = " class='red'"
                html.append(f"<tr{row_cls}>"
                            f"<td>{esc(r.get('last_time_moved_utc'))}</td>"
                            f"<td>{esc(r.get('task_id'))}</td>"
                            f"<td>{esc(r.get('real_activity'))}</td>"
                            f"<td>{esc(r.get('snapshot_file'))}</td>"
                            "</tr>")
            html.append("</tbody></table>")

            # 스냅샷 탐색
            imgs = []
            for _, r in sub_r.iterrows():
                name = str(r.get("snapshot_file","")).strip()
                tid  = str(r.get("task_id","")).strip()
                digits = "".join(ch for ch in tid if ch.isdigit())

                candidates = []
                if name: candidates.append(name)
                if digits: candidates += [f"{digits}{e}" for e in exts] + [f"{digits}_reduced{e}" for e in exts]

                found = None
                for cand in candidates:
                    lc = cand.lower()
                    if lc in snap_index:
                        found = snap_index[lc]
                        break
                    # endswith 매칭 허용
                    for key,path in snap_index.items():
                        if key.endswith(lc):
                            found = path
                            break
                    if found: break
                if found:
                    rel = os.path.relpath(found, start=out_path.parent).replace("\\","/")
                    imgs.append((rel, found.name))

            if imgs:
                html.append("<h3>Snapshot Images</h3><div class='snapshots'>")
                for rel, name in sorted(set(imgs)):
                    html.append(f"<figure><img src='{rel}' width='240'><figcaption>{esc(name)}</figcaption></figure>")
                html.append("</div>")

    html.append("</body></html>")
    out_path.write_text("\n".join(html), encoding="utf-8")
    print(f"[OK] 보고서 생성 완료 → {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Android Report (RecentTasks + Snapshots + UsageStats subset)")
    ap.add_argument("--db_rct", default=str(DEFAULT_DB_RCT))
    ap.add_argument("--db_usg", default=str(DEFAULT_DB_USG))
    ap.add_argument("--snap", default=str(DEFAULT_SNAP_DIR))
    ap.add_argument("--html", default=str(DEFAULT_HTML))
    args = ap.parse_args()

    df_r = read_recenttasks(Path(args.db_rct))
    df_u = read_usagestats(Path(args.db_usg))
    build_html(df_r, df_u, Path(args.snap), Path(args.html))


if __name__ == "__main__":
    main()
