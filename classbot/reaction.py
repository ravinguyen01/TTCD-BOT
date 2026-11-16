"""Map text channels to classes and award points from teacher reactions."""

from decimal import Decimal

from classbot.points import daily_points_rows
from classbot.roster import discord_display_name
from classbot.accounts import primary_uid


def reaction_points(emoji):
    if emoji.id is not None:
        return Decimal('1') if emoji.id == 988685030916255815 else None
    name = ''.join(
        char for char in str(emoji)
        if char != '\ufe0f' and not '\U0001f3fb' <= char <= '\U0001f3ff'
    )
    return {
        '👍': Decimal('0.1'),
        '🫰': Decimal('0.2'),
        '⭐': Decimal('0.5'),
    }.get(name)


async def unmap_channel(pool, *, guild_id, channel_id):
    async with pool.acquire() as conn:
        return await conn.fetchval('''
            DELETE FROM class_channels WHERE guild_id = $1 AND channel_id = $2
            RETURNING class_id
        ''', guild_id, channel_id) is not None


async def map_channel(pool, *, guild_id, channel_id, role_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, class_code FROM classes
            WHERE guild_id = $1 AND class_role_id = $2
        """, guild_id, role_id)
        if row is None:
            return None
        await conn.execute("""
            INSERT INTO class_channels(guild_id, channel_id, class_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, channel_id) DO UPDATE SET
                class_id = EXCLUDED.class_id
        """, guild_id, channel_id, row["id"])
        return row["class_code"]


async def get_channel_class(pool, *, guild_id, channel_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT c.id, c.class_role_id, c.class_code
            FROM class_channels cc JOIN classes c ON c.id = cc.class_id
            WHERE cc.guild_id = $1 AND cc.channel_id = $2
        """, guild_id, channel_id)


async def award_reaction(pool, *, guild_id, channel_id, message_id,
                         reactor_uid, emoji, target, class_id, day, points):
    async with pool.acquire() as conn:
        async with conn.transaction():
            class_row = await conn.fetchrow("""
                SELECT id, class_code, spreadsheet_id, points_sheet_id
                FROM classes WHERE id = $1 AND guild_id = $2 FOR UPDATE
            """, class_id, guild_id)
            if class_row is None:
                return None
            target_uid = await primary_uid(conn, guild_id, target.id)
            if target_uid != target.id:
                raise ValueError('Phải đối chiếu nick chính trước khi lưu điểm emoji')
            if await primary_uid(conn, guild_id, reactor_uid) == target_uid:
                return None
            profile = await conn.fetchval("""
                SELECT full_name FROM profiles
                WHERE guild_id = $1 AND discord_uid = $2
                    AND consented_at IS NOT NULL AND BTRIM(full_name) <> ''
            """, guild_id, target.id)
            enrollment_id = await conn.fetchval("""
                INSERT INTO enrollments
                    (class_id, discord_uid, discord_username, display_name, discord_display_name)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (class_id, discord_uid) DO UPDATE SET
                    discord_username = EXCLUDED.discord_username,
                    discord_display_name = EXCLUDED.discord_display_name,
                    display_name = EXCLUDED.display_name,
                    active = TRUE
                RETURNING id
            """, class_id, target.id, target.name, profile or discord_display_name(target),
                 discord_display_name(target))
            inserted = await conn.fetchval("""
                INSERT INTO reaction_awards
                    (guild_id, channel_id, message_id, reactor_uid, emoji,
                     class_id, enrollment_id, class_date, points)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (guild_id, channel_id, message_id, reactor_uid, emoji)
                DO NOTHING
                RETURNING message_id
            """, guild_id, channel_id, message_id, reactor_uid, emoji,
                 class_id, enrollment_id, day, points)
            if inserted is not None:
                await conn.execute("""
                    UPDATE sheet_sync SET data_version = data_version + 1
                    WHERE class_id = $1
                """, class_id)
            rows = await daily_points_rows(conn, class_id, day)
            version = await conn.fetchval(
                "SELECT data_version FROM sheet_sync WHERE class_id = $1", class_id
            )
    return {
        "class_id": class_id,
        "code": class_row["class_code"],
        "spreadsheet_id": class_row["spreadsheet_id"],
        "sheet_id": class_row["points_sheet_id"],
        "rows": [dict(row) for row in rows],
        "version": version,
        "inserted": inserted is not None,
        "total": next(row["total"] for row in rows if row["id"] == enrollment_id),
        "day": day.isoformat(),
    }
