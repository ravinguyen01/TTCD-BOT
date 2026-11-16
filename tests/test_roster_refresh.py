"""Refresh membership and today's attendance without shifting historical cells."""
import asyncio
import os
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg

from classbot.attendance import record_attendance
from classbot.class_sheet import load_class_report, report_values, write_class_report
from classbot.points import add_points
from classbot.roster import HEADER, save_roster


class Pool:
    def __init__(self,conn): self.conn=conn
    def acquire(self): return self
    async def __aenter__(self): return self.conn
    async def __aexit__(self,*args): pass


class Worksheet:
    id=44
    col_count=30
    row_count=100
    def __init__(self,values):
        self.old=deepcopy(values)
        self.cleared=[]
        self.formats=[]
    def get_all_values(self): return self.old
    def update(self,values,range_name,raw):
        assert raw
        self.written=values
    def batch_clear(self,ranges): self.cleared.extend(ranges)
    def batch_format(self,formats): self.formats.extend(formats)
    def freeze(self,rows): assert rows==1


async def main():
    conn=await asyncpg.connect(os.environ['DATABASE_URL'])
    tx=conn.transaction(isolation='repeatable_read')
    await tx.start()
    try:
        pool=Pool(conn)
        gid=-909072
        a,b,c,d=[SimpleNamespace(id=i,name=f'user{i}',display_name=f'Student {i}') for i in (1,2,3,4)]
        kwargs=dict(guild_id=gid,voice_channel_id=None,role_id=7,code='MOCK_REFRESH',spreadsheet_id='mock')
        saved=await save_roster(pool,members=[a,b,c],**kwargs)
        cid=saved['class_id']
        yesterday=date(2026,11,15)
        today=yesterday+timedelta(days=1)
        await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[1,3],day=yesterday)
        await add_points(pool,guild_id=gid,role_id=7,target_uid=3,actor_uid=9,
                         interaction_id=10,points=Decimal('0.2'),day=yesterday)
        historic=await conn.fetch('SELECT * FROM attendance WHERE class_id=$1 ORDER BY enrollment_id',cid)
        old_report=await load_class_report(pool,cid)
        old_values=report_values(old_report,[])[0]
        saved=await save_roster(pool,members=[a,c,d],**kwargs)
        assert saved['added']==1 and saved['removed']==1 and saved['active_count']==3
        assert [row[2] for row in saved['rows']]==['1','3','4']
        marked=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[3,4],day=today)
        assert {r['discord_uid']:r['present'] for r in marked['rows']}=={1:False,3:True,4:True}
        refreshed=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[1,4],day=today)
        assert {r['discord_uid']:r['present'] for r in refreshed['rows']}=={1:True,3:False,4:True}
        assert historic==await conn.fetch('SELECT * FROM attendance WHERE class_id=$1 AND class_date=$2 ORDER BY enrollment_id',cid,yesterday)
        report=await load_class_report(pool,cid)
        values,days,states=report_values(report,old_values[0])
        assert values[0]==HEADER+['15-11-2026','16-11-2026']
        by_uid={row[2]:row for row in values[1:]}
        assert by_uid['3'][3]==0.2 and by_uid['3'][4]==0
        assert by_uid['4'][3]=='' and by_uid['4'][4]==0
        ws=Worksheet(old_values)
        book=SimpleNamespace(get_worksheet_by_id=lambda _:ws)
        report['attendance_sheet_id']=44
        with patch('classbot.class_sheet.gspread.service_account',return_value=SimpleNamespace(open_by_key=lambda _:book)):
            write_class_report('mock',report)
        assert ws.written==values
        assert any(f['range']=='E3:E3' and f['format']['backgroundColor']['red']==0.96 for f in ws.formats)
        saved=await save_roster(pool,members=[a],**kwargs)
        assert saved['removed']==2
        shrunk=await load_class_report(pool,cid)
        shrunk['attendance_sheet_id']=44
        ws=Worksheet(values)
        with patch('classbot.class_sheet.gspread.service_account',return_value=SimpleNamespace(open_by_key=lambda _:SimpleNamespace(get_worksheet_by_id=lambda _:ws))):
            write_class_report('mock',shrunk)
        assert ws.cleared==['A3:E4'] and len(ws.written)==2
        saved=await save_roster(pool,members=[],**kwargs)
        assert saved['removed']==1 and not saved['rows']
        empty=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[],day=today)
        assert empty['rows']==[]
        empty_report=await load_class_report(pool,cid)
        assert len(empty_report['rows'])==0
        empty_report['attendance_sheet_id']=44
        ws=Worksheet(values)
        with patch('classbot.class_sheet.gspread.service_account',return_value=SimpleNamespace(open_by_key=lambda _:SimpleNamespace(get_worksheet_by_id=lambda _:ws))):
            write_class_report('mock',empty_report)
        assert len(ws.written)==1 and ws.cleared==['A2:E4']
        saved=await save_roster(pool,members=[c],**kwargs)
        restored=await load_class_report(pool,cid)
        assert report_values(restored,[])[0][1][3]==0.2
        assert await conn.fetchval('SELECT COUNT(*) FROM enrollments WHERE class_id=$1',cid)==4
        unknown=Worksheet([HEADER+['01-01-2020'],['Unknown','unknown','9','manual value']])
        with patch('classbot.class_sheet.gspread.service_account',return_value=SimpleNamespace(open_by_key=lambda _:SimpleNamespace(get_worksheet_by_id=lambda _:unknown))):
            try: write_class_report('mock',report)
            except ValueError: pass
            else: raise AssertionError('Unbacked historical data overwritten')
        print('PASS: roster add/remove, same-day rescan, prior-day data preserved, '
              'UID-aligned values/colors, stale-row cleanup, empty class, rejoin history and unknown-data protection.')
    finally:
        await tx.rollback()
        await conn.close()


asyncio.run(main())
