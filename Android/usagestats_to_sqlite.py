# usagestats_to_sqlite.py
# 입력: ./data/usagestats
# 출력: ./data/usagestats_parsed.sqlite
# 참고: ./protobuf/ 폴더에 usagestatsservice_pb2.py, usagestatsservice_v2_pb2.py 등 형제 pb2 파일이 있어야 합니다.
#       (google.protobuf 런타임이 없으면 v2는 스킵하고 XML/v1만 처리합니다)

import os
import sys
import glob
import json
import sqlite3
import xml.etree.ElementTree as ET
from enum import IntEnum

# -----------------------------
# 경로/패키지 설정 (import 문제 방지)
# -----------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
USAGESTATS_ROOT = os.path.join(DATA_DIR, "usagestats")
DB_PATH = os.path.join(DATA_DIR, "usagestats_parsed.sqlite")

PROTO_DIR = os.path.join(SCRIPT_DIR, "protobuf")

# sys.path에 프로젝트/프로토 경로 우선 등록
for p in (SCRIPT_DIR, PROTO_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# 'protobuf' 로컬 폴더를 패키지로 강제 등록 (상대임포트 보호)
if "protobuf" not in sys.modules:
    import types
    pkg = types.ModuleType("protobuf")
    pkg.__path__ = [PROTO_DIR]  # 패키지 경로로 인식
    sys.modules["protobuf"] = pkg

# google.protobuf 런타임 존재 확인
_HAVE_GOOGLE = True
try:
    import google.protobuf  # noqa: F401
except Exception as _e:
    _HAVE_GOOGLE = False
    print("[WARN] google.protobuf 런타임이 없어 v2 파싱은 건너뜁니다. (XML/v1은 계속 처리)")

# pb2 모듈 로드 (런타임 없으면 실패 → None)
try:
    import protobuf.usagestatsservice_pb2 as usagestatsservice_pb2  # v1
except Exception as e:
    usagestatsservice_pb2 = None
    print("[WARN] usagestatsservice_pb2 로드 실패:", e)

try:
    import protobuf.usagestatsservice_v2_pb2 as usagestatsservice_v2_pb2  # v2
except Exception as e:
    usagestatsservice_v2_pb2 = None
    if _HAVE_GOOGLE:
        print("[WARN] usagestatsservice_v2_pb2 로드 실패:", e)
    else:
        # 위에서 이미 런타임 경고 출력했으니 추가 메시지는 생략 가능
        pass


# -----------------------------
# 공통 정의
# -----------------------------
class EventType(IntEnum):
    NONE = 0
    ACTIVITY_RESUMED = 1          # MOVE_TO_FOREGROUND
    ACTIVITY_PAUSED = 2           # MOVE_TO_BACKGROUND
    END_OF_DAY = 3
    CONTINUE_PREVIOUS_DAY = 4
    CONFIGURATION_CHANGE = 5
    SYSTEM_INTERACTION = 6
    USER_INTERACTION = 7
    SHORTCUT_INVOCATION = 8
    CHOOSER_ACTION = 9
    NOTIFICATION_SEEN = 10
    STANDBY_BUCKET_CHANGED = 11
    NOTIFICATION_INTERRUPTION = 12
    SLICE_PINNED_PRIV = 13
    SLICE_PINNED = 14
    SCREEN_INTERACTIVE = 15
    SCREEN_NON_INTERACTIVE = 16
    KEYGUARD_SHOWN = 17
    KEYGUARD_HIDDEN = 18
    FOREGROUND_SERVICE_START = 19
    FOREGROUND_SERVICE_STOP = 20
    CONTINUING_FOREGROUND_SERVICE = 21
    ROLLOVER_FOREGROUND_SERVICE = 22
    ACTIVITY_STOPPED = 23
    ACTIVITY_DESTROYED = 24
    FLUSH_TO_DISK = 25
    DEVICE_SHUTDOWN = 26
    DEVICE_STARTUP = 27
    USER_UNLOCKED = 28
    USER_STOPPED = 29
    LOCUS_ID_SET = 30

    def __str__(self):
        return self.name


def _get_string_by_token(packages_map, token1, token2=0):
    """v2: package_token / class_token -> 문자열"""
    strings = packages_map.get(token1)
    if not strings:
        return ""
    if token2 == 0:
        return strings[0]
    if 0 < token2 <= len(strings):
        return strings[token2 - 1]
    return ""


# -----------------------------
# DB
# -----------------------------
def init_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE data(
            usage_type TEXT,
            lastime INTEGER,
            timeactive INTEGER,
            last_time_service_used INTEGER,
            last_time_visible INTEGER,
            total_time_visible INTEGER,
            app_launch_count INTEGER,
            package TEXT,
            types TEXT,
            classs TEXT,
            source TEXT,
            fullatt TEXT
        )
        """
    )
    db.commit()
    return db


# -----------------------------
# v1(XML/protobuf) 파싱
# -----------------------------
def _read_pb_v1(path: str):
    if usagestatsservice_pb2 is None:
        raise RuntimeError("v1 protobuf 모듈(usagestatsservice_pb2)을 로드하지 못했습니다.")
    msg = usagestatsservice_pb2.IntervalStatsProto()
    with open(path, "rb") as f:
        msg.ParseFromString(f.read())
    return msg


def _add_v1_to_db(sourced: str, base_epoch: int, stats, db: sqlite3.Connection):
    cur = db.cursor()
    pool = list(getattr(stats, "stringpool").strings)

    # packages
    for rec in stats.packages:
        finalt = ""
        if rec.HasField("last_time_active_ms"):
            t = rec.last_time_active_ms
            finalt = abs(t) if t < 0 else t + base_epoch

        tac = ""
        if rec.HasField("total_time_active_ms"):
            tac = abs(rec.total_time_active_ms)

        pkg = ""
        idx = getattr(rec, "package_index", 0)
        if 0 < idx <= len(pool):
            pkg = pool[idx - 1]

        alc = ""
        if rec.HasField("app_launch_count"):
            alc = abs(rec.app_launch_count)

        cur.execute(
            """
            INSERT INTO data
            (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
             total_time_visible,app_launch_count,package,types,classs,source,fullatt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("packages", finalt, tac, "", "", "", alc, pkg, "", "", sourced, ""),
        )

    # configurations
    for conf in stats.configurations:
        finalt = ""
        if conf.HasField("last_time_active_ms"):
            t = conf.last_time_active_ms
            finalt = abs(t) if t < 0 else t + base_epoch

        tac = ""
        if conf.HasField("total_time_active_ms"):
            tac = abs(conf.total_time_active_ms)

        cur.execute(
            """
            INSERT INTO data
            (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
             total_time_visible,app_launch_count,package,types,classs,source,fullatt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("configurations", finalt, tac, "", "", "", "", "", "", "", sourced, str(conf.config)),
        )

    # event-log
    for ev in stats.event_log:
        finalt = ""
        if ev.HasField("time_ms"):
            t = ev.time_ms
            finalt = abs(t) if t < 0 else t + base_epoch

        pkg = ""
        classy = ""
        if ev.HasField("package_index"):
            idx = ev.package_index
            if 0 < idx <= len(pool):
                pkg = pool[idx - 1]
        if ev.HasField("class_index"):
            idx = ev.class_index
            if 0 < idx <= len(pool):
                classy = pool[idx - 1]

        tipes = ""
        if ev.HasField("type"):
            tipes = str(EventType(ev.type)) if ev.type <= max(EventType).value else str(ev.type)

        cur.execute(
            """
            INSERT INTO data
            (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
             total_time_visible,app_launch_count,package,types,classs,source,fullatt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("event-log", finalt, "", "", "", "", "", pkg, tipes, classy, sourced, ""),
        )

    db.commit()


def _parse_xml_or_v1_dir(root_dir: str, db: sqlite3.Connection):
    for fp in glob.iglob(os.path.join(root_dir, "**"), recursive=True):
        if not os.path.isfile(fp):
            continue

        name = os.path.basename(fp)
        if name == "version":
            continue

        # source 구분
        if "daily" in fp:
            src = "daily"
        elif "weekly" in fp:
            src = "weekly"
        elif "monthly" in fp:
            src = "monthly"
        elif "yearly" in fp:
            src = "yearly"
        else:
            src = ""

        try:
            base_epoch = int(name)
        except Exception:
            print("[WARN] 파일명이 타임스탬프 형식이 아님:", fp)
            continue

        # XML 여부 판별
        try:
            ET.parse(fp)
            is_xml = True
        except ET.ParseError:
            is_xml = False

        if not is_xml:
            # v1 protobuf 시도
            try:
                stats = _read_pb_v1(fp)
            except Exception:
                print("[WARN] XML도 아니고 v1 protobuf도 아님 → 스킵:", fp)
                continue
            print("[V1 PB] 처리:", fp)
            _add_v1_to_db(src, base_epoch, stats, db)
            continue

        # XML 처리
        tree = ET.parse(fp)
        root = tree.getroot()
        print("[XML] 처리:", fp)
        cur = db.cursor()

        for elem in root:
            tag = elem.tag

            if tag == "packages":
                for sub in elem:
                    fullatt = json.dumps(sub.attrib)
                    t = int(sub.attrib["lastTimeActive"])
                    finalt = abs(t) if t < 0 else int(base_epoch + t)
                    pkg = sub.attrib.get("package", "")
                    tac = sub.attrib.get("timeActive", "")
                    alc = sub.attrib.get("appLaunchCount", "")
                    cur.execute(
                        """
                        INSERT INTO data
                        (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
                         total_time_visible,app_launch_count,package,types,classs,source,fullatt)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (tag, finalt, tac, "", "", "", alc, pkg, "", "", src, fullatt),
                    )

            elif tag == "configurations":
                for sub in elem:
                    fullatt = json.dumps(sub.attrib)
                    t = int(sub.attrib["lastTimeActive"])
                    finalt = abs(t) if t < 0 else int(base_epoch + t)
                    tac = sub.attrib.get("timeActive", "")
                    cur.execute(
                        """
                        INSERT INTO data
                        (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
                         total_time_visible,app_launch_count,package,types,classs,source,fullatt)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (tag, finalt, tac, "", "", "", "", "", "", "", src, fullatt),
                    )

            elif tag == "event-log":
                for sub in elem:
                    t = int(sub.attrib["time"])
                    finalt = abs(t) if t < 0 else int(base_epoch + t)
                    pkg = sub.attrib.get("package", "")
                    tipes = sub.attrib.get("type", "")
                    classy = sub.attrib.get("class", "")
                    fullatt = json.dumps(sub.attrib)
                    cur.execute(
                        """
                        INSERT INTO data
                        (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
                         total_time_visible,app_launch_count,package,types,classs,source,fullatt)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (tag, finalt, "", "", "", "", "", pkg, tipes, classy, src, fullatt),
                    )

        db.commit()


# -----------------------------
# v2 파싱
# -----------------------------
def _read_pb_v2(path: str):
    if usagestatsservice_v2_pb2 is None:
        raise RuntimeError("v2 protobuf 모듈(usagestatsservice_v2_pb2)을 로드하지 못했습니다.")
    msg = usagestatsservice_v2_pb2.IntervalStatsObfuscatedProto()
    with open(path, "rb") as f:
        msg.ParseFromString(f.read())
    return msg


def _add_v2_to_db(sourced: str, base_epoch: int, stats_ob, db: sqlite3.Connection, packages_map: dict):
    cur = db.cursor()

    # packages
    for rec in stats_ob.packages:
        finalt = ""
        if rec.HasField("last_time_active_ms"):
            t = rec.last_time_active_ms
            finalt = abs(t) if t < 0 else t + base_epoch

        tac = ""
        if rec.HasField("total_time_active_ms"):
            tac = abs(rec.total_time_active_ms)

        pkg = _get_string_by_token(packages_map, rec.package_token)

        alc = ""
        if rec.HasField("app_launch_count"):
            alc = abs(rec.app_launch_count)

        cur.execute(
            """
            INSERT INTO data
            (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
             total_time_visible,app_launch_count,package,types,classs,source,fullatt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("packages", finalt, tac, "", "", "", alc, pkg, "", "", sourced, ""),
        )

    # configurations
    for conf in stats_ob.configurations:
        finalt = ""
        if conf.HasField("last_time_active_ms"):
            t = conf.last_time_active_ms
            finalt = abs(t) if t < 0 else t + base_epoch

        tac = ""
        if conf.HasField("total_time_active_ms"):
            tac = abs(conf.total_time_active_ms)

        cur.execute(
            """
            INSERT INTO data
            (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
             total_time_visible,app_launch_count,package,types,classs,source,fullatt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("configurations", finalt, tac, "", "", "", "", "", "", "", sourced, str(conf.config)),
        )

    # event-log
    for ev in stats_ob.event_log:
        finalt = ""
        if ev.HasField("time_ms"):
            t = ev.time_ms
            finalt = abs(t) if t < 0 else t + base_epoch

        pkg = ""
        classy = ""
        if ev.HasField("package_token"):
            pkg = _get_string_by_token(packages_map, ev.package_token)
        if ev.HasField("class_token"):
            classy = _get_string_by_token(packages_map, ev.package_token, ev.class_token)

        tipes = ""
        if ev.HasField("type"):
            tipes = str(EventType(ev.type)) if ev.type <= max(EventType).value else str(ev.type)

        cur.execute(
            """
            INSERT INTO data
            (usage_type,lastime,timeactive,last_time_service_used,last_time_visible,
             total_time_visible,app_launch_count,package,types,classs,source,fullatt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("event-log", finalt, "", "", "", "", "", pkg, tipes, classy, sourced, ""),
        )

    db.commit()


def _parse_v2_dir(root_dir: str, db: sqlite3.Connection):
    if usagestatsservice_v2_pb2 is None:
        print("[WARN] v2 protobuf 모듈이 없어 v2 폴더를 건너뜁니다.")
        return

    mappings_path = os.path.join(root_dir, "mappings")
    if not os.path.exists(mappings_path):
        print("[WARN] mappings 파일이 없어 v2 폴더로 보이지 않습니다:", root_dir)
        return

    # mappings 로드 → 토큰→문자열 매핑
    mappings = usagestatsservice_v2_pb2.ObfuscatedPackagesProto()
    with open(mappings_path, "rb") as f:
        mappings.ParseFromString(f.read())

    packages_map = {}
    for pkg in mappings.packages_map:
        if pkg.HasField("package_token"):
            packages_map[pkg.package_token] = list(pkg.strings)

    # 실제 데이터 파일들
    for fp in glob.iglob(os.path.join(root_dir, "**"), recursive=True):
        if not os.path.isfile(fp):
            continue

        name = os.path.basename(fp)
        if name in ("version", "migrated", "mappings"):
            continue

        # source 구분
        if "daily" in fp:
            src = "daily"
        elif "weekly" in fp:
            src = "weekly"
        elif "monthly" in fp:
            src = "monthly"
        elif "yearly" in fp:
            src = "yearly"
        else:
            src = ""

        try:
            base_epoch = int(name)
        except Exception:
            print("[WARN] 파일명이 타임스탬프 형식이 아님:", fp)
            continue

        try:
            stats_ob = _read_pb_v2(fp)
        except Exception as e:
            print("[WARN] v2 protobuf 파싱 실패:", fp, ":", e)
            continue

        print("[V2 PB] 처리:", fp)
        _add_v2_to_db(src, base_epoch, stats_ob, db, packages_map)


# -----------------------------
# 메인
# -----------------------------
def main():
    if not os.path.isdir(USAGESTATS_ROOT):
        print("[ERROR] 'data/usagestats' 폴더를 찾지 못했습니다:", USAGESTATS_ROOT)
        return

    db = init_db(DB_PATH)

    roots = []

    # 1) data/usagestats 바로 아래가 v1/Xml 구조이거나 mappings가 있으면 루트로 사용
    if any(
        os.path.isdir(os.path.join(USAGESTATS_ROOT, d))
        for d in ("daily", "weekly", "monthly", "yearly")
    ) or os.path.exists(os.path.join(USAGESTATS_ROOT, "mappings")):
        roots.append(USAGESTATS_ROOT)

    # 2) 숫자(UID) 하위 폴더도 루트로 사용
    for name in os.listdir(USAGESTATS_ROOT):
        full = os.path.join(USAGESTATS_ROOT, name)
        if os.path.isdir(full) and name.isdigit():
            roots.append(full)

    if not roots:
        print("[ERROR] usagestats 폴더 구조를 인식하지 못했습니다.")
        db.close()
        return

    for root in roots:
        print("\n=== 폴더 처리 중:", root, "===")
        if os.path.exists(os.path.join(root, "mappings")):
            _parse_v2_dir(root, db)
        else:
            _parse_xml_or_v1_dir(root, db)

    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM data")
    total = cur.fetchone()[0]
    db.close()

    print("\n[OK] 변환 완료. 총 레코드 수:", total)
    print("[OK] SQLite 파일:", DB_PATH)


if __name__ == "__main__":
    main()
