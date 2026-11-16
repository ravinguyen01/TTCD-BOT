"""Admin-approved account identities; historic transactions stay untouched."""

import asyncpg
import discord
from discord import app_commands


async def primary_uid(conn, guild_id, uid):
    return await conn.fetchval('''SELECT primary_uid FROM account_links
        WHERE guild_id=$1 AND secondary_uid=$2''', guild_id, uid) or uid


async def link_accounts(pool, *, guild_id, primary, secondary, actor):
    if primary == secondary:
        raise ValueError('Hai tài khoản phải khác nhau.')
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock($1)', guild_id)
            if await primary_uid(conn, guild_id, primary) != primary:
                raise ValueError('Nick chính đang là nick phụ của người khác. Hãy gỡ liên kết cũ trước.')
            old = await conn.fetchval('''SELECT primary_uid FROM account_links
                WHERE guild_id=$1 AND secondary_uid=$2''', guild_id, secondary)
            if old == primary:
                return False
            if old is not None:
                raise ValueError('Nick phụ đã liên kết với nick chính khác. Hãy gỡ liên kết cũ trước.')
            if await conn.fetchval('''SELECT EXISTS(SELECT 1 FROM account_links
                WHERE guild_id=$1 AND primary_uid=$2)''', guild_id, secondary):
                raise ValueError('Nick phụ đang là nick chính có tài khoản liên kết. Hãy gỡ các liên kết đó trước.')
            await conn.execute('''INSERT INTO account_links
                (guild_id,secondary_uid,primary_uid,actor_uid) VALUES ($1,$2,$3,$4)''',
                guild_id, secondary, primary, actor)
    return True


async def unlink_account(pool, *, guild_id, secondary):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock($1)', guild_id)
            return await conn.fetchval('''DELETE FROM account_links
                WHERE guild_id=$1 AND secondary_uid=$2 RETURNING primary_uid''', guild_id, secondary)


async def canonical_members(pool, guild, members):
    """A class role on either account enrolls its primary account once."""
    async with pool.acquire() as conn:
        links = await conn.fetch('SELECT secondary_uid,primary_uid FROM account_links WHERE guild_id=$1', guild.id)
    mapping = {row['secondary_uid']: row['primary_uid'] for row in links}
    known = {member.id: member for member in members}
    result = {}
    for member in members:
        uid = mapping.get(member.id, member.id)
        if uid not in result:
            person = known.get(uid) or guild.get_member(uid)
            if person is None:
                person = await guild.fetch_member(uid)
            if person.bot:
                raise ValueError('Nick chính phải là tài khoản người dùng trong server.')
            result[uid] = person
    return list(result.values())


async def resolve_class_member(pool, guild, member, role_id):
    async with pool.acquire() as conn:
        uid = await primary_uid(conn, guild.id, member.id)
        linked = await conn.fetch('''SELECT secondary_uid FROM account_links
            WHERE guild_id=$1 AND primary_uid=$2''', guild.id, uid)
    primary = member if uid == member.id else guild.get_member(uid) or await guild.fetch_member(uid)
    candidates = {uid, member.id, *(row['secondary_uid'] for row in linked)}
    for candidate in candidates:
        user = member if candidate == member.id else guild.get_member(candidate)
        if user is None:
            try:
                user = await guild.fetch_member(candidate)
            except discord.NotFound:
                continue
        if not user.bot and any(role.id == role_id for role in user.roles):
            return primary
    return None


def register_account_commands(bot, guild_id):
    async def allowed(interaction):
        if (interaction.guild is None or not isinstance(interaction.user, discord.Member)
                or not interaction.user.guild_permissions.manage_roles):
            await interaction.response.send_message('Bạn cần quyền Manage Roles.', ephemeral=True)
            return False
        if bot.db_pool is None:
            await interaction.response.send_message('Database chưa sẵn sàng.', ephemeral=True)
            return False
        return True

    @app_commands.command(name='lienketnick', description='Liên kết nick phụ với nick chính của cùng học viên')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(chinh='Tài khoản chính, ưu tiên đã xác minh', phu='Tài khoản phụ của cùng người')
    async def link(interaction: discord.Interaction, chinh: discord.Member, phu: discord.Member):
        if not await allowed(interaction):
            return
        if chinh.bot or phu.bot or chinh.guild.id != interaction.guild_id or phu.guild.id != interaction.guild_id:
            await interaction.response.send_message('Chọn hai tài khoản người dùng trong server.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            created = await link_accounts(bot.db_pool, guild_id=interaction.guild_id,
                                         primary=chinh.id, secondary=phu.id, actor=interaction.user.id)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except asyncpg.PostgresError:
            await interaction.followup.send('Chưa lưu được liên kết. Hãy thử lại.', ephemeral=True)
            return
        status = 'Đã liên kết' if created else 'Đã có liên kết'
        await interaction.followup.send(
            f'{status} nick phụ {phu.mention} → nick chính {chinh.mention}. '
            'Chạy lại /taodanhsach và /diemdanh cho lớp để cập nhật, chỉ tính một học viên; '
            'có mặt nếu một trong hai nick ở voice. Điểm mới của hai nick ghi về nick chính. '
            'Điểm danh ngày hiện tại được quét lại khi gọi lệnh; các ngày trước và giao dịch điểm cũ giữ nguyên.',
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name='golienketnick', description='Gỡ liên kết nick phụ khỏi nick chính')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(phu='Nick phụ cần gỡ liên kết')
    async def unlink(interaction: discord.Interaction, phu: discord.Member):
        if not await allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            old = await unlink_account(bot.db_pool, guild_id=interaction.guild_id, secondary=phu.id)
        except asyncpg.PostgresError:
            await interaction.followup.send('Chưa gỡ được liên kết. Hãy thử lại.', ephemeral=True)
            return
        await interaction.followup.send(
            'Đã gỡ liên kết. Chạy lại /taodanhsach và /diemdanh để tính hai tài khoản riêng. '
            'Điểm đã ghi trước đó giữ nguyên.' if old is not None else 'Tài khoản này không phải nick phụ đã liên kết.',
            ephemeral=True,
        )

    bot.tree.add_command(link, guild=discord.Object(id=guild_id))
    bot.tree.add_command(unlink, guild=discord.Object(id=guild_id))
