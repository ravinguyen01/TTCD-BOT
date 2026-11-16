"""Offline Discord doubles; DB writes are always rolled back."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import discord

from classbot.onboarding import Onboarding, RegistrationModal, RegistrationView, save_profile, validate_profile
from classbot.verification_sheet import sheet_values


class Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


async def main():
    assert validate_profile('  Nguyen   An ', '+84 912 345 678',
                            'https://www.facebook.com/mock') == (
        'Nguyen An', '0912345678', 'https://www.facebook.com/mock')
    for name, phone, url in [
        ('A', '0912345678', 'https://facebook.com/mock'),
        ('Mock Name', '0123', 'https://facebook.com/mock'),
        ('Mock Name', '0912345678', 'https://facebook.com.evil.test/mock'),
        ('Mock Name', '0912345678', 'https://facebook.com@evil.test/mock'),
        ('Mock Name', '0912345678', 'https://facebook.com/'),
    ]:
        try:
            validate_profile(name, phone, url)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid profile accepted')
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    transaction = conn.transaction()
    await transaction.start()
    try:
        gid, uid, rid = -909009, -909008, 22
        await conn.execute('''INSERT INTO onboarding_config
            (guild_id,channel_id,verified_role_id) VALUES ($1,1,$2)''', gid, rid)
        class_id = await conn.fetchval('''INSERT INTO classes
            (guild_id,class_role_id,class_code) VALUES ($1,2,'MOCK_REGISTRATION') RETURNING id''', gid)
        await conn.execute('''INSERT INTO enrollments
            (class_id,discord_uid,discord_username,display_name)
            VALUES ($1,$2,'mock','mock')''', class_id, uid)
        for name in ['Mock Name', 'Updated Mock']:
            await save_profile(Pool(conn), guild_id=gid, user_id=uid, username='mock',
                               full_name=name, phone='0912345678', facebook='https://facebook.com/mock',
                               consent=True)
        assert await conn.fetchval('SELECT COUNT(*) FROM profiles WHERE guild_id=$1', gid) == 1
        assert await conn.fetchval('SELECT display_name FROM enrollments WHERE class_id=$1', class_id) == 'Updated Mock'
        bot = SimpleNamespace(db_pool=Pool(conn))
        service = Onboarding(bot, gid)
        assert RegistrationView(service).is_persistent()
        modal = RegistrationModal(service, {'guild_id': gid})
        payload = modal.to_dict()
        assert len(payload['components']) == 4
        assert modal.consent.required and modal.consent.min_values == 1
        assert not modal.consent.options[0].default
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await modal.on_submit(interaction)
        interaction.followup.send.assert_awaited_once()
        try:
            await save_profile(Pool(conn), guild_id=gid, user_id=uid, username='mock',
                               full_name='Should Not Save', phone='0912345678',
                               facebook='https://facebook.com/mock', consent=False)
        except ValueError:
            pass
        else:
            raise AssertionError('Saved without consent')
        profile = await conn.fetchrow('SELECT * FROM profiles WHERE guild_id=$1', gid)
        assert profile['full_name'] == 'Updated Mock' and profile['consented_at'] is not None
        values = sheet_values([profile])
        assert values[1][2] == str(uid) and values[1][3] == '0912345678'
        assert values[1][5] is True and isinstance(values[1][7], float)
        role = discord.Object(id=rid)
        member = SimpleNamespace(pending=True, roles=[], add_roles=AsyncMock())
        guild = SimpleNamespace(id=gid, get_role=lambda _: role,
                                fetch_member=AsyncMock(return_value=member),
                                me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True),
                                                   top_role=100))
        # Small role double implements Discord's hierarchy comparisons.
        class Role:
            managed = False
            def is_default(self): return False
            def __ge__(self, other): return False
        role = Role()
        assert not await service.grant_role(guild, uid)
        member.add_roles.assert_not_awaited()
        member.pending = False
        assert await service.grant_role(guild, uid)
        member.add_roles.assert_awaited_once()
        assert await conn.fetchval('SELECT role_status FROM profiles WHERE guild_id=$1', gid) == 'granted'
        member.roles = [role]
        assert await service.grant_role(guild, uid)
        member.add_roles.assert_awaited_once()
        member.roles = []
        member.add_roles.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'Mock denied')
        assert not await service.grant_role(guild, uid)
        print('PASS: validation, update without duplicates, consent required/default off, '
              '4-component modal, Sheet values preserve phone/UID, persistent button, '
              'rules screening, role grant, repeat and permission error; fake data rolled back.')
    finally:
        await transaction.rollback()
        await conn.close()


asyncio.run(main())
