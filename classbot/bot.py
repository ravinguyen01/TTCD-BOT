"""Minimal Discord connection check for the new class bot."""

import asyncio
import os
from datetime import date

import discord
import asyncpg
import gspread
from discord import app_commands

from classbot.attendance import class_day, record_attendance
from classbot.points import add_points as record_points, sync_points, validate_points
from classbot.reaction import (award_reaction, get_channel_class, map_channel,
                              reaction_points, unmap_channel)
from classbot.roster import class_code_for_role, save_roster, sync_roster
from classbot.onboarding import RegistrationView, register_onboarding
from classbot.attendance_notice import attendance_embeds, attendance_notices
from classbot.accounts import canonical_members, register_account_commands, resolve_class_member


def required_int(name):
    value = os.environ.get(name)
    if not value or not value.isdecimal():
        raise RuntimeError(f"Thiếu {name} hoặc ID không hợp lệ trong .env")
    return int(value)


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Thiếu BOT_TOKEN trong .env")

    application_id = required_int("APPLICATION_ID")
    guild_id = required_int("GUILD_ID")
    test_channel_id = required_int("BOT_TEST_CHANNEL_ID")
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "/run/secrets/google.json")
    database_url = os.environ.get("DATABASE_URL")
    teacher_role_id = required_int("TEACHER_ROLE_ID")

    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    intents.voice_states = True
    intents.reactions = True

    class TestBot(discord.Client):
        def __init__(self):
            super().__init__(intents=intents, application_id=application_id)
            self.tree = app_commands.CommandTree(self)
            self.db_pool = None

        async def setup_hook(self):
            if database_url:
                self.db_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
            self.add_view(RegistrationView(self.onboarding))
            if self.db_pool is not None:
                self.onboarding.retry_pending.start()
            guild = discord.Object(id=guild_id)
            synced = await self.tree.sync(guild=guild)
            print(f"Đã đồng bộ {len(synced)} lệnh cho server thử {guild_id}")

        async def on_ready(self):
            print(f"Bot đã online: {self.user} (ID {self.user.id})")

        async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
            points = reaction_points(payload.emoji)
            if (
                payload.guild_id != guild_id
                or points is None
                or self.user is None
                or payload.user_id == self.user.id
                or self.db_pool is None
            ):
                return
            try:
                mapped = await get_channel_class(
                    self.db_pool, guild_id=guild_id, channel_id=payload.channel_id
                )
                if mapped is None:
                    return
                guild = self.get_guild(guild_id)
                if guild is None:
                    return
                reactor = payload.member or guild.get_member(payload.user_id)
                if reactor is None:
                    reactor = await guild.fetch_member(payload.user_id)
                if reactor.bot or not (
                    reactor.guild_permissions.manage_roles
                    or any(role.id == teacher_role_id for role in reactor.roles)
                ):
                    return
                channel = guild.get_channel(payload.channel_id)
                if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                    return
                message = await channel.fetch_message(payload.message_id)
                if message.author.bot or message.author.id == reactor.id:
                    return
                target = guild.get_member(message.author.id)
                if target is None:
                    target = await guild.fetch_member(message.author.id)
                target = await resolve_class_member(self.db_pool, guild, target, mapped['class_role_id'])
                if target is None:
                    return
                saved = await award_reaction(
                    self.db_pool, guild_id=guild_id, channel_id=payload.channel_id,
                    message_id=payload.message_id, reactor_uid=reactor.id,
                    emoji=str(payload.emoji), target=target, class_id=mapped["id"],
                    day=class_day(), points=points,
                )
                if saved is not None and saved["inserted"]:
                    sheet_synced = True
                    try:
                        await sync_points(
                            self.db_pool, credentials_path=credentials_path, saved=saved
                        )
                    except (OSError, ValueError, gspread.exceptions.GSpreadException,
                            asyncpg.PostgresError):
                        sheet_synced = False
                        print("Điểm emoji đã lưu, nhưng Sheets đang chờ đồng bộ.")
                    note = " (Sheet đang chờ đồng bộ)" if not sheet_synced else ""
                    try:
                        await channel.send(
                            f"{reactor.mention} đã cộng {payload.emoji} +{points} điểm cho {target.mention} "
                            f"trong lớp {saved['code']}. Tổng ngày {date.fromisoformat(saved['day']).strftime('%d-%m-%Y')}: "
                            f"{saved['total']}.{note}",
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    except discord.HTTPException:
                        print("Đã lưu điểm emoji nhưng không gửi được thông báo công khai.")
            except (discord.HTTPException, asyncpg.PostgresError):
                print("Không xử lý được sự kiện emoji; kiểm tra quyền kênh và database.")

        async def close(self):
            self.onboarding.retry_pending.cancel()
            if self.db_pool is not None:
                await self.db_pool.close()
            await super().close()

    bot = TestBot()
    bot.onboarding = register_onboarding(bot, guild_id)
    register_account_commands(bot, guild_id)

    @bot.tree.command(
        name="kiemtra",
        description="Kiểm tra bot lớp học đã kết nối",
        guild=discord.Object(id=guild_id),
    )
    async def kiemtra(interaction: discord.Interaction):
        if interaction.channel_id != test_channel_id:
            await interaction.response.send_message(
                "Hãy dùng lệnh này trong kênh bot-test.", ephemeral=True
            )
            return
        await interaction.response.send_message("Bot lớp học đã kết nối!", ephemeral=True)

    @bot.tree.command(
        name="add",
        description="Gắn role cho mọi người đang ở cùng phòng voice với bạn",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.describe(role="Role muốn gắn cho người trong phòng voice")
    @app_commands.default_permissions(manage_roles=True)
    async def add_role(interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        actor = interaction.user
        if guild is None or not isinstance(actor, discord.Member):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return
        if not actor.guild_permissions.manage_roles:
            await interaction.response.send_message("Bạn cần quyền Manage Roles.", ephemeral=True)
            return
        channel = actor.voice.channel if actor.voice else None
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "Hãy vào một phòng voice trước khi dùng /add.", ephemeral=True
            )
            return
        bot_member = guild.me or await guild.fetch_member(bot.user.id)
        if (
            role.guild.id != guild.id
            or role.is_default()
            or role.managed
            or role >= bot_member.top_role
        ):
            await interaction.response.send_message(
                "Bot không thể gắn role này. Kiểm tra thứ tự role trong Server Settings.",
                ephemeral=True,
            )
            return
        if guild.owner_id != actor.id and role >= actor.top_role:
            await interaction.response.send_message(
                "Role được chọn cần nằm dưới role cao nhất của bạn.", ephemeral=True
            )
            return
        if not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Bot chưa có quyền Manage Roles.", ephemeral=True
            )
            return

        # Chụp danh sách UID ngay lúc nhận lệnh; fetch thêm khi member chưa ở cache.
        user_ids = tuple(channel.voice_states)
        await interaction.response.defer(ephemeral=True)
        added = already = skipped = failed = 0
        for user_id in user_ids:
            try:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                if member.bot:
                    skipped += 1
                elif role in member.roles:
                    already += 1
                else:
                    await member.add_roles(role, reason=f"/add bởi {actor.id}")
                    added += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
        await interaction.followup.send(
            f"Đã gắn {role.mention}: {added} người. "
            f"Đã có role: {already}; bot bỏ qua: {skipped}; lỗi: {failed}.",
            ephemeral=True,
        )

    @bot.tree.command(
        name="sheetcheck",
        description="Kiểm tra bot có đọc được bảng Google Sheets thử hay không",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.default_permissions(manage_guild=True)
    async def sheetcheck(interaction: discord.Interaction):
        actor = interaction.user
        if not isinstance(actor, discord.Member) or not actor.guild_permissions.manage_guild:
            await interaction.response.send_message("Bạn cần quyền quản lý server.", ephemeral=True)
            return
        if not spreadsheet_id:
            await interaction.response.send_message("Thiếu SPREADSHEET_ID.", ephemeral=True)
            return
        if not os.path.isfile(credentials_path):
            await interaction.response.send_message(
                "Chưa có file key Google ở secrets/google.json.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            title = await asyncio.to_thread(
                lambda: gspread.service_account(filename=credentials_path)
                .open_by_key(spreadsheet_id)
                .title
            )
        except (OSError, ValueError, gspread.exceptions.GSpreadException):
            await interaction.followup.send(
                "Không đọc được bảng. Kiểm tra key, Sheets API và quyền Editor của service account.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Đã kết nối Google Sheets: {title}", ephemeral=True
        )

    @bot.tree.command(
        name="taodanhsach",
        description="Tạo hoặc cập nhật danh sách lớp từ role đã chọn",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.describe(role="Role của lớp cần tạo danh sách")
    @app_commands.default_permissions(manage_roles=True)
    async def taodanhsach(interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        actor = interaction.user
        if guild is None or not isinstance(actor, discord.Member):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return
        if not actor.guild_permissions.manage_roles:
            await interaction.response.send_message("Bạn cần quyền Manage Roles.", ephemeral=True)
            return
        if role.is_default():
            await interaction.response.send_message(
                "Hãy chọn một role lớp, không chọn @everyone.", ephemeral=True
            )
            return
        if bot.db_pool is None or not spreadsheet_id or not os.path.isfile(credentials_path):
            await interaction.response.send_message(
                "Chưa đủ cấu hình PostgreSQL hoặc Google Sheets.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        members = []
        try:
            async for member in guild.fetch_members(limit=None):
                if not member.bot and any(r.id == role.id for r in member.roles):
                    members.append(member)
        except discord.HTTPException:
            await interaction.followup.send(
                "Không quét được toàn bộ server; danh sách chưa được ghi.", ephemeral=True
            )
            return
        try:
            members = await canonical_members(bot.db_pool, guild, members)
            saved = await save_roster(
                bot.db_pool, guild_id=guild.id, voice_channel_id=None,
                role_id=role.id, code=class_code_for_role(role), spreadsheet_id=spreadsheet_id,
                members=members,
            )
        except (asyncpg.PostgresError, OSError, ValueError, discord.HTTPException):
            await interaction.followup.send(
                "Không lưu được danh sách vào PostgreSQL.", ephemeral=True
            )
            return
        try:
            sheet_id = await sync_roster(
                bot.db_pool, credentials_path=credentials_path,
                spreadsheet_id=spreadsheet_id, code=saved["code"], saved=saved,
            )
        except (OSError, ValueError, gspread.exceptions.GSpreadException,
                asyncpg.PostgresError):
            await interaction.followup.send(
                "Đã lưu danh sách vào PostgreSQL, nhưng chưa ghi được Google Sheets. "
                "Hãy chạy lại lệnh sau khi kiểm tra bảng.", ephemeral=True
            )
            return
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}"
        await interaction.followup.send(
            f"Đã quét {len(members)} người có role {role.mention}; "
            f"danh sách {saved['code']} hiện có {saved['active_count']} học viên hoạt động. "
            f"Thêm {saved['added']}, đưa khỏi danh sách {saved['removed']}. "
            f"Tên từ hồ sơ: {saved['named']}; tên Discord: "
            f"{len(members) - saved['named']}. [Mở tab điểm danh]({url})",
            ephemeral=True,
        )

    @bot.tree.command(
        name="diemdanh",
        description="Điểm danh người có role theo phòng voice admin đang ở",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.describe(role="Role của lớp cần điểm danh")
    @app_commands.default_permissions(manage_roles=True)
    async def diemdanh(interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        actor = interaction.user
        if guild is None or not isinstance(actor, discord.Member):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return
        if not actor.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Bạn cần quyền Manage Roles.", ephemeral=True
            )
            return
        if role.guild.id != guild.id or role.is_default():
            await interaction.response.send_message(
                "Hãy chọn một role lớp trong server.", ephemeral=True
            )
            return
        if bot.db_pool is None or not spreadsheet_id or not os.path.isfile(credentials_path):
            await interaction.response.send_message(
                "Chưa đủ cấu hình PostgreSQL hoặc Google Sheets.", ephemeral=True
            )
            return
        channel = actor.voice.channel if actor.voice else None
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "Hãy vào phòng voice của lớp trước khi điểm danh.", ephemeral=True
            )
            return
        voice_uids = tuple(channel.voice_states)
        notice_channel = interaction.channel
        if notice_channel is None or guild.me is None:
            await interaction.response.send_message('Không xác định được kênh thông báo.', ephemeral=True)
            return
        permissions = notice_channel.permissions_for(guild.me)
        can_send = (permissions.send_messages_in_threads if isinstance(notice_channel, discord.Thread)
                    else permissions.send_messages)
        if not permissions.view_channel or not can_send:
            await interaction.response.send_message(
                'Bot cần quyền xem và gửi tin nhắn tại kênh này để thông báo điểm danh công khai.',
                ephemeral=True,
            )
            return
        day = class_day()
        await interaction.response.defer(ephemeral=True)
        members = []
        try:
            async for member in guild.fetch_members(limit=None):
                if not member.bot and any(r.id == role.id for r in member.roles):
                    members.append(member)
        except discord.HTTPException:
            await interaction.followup.send(
                "Không quét được người có role; chưa ghi điểm danh mới.", ephemeral=True
            )
            return
        try:
            roster = await save_roster(
                bot.db_pool, guild_id=guild.id, voice_channel_id=None,
                role_id=role.id, code=class_code_for_role(role),
                spreadsheet_id=spreadsheet_id,
                members=await canonical_members(bot.db_pool, guild, members),
            )
            saved = await record_attendance(
                bot.db_pool, guild_id=guild.id, role_id=role.id,
                voice_uids=voice_uids, day=day,
            )
        except (ValueError, asyncpg.PostgresError, discord.HTTPException):
            await interaction.followup.send(
                "Không lưu được điểm danh. Kiểm tra danh sách lớp và PostgreSQL.",
                ephemeral=True,
            )
            return
        if saved is None:
            await interaction.followup.send(
                "Không tìm thấy lớp đã lưu; hãy thử lại lệnh.",
                ephemeral=True,
            )
            return
        sheet_synced = True
        try:
            sheet_id = await sync_roster(
                bot.db_pool, credentials_path=credentials_path,
                spreadsheet_id=spreadsheet_id, code=roster["code"], saved=roster,
            )
            saved["sheet_id"] = sheet_id
        except (OSError, ValueError, gspread.exceptions.GSpreadException,
                asyncpg.PostgresError):
            sheet_synced = False
        try:
            if permissions.embed_links:
                for embed in attendance_embeds(saved):
                    await notice_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            else:
                for text in attendance_notices(saved):
                    await notice_channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await interaction.followup.send(
                'Đã lưu điểm danh nhưng chưa gửi đủ thông báo công khai. '
                'Kiểm tra quyền gửi tin nhắn rồi chạy lại /diemdanh để quét và cập nhật lại.',
                ephemeral=True,
            )
            return
        if not sheet_synced:
            await interaction.followup.send(
                'Đã thông báo điểm danh công khai. Sheets đang chờ cập nhật; '
                'chạy lại /diemdanh để quét lại và cập nhật.', ephemeral=True,
            )
            return
        await interaction.followup.send(
            'Đã thông báo điểm danh công khai. '
            f"[Mở tab](https://docs.google.com/spreadsheets/d/"
            f"{saved['spreadsheet_id']}/edit#gid={saved['sheet_id']})",
            ephemeral=True,
        )

    @bot.tree.command(
        name="cong",
        description="Cộng hoặc trừ điểm cho học viên trong lớp đang học",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.describe(
        role="Role của lớp", hoc_vien="Học viên nhận điểm",
        diem="Điểm từ -100 đến 100, tối đa hai chữ số thập phân",
    )
    async def cong(
        interaction: discord.Interaction, role: discord.Role,
        hoc_vien: discord.Member, diem: float,
    ):
        guild = interaction.guild
        actor = interaction.user
        if guild is None or not isinstance(actor, discord.Member):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return
        if not (
            actor.guild_permissions.manage_roles
            or any(r.id == teacher_role_id for r in actor.roles)
        ):
            await interaction.response.send_message(
                "Bạn cần role giáo viên hoặc quyền Manage Roles.", ephemeral=True
            )
            return
        if not actor.voice or not isinstance(actor.voice.channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "Hãy vào phòng voice của lớp trước khi cộng điểm.", ephemeral=True
            )
            return
        if role.guild.id != guild.id or role.is_default():
            await interaction.response.send_message(
                "Học viên cần có role lớp đã chọn.", ephemeral=True
            )
            return
        try:
            points = validate_points(diem)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            canonical = await resolve_class_member(bot.db_pool, guild, hoc_vien, role.id)
            if canonical is None:
                await interaction.followup.send('Học viên hoặc nick liên kết cần có role lớp đã chọn.', ephemeral=True)
                return
            saved = await record_points(
                bot.db_pool, guild_id=guild.id, role_id=role.id,
                target_uid=canonical.id, actor_uid=actor.id,
                interaction_id=interaction.id, points=points, day=class_day(),
            )
        except ValueError as error:
            await interaction.followup.send(
                f"{error}. Hãy chạy /taodanhsach cho role này trước.", ephemeral=True
            )
            return
        except asyncpg.PostgresError:
            await interaction.followup.send("Không lưu được điểm vào PostgreSQL.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send('Không đọc được nick chính hoặc role lớp. Chưa cộng điểm.', ephemeral=True)
            return
        sheet_synced = True
        try:
            sheet_id = await sync_points(
                bot.db_pool, credentials_path=credentials_path, saved=saved
            )
        except (OSError, ValueError, gspread.exceptions.GSpreadException,
                asyncpg.PostgresError):
            sheet_synced = False
            sheet_id = None
        if not saved["inserted"]:
            await interaction.followup.send("Lệnh này đã được xử lý trước đó.", ephemeral=True)
            return
        note = " Sheet đang chờ đồng bộ." if not sheet_synced else ""
        try:
            await interaction.channel.send(
                f"{actor.mention} đã {'cộng' if points > 0 else 'trừ'} "
                f"{points:+} điểm cho {hoc_vien.mention} trong lớp {saved['code']}. "
                f"Tổng ngày {date.fromisoformat(saved['day']).strftime('%d-%m-%Y')}: {saved['total']}.{note}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Đã lưu điểm nhưng không gửi được thông báo công khai. "
                "Hãy cấp quyền Send Messages cho bot tại kênh này.", ephemeral=True,
            )
            return
        link = (f"[Mở tab](https://docs.google.com/spreadsheets/d/"
                f"{saved['spreadsheet_id']}/edit#gid={sheet_id})" if sheet_id else "")
        await interaction.followup.send(
            f"Đã thông báo công khai. {link}{note}", ephemeral=True,
        )

    @bot.tree.command(
        name="gankenh",
        description="Gắn kênh text hoặc voice hiện tại với role lớp để cộng điểm bằng emoji",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.describe(role="Role của lớp dùng kênh này")
    @app_commands.default_permissions(manage_roles=True)
    async def gankenh(interaction: discord.Interaction, role: discord.Role):
        guild = interaction.guild
        actor = interaction.user
        channel = interaction.channel
        if guild is None or not isinstance(actor, discord.Member) or not actor.guild_permissions.manage_roles:
            await interaction.response.send_message("Bạn cần quyền Manage Roles.", ephemeral=True)
            return
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            await interaction.response.send_message(
                "Hãy dùng lệnh trong kênh text hoặc phần chat của kênh voice lớp.",
                ephemeral=True,
            )
            return
        if role.guild.id != guild.id or role.is_default():
            await interaction.response.send_message("Hãy chọn role lớp hợp lệ.", ephemeral=True)
            return
        permissions = channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.read_message_history
                and permissions.send_messages):
            await interaction.response.send_message(
                "Bot cần quyền View Channel, Read Message History và Send Messages tại kênh này.",
                ephemeral=True,
            )
            return
        try:
            code = await map_channel(
                bot.db_pool, guild_id=guild.id, channel_id=channel.id,
                role_id=role.id,
            )
        except asyncpg.PostgresError:
            await interaction.response.send_message(
                "Không lưu được ánh xạ kênh.", ephemeral=True
            )
            return
        if code is None:
            await interaction.response.send_message(
                "Chưa có danh sách lớp này. Hãy chạy /taodanhsach trước.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Đã gắn {channel.mention} với lớp {code}. "
            "Điểm emoji: 👍🏻 +0.1, 🫰🏻 +0.2, ⭐ +0.5, <:1000:988685030916255815> +1.",
            ephemeral=True,
        )

    bot.tree.add_command(
        app_commands.Command(
            name="ganrole",
            description="Gắn kênh text hoặc voice hiện tại với role lớp",
            callback=gankenh.callback,
        ),
        guild=discord.Object(id=guild_id),
    )

    @bot.tree.command(
        name="goganrole", description="Gỡ liên kết role lớp khỏi kênh hiện tại",
        guild=discord.Object(id=guild_id),
    )
    @app_commands.default_permissions(manage_roles=True)
    async def goganrole(interaction: discord.Interaction):
        actor = interaction.user
        if (interaction.guild is None or not isinstance(actor, discord.Member)
                or not actor.guild_permissions.manage_roles):
            await interaction.response.send_message("Bạn cần quyền Manage Roles.", ephemeral=True)
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel)):
            await interaction.response.send_message("Hãy dùng lệnh trong kênh text hoặc chat voice.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            removed = await unmap_channel(
                bot.db_pool, guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
            )
        except asyncpg.PostgresError:
            await interaction.followup.send("Không gỡ được liên kết, hãy thử lại.", ephemeral=True)
            return
        await interaction.followup.send(
            "Đã gỡ liên kết role khỏi kênh này. Điểm đã lưu được giữ nguyên."
            if removed else "Kênh này chưa gắn role lớp nào.", ephemeral=True,
        )

    bot.run(token)


if __name__ == "__main__":
    main()
