"""Account linking integration test; Discord is fake and SQL is rolled back."""
import asyncio
import os
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg

from classbot.accounts import (canonical_members, link_accounts, primary_uid,
                               resolve_class_member, unlink_account)
from classbot.attendance import record_attendance, load_daily_report
from classbot.points import add_points
from classbot.reaction import award_reaction
from classbot.roster import save_roster


class Pool:
    def __init__(self, conn): self.conn=conn
    def acquire(self): return self
    async def __aenter__(self): return self.conn
    async def __aexit__(self,*args): pass


async def main():
    conn=await asyncpg.connect(os.environ['DATABASE_URL'])
    tx=conn.transaction()
    await tx.start()
    try:
        gid=-909071
        pool=Pool(conn)
        assert await link_accounts(pool,guild_id=gid,primary=100,secondary=200,actor=900)
        assert not await link_accounts(pool,guild_id=gid,primary=100,secondary=200,actor=900)
        assert await primary_uid(conn,gid,200)==100
        for primary,secondary in [(100,100),(200,100),(300,200),(300,100)]:
            try: await link_accounts(pool,guild_id=gid,primary=primary,secondary=secondary,actor=900)
            except ValueError: pass
            else: raise AssertionError('Invalid link accepted')
        assert await primary_uid(conn,gid-1,200)==200
        role=SimpleNamespace(id=7)
        a=SimpleNamespace(id=100,name='main',display_name='Primary Display',roles=[role],bot=False)
        b=SimpleNamespace(id=200,name='secondary',display_name='Secondary Display',roles=[role],bot=False)
        lookup={100:a,200:b}
        guild=SimpleNamespace(id=gid,get_member=lookup.get,
                              fetch_member=AsyncMock(side_effect=lambda uid:lookup[uid]))
        assert [m.id for m in await canonical_members(pool,guild,[b,a])]==[100]
        assert [m.id for m in await canonical_members(pool,guild,[b])]==[100]
        assert (await resolve_class_member(pool,guild,b,7)).id==100
        assert await resolve_class_member(pool,guild,b,8) is None
        members=await canonical_members(pool,guild,[a,b])
        saved=await save_roster(pool,guild_id=gid,voice_channel_id=None,role_id=7,
                                code='MOCK_LINK',spreadsheet_id='mock',members=members)
        assert len(saved['rows'])==1 and saved['rows'][0][2]=='100'
        day=date(2026,11,16)
        for offset,voice in [(0,[100]),(1,[200]),(2,[100,200]),(3,[])]:
            report=await record_attendance(pool,guild_id=gid,role_id=7,
                                          voice_uids=voice,day=day+timedelta(days=offset))
            marked=[row for row in report['rows'] if row['present'] is not None]
            assert len(marked)==1 and marked[0]['present']==bool(voice)
        repeated=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[],day=day)
        assert repeated['already'] and not repeated['rows'][0]['present']
        kwargs=dict(guild_id=gid,role_id=7,actor_uid=900,points=Decimal('0.2'),day=day)
        await add_points(pool,target_uid=200,interaction_id=1,**kwargs)
        result=await add_points(pool,target_uid=100,interaction_id=2,**kwargs)
        assert result['total']==Decimal('0.4')
        again=await add_points(pool,target_uid=200,interaction_id=2,**kwargs)
        assert not again['inserted'] and again['total']==Decimal('0.4')
        award=dict(guild_id=gid,channel_id=5,message_id=99,reactor_uid=900,emoji='star',
                   target=a,class_id=saved['class_id'],day=day,points=Decimal('0.5'))
        assert (await award_reaction(pool,**award))['total']==Decimal('0.9')
        assert not (await award_reaction(pool,**award))['inserted']
        assert await award_reaction(pool,**{**award,'reactor_uid':200,'message_id':100}) is None
        daily=await load_daily_report(pool,class_id=saved['class_id'],day=day)
        assert len(daily['rows'])==1 and daily['rows'][0]['total']==Decimal('0.9')
        assert await unlink_account(pool,guild_id=gid,secondary=200)==100
        assert await unlink_account(pool,guild_id=gid,secondary=200) is None
        assert await primary_uid(conn,gid,200)==200
        saved2=await save_roster(pool,guild_id=gid,voice_channel_id=None,role_id=7,
                                code='MOCK_LINK',spreadsheet_id='mock',members=[a,b])
        assert len(saved2['rows'])==2
        assert (await load_daily_report(pool,class_id=saved['class_id'],day=day))['rows'][0]['total']==Decimal('0.9')
        historic=day+timedelta(days=4)
        before_link=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[200],day=historic)
        assert sum(r['present'] is not None for r in before_link['rows'])==2
        await add_points(pool,target_uid=200,interaction_id=3,**{**kwargs,'points':Decimal('2'),'day':historic})
        await link_accounts(pool,guild_id=gid,primary=100,secondary=200,actor=900)
        after_link=await save_roster(pool,guild_id=gid,voice_channel_id=None,role_id=7,
                                    code='MOCK_LINK',spreadsheet_id='mock',members=[a])
        assert after_link['active_count']==1 and len(after_link['rows'])==1
        historical_again=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[100],day=historic)
        assert len(historical_again['rows'])==1 and historical_again['rows'][0]['present']
        future=await record_attendance(pool,guild_id=gid,role_id=7,voice_uids=[200],day=historic+timedelta(days=1))
        marked=[r for r in future['rows'] if r['present'] is not None]
        assert len(marked)==1 and marked[0]['discord_uid']==100 and marked[0]['present']
        assert await conn.fetchval('''SELECT p.points FROM point_transactions p JOIN enrollments e
            ON e.id=p.enrollment_id WHERE p.interaction_id=3 AND e.discord_uid=200''')==Decimal('2')
        print('PASS: link/unlink, idempotency, cycle/conflict guards, guild isolation, '
              'one roster row, primary/secondary/both/neither attendance, repeated day refresh, '
              'shared decimal points, reaction deduplication/self-award guard, '
              'existing duplicate rows excluded from future counts and historic preservation.')
    finally:
        await tx.rollback()
        await conn.close()


asyncio.run(main())
