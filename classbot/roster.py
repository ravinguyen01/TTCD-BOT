"""Store a class roster in PostgreSQL, then project it into Google Sheets."""

import asyncio
import re

import gspread


HEADER = ["Họ và tên", "Tên Discord", "Discord UID"]
LEGACY_HEADER = ["Tên học viên", "Tên Discord", "Discord UID"]


def discord_display_name(member):
    return (getattr(member, 'display_name', None)
            or getattr(member, 'global_name', None) or member.name)


def roster_header(headers):
    """Use the new title for new tabs, while accepting existing class tabs."""
    if not headers:
        return HEADER
    if headers[:3] in (HEADER, LEGACY_HEADER):
        return headers[:3]
    raise ValueError('Tiêu đề tab danh sách đã thay đổi')


def class_code_for_role(role):
    """Stable, readable tab name; the role ID prevents duplicate-name collisions."""
    name = re.sub(r"[\\/\[\]:*?]", "_", role.name)
    name = re.sub(r"\s+", " ", name).strip(" .'") or "Lop"
    return f"{name[:70]}-{str(role.id)[-6:]}"


async def save_roster(pool, *, guild_id, voice_channel_id, role_id, code,
                      spreadsheet_id, members):
    """Commit Discord's role snapshot before any external Sheets request."""
    uids = [member.id for member in members]
    async with pool.acquire() as conn:
        async with conn.transaction():
            class_row = await conn.fetchrow("""
                INSERT INTO classes
                    (guild_id, voice_channel_id, class_role_id, class_code, spreadsheet_id)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, class_role_id) DO UPDATE SET
                    spreadsheet_id = EXCLUDED.spreadsheet_id
                RETURNING id, attendance_sheet_id, class_code
            """, guild_id, voice_channel_id, role_id, code, spreadsheet_id)
            class_id = class_row["id"]
            previous = {row['discord_uid'] for row in await conn.fetch(
                'SELECT discord_uid FROM enrollments WHERE class_id=$1 AND active=TRUE', class_id)}
            named = 0
            profiles = await conn.fetch("""
                    SELECT discord_uid, full_name FROM profiles
                    WHERE guild_id = $1 AND discord_uid = ANY($2::bigint[])
                      AND consented_at IS NOT NULL AND BTRIM(full_name) <> ''
                """, guild_id, uids)
            names = {row["discord_uid"]: row["full_name"] for row in profiles}
            await conn.execute(
                "UPDATE enrollments SET active = FALSE WHERE class_id = $1", class_id
            )
            for member in members:
                username = member.name
                discord_name = discord_display_name(member)
                full_name = names.get(member.id)
                if full_name:
                    named += 1
                await conn.execute("""
                        INSERT INTO enrollments
                            (class_id, discord_uid, discord_username, display_name, discord_display_name)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (class_id, discord_uid) DO UPDATE SET
                            discord_username = EXCLUDED.discord_username,
                            discord_display_name = EXCLUDED.discord_display_name,
                            display_name = EXCLUDED.display_name,
                            active = TRUE
                    """, class_id, member.id, username, full_name or discord_name, discord_name)
            roster = await conn.fetch("""
                SELECT display_name, discord_username, discord_display_name, discord_uid, active
                FROM enrollments WHERE class_id = $1 AND active=TRUE ORDER BY id
            """, class_id)
            await conn.execute("""
                    INSERT INTO sheet_sync(class_id, data_version)
                    VALUES ($1, 1)
                    ON CONFLICT (class_id) DO UPDATE SET
                        data_version = sheet_sync.data_version + 1
                """, class_id)
            version = await conn.fetchval(
                "SELECT data_version FROM sheet_sync WHERE class_id = $1", class_id
            )
    return {
        "class_id": class_id,
        "sheet_id": class_row["attendance_sheet_id"],
        "code": class_row["class_code"],
        "rows": [[row["display_name"], row["discord_display_name"] or row["discord_username"],
                  str(row["discord_uid"])] for row in roster],
        "named": named,
        "active_count": sum(row['active'] for row in roster),
        "added": len(set(uids) - previous),
        "removed": len(previous - set(uids)),
        "version": version,
    }


def write_roster_sheet(credentials_path, spreadsheet_id, title, rows, sheet_id):
    client = gspread.service_account(filename=credentials_path)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = None
    if sheet_id is not None:
        worksheet = spreadsheet.get_worksheet_by_id(sheet_id)
    if worksheet is None:
        try:
            worksheet = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=title, rows=max(len(rows) + 1, 100), cols=30
            )
        else:
            roster_header(worksheet.row_values(1))
    if worksheet.row_count < len(rows) + 1:
        worksheet.resize(rows=len(rows) + 1)
    values = [roster_header(worksheet.row_values(1)), *rows]
    worksheet.update(values, range_name=f"A1:C{len(values)}", raw=True)
    return worksheet.id


async def sync_roster(pool, *, credentials_path, spreadsheet_id, code, saved):
    from classbot.class_sheet import sync_class_sheet
    return await sync_class_sheet(pool, credentials_path=credentials_path, class_id=saved['class_id'])
