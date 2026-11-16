"""Private registration forms, persistent buttons and retryable role grants."""

import asyncio
import os
import re
from urllib.parse import urlsplit

import asyncpg
import discord
import gspread
from discord import app_commands
from discord.ext import tasks
from classbot.verification_sheet import sync_profiles

GREETING = 'Chào bạn đã đến với Trung tâm Chí Dũng.'
CONSENT_LABEL = 'Tôi đồng ý chia sẻ thông tin để được Trung tâm hỗ trợ.'
CONSENT_VERSION = 'verification-sheet-v2'
SUCCESS_MESSAGE = ('Xác minh thành công! Bạn có thể tham quan <#1258743513839829032> '
                   'để biết thêm về các lớp của Trung tâm nhé.')


def panel_content(privacy_url=None):
    content = GREETING + '\n\nHãy bấm nút Xác minh bên dưới để tham gia server.'
    if privacy_url:
        content += '\nChính sách quyền riêng tư: ' + privacy_url
    return content


def validate_profile(full_name, phone, facebook):
    full_name = ' '.join(full_name.split())
    phone = re.sub(r'[\s.()-]', '', phone)
    if phone.startswith('+84'):
        phone = '0' + phone[3:]
    facebook = facebook.strip()
    if not 2 <= len(full_name) <= 100 or any(ord(c) < 32 for c in full_name):
        raise ValueError('Họ tên cần từ 2 đến 100 ký tự.')
    if not re.fullmatch(r'0[1-9][0-9]{8}', phone):
        raise ValueError('Số điện thoại cần 10 chữ số, bắt đầu bằng 0 (hoặc dùng +84).')
    try:
        url = urlsplit(facebook)
        valid = (url.scheme == 'https' and url.hostname in
                 {'facebook.com', 'www.facebook.com', 'm.facebook.com'}
                 and url.path.strip('/') and not url.username and not url.password
                 and url.port in (None, 443))
    except ValueError:
        valid = False
    if not valid or len(facebook) > 300:
        raise ValueError('Hãy nhập link trang Facebook, ví dụ https://www.facebook.com/tenban.')
    return full_name, phone, facebook


async def save_profile(pool, *, guild_id, user_id, username, full_name, phone, facebook,
                       consent=False):
    if not consent:
        raise ValueError('Bạn cần tick ô đồng ý chia sẻ thông tin trước khi gửi.')
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('''
                INSERT INTO profiles
                    (guild_id, discord_uid, full_name, phone, facebook_url, username, role_status,
                     consented_at, consent_version, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'pending', now(), $7, now())
                ON CONFLICT (guild_id, discord_uid) DO UPDATE SET
                    full_name = EXCLUDED.full_name, phone = EXCLUDED.phone,
                    facebook_url = EXCLUDED.facebook_url, username = EXCLUDED.username,
                    role_status = 'pending', consented_at = now(),
                    consent_version = EXCLUDED.consent_version, updated_at = now()
            ''', guild_id, user_id, full_name, phone, facebook, username, CONSENT_VERSION)
            await conn.execute('''INSERT INTO verification_sync(guild_id,data_version)
                VALUES ($1,1) ON CONFLICT (guild_id) DO UPDATE SET
                data_version=verification_sync.data_version+1''', guild_id)
            # Only the name is available to the class roster/Sheets projection.
            await conn.execute('''
                UPDATE enrollments e SET display_name = $3
                FROM classes c WHERE c.id = e.class_id
                    AND c.guild_id = $1 AND e.discord_uid = $2
            ''', guild_id, user_id, full_name)


