"""Verify name matching by Discord UID, not by display name or ordering."""
import asyncio
import os
from datetime import date
from types import SimpleNamespace

import asyncpg

from classbot.roster import HEADER, LEGACY_HEADER, discord_display_name, roster_header, save_roster


class Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self): return self
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): pass


async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    tx = conn.transaction()
    await tx.start()
    try:
        gid = -909070
        await conn.executemany('''INSERT INTO profiles
            (guild_id,discord_uid,full_name,phone,facebook_url,username,role_status,consented_at)
            VALUES ($1,$2,$3,'0900000000','https://facebook.com/mock','old-name','granted',
                    CASE WHEN $4::boolean THEN now() ELSE NULL END)''', [
                (gid, 101, 'Verified Full Name', True),
                (gid, 102, 'Legacy Unverified Name', False),
            ])
        members = [SimpleNamespace(id=103,name='same-discord-name',global_name='Global Display'),
                   SimpleNamespace(id=101,name='renamed-discord-account',display_name='Verified Nick'),
                   SimpleNamespace(id=102,name='same-discord-name',display_name='Server Nick')]
        assert discord_display_name(SimpleNamespace(name='username-only'))=='username-only'
        saved = await save_roster(Pool(conn),guild_id=gid,voice_channel_id=None,
                                 role_id=7,code='MOCK_NAME_LOOKUP',spreadsheet_id='mock',members=members)
        names = {row[2]:row[0] for row in saved['rows']}
        assert names == {'101':'Verified Full Name','102':'Server Nick','103':'Global Display'}
        assert next(row[1] for row in saved['rows'] if row[2]=='101')=='Verified Nick'
        assert len(saved['rows'])==3 and saved['named']==1
        await conn.execute('UPDATE profiles SET full_name=$2 WHERE guild_id=$1 AND discord_uid=101',
                           gid,'Updated Verified Name')
        saved = await save_roster(Pool(conn),guild_id=gid,voice_channel_id=None,
                                 role_id=7,code='MOCK_NAME_LOOKUP',spreadsheet_id='mock',members=members)
        assert next(row[0] for row in saved['rows'] if row[2]=='101')=='Updated Verified Name'
        class_id=saved['class_id']
        day=date(2026,11,16)
        await conn.execute('''INSERT INTO attendance(class_id,enrollment_id,class_date,present)
            SELECT class_id,id,$2,discord_uid=101 FROM enrollments WHERE class_id=$1''',class_id,day)
        before=await conn.fetch('SELECT enrollment_id,present FROM attendance WHERE class_id=$1 ORDER BY enrollment_id',class_id)
        members[2].display_name='Updated Server Nick'
        members.append(SimpleNamespace(id=104,name='new_member',display_name='New Member'))
        refreshed=await save_roster(Pool(conn),guild_id=gid,voice_channel_id=None,
                                role_id=7,code='MOCK_NAME_LOOKUP',spreadsheet_id='mock',members=members)
        assert len(refreshed['rows'])==4 and refreshed['added']==1
        assert next(row[0] for row in refreshed['rows'] if row[2]=='102')=='Updated Server Nick'
        assert before==await conn.fetch('SELECT enrollment_id,present FROM attendance WHERE class_id=$1 ORDER BY enrollment_id',class_id)
        assert HEADER[0]=='Họ và tên'
        assert roster_header([])==HEADER
        assert roster_header(LEGACY_HEADER+['16-11-2026'])==LEGACY_HEADER
        assert roster_header(HEADER+['16-11-2026'])==HEADER
        try: roster_header(['Unrelated','tab'])
        except ValueError: pass
        else: raise AssertionError('Unrelated header accepted')
        print('PASS: verified name/server nickname/global name/username priority, '
              'duplicate usernames, roster additions preserve recorded attendance, new and legacy headers. Mock data rolled back.')
    finally:
        await tx.rollback()
        await conn.close()


asyncio.run(main())
