#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
iOS Forensic Report Generator - By Application

1. Convert .ktx snapshots under the data folder (or --dir target) to PNG using ios_ktx2png.exe
2. Parse KnowledgeC.db with kc_to_sqlite.py and extract /app/usage events
3. Parse applicationState.db with appstate_snapshots.py and extract snapshot metadata
4. Generate an application-level HTML report based on Bundle ID
   - KnowledgeC /app/usage event table
   - applicationState snapshot metadata table
     - Compare the last usage time (end_kst_iso) with the snapshot creation time (creationDate)
     - Within 1 minute (60 seconds): blue; larger differences: red
   - Snapshot image previews for each application
"""

import argparse
import sqlite3
import subprocess
from pathlib import Path
from collections import defaultdict

import pandas as pd

from kc_to_sqlite import convert_and_write
from appstate_snapshots import extract_all_snapshots

# Allowed tolerance between end_kst_iso and creationDate, in seconds
MATCH_THRESHOLD_SECONDS = 60

# ------------------------------------------------------------
# Common path setup: script location and data folder
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


# ------------------------------------------------------------
# 1. KTX to PNG conversion
# ------------------------------------------------------------
def run_ios_ktx2png_on_folder(base_dir: Path, exe_name: str = "ios_ktx2png.exe"):
    exe_path = BASE_DIR / exe_name  # Assume the executable is in the same folder as this script
    if not exe_path.exists():
        raise SystemExit(f"[!] Could not find {exe_name} in {BASE_DIR}.")

    ktx_files = sorted(base_dir.rglob("*.ktx"))
    png_files = []

    if not ktx_files:
        print("[!] No KTX files found.")
        return png_files

    for ktx in ktx_files:
        # macOS AppleDouble files (._*) contain metadata, not image data.
        # Converting them creates broken ._*.ktx.png entries in the report.
        if ktx.name.startswith("._"):
            print(f"[SKIP] {ktx} (AppleDouble metadata file excluded)")
            continue

        # Exclude DEFAULT GROUP folders because they do not contain user-facing snapshots
        if "{DEFAULT GROUP}" in str(ktx.parent):
            print(f"[SKIP] {ktx} (DEFAULT GROUP folder excluded)")
            continue

        png_path = ktx.with_suffix(ktx.suffix + ".png")
        cmd = [str(exe_path), str(ktx), str(png_path)]

        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            png_files.append(png_path)
        except Exception as e:
            print(f"[ERROR] Conversion failed: {ktx} ({e})")

    print(f"[OK] KTX to PNG conversion completed: {len(png_files)}PNG files generated")
    return png_files


# ------------------------------------------------------------
# Utility: automatically find datetime columns and convert them with to_datetime
# ------------------------------------------------------------
def find_datetime_series(df: pd.DataFrame, preferred_cols, fallback_keywords=None):
    """
    preferred_cols: list of column names to check first
    fallback_keywords: keywords to try when included in a column name (case-insensitive substring match)
    """
    # 1. Prefer exact column-name matches
    for col in preferred_cols:
        if col in df.columns:
            s = pd.to_datetime(df[col], errors="coerce")
            if s.notna().any():
                return col, s

    # 2. Keyword-based fallback
    if fallback_keywords:
        for col in df.columns:
            low = col.lower()
            if all(k in low for k in fallback_keywords):
                s = pd.to_datetime(df[col], errors="coerce")
                if s.notna().any():
                    return col, s

    return None, None


# ------------------------------------------------------------
# 2. KnowledgeC (/app/usage) parsing
# ------------------------------------------------------------
def parse_knowledgec(base_dir: Path) -> pd.DataFrame:
    """
    Convert KnowledgeC.db to KnowledgeC_parsed.sqlite, then
    extract only the /app/usage stream.
    """
    # 1. Search in base_dir
    candidates = list(base_dir.glob("KnowledgeC*.db"))

    # 2. If not found, search in ./data
    if not candidates and DATA_DIR.exists():
        print("[KC] KnowledgeC*.db was not found in base_dir; searching the data folder.")
        candidates = list(DATA_DIR.glob("KnowledgeC*.db"))

    if not candidates:
        print("[!] Could not find KnowledgeC*.db.")
        return pd.DataFrame()

    kc_db = None
    for c in candidates:
        if c.name == "KnowledgeC.db":
            kc_db = c
            break
    if kc_db is None:
        kc_db = candidates[0]

    # Create the output sqlite file in the same folder as the source DB
    out_db = kc_db.with_name("KnowledgeC_parsed.sqlite")
    print(f"[KC] Input DB: {kc_db}")
    print(f"[KC] Output sqlite: {out_db}")

    convert_and_write(kc_db, out_db)

    conn = sqlite3.connect(str(out_db))
    table = "events"  # Default table name created by kc_to_sqlite

    # Find the stream column
    cols = pd.read_sql_query(f"PRAGMA table_info({table});", conn)["name"].tolist()
    stream_col = None
    for c in cols:
        if "stream" in c.lower():
            stream_col = c
            break

    if stream_col is None:
        conn.close()
        print("[!] Could not find a stream-related column.")
        return pd.DataFrame()

    # Filter /app/usage events
    query = f"""
        SELECT *
        FROM {table}
        WHERE {stream_col} LIKE '%app/usage%'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"[KC] {table}.{stream_col} /app/usage events extracted from {len(df)}")

    if df.empty:
        return df

    # ---- Build Bundle ID ----
    bundle_source = None
    for c in df.columns:
        cl = c.lower()
        if "bundle" in cl and "id" in cl:
            bundle_source = c
            break

    df["Bundle ID"] = pd.NA

    if bundle_source is not None:
        df["Bundle ID"] = df[bundle_source]

    if "valuestring" in df.columns:
        df["Bundle ID"] = df["Bundle ID"].fillna(df["valuestring"])

    df["Bundle ID"] = df["Bundle ID"].astype(str).str.strip()
    df = df[df["Bundle ID"] != ""]
    print(f"[KC] /app/usage events with populated Bundle ID: {len(df)}")

    return df


