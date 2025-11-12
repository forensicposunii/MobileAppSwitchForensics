#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Usage:
  python kc_to_sqlite.py --in "C:\\DF\\KnowledgeC.db" --out "C:\\DF\\KnowledgeC_parsed.sqlite"

설명:
- 입력: iOS KnowledgeC.db (SQLite)
- 출력: 변환된 시간(UTC/KST ISO8601)과 duration_sec가 포함된 SQLite DB
- 생성 테이블:
    - events(event_pk, stream, bundle_id, valuestring, start_mac, end_mac,
             start_utc_iso, end_utc_iso, start_kst_iso, end_kst_iso, duration_sec)
    - metadata(source_path, generated_at, note, bundle_id_column)
    - events_preview(샘플 50건)
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

try:
    import pandas as pd
except Exception as e:
    raise SystemExit("pandas가 필요합니다. pip install pandas 실행 후 다시 시도하세요.") from e


def mac_to_dt(x):
    """Mac Absolute Time(초, 기준 2001-01-01 UTC)을 datetime으로 변환."""
    if pd.isna(x):
        return pd.NaT
    try:
        return datetime(2001, 1, 1) + timedelta(seconds=float(x))
    except Exception:
        return pd.NaT


def get_columns(conn, table):
    """PRAGMA table_info로 컬럼 목록 얻게."""
    try:
        return pd.read_sql_query(f"PRAGMA table_info({table});", conn)["name"].tolist()
    except Exception:
        return []


def build_query(src_conn):
    """스키마 차이를 감안해 동적으로 SELECT 쿼리 생성."""
    tables = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table';", src_conn
    )["name"].tolist()

    has_zsn = "ZSTREAMNAME" in tables
    has_zsmeta = "ZSTRUCTUREDMETADATA" in tables
    meta_cols = get_columns(src_conn, "ZSTRUCTUREDMETADATA") if has_zsmeta else []

    # 번들 식별자 후보 컬럼들
    bundle_candidates = [
        "ZBUNDLEID",
        "Z_DKAPPLICATIONACTIVITYMETADATAKEY_BUNDLEID",
        "ZBUNDLEIDENTIFIER",
        "Z_DKBUNDLEID",
    ]
    bundle_col = next((c for c in bundle_candidates if c in meta_cols), None)

    select_fields = [
        "ZOBJECT.Z_PK AS event_pk",
        "ZOBJECT.ZSTARTDATE AS start_mac",
        "ZOBJECT.ZENDDATE AS end_mac",
        "ZOBJECT.ZVALUESTRING AS valuestring",
    ]
    join_clauses = []

    # stream 컬럼 확보
    if has_zsn:
        select_fields.append("ZSTREAMNAME.ZSTREAMNAME AS stream")
        join_clauses.append(
            "LEFT JOIN ZSTREAMNAME ON ZOBJECT.ZSTREAMNAME = ZSTREAMNAME.Z_PK"
        )
    else:
        zobj_cols = get_columns(src_conn, "ZOBJECT")
        if "ZSTREAMNAME" in zobj_cols:
            select_fields.append("ZOBJECT.ZSTREAMNAME AS stream")
        else:
            select_fields.append("NULL AS stream")

    # bundle id 확보
    if has_zsmeta and bundle_col:
        select_fields.append(f"ZSTRUCTUREDMETADATA.{bundle_col} AS bundle_id")
        join_clauses.append(
            "LEFT JOIN ZSTRUCTUREDMETADATA ON ZOBJECT.ZSTRUCTUREDMETADATA = ZSTRUCTUREDMETADATA.Z_PK"
        )
    else:
        select_fields.append("NULL AS bundle_id")

    sql = f"""
    SELECT
        {", ".join(select_fields)}
    FROM ZOBJECT
    {" ".join(join_clauses)}
    ORDER BY ZOBJECT.ZSTARTDATE ASC
    """
    return sql, bundle_col or "N/A"


def convert_and_write(src_db: Path, out_db: Path):
    # 입력 열기
    src_conn = sqlite3.connect(str(src_db))
    sql, bundle_col_name = build_query(src_conn)

    # 쿼리 실행
    df = pd.read_sql_query(sql, src_conn)

    # 시간 변환
    df["start_utc"] = df["start_mac"].apply(mac_to_dt)
    df["end_utc"] = df["end_mac"].apply(mac_to_dt)
    df["start_kst"] = df["start_utc"] + pd.to_timedelta(9, unit="h")
    df["end_kst"] = df["end_utc"] + pd.to_timedelta(9, unit="h")
    df["duration_sec"] = (df["end_utc"] - df["start_utc"]).dt.total_seconds()

    # ISO8601 문자열 컬럼
    for col in ["start_utc", "end_utc", "start_kst", "end_kst"]:
        df[col + "_iso"] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # 출력 스키마 정리
    out_cols = [
        "event_pk",
        "stream",
        "bundle_id",
        "valuestring",
        "start_mac",
        "end_mac",
        "start_utc_iso",
        "end_utc_iso",
        "start_kst_iso",
        "end_kst_iso",
        "duration_sec",
    ]
    out_df = df[out_cols].copy()

    # 출력 DB 준비
    if out_db.exists():
        out_db.unlink()
    out_conn = sqlite3.connect(str(out_db))
    cur = out_conn.cursor()

    # events 테이블 저장
    out_df.to_sql("events", out_conn, if_exists="replace", index=False)

    # metadata 저장
    meta_df = pd.DataFrame(
        {
            "key": ["source_path", "generated_at", "note", "bundle_id_column"],
            "value": [
                str(src_db),
                datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "Mac Absolute Time → UTC/KST ISO8601 변환, duration_sec 포함.",
                bundle_col_name,
            ],
        }
    )
    meta_df.to_sql("metadata", out_conn, if_exists="replace", index=False)

    # preview 저장
    out_df.head(50).to_sql("events_preview", out_conn, if_exists="replace", index=False)

    # 인덱스 생성
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_time ON events(start_utc_iso, end_utc_iso);"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_bundle ON events(bundle_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream);")
    out_conn.commit()

    out_conn.close()
    src_conn.close()


def main():
    p = argparse.ArgumentParser(
        description="KnowledgeC.db를 읽어 변환된 시간 필드를 포함한 새 SQLite DB로 내보냅니다."
    )
    p.add_argument("--in", dest="in_path", required=True, help="입력 KnowledgeC.db 경로")
    p.add_argument("--out", dest="out_path", required=True, help="출력 .sqlite 경로")
    args = p.parse_args()

    src = Path(args.in_path)
    out = Path(args.out_path)

    if not src.exists():
        raise SystemExit(f"입력 DB가 존재하지 않습니다: {src}")

    out.parent.mkdir(parents=True, exist_ok=True)
    convert_and_write(src, out)
    print(f"[OK] 변환 완료 -> {out}")


if __name__ == "__main__":
    main()
