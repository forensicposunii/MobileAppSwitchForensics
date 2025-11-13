#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Android recent_tasks SQLite + HTML 파서 (간략 버전)
필드:
  - task_id (파일명)
  - real_activity
  - last_time_moved (ms)
  - last_time_moved_utc (UTC ISO)
  - snapshot_file (snapshots 폴더 안의 이미지 파일명)

ABX(Binary XML) 지원 (ALEAPP의 scripts\ilapfuncs.py 필요)
"""

import os
import glob
import argparse
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ABX 파서 (ALEAPP의 scripts\ilapfuncs.py)
try:
    from scripts.ilapfuncs import abxread, checkabx
    print("[INFO] ALEAPP ilapfuncs 로딩 성공 (ABX 지원 활성화)")
except ImportError as e:
    abxread = None
    checkabx = None
    print(f"[WARN] ALEAPP ilapfuncs 로딩 실패, ABX(Binary XML)는 일반 XML처럼 처리됩니다. ({e})")


def ms_to_iso(ms):
    """millisecond epoch → UTC ISO string"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def init_db(db_path):
    """SQLite DB 생성"""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recent_tasks (
            task_id TEXT,
            real_activity TEXT,
            last_time_moved INTEGER,
            last_time_moved_utc TEXT,
            snapshot_file TEXT
        )
    """)
    conn.commit()
    return conn


def insert_row(conn, task_id, real_activity, last_time_moved, iso_time, snapshot_file):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO recent_tasks
            (task_id, real_activity, last_time_moved, last_time_moved_utc, snapshot_file)
        VALUES (?, ?, ?, ?, ?)
    """, (task_id, real_activity, last_time_moved, iso_time, snapshot_file))
    conn.commit()


def find_snapshot_for_task(snapshots_dir, task_id):
    """snapshots 폴더에서 task_id.* 파일 찾기 (jpg, png 등)"""
    if not task_id:
        return None
    patterns = [
        os.path.join(snapshots_dir, f"{task_id}.*"),
        os.path.join(snapshots_dir, f"{task_id}_*.*"),
    ]
    for pattern in patterns:
        files = glob.glob(pattern)
        if files:
            return os.path.basename(files[0])
    return None


def parse_recent_task(file_path, snapshots_dir):
    """
    XML 또는 ABX recent_task 파일에서
    (task_id, real_activity, last_time_moved, last_time_moved_utc, snapshot_file) 추출
    """
    try:
        if checkabx and checkabx(file_path):
            tree = abxread(file_path, False)
        else:
            tree = ET.parse(file_path)

        root = tree.getroot()
        attrs = root.attrib

        task_id = os.path.splitext(os.path.basename(file_path))[0]
        real_activity = attrs.get("real_activity", "N/A")
        last_time_moved = attrs.get("last_time_moved", "0")
        iso_time = ms_to_iso(last_time_moved)

        snapshot_file = find_snapshot_for_task(snapshots_dir, task_id)

        return task_id, real_activity, last_time_moved, iso_time, snapshot_file
    except Exception as e:
        print(f"[WARN] 파싱 실패: {file_path} ({e})")
        return None


def build_html(db_path, snapshots_dir_name, html_path):
    """SQLite 내용 + snapshots 를 이용해 HTML 리포트 생성"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            last_time_moved_utc,
            task_id,
            real_activity,
            snapshot_file
        FROM recent_tasks
        ORDER BY last_time_moved DESC
    """)
    rows = cur.fetchall()
    conn.close()

    db_name = os.path.basename(db_path)

    with open(html_path, "w", encoding="utf-8") as f:
        # f-string 으로 헤더 구성 (문자열 포맷 연산자 % 사용 안 함)
        f.write(f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Android Recent Tasks (Snapshots)</title>
<style>
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin: 20px; }}
h1 {{ font-size: 24px; margin-bottom: 10px; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
th, td {{ border: 1px solid #ccc; padding: 4px 6px; font-size: 12px; vertical-align: top; }}
th {{ background: #f0f0f0; }}
img {{ max-width: 280px; max-height: 500px; border: 1px solid #ddd; }}
</style>
</head>
<body>
<h1>📱 Android Recent Tasks (with Snapshots)</h1>
<p>SQLite: {db_name}<br>Snapshots 폴더: {snapshots_dir_name}</p>
<table>
<tr>
  <th>Last Time Moved (UTC)</th>
  <th>Task ID (파일명)</th>
  <th>real_activity</th>
  <th>Snapshot</th>
</tr>
""")

        for last_iso, task_id, real_activity, snapshot_file in rows:
            f.write("<tr>")
            f.write(f"<td>{last_iso or ''}</td>")
            f.write(f"<td>{task_id or ''}</td>")
            f.write(f"<td>{real_activity or ''}</td>")
            if snapshot_file:
                img_src = os.path.join(snapshots_dir_name, snapshot_file).replace("\\", "/")
                f.write(f'<td><img src="{img_src}" alt="{snapshot_file}"></td>')
            else:
                f.write("<td>NO IMAGE</td>")
            f.write("</tr>\n")

        f.write("""
</table>
</body>
</html>
""")


def process_recent_tasks(root_dir, db_path, html_path):
    """
    root_dir 아래에:
      recent_tasks/
      snapshots/
    가 있다고 가정.
    """
    recent_dir = os.path.join(root_dir, "recent_tasks")
    snapshots_dir = os.path.join(root_dir, "snapshots")

    if not os.path.isdir(recent_dir):
        raise SystemExit(f"[!] recent_tasks 폴더를 찾을 수 없습니다: {recent_dir}")
    if not os.path.isdir(snapshots_dir):
        print(f"[WARN] snapshots 폴더를 찾을 수 없습니다: {snapshots_dir}")
        snapshots_dir_name = "snapshots"
    else:
        snapshots_dir_name = os.path.basename(snapshots_dir)

    conn = init_db(db_path)
    count = 0

    for file in glob.glob(os.path.join(recent_dir, "**"), recursive=True):
        if os.path.isfile(file):
            parsed = parse_recent_task(file, snapshots_dir)
            if parsed:
                insert_row(conn, *parsed)
                count += 1

    conn.close()
    print(f"[OK] {count}개 recent_task 항목이 SQLite에 저장되었습니다 → {db_path}")

    build_html(db_path, snapshots_dir_name, html_path)
    print(f"[OK] HTML 리포트 생성 완료 → {html_path}")


def main():
    ap = argparse.ArgumentParser(
        description="Android recent_tasks SQLite + Snapshots HTML 파서"
    )
    ap.add_argument("--dir", required=True,
                    help="recent_tasks / snapshots 폴더가 포함된 루트 디렉터리")
    ap.add_argument("--db", default="RecentTasks.db",
                    help="출력 SQLite 파일명 (기본: RecentTasks.db)")
    ap.add_argument("--html", default="android_recenttasks.html",
                    help="출력 HTML 파일명 (기본: android_recenttasks.html)")
    args = ap.parse_args()

    process_recent_tasks(args.dir, args.db, args.html)


if __name__ == "__main__":
    main()