# ------------------------------------------------------------
# 3. applicationState parsing
# ------------------------------------------------------------
def parse_appstate(base_dir: Path) -> pd.DataFrame:
    """
    Extract snapshot information from applicationState.db.
    """
    db_path = base_dir / "applicationState.db"
    if not db_path.exists():
        alt_path = DATA_DIR / "applicationState.db"
        if alt_path.exists():
            print("[APPSTATE] applicationState.db was not found in base_dir; using the DB in the data folder.")
            db_path = alt_path
        else:
            print("[!] Could not find applicationState.db.")
            return pd.DataFrame()

    print(f"[APPSTATE] Input DB: {db_path}")
    rows = extract_all_snapshots(db_path)
    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Exclude DEFAULT GROUP
    if "Snapshot Group" in df.columns:
        before = len(df)
        df = df[
            ~df["Snapshot Group"].str.contains(
                r"\{DEFAULT GROUP\}", case=False, na=False
            )
        ]
        print(
            f"[APPSTATE] DEFAULT GROUP excluded: {before - len(df)}rows removed, "
            f"remaining {len(df)}snapshots"
        )

    return df


# ------------------------------------------------------------
# 4. Map by application and generate HTML
# ------------------------------------------------------------
def build_html_by_app(
    base_dir: Path,
    kc_df: pd.DataFrame,
    appstate_df: pd.DataFrame,
    png_files,
    html_name: str,
):
    html_path = base_dir / html_name

    kc_grouped = defaultdict(lambda: pd.DataFrame())
    app_grouped = defaultdict(lambda: pd.DataFrame())

    # ---- KnowledgeC: group by Bundle ID ----
    if not kc_df.empty and "Bundle ID" in kc_df.columns:
        for b, group in kc_df.groupby("Bundle ID"):
            b_str = str(b).strip()
            if b_str:
                kc_grouped[b_str] = group

    # ---- applicationState: group by Bundle ID ----
    if not appstate_df.empty:
        bundle_col2 = "Bundle ID"
        if bundle_col2 not in appstate_df.columns:
            for c in appstate_df.columns:
                if "bundle" in c.lower():
                    bundle_col2 = c
                    break

        for b, group in appstate_df.groupby(bundle_col2):
            b_str = str(b).strip()
            if b_str:
                app_grouped[b_str] = group

    # ---- PNG files: map by Bundle ID in path ----
    png_map = defaultdict(list)
    for p in png_files:
        p_str = str(p)
        for b in set(list(kc_grouped.keys()) + list(app_grouped.keys())):
            if b and b in p_str:
                png_map[b].append(p)

    # ---- Generate HTML sections ----
    sections = []
    bundle_ids = sorted(set(list(kc_grouped.keys()) + list(app_grouped.keys())))

    for b in bundle_ids:
        sections.append(f"<h2>{b}</h2>")

        # ------ 1. KnowledgeC Events: calculate the latest end_kst_iso (or fallback) ------
        last_end_ts = None
        df1_display = None
        if not kc_grouped[b].empty:
            df1 = kc_grouped[b].copy()

            # Prefer end_kst_iso first,
            # and fall back to end_utc_iso / endDate only when needed
            end_col, end_series = find_datetime_series(
                df1,
                preferred_cols=["end_kst_iso", "end_utc_iso", "endDate", "end_date"],
                fallback_keywords=["end", "kst"],
            )
            if end_series is not None:
                last_end_ts = end_series.max()

            # Keep the display unchanged
            df1_display = df1
            html1 = df1_display.to_html(
                index=False, border=1, classes=["kc-table"], justify="center"
            )
            sections.append("<h3>KnowledgeC /app/usage Events</h3>" + html1)
        else:
            sections.append("<p><i>No /app/usage events are available for this application.</i></p>")

        # ------ 2. ApplicationState snapshots: apply color to creationDate ------
        if not app_grouped[b].empty:
            df2 = app_grouped[b].copy()

            # Find candidate creationDate columns, such as creation_utc_iso or creationDate
            creation_col, creation_series = find_datetime_series(
                df2,
                preferred_cols=[
                    "creation_utc_iso",
                    "creationDate",
                    "creation_date",
                    "snapshot_utc_iso",
                ],
                fallback_keywords=["creation"],
            )

            df2_display = df2.copy()

            if creation_col is not None and last_end_ts is not None:
                # Remove timezone information from the reference end time for a naive comparison
                last_end_ref = last_end_ts
                if getattr(last_end_ref, "tzinfo", None) is not None:
                    last_end_ref = last_end_ref.tz_localize(None)

                def color_creation(val):
                    ts = pd.to_datetime(val, errors="coerce")
                    if pd.isna(ts):
                        return val

                    # Remove timezone information when tz-aware
                    if getattr(ts, "tzinfo", None) is not None:
                        ts_local = ts.tz_localize(None)
                    else:
                        ts_local = ts

                    delta = abs((ts_local - last_end_ref).total_seconds())
                    if delta <= MATCH_THRESHOLD_SECONDS:
                        # Within 1 minute (60 seconds): blue
                        return f'<span style="color:blue;font-weight:bold">{val}</span>'
                    else:
                        # Larger differences: red
                        return f'<span style="color:red;font-weight:bold">{val}</span>'

                df2_display[creation_col] = (
                    df2_display[creation_col].astype(str).apply(color_creation)
                )

            html2 = df2_display.to_html(
                index=False,
                border=1,
                classes=["appstate-table"],
                justify="center",
                escape=False,  # Keep span HTML as-is
            )
            sections.append("<h3>ApplicationState Snapshots</h3>" + html2)
        else:
            if png_map[b]:
                sections.append(
                    "<p><i>No snapshot metadata is available from applicationState.db, "
                    "but snapshot images extracted from the file system are shown below.</i></p>"
                )
            else:
                sections.append("<p><i>No snapshot data is available.</i></p>")

        # ------ 3) Snapshot Images ------
        if png_map[b]:
            imgs = "".join(
                f'<figure><img src="{p.relative_to(base_dir)}" '
                f'width="240"><figcaption>{p.name}</figcaption></figure>'
                for p in png_map[b]
            )
            sections.append(
                "<h3>Snapshot Images</h3>"
                "<div class='snapshots'>" + imgs + "</div>"
            )

        sections.append("<hr>")

    # ---- Write final HTML ----
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>iOS Forensic Report - By Application</title>
<style>
body {{
  font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  margin:20px;
}}
h1 {{font-size:24px;margin-bottom:10px;}}
h2 {{margin-top:40px;color:#0a58ca;}}
h3 {{margin-top:20px;}}
hr {{margin-top:30px;border:0;border-top:1px solid #ccc;}}
.snapshots {{
  display:flex;flex-wrap:wrap;gap:12px;
}}
.snapshots figure {{text-align:center;width:240px;}}
.snapshots img {{max-width:100%;border:1px solid #aaa;}}
table {{font-size:12px;border-collapse:collapse;width:100%;}}
th,td {{border:1px solid #999;padding:3px 6px;white-space:nowrap;}}
th {{background:#f0f0f0;}}
</style>
</head>
<body>
<h1>iOS Forensic Report - By Application</h1>
<p>Base directory: {base_dir}</p>
{''.join(sections)}
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    print(f"[OK] Report generated -> {html_path}")


# ------------------------------------------------------------
# 5. Entry point
# ------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="iOS forensic report generator by application")
    ap.add_argument(
        "--dir",
        required=True,
        help="Target analysis folder path containing KTX snapshots, KnowledgeC.db, and applicationState.db",
    )
    ap.add_argument(
        "--html",
        default="ios_by_app.html",
        help="Output HTML filename (default: ios_by_app.html)",
    )
    args = ap.parse_args()

    base_dir = Path(args.dir).expanduser().resolve()

    png_files = run_ios_ktx2png_on_folder(base_dir)
    kc_df = parse_knowledgec(base_dir)
    app_df = parse_appstate(base_dir)
    build_html_by_app(base_dir, kc_df, app_df, png_files, args.html)


if __name__ == "__main__":
    main()


