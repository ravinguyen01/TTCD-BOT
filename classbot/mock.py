"""Offline acceptance fixture for the class bot. No Discord or Google credentials needed."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL,
    uid TEXT NOT NULL, username TEXT NOT NULL, display_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(class_id, uid)
);
CREATE TABLE IF NOT EXISTS attendance (
    class_id INTEGER NOT NULL, enrollment_id INTEGER NOT NULL,
    class_date TEXT NOT NULL, present INTEGER NOT NULL,
    PRIMARY KEY(class_id, enrollment_id, class_date)
);
CREATE TABLE IF NOT EXISTS point_transactions (
    interaction_id TEXT PRIMARY KEY, class_id INTEGER NOT NULL,
    enrollment_id INTEGER NOT NULL, class_date TEXT NOT NULL,
    points INTEGER NOT NULL, actor_uid TEXT NOT NULL
);
"""


def today():
    return datetime.now(timezone(timedelta(hours=7))).date().isoformat()


class MockStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if 'active' not in {row['name'] for row in self.db.execute('PRAGMA table_info(enrollments)')}:
            self.db.execute('ALTER TABLE enrollments ADD COLUMN active INTEGER NOT NULL DEFAULT 1')

    def class_id(self, code):
        row = self.db.execute("SELECT id FROM classes WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise ValueError(f"Không tìm thấy lớp: {code}")
        return row["id"]

    def add_class(self, code):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO classes(code) VALUES (?)", (code,))

    def roster(self, code, members):
        class_id = self.class_id(code)
        with self.db:
            self.db.execute('UPDATE enrollments SET active = 0 WHERE class_id = ?', (class_id,))
            for member in members:
                self.db.execute("""
                    INSERT INTO enrollments(class_id, uid, username, display_name, active)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(class_id, uid) DO UPDATE SET
                      username = excluded.username,
                      display_name = excluded.display_name,
                      active = 1
                """, (class_id, str(member["uid"]), member["username"],
                      member.get("full_name") or member.get('display_name') or member["username"]))

    def attendance(self, code, voice_uids, class_date):
        class_id = self.class_id(code)
        voice = set(map(str, voice_uids))
        rows = self.db.execute(
            "SELECT id, uid FROM enrollments WHERE class_id = ? AND active = 1", (class_id,)
        ).fetchall()
        with self.db:
            self.db.executemany(
                """INSERT INTO attendance VALUES (?, ?, ?, ?)
                   ON CONFLICT(class_id,enrollment_id,class_date) DO UPDATE SET present=excluded.present""",
                [(class_id, row["id"], class_date, int(row["uid"] in voice))
                 for row in rows],
            )
        return True

    def add_points(self, code, uid, points, actor_uid, interaction_id, class_date):
        class_id = self.class_id(code)
        row = self.db.execute(
            "SELECT id FROM enrollments WHERE class_id = ? AND uid = ? AND active = 1",
            (class_id, str(uid)),
        ).fetchone()
        if row is None:
            raise ValueError(f"Học viên {uid} không ở trong lớp {code}")
        with self.db:
            cursor = self.db.execute("""
                INSERT OR IGNORE INTO point_transactions
                  (interaction_id, class_id, enrollment_id, class_date, points, actor_uid)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(interaction_id), class_id, row["id"], class_date,
                  points, str(actor_uid)))
        return cursor.rowcount == 1

    def report(self, code, class_date):
        class_id = self.class_id(code)
        rows = self.db.execute("""
            SELECT e.uid, e.username, e.display_name,
                   CASE WHEN a.present = 1 THEN 'Có mặt'
                        WHEN a.present = 0 THEN 'Vắng' ELSE NULL END AS attendance,
                   (SELECT SUM(p.points) FROM point_transactions p
                    WHERE p.enrollment_id = e.id AND p.class_date = ?) AS points
            FROM enrollments e
            LEFT JOIN attendance a ON a.enrollment_id = e.id AND a.class_date = ?
            WHERE e.class_id = ? AND e.active = 1 ORDER BY e.id
        """, (class_date, class_date, class_id)).fetchall()
        return [dict(row) for row in rows]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Chạy thử bot lớp học bằng dữ liệu giả")
    parser.add_argument("--db", default="mock.sqlite3", help="File dữ liệu thử")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo")
    report = sub.add_parser("report")
    report.add_argument("code")
    report.add_argument("--date", default=today())
    args = parser.parse_args()
    store = MockStore(Path(args.db))
    if args.command == "demo":
        store.add_class("LOP_MAU_01")
        store.roster("LOP_MAU_01", [
            {"uid": "101", "username": "minh-an", "full_name": "Nguyễn Minh An"},
            {"uid": "102", "username": "linh-hoc"},
        ])
        store.attendance("LOP_MAU_01", ["101"], today())
        store.add_points("LOP_MAU_01", "101", 2, "900", "demo-1", today())
        store.add_points("LOP_MAU_01", "101", 3, "900", "demo-2", today())
        print(json.dumps(store.report("LOP_MAU_01", today()), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(store.report(args.code, args.date), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
