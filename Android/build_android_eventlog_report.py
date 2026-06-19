#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Android UsageStats event-log 타임라인 리포트 생성기

전제:
- usagestats_to_sqlite.py 로 생성한 usagestats_parsed.sqlite 가 존재하고,
  그 안에 data 테이블이 다음 컬럼을 가진다고 가정:
    usage_type, lastime, timeactive, last_time_service_used,
    last_time_visible, total_time_visible, app_launch_count,
    package, types, classs, source, fullatt

기능:
- usage_type = 'event-log' 인 행만 추출
- lastime(ms) → KST(UTC+9) 로 변환
- Package / activity(Types) / Class / Source 와 함께
  시간 내림차순(최근 이벤트 먼저)으로 정렬
- HTML 테이블로 출력
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


def build_eventlog_report(
    base_dir: Path,
    db_name: str = "usagestats_parsed.sqlite",
    html_name: str = "android_eventlog.html",
):
    db_path = (
        Path(db_name) if Path(db_name).is_absolute() else base_dir / db_name
    )
    if not db_path.exists():
        raise SystemExit(f"[!] DB 파일을 찾을 수 없습니다: {db_path}")

    print(f"[INFO] DB: {db_path}")

    conn = sqlite3.connect(str(db_path))

    # lastime(ms) → KST(UTC+9) 변환해서 컬럼 이름도 그대로 달아줌
    query = """
    SELECT
        datetime(lastime/1000, 'unixepoch', '+9 hours')
            AS "Last Time Active (KST, UTC+9)",
        usage_type AS "Usage Type",
        package    AS "Package",
        types      AS "activity",
        classs     AS "Class",
        source     AS "Source"
    FROM data
    WHERE usage_type = 'event-log'
    ORDER BY lastime DESC;
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"[INFO] event-log 행 개수: {len(df)}")

    # HTML 테이블 생성
    table_html = df.to_html(
        index=False,
        border=1,
        justify="center",
        classes=["eventlog-table"],
    )

    # 간단한 스타일 포함한 전체 HTML 조립
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Android UsageStats Event-log Timeline</title>
<style>
body {{
  font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  margin:20px;
}}
h1 {{
  font-size:24px;
  margin-bottom:10px;
}}
p {{
  margin:4px 0 12px 0;
}}
table {{
  font-size:12px;
  border-collapse:collapse;
  width:100%;
}}
th, td {{
  border:1px solid #999;
  padding:3px 6px;
  white-space:nowrap;
}}
th {{
  background:#f0f0f0;
}}
</style>
</head>
<body>
<h1>📱 Android UsageStats Event-log Timeline</h1>
<p>기준 폴더: {base_dir}</p>
<p>설명: usage_type = <b>event-log</b> 인 레코드만, <b>lastime</b> 기준 내림차순으로 정렬한 타임라인입니다.</p>
{table_html}
</body>
</html>"""

    out_path = base_dir / html_name
    out_path.write_text(html, encoding="utf-8")
    print(f"[OK] HTML 리포트 생성 완료 → {out_path}")


def main():
    ap = argparse.ArgumentParser(
        description="Android UsageStats event-log 타임라인 리포트 생성기"
    )
    ap.add_argument(
        "--dir",
        required=True,
        help="usagestats_parsed.sqlite 가 있는 폴더 경로",
    )
    ap.add_argument(
        "--db",
        default="usagestats_parsed.sqlite",
        help="사용할 SQLite 파일 이름 (기본: usagestats_parsed.sqlite)",
    )
    ap.add_argument(
        "--html",
        default="android_eventlog.html",
        help="출력 HTML 파일 이름 (기본: android_eventlog.html)",
    )
    args = ap.parse_args()

    base_dir = Path(args.dir).expanduser().resolve()
    build_eventlog_report(base_dir, db_name=args.db, html_name=args.html)


if __name__ == "__main__":
    main()
