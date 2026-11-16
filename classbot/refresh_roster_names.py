"""Refresh existing roster labels; preserve enrollments, attendance and points."""

import asyncio
import os

import asyncpg
import discord

from classbot.roster import discord_display_name
from classbot.class_sheet import sync_class_sheet


async def main():
    guild_id = int(os.environ['GUILD_ID'])
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2)
    intents = discord.Intents.none()
    intents.members = True
    try:
        async with discord.Client(intents=intents) as client:
            await client.login(os.environ['BOT_TOKEN'])
            guild = await client.fetch_guild(guild_id)
            members = {member.id: member async for member in guild.fetch_members(limit=None)}
        async with pool.acquire() as conn:
            async with conn.transaction():
                records = await conn.fetch('''
                    SELECT e.id, e.discord_uid, p.full_name
                    FROM enrollments e JOIN classes c ON c.id=e.class_id
                    LEFT JOIN profiles p ON p.guild_id=c.guild_id AND p.discord_uid=e.discord_uid
                        AND p.consented_at IS NOT NULL AND BTRIM(p.full_name)<>''
                    WHERE c.guild_id=$1
                ''', guild_id)
                updates = []
                for record in records:
                    member = members.get(record['discord_uid'])
                    if member is not None:
                        name = discord_display_name(member)
                        updates.append((record['id'], member.name, name, record['full_name'] or name))
                await conn.executemany('''UPDATE enrollments SET discord_username=$2,
                    discord_display_name=$3, display_name=$4 WHERE id=$1''', updates)
            classes = await conn.fetch('''SELECT id,class_code,spreadsheet_id,attendance_sheet_id
                FROM classes WHERE guild_id=$1 AND attendance_sheet_id IS NOT NULL''', guild_id)
            for row in classes:
                await sync_class_sheet(pool, credentials_path=os.environ['GOOGLE_CREDENTIALS_PATH'],
                                       class_id=row['id'])
        print(f'Refreshed {len(updates)} enrollment labels in {len(classes)} tabs; attendance/points unchanged.')
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