class RegistrationModal(discord.ui.Modal, title='Xác minh thông tin'):
    def __init__(self, service, config):
        super().__init__(timeout=600)
        self.service = service
        self.config = dict(config)
        self.full_name = discord.ui.TextInput(min_length=2, max_length=100)
        self.phone = discord.ui.TextInput(max_length=30)
        self.facebook = discord.ui.TextInput(placeholder='https://www.facebook.com/tenban', max_length=300)
        self.consent = discord.ui.CheckboxGroup(
            custom_id='verification:consent:v1', required=True, min_values=1, max_values=1,
            options=[discord.CheckboxGroupOption(label=CONSENT_LABEL, value='agree', default=False)],
        )
        self.add_item(discord.ui.Label(text='Họ và tên', component=self.full_name))
        self.add_item(discord.ui.Label(text='Số điện thoại', component=self.phone))
        self.add_item(discord.ui.Label(text='Link Facebook', component=self.facebook))
        self.add_item(discord.ui.Label(text='Xác nhận', component=self.consent))

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if 'agree' not in self.consent.values:
            await interaction.followup.send('Bạn cần tick ô đồng ý chia sẻ thông tin trước khi gửi.', ephemeral=True)
            return
        try:
            values = validate_profile(self.full_name.value, self.phone.value, self.facebook.value)
        except ValueError as error:
            await interaction.followup.send(str(error) + ' Bấm Xác minh để nhập lại.', ephemeral=True)
            return
        try:
            current = await self.service.config(interaction.guild_id)
            if current is None or dict(current) != self.config:
                await interaction.followup.send(
                    'Cấu hình xác minh đã thay đổi. Hãy mở biểu mẫu từ bảng xác minh mới nhất.',
                    ephemeral=True,
                )
                return
            await save_profile(
                self.service.bot.db_pool, guild_id=interaction.guild_id,
                user_id=interaction.user.id, username=interaction.user.name,
                full_name=values[0], phone=values[1], facebook=values[2], consent=True,
            )
            granted = await self.service.grant_role(interaction.guild, interaction.user.id)
        except asyncpg.PostgresError:
            await interaction.followup.send(
                'Chưa hoàn tất xác minh do lỗi lưu dữ liệu. Hãy thử lại sau.', ephemeral=True,
            )
            return
        synced = await self.service.sync_sheet()
        status = (SUCCESS_MESSAGE if granted else
            'Đã lưu hồ sơ. Role đang chờ cấp; bot sẽ tự thử lại. '
            'Nếu server có bước chấp nhận nội quy, hãy hoàn tất bước đó.')
        if not synced:
            status += ' Sheet đang chờ cập nhật; bot sẽ tự thử lại.'
        await interaction.followup.send(status, ephemeral=True)

    async def on_error(self, interaction, error):
        # Do not log form values or exception context containing private data.
        print('Không hoàn tất biểu mẫu xác minh; cần kiểm tra dịch vụ.')
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send('Chưa hoàn tất xác minh. Hãy thử lại hoặc liên hệ quản trị viên.', ephemeral=True)


class RegistrationView(discord.ui.View):
    def __init__(self, service):
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label='Xác minh', style=discord.ButtonStyle.primary,
                       custom_id='classbot:registration:v1')
    async def register(self, interaction, button):
        try:
            config = await self.service.config(interaction.guild_id)
        except asyncpg.PostgresError:
            await interaction.response.send_message('Dịch vụ đang bận, hãy thử lại sau.', ephemeral=True)
            return
        if (config is None or interaction.message is None
                or config['message_id'] != interaction.message.id
                or config['channel_id'] != interaction.channel_id):
            await interaction.response.send_message(
                'Bảng xác minh này đã hết hiệu lực. Hãy dùng bảng xác minh mới nhất.', ephemeral=True,
            )
            return
        await interaction.response.send_modal(RegistrationModal(self.service, config))


