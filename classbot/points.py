"""Signed decimal point transactions and idempotent daily Sheets totals."""

import asyncio
from decimal import Decimal

import gspread

from classbot.attendance import column_name, sync_attendance
from classbot.roster import HEADER
from classbot.accounts import primary_uid


def validate_points(value):
    points = Decimal(str(value))
    if not points.is_finite() or points == 0 or abs(points) > 100:
        raise ValueError("Điểm phải khác 0 và nằm từ -100 đến 100")
    if points != points.quantize(Decimal("0.01")):
        raise ValueError("Điểm chỉ nhận tối đa hai chữ số thập phân")
    return points


async def daily_points_rows(conn, class_id, day):
    return await conn.fetch("""
        SELECT e.id, e.discord_uid, e.discord_username, e.discord_display_name, e.display_name,
               (SELECT COUNT(*) FROM point_transactions p
                WHERE p.enrollment_id = e.id AND p.class_date = $2)
             + (SELECT COUNT(*) FROM reaction_awards r
                WHERE r.enrollment_id = e.id AND r.class_date = $2)
                 AS transactions,
               (SELECT COALESCE(SUM(p.points), 0) FROM point_transactions p
                WHERE p.enrollment_id = e.id AND p.class_date = $2)
             + (SELECT COALESCE(SUM(r.points), 0) FROM reaction_awards r
                WHERE r.enrollment_id = e.id AND r.class_date = $2)
                 AS total
        FROM enrollments e WHERE e.class_id = $1 AND e.active=TRUE ORDER BY e.id
    """, class_id, day)


async def add_points(pool, *, guild_id, role_id, target_uid, actor_uid,
                     interaction_id, points, day):
    async with pool.acquire() as conn:
        async with conn.transaction():
            class_row = await conn.fetchrow("""
                SELECT id, class_code, spreadsheet_id, points_sheet_id
                FROM classes WHERE guild_id = $1 AND class_role_id = $2
                FOR UPDATE
            """, guild_id, role_id)
            if class_row is None:
                raise ValueError("Chưa có danh sách lớp cho role này")
            class_id = class_row["id"]
            target_uid = await primary_uid(conn, guild_id, target_uid)
            target = await conn.fetchrow("""
                SELECT id FROM enrollments
                WHERE class_id = $1 AND discord_uid = $2 AND active = TRUE
            """, class_id, target_uid)
            if target is None:
                raise ValueError("Học viên chưa có trong danh sách lớp đang hoạt động")
            inserted = await conn.fetchval("""
                INSERT INTO point_transactions
                    (interaction_id, class_id, enrollment_id, class_date,
                     points, actor_uid)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (interaction_id) DO NOTHING
                RETURNING interaction_id
            """, interaction_id, class_id, target["id"], day, points, actor_uid)
            if inserted is not None:
                await conn.execute("""
                    UPDATE sheet_sync SET data_version = data_version + 1
                    WHERE class_id = $1
                """, class_id)
            rows = await daily_points_rows(conn, class_id, day)
            version = await conn.fetchval(
                "SELECT data_version FROM sheet_sync WHERE class_id = $1", class_id
            )
    target_total = next(row["total"] for row in rows if row["id"] == target["id"])
    return {
        "class_id": class_id,
        "code": class_row["class_code"],
        "spreadsheet_id": class_row["spreadsheet_id"],
        "sheet_id": class_row["points_sheet_id"],
        "rows": [dict(row) for row in rows],
        "version": version,
        "inserted": inserted is not None,
        "total": target_total,
        "day": day.isoformat(),
    }


def write_points_sheet(credentials_path, saved):
    spreadsheet = gspread.service_account(filename=credentials_path).open_by_key(
        saved["spreadsheet_id"]
    )
    worksheet = None
    if saved["sheet_id"] is not None:
        worksheet = spreadsheet.get_worksheet_by_id(saved["sheet_id"])
    if worksheet is None:
        title = f"{saved['code']} - Diem cong"
        try:
            worksheet = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=title, rows=max(len(saved["rows"]) + 1, 100), cols=30
            )
        else:
            if worksheet.row_values(1) != HEADER:
                raise ValueError("Tab điểm trùng tên nhưng không do bot quản lý")
    headers = worksheet.row_values(1)
    if headers and headers[:3] != HEADER:
        raise ValueError("Tiêu đề tab điểm đã thay đổi")
    day = saved["day"]
    col = headers.index(day) + 1 if day in headers else max(4, len(headers) + 1)
    if worksheet.col_count < col:
        worksheet.resize(cols=col)
    if worksheet.row_count < len(saved["rows"]) + 1:
        worksheet.resize(rows=len(saved["rows"]) + 1)
    roster_values = [HEADER] + [
        [row["display_name"], row.get("discord_display_name") or row["discord_username"], str(row["discord_uid"])]
        for row in saved["rows"]
    ]
    totals = [[day]] + [
        [float(row["total"]) if row["transactions"] else ""]
        for row in saved["rows"]
    ]
    letter = column_name(col)
    worksheet.batch_update([
        {"range": f"A1:C{len(roster_values)}", "values": roster_values},
        {"range": f"{letter}1:{letter}{len(totals)}", "values": totals},
    ], raw=True)
    return worksheet.id


async def sync_points(pool, *, credentials_path, saved):
    report_request = {**saved, "sheet_id": None}
    await sync_attendance(pool, credentials_path=credentials_path, saved=report_request)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT attendance_sheet_id FROM classes WHERE id = $1", saved["class_id"]
        )
