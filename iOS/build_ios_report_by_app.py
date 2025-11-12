#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
📱 iOS Forensic Report Generator — Application별 리포트 버전

이 스크립트는 지정한 폴더에서:
1. 모든 하위 폴더의 .ktx 파일을 ios_ktx2png.exe로 PNG 변환
   (단, "{DEFAULT GROUP}" 폴더는 변환 대상에서 제외)
2. KnowledgeC.db → kc_to_sqlite.py 로 변환 후 /app/usage 이벤트 추출
3. applicationState.db → appstate_snapshots.py 로 스냅샷 정보 추출
4. 두 데이터의 Bundle ID를 기준으로 묶어 앱별 리포트 섹션 생성
   - 앱별 usage events (KnowledgeC)
   - 앱별 snapshot manifest (applicationState)
   - 해당 앱의 스냅샷 PNG 미리보기
"""

import argparse
import sqlite3
import subprocess
from pathlib import Path
from collections import defaultdict

import pandas as pd

from kc_to_sqlite import convert_and_write
from appstate_snapshots import extract_all_snapshots

# ------------------------------------------------------------
# 공통 경로 설정: 스크립트 위치 및 data 폴더
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


# ------------------------------------------------------------
# 1️⃣ KTX 변환
# ------------------------------------------------------------
def run_ios_ktx2png_on_folder(base_dir: Path, exe_name: str = "ios_ktx2png.exe"):
    exe_path = BASE_DIR / exe_name  # exe는 스크립트와 같은 폴더에 있다고 가정
    if not exe_path.exists():
        raise SystemExit(f"[!] {exe_name} 파일을 {BASE_DIR} 안에서 찾지 못했습니다.")

    ktx_files = sorted(base_dir.rglob("*.ktx"))
    png_files = []

    if not ktx_files:
        print("[!] KTX 파일이 없습니다.")
        return png_files

    for ktx in ktx_files:
        if "{DEFAULT GROUP}" in str(ktx.parent):
            print(f"[SKIP] {ktx} (DEFAULT GROUP 폴더 제외)")
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
            print(f"[ERROR] 변환 실패: {ktx} ({e})")

    print(f"[OK] 변환 완료: {len(png_files)}개 PNG 생성")
    return png_files


# ------------------------------------------------------------
# 2️⃣ KnowledgeC 분석 (/app/usage)
# ------------------------------------------------------------
def parse_knowledgec(base_dir: Path) -> pd.DataFrame:
    """
    KnowledgeC.db → KnowledgeC_parsed.sqlite 변환 후,
    events 테이블에서 stream LIKE '%app/usage%' 인 행만 추출.

    - 우선 base_dir에서 KnowledgeC*.db 검색
    - 없으면 스크립트 기준 ./data 폴더에서 검색
    - 변환된 sqlite는 원본 DB와 같은 폴더에 생성
    """
    # 1) base_dir에서 검색
    candidates = list(base_dir.glob("KnowledgeC*.db"))

    # 2) 없으면 ./data 에서 검색
    if not candidates and DATA_DIR.exists():
        print("[KC] base_dir 에서 KnowledgeC*.db 를 찾지 못해 data 폴더를 검색합니다.")
        candidates = list(DATA_DIR.glob("KnowledgeC*.db"))

    if not candidates:
        print("[!] KnowledgeC*.db 파일을 찾지 못했습니다.")
        return pd.DataFrame()

    kc_db = None
    for c in candidates:
        if c.name == "KnowledgeC.db":
            kc_db = c
            break
    if kc_db is None:
        kc_db = candidates[0]

    # 출력 sqlite는 원본 DB와 같은 폴더에 생성
    out_db = kc_db.with_name("KnowledgeC_parsed.sqlite")
    print(f"[KC] 입력 DB: {kc_db}")
    print(f"[KC] 출력 sqlite: {out_db}")

    convert_and_write(kc_db, out_db)

    conn = sqlite3.connect(str(out_db))

    table = "events"  # kc_to_sqlite 가 만들어주는 기본 테이블명

    # stream 컬럼 찾기
    cols = pd.read_sql_query(f"PRAGMA table_info({table});", conn)["name"].tolist()
    stream_col = None
    for c in cols:
        if "stream" in c.lower():
            stream_col = c
            break

    if stream_col is None:
        conn.close()
        print("[!] stream 관련 컬럼을 찾지 못했습니다.")
        return pd.DataFrame()

    # /app/usage 필터
    query = f"""
        SELECT *
        FROM {table}
        WHERE {stream_col} LIKE '%app/usage%'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"[KC] {table}.{stream_col}에서 app/usage 이벤트 {len(df)}개 추출")

    if df.empty:
        return df

    # ---- Bundle ID 만들기 ----
    # 1) bundle_id / ...bundle...id... 계열 컬럼 우선
    bundle_source = None
    for c in df.columns:
        cl = c.lower()
        if "bundle" in cl and "id" in cl:
            bundle_source = c
            break

    # 새 컬럼 초기화
    df["Bundle ID"] = pd.NA

    if bundle_source is not None:
        df["Bundle ID"] = df[bundle_source]

    # 2) valuestring 에 번들명이 들어있으면 거기서 채우기
    if "valuestring" in df.columns:
        df["Bundle ID"] = df["Bundle ID"].fillna(df["valuestring"])

    # 3) 완전히 비어 있는 행 제거
    df["Bundle ID"] = df["Bundle ID"].astype(str).str.strip()
    df = df[df["Bundle ID"] != ""]
    print(f"[KC] Bundle ID 채워진 app/usage 이벤트 {len(df)}개")

    return df