class Onboarding:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.sheet_lock = asyncio.Lock()
        self.panel_refreshed = False

    async def sync_sheet(self, force=False):
        try:
            async with self.sheet_lock:
                await sync_profiles(
                    self.bot.db_pool, guild_id=self.guild_id,
                    spreadsheet_id=os.environ['SPREADSHEET_ID'],
                    credentials_path=os.environ.get('GOOGLE_CREDENTIALS_PATH', '/run/secrets/google.json'),
                    force=force,
                )
            return True
        except (KeyError, OSError, ValueError, gspread.exceptions.GSpreadException, asyncpg.PostgresError):
            print('Thông tin xác minh đã lưu; Sheet đang chờ cập nhật.')
            return False

    async def refresh_panel(self, guild):
        config = await self.config(guild.id)
        if config and config['message_id']:
            channel = guild.get_channel(config['channel_id'])
            if channel:
                message = await channel.fetch_message(config['message_id'])
                await message.edit(content=panel_content(config['privacy_url']), view=RegistrationView(self))

    async def config(self, guild_id):
        async with self.bot.db_pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM onboarding_config WHERE guild_id = $1', guild_id)

    async def grant_role(self, guild, user_id):
        config = await self.config(guild.id)
        if config is None:
            return False
        role = guild.get_role(config['verified_role_id'])
        if (role is None or role.is_default() or role.managed or guild.me is None
                or not guild.me.guild_permissions.manage_roles or role >= guild.me.top_role):
            return False
        try:
            member = await guild.fetch_member(user_id)
            if member.pending:
                return False
            if role not in member.roles:
                await member.add_roles(role, reason='Hoàn tất xác minh thông tin')
        except discord.HTTPException:
            return False
        async with self.bot.db_pool.acquire() as conn:
            changed = await conn.fetchval('''
                UPDATE profiles SET role_status = 'granted'
                WHERE guild_id = $1 AND discord_uid = $2 AND role_status <> 'granted'
                RETURNING discord_uid
            ''', guild.id, user_id)
            if changed is not None:
                await conn.execute('''UPDATE verification_sync SET data_version=data_version+1
                    WHERE guild_id=$1''', guild.id)
        return True

    @tasks.loop(seconds=60)
    async def retry_pending(self):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return
        try:
            if not self.panel_refreshed:
                try:
                    await self.refresh_panel(guild)
                    self.panel_refreshed = True
                except discord.HTTPException:
                    print('Chưa cập nhật được bảng xác minh hiện có.')
            async with self.bot.db_pool.acquire() as conn:
                users = await conn.fetch('''
                    SELECT discord_uid FROM profiles
                    WHERE guild_id = $1 AND role_status = 'pending'
                ''', self.guild_id)
            for row in users:
                await self.grant_role(guild, row['discord_uid'])
            if await self.config(self.guild_id) is not None:
                await self.sync_sheet()
        except (asyncpg.PostgresError, discord.HTTPException):
            print('Đang chờ thử lại cấp role xác minh.')

    @retry_pending.before_loop
    async def before_retry(self):
        await self.bot.wait_until_ready()

    async def setup_panel(self, interaction, kenh, role, chinh_sach=None):
        guild, actor = interaction.guild, interaction.user
        if (guild is None or not isinstance(actor, discord.Member)
                or not actor.guild_permissions.manage_roles):
            await interaction.response.send_message('Bạn cần quyền Manage Roles.', ephemeral=True)
            return
        if (role.guild.id != guild.id or kenh.guild.id != guild.id or role.is_default()
                or role.managed or guild.me is None or role >= guild.me.top_role
                or not guild.me.guild_permissions.manage_roles
                or (actor.id != guild.owner_id and role >= actor.top_role)):
            await interaction.response.send_message(
                'Chọn role học viên nằm dưới role của bot và role của bạn. Bot cần Manage Roles.',
                ephemeral=True,
            )
            return
        permissions = kenh.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages):
            await interaction.response.send_message('Bot cần View Channel và Send Messages ở kênh đã chọn.', ephemeral=True)
            return
        if chinh_sach:
            try:
                url = urlsplit(chinh_sach)
                valid_url = url.scheme == 'https' and url.hostname and not url.username
            except ValueError:
                valid_url = False
            if not valid_url or len(chinh_sach) > 500:
                await interaction.response.send_message('Link chính sách cần bắt đầu bằng https://.', ephemeral=True)
                return
        await interaction.response.defer(ephemeral=True)
        content = panel_content(chinh_sach)
        message = None
        try:
            message = await kenh.send(content, view=RegistrationView(self),
                                      allowed_mentions=discord.AllowedMentions.none())
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO onboarding_config
                        (guild_id, channel_id, verified_role_id, message_id, privacy_url)
                    VALUES ($1,$2,$3,$4,$5)
                    ON CONFLICT (guild_id) DO UPDATE SET
                        channel_id=EXCLUDED.channel_id, verified_role_id=EXCLUDED.verified_role_id,
                        message_id=EXCLUDED.message_id, privacy_url=EXCLUDED.privacy_url
                ''', guild.id, kenh.id, role.id, message.id, chinh_sach)
        except (discord.HTTPException, asyncpg.PostgresError):
            if message:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
            await interaction.followup.send('Chưa tạo được bảng xác minh. Kiểm tra quyền kênh và thử lại.', ephemeral=True)
            return
        await interaction.followup.send(
            f'Đã tạo bảng xác minh tại {kenh.mention}, cấp role {role.mention}. '
            'Hãy cho người chưa có role xem được kênh xác minh; cấu hình các kênh học '
            'để role học viên được xem.', ephemeral=True,
        )


def register_onboarding(bot, guild_id):
    service = Onboarding(bot, guild_id)

    @app_commands.command(name='setupxacminh', description='Tạo bảng xác minh thông tin và chọn role tự cấp')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(kenh='Kênh hiển thị nút xác minh', role='Role được cấp sau xác minh',
                           chinh_sach='Link HTTPS chính sách quyền riêng tư, nếu đã có')
    async def setup(interaction: discord.Interaction, kenh: discord.TextChannel,
                    role: discord.Role, chinh_sach: str = None):
        await service.setup_panel(interaction, kenh, role, chinh_sach)

    bot.tree.add_command(setup, guild=discord.Object(id=guild_id))
    return service
