#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
applicationState.db 에서 iOS 스냅샷 정보를 추출해서
다음 컬럼을 가진 테이블을 생성한다.

- Creation Date (KST 기준)
- Bundle ID
- Snapshot Group
- Relative Path   (예: BE8A66F3-...@3x.ktx)
- Snapshot Index  (0,1,2,...)

사용 예:
    # 1) 기본값 사용 (./data/applicationState.db → ./data/appstate_snapshots.csv)
    python appstate_snapshots.py

    # 2) 다른 위치에 있는 DB/CSV 사용 시
    python appstate_snapshots.py --db "D:\\DF\\applicationState.db" --out "D:\\DF\\snapshots.csv"
"""

import argparse
import sqlite3
import plistlib
from plistlib import UID
from datetime import datetime, timedelta
from pathlib import Path
import csv


COCOA_EPOCH = datetime(2001, 1, 1)  # 2001-01-01 00:00:00 UTC 기준
LOCAL_OFFSET_HOURS = 9              # KST 로 보고 싶으면 9, UTC로만 보고 싶으면 0

# ★ 새로 추가된 부분: 현재 스크립트 기준 기본 경로 설정
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "applicationState.db"
DEFAULT_OUT_PATH = DATA_DIR / "appstate_snapshots.csv"


def decode_snapshot_manifest_blob(blob: bytes):
    """
    kvs.value 에 들어있는 NSKeyedArchiver bplist (XBApplicationSnapshotManifest) 를 파싱해서
    하나의 앱에 대한 스냅샷 목록을 리스트로 리턴한다.

    리턴 형식: [
        {
            "creation_date_local": str,
            "snapshot_group": str,
            "relative_path": str,
            "snapshot_index": int,
        },
        ...
    ]
    """
    # 1) bplist 디코드 (중첩 bplist 대응: 한 번 더 bplist00 이 나오면 한 번 더 loads)
    inner = plistlib.loads(blob)
    if isinstance(inner, (bytes, bytearray)) and inner.startswith(b"bplist00"):
        archive = plistlib.loads(inner)
    else:
        archive = inner

    objects = archive["$objects"]
    top = archive["$top"]

    root_uid = top["root"]
    if not isinstance(root_uid, UID):
        raise ValueError("unexpected root UID type")

    root = objects[root_uid.data]

    # 루트 객체 안에 snapshots 딕셔너리 있음
    snapshots_uid = root["snapshots"]
    snapshots_dict = objects[snapshots_uid.data]

    keys = snapshots_dict["NS.keys"]       # 각 그룹 이름 (UID 리스트)
    vals = snapshots_dict["NS.objects"]    # 각 그룹에 대한 스냅샷 리스트 (UID 리스트)

    rows = []
    offset = timedelta(hours=LOCAL_OFFSET_HOURS)

    for key_uid, val_uid in zip(keys, vals):
        group_name = objects[key_uid.data]            # 예: "sceneID:ph.telegra.Telegraph-default"
        group_obj = objects[val_uid.data]             # {'identifier': ..., 'snapshots': UID(...)}
        snaplist_uid = group_obj["snapshots"]
        snaplist = objects[snaplist_uid.data]["NS.objects"]  # 스냅샷 객체 UID 리스트

        for idx, snap_uid in enumerate(snaplist):
            snap = objects[snap_uid.data]

            # creationDate → {'NS.time': float}
            creation_dt_str = ""
            cd_uid = snap.get("creationDate")
            if isinstance(cd_uid, UID):
                cd_obj = objects[cd_uid.data]
                sec = cd_obj.get("NS.time")
                if isinstance(sec, (int, float)):
                    utc_dt = COCOA_EPOCH + timedelta(seconds=sec)
                    local_dt = utc_dt + offset
                    # 엑셀/판다스에서 보기 좋은 포맷
                    creation_dt_str = local_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            # relativePath → '*.ktx'
            rel_path = ""
            rel_uid = snap.get("relativePath")
            if isinstance(rel_uid, UID):
                rel_path = objects[rel_uid.data]

            rows.append(
                {
                    "creation_date_local": creation_dt_str,
                    "snapshot_group": group_name,
                    "relative_path": rel_path,
                    "snapshot_index": idx,
                }
            )

    return rows


def extract_all_snapshots(db_path: Path):
    """
    applicationState.db 전체에서 'XBApplicationSnapshotManifest' 항목을 찾아
    모든 앱의 스냅샷 정보를 추출한다.

    반환 형식: [
        {
            "Creation Date": str,
            "Bundle ID": str,
            "Snapshot Group": str,
            "Relative Path": str,
            "Snapshot Index": int,
        },
        ...
    ]
    """
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # 1) key_tab 에서 'XBApplicationSnapshotManifest' 키 id 찾기
    cur.execute("SELECT id FROM key_tab WHERE key='XBApplicationSnapshotManifest';")
    row = cur.fetchone()
    if not row:
        con.close()
        raise SystemExit("[!] key_tab 에 XBApplicationSnapshotManifest 키가 없습니다.")
    manifest_key_id = row[0]

    # 2) kvs + application_identifier_tab 조인
    query = """
        SELECT
            kvs.value,                              -- NSKeyedArchiver bplist blob
            application_identifier_tab.application_identifier AS bundle_id
        FROM kvs
        JOIN application_identifier_tab
          ON kvs.application_identifier = application_identifier_tab.id
        WHERE kvs.key = ?
    """
    cur.execute(query, (manifest_key_id,))

    all_rows = []

    for value_blob, bundle_id in cur.fetchall():
        try:
            # decode_snapshot_manifest_blob() 은 이미 위에서 정의되어 있음
            snaps = decode_snapshot_manifest_blob(value_blob)
        except Exception as e:
            print(f"[WARN] {bundle_id} 스냅샷 디코딩 실패: {e}")
            continue

        for snap in snaps:
            all_rows.append(
                {
                    "Creation Date": snap["creation_date_local"],
                    "Bundle ID": bundle_id,
                    "Snapshot Group": snap["snapshot_group"],
                    "Relative Path": snap["relative_path"],
                    "Snapshot Index": snap["snapshot_index"],
                }
            )

    con.close()

    # 3) 정렬 (시간 → Bundle ID → 그룹 → 인덱스 순)
    all_rows.sort(
        key=lambda r: (
            r["Creation Date"],
            r["Bundle ID"],
            r["Snapshot Group"],
            r["Snapshot Index"],
        )
    )

    return all_rows


def write_csv(rows, out_path: Path):
    if not rows:
        print("[!] 출력할 행이 없습니다.")
        return

    # 출력 폴더가 없으면 생성 (특히 ./data 사용 시)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["Creation Date", "Bundle ID", "Snapshot Group", "Relative Path", "Snapshot Index"]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"[+] CSV 저장 완료: {out_path}")


def main():
    ap = argparse.ArgumentParser(description="applicationState.db 에서 스냅샷 정보 추출")
    ap.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"applicationState.db 경로 (기본값: {DEFAULT_DB_PATH})",
    )
    ap.add_argument(
        "--out",
        default=str(DEFAULT_OUT_PATH),
        help=f"결과 CSV 파일 경로 (기본값: {DEFAULT_OUT_PATH})",
    )
    args = ap.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    if not db_path.exists():
        raise SystemExit(f"[!] applicationState.db 를 찾을 수 없습니다: {db_path}")

    rows = extract_all_snapshots(db_path)
    write_csv(rows, out_path)


if __name__ == "__main__":
    main()