# ------------------------------------------------------------
# 3️⃣ applicationState 분석
# ------------------------------------------------------------
def parse_appstate(base_dir: Path) -> pd.DataFrame:
    """
    applicationState.db를 찾아 스냅샷 정보를 추출한다.

    - 우선 base_dir/applicationState.db 확인
    - 없으면 ./data/applicationState.db 사용
    """
    db_path = base_dir / "applicationState.db"
    if not db_path.exists():
        alt_path = DATA_DIR / "applicationState.db"
        if alt_path.exists():
            print("[APPSTATE] base_dir 에서 applicationState.db 를 찾지 못해 data 폴더의 DB를 사용합니다.")
            db_path = alt_path
        else:
            print("[!] applicationState.db를 찾을 수 없습니다.")
            return pd.DataFrame()

    print(f"[APPSTATE] 입력 DB: {db_path}")
    rows = extract_all_snapshots(db_path)
    df = pd.DataFrame(rows)

    if "Snapshot Group" in df.columns:
        before = len(df)
        df = df[
            ~df["Snapshot Group"].str.contains(
                r"\{DEFAULT GROUP\}", case=False, na=False
            )
        ]
        print(
            f"[APPSTATE] DEFAULT GROUP 제외: {before - len(df)}행 제거, "
            f"남은 {len(df)}개 스냅샷"
        )

    return df


# ------------------------------------------------------------
# 4️⃣ 앱별 매핑 후 HTML 생성
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

    # ---- KnowledgeC: Bundle ID 기준 그룹 ----
    if not kc_df.empty and "Bundle ID" in kc_df.columns:
        for b, group in kc_df.groupby("Bundle ID"):
            b_str = str(b).strip()
            if b_str:
                kc_grouped[b_str] = group

    # ---- applicationState: Bundle ID 기준 그룹 ----
    if not appstate_df.empty:
        bundle_col2 = "Bundle ID"
        if bundle_col2 not in appstate_df.columns:
            # 혹시라도 이름이 다를 경우 대비 (bundle 이 들어간 첫 컬럼)
            for c in appstate_df.columns:
                if "bundle" in c.lower():
                    bundle_col2 = c
                    break

        for b, group in appstate_df.groupby(bundle_col2):
            b_str = str(b).strip()
            if b_str:
                app_grouped[b_str] = group

    # ---- PNG 파일: 경로에 bundle 문자열이 들어있는 걸 묶기 ----
    png_map = defaultdict(list)
    for p in png_files:
        p_str = str(p)
        for b in set(list(kc_grouped.keys()) + list(app_grouped.keys())):
            if b and b in p_str:
                png_map[b].append(p)

    # ---- HTML 섹션 생성 ----
    sections = []
    bundle_ids = sorted(set(list(kc_grouped.keys()) + list(app_grouped.keys())))

    for b in bundle_ids:
        sections.append(f"<h2>{b}</h2>")

        # KnowledgeC Events
        if not kc_grouped[b].empty:
            df1 = kc_grouped[b]
            html1 = df1.to_html(
                index=False, border=1, classes=["kc-table"], justify="center"
            )
            sections.append("<h3>KnowledgeC.app/usage Events</h3>" + html1)
        else:
            sections.append("<p><i>해당 앱의 app/usage 이벤트 없음.</i></p>")

        # ApplicationState snapshots
        if not app_grouped[b].empty:
            df2 = app_grouped[b]
            html2 = df2.to_html(
                index=False, border=1, classes=["appstate-table"], justify="center"
            )
            sections.append("<h3>ApplicationState Snapshots</h3>" + html2)
        else:
            # 여기에서 PNG 유무에 따라 안내 문구를 다르게 표시
            if png_map[b]:
                sections.append(
                    "<p><i>applicationState.db 기준 스냅샷 메타데이터는 없지만, "
                    "파일 시스템에서 추출된 스냅샷 이미지는 아래에 표시됩니다.</i></p>"
                )
            else:
                sections.append("<p><i>스냅샷 데이터 없음.</i></p>")

        # PNG images
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

    # ---- 최종 HTML 작성 ----
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>iOS Forensic Report — Application별</title>
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
<h1>📱 iOS Forensic Report — Application별</h1>
<p>기준 폴더: {base_dir}</p>
{''.join(sections)}
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    print(f"[OK] 앱별 리포트 생성 완료 → {html_path}")


# ------------------------------------------------------------
# 5️⃣ 엔트리 포인트
# ------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="앱별 iOS Forensic 리포트 생성기")
    ap.add_argument(
        "--dir",
        required=True,
        help="분석 대상 폴더 경로 (KTX 스냅샷이 위치한 폴더)",
    )
    ap.add_argument(
        "--html",
        default="ios_by_app.html",
        help="출력 HTML 파일 이름 (기본: ios_by_app.html)",
    )
    args = ap.parse_args()

    base_dir = Path(args.dir).expanduser().resolve()

    png_files = run_ios_ktx2png_on_folder(base_dir)
    kc_df = parse_knowledgec(base_dir)
    app_df = parse_appstate(base_dir)
    build_html_by_app(base_dir, kc_df, app_df, png_files, args.html)


if __name__ == "__main__":
    main()
