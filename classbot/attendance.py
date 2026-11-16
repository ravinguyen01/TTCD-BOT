"""Refresh today's voice attendance; preserve other dates and point transactions."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import gspread

from classbot.roster import roster_header


def class_day():
    return datetime.now(timezone(timedelta(hours=7))).date()


def column_name(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def attendance_formats(letter, rows):
    colors = {
        True: {"red": 0.72, "green": 0.88, "blue": 0.70},
        False: {"red": 0.96, "green": 0.72, "blue": 0.72},
        None: {"red": 1.0, "green": 1.0, "blue": 1.0},
    }
    formats = []
    start = 2
    current = None
    for row_number, row in enumerate(rows, start=2):
        state = row["present"]
        if row_number > 2 and state != current:
            formats.append({
                "range": f"{letter}{start}:{letter}{row_number - 1}",
                "format": {"backgroundColor": colors[current]},
            })
            start = row_number
        current = state
    if rows:
        formats.append({
            "range": f"{letter}{start}:{letter}{len(rows) + 1}",
            "format": {"backgroundColor": colors[current]},
        })
    return formats


async def load_daily_report(pool, *, class_id, day):
    """Project saved attendance and points into one daily column."""
    async with pool.acquire() as conn:
        class_row = await conn.fetchrow("""
            SELECT c.id, c.spreadsheet_id, c.attendance_sheet_id, s.data_version
            FROM classes c JOIN sheet_sync s ON s.class_id = c.id
            WHERE c.id = $1
        """, class_id)
        if class_row is None:
            raise ValueError("Không tìm thấy lớp")
        rows = await conn.fetch("""
            SELECT e.discord_uid, e.discord_username, e.discord_display_name, e.display_name,
                   a.present,
                   COALESCE(p.total, 0) + COALESCE(r.total, 0) AS total,
                   COALESCE(p.n, 0) + COALESCE(r.n, 0) AS transactions
            FROM enrollments e
            LEFT JOIN attendance a ON a.enrollment_id = e.id
                AND a.class_id = e.class_id AND a.class_date = $2
            LEFT JOIN LATERAL (
                SELECT SUM(points) AS total, COUNT(*) AS n
                FROM point_transactions
                WHERE enrollment_id = e.id AND class_date = $2
            ) p ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(points) AS total, COUNT(*) AS n
                FROM reaction_awards
                WHERE enrollment_id = e.id AND class_date = $2
            ) r ON TRUE
            WHERE e.class_id = $1 AND e.active=TRUE ORDER BY e.id
        """, class_id, day)
    return {
        "class_id": class_id,
        "spreadsheet_id": class_row["spreadsheet_id"],
        "sheet_id": class_row["attendance_sheet_id"],
        "version": class_row["data_version"],
        "rows": [dict(row) for row in rows],
        "day": day.isoformat(),
    }


async def has_attendance(pool, *, guild_id, role_id, day):
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM classes c
                JOIN attendance a ON a.class_id = c.id
                WHERE c.guild_id = $1 AND c.class_role_id = $2 AND a.class_date = $3
            )
        """, guild_id, role_id, day)


async def record_attendance(pool, *, guild_id, role_id, voice_uids, day):
    voice_uids = set(voice_uids)
    async with pool.acquire() as conn:
        async with conn.transaction():
            class_row = await conn.fetchrow("""
                SELECT id, class_code, spreadsheet_id, attendance_sheet_id
                FROM classes WHERE guild_id = $1 AND class_role_id = $2
                FOR UPDATE
            """, guild_id, role_id)
            if class_row is None:
                return None
            class_id = class_row["id"]
            roster = await conn.fetch("""
                SELECT id, discord_uid, discord_username, display_name
                FROM enrollments WHERE class_id = $1 AND active = TRUE ORDER BY id
            """, class_id)
            existing = await conn.fetchval("""
                SELECT EXISTS(SELECT 1 FROM attendance
                              WHERE class_id = $1 AND class_date = $2)
            """, class_id, day)
            linked = await conn.fetch('''SELECT primary_uid FROM account_links
                WHERE guild_id=$1 AND secondary_uid=ANY($2::bigint[])''', guild_id, list(voice_uids))
            voice_uids.update(row['primary_uid'] for row in linked)
            if roster:
                await conn.executemany("""
                    INSERT INTO attendance(class_id, enrollment_id, class_date, present)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (class_id,enrollment_id,class_date) DO UPDATE SET
                        present=EXCLUDED.present, captured_at=now()
                """, [(class_id, row["id"], day,
                       row["discord_uid"] in voice_uids) for row in roster])
            await conn.execute("""
                UPDATE sheet_sync SET data_version = data_version + 1
                WHERE class_id = $1
            """, class_id)
            records = await conn.fetch("""
                SELECT e.discord_uid, e.discord_username, e.discord_display_name, e.display_name,
                       e.active, a.present
                FROM enrollments e
                LEFT JOIN attendance a ON a.enrollment_id = e.id AND a.class_date = $2
                WHERE e.class_id = $1 AND e.active=TRUE
                ORDER BY e.id
            """, class_id, day)
            version = await conn.fetchval(
                "SELECT data_version FROM sheet_sync WHERE class_id = $1", class_id
            )
    return {
        "class_id": class_id,
        "code": class_row["class_code"],
        "spreadsheet_id": class_row["spreadsheet_id"],
        "sheet_id": class_row["attendance_sheet_id"],
        "version": version,
        "already": existing,
        "rows": [dict(row) for row in records],
        "day": day.isoformat(),
    }


def write_attendance_sheet(credentials_path, saved):
    spreadsheet = gspread.service_account(filename=credentials_path).open_by_key(
        saved["spreadsheet_id"]
    )
    worksheet = spreadsheet.get_worksheet_by_id(saved["sheet_id"])
    if worksheet is None:
        raise ValueError("Không tìm thấy tab điểm danh đã tạo")
    headers = worksheet.row_values(1)
    header = roster_header(headers)
    old_day = saved["day"]
    day = date.fromisoformat(old_day).strftime('%d-%m-%Y')
    if day in headers:
        col = headers.index(day) + 1
    elif old_day in headers:
        col = headers.index(old_day) + 1
    else:
        col = max(4, len(headers) + 1)
    if worksheet.col_count < col:
        worksheet.resize(cols=col)
    if worksheet.row_count < len(saved["rows"]) + 1:
        worksheet.resize(rows=len(saved["rows"]) + 1)
    roster_values = [header] + [
        [row["display_name"], row.get("discord_display_name") or row["discord_username"], str(row["discord_uid"])]
        for row in saved["rows"]
    ]
    values = [[day]] + [
        [float(row["total"]) if row["present"] is not None or row["transactions"] else ""]
        for row in saved["rows"]
    ]
    letter = column_name(col)
    worksheet.batch_update([
        {"range": f"A1:C{len(roster_values)}", "values": roster_values},
        {"range": f"{letter}1:{letter}{len(values)}", "values": values},
    ], raw=True)
    worksheet.batch_format(attendance_formats(letter, saved["rows"]))


async def sync_attendance(pool, *, credentials_path, saved):
    from classbot.class_sheet import sync_class_sheet
    return await sync_class_sheet(pool, credentials_path=credentials_path, class_id=saved['class_id'])
