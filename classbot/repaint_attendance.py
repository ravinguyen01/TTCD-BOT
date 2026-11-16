"""Reapply attendance values and colors from PostgreSQL to managed Sheets tabs."""

import asyncio
import os

import asyncpg

from classbot.class_sheet import sync_class_sheet


async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    count = 0
    try:
        async with pool.acquire() as conn:
            sessions = await conn.fetch("""
                SELECT c.id FROM classes c
                WHERE c.attendance_sheet_id IS NOT NULL
                ORDER BY c.id
            """)
            for session in sessions:
                await sync_class_sheet(pool, credentials_path=os.environ['GOOGLE_CREDENTIALS_PATH'],
                                       class_id=session['id'])
                count += 1
    finally:
        await pool.close()
    print(f"Đã đồng bộ danh sách, điểm và màu cho {count} tab lớp.")


if __name__ == "__main__":
    asyncio.run(main())
