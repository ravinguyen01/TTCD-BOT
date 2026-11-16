"""Public attendance summaries, split safely for large classes."""

from datetime import date

from discord import Embed
from discord.utils import escape_markdown


def attendance_notices(saved):
    present = sum(row['present'] is True for row in saved['rows'])
    absent = [row for row in saved['rows'] if row['present'] is False]
    code = escape_markdown(' '.join(saved['code'].split()))
    day = date.fromisoformat(saved['day']).strftime('%d-%m-%Y')
    text = (f'**Điểm danh — {code} — {day}**\n'
            f'**Sĩ số: {present + len(absent)} | Hiện diện: {present} | Vắng: {len(absent)}**')
    if saved['already']:
        text += '\nĐã cập nhật theo danh sách lớp và voice tại lần gọi này.'
    if not absent:
        return [text + '\nKhông có học viên vắng.']
    text += '\n\n**Người vắng — Họ và tên | Tên Discord:**'
    messages = []
    for index, row in enumerate(absent, start=1):
        discord_name = row.get('discord_display_name') or row['discord_username']
        name = ' '.join((row['display_name'] or discord_name).split())
        username = escape_markdown(' '.join(discord_name.split()))
        line = f'\n{index}. {escape_markdown(name)} | {username}'
        if len((text + line).encode('utf-16-le')) // 2 > 1800:
            messages.append(text)
            text = '**Người vắng (tiếp):**'
        text += line
    messages.append(text)
    return messages


def attendance_embeds(saved):
    """Pair numbered name columns; each page stays within Discord field limits."""
    present = sum(row['present'] is True for row in saved['rows'])
    absent = [row for row in saved['rows'] if row['present'] is False]
    day = date.fromisoformat(saved['day']).strftime('%d-%m-%Y')
    summary = f'Sĩ số: {present + len(absent)} | Hiện diện: {present} | Vắng: {len(absent)}'
    if saved['already']:
        summary += '\nĐã cập nhật theo danh sách lớp và voice tại lần gọi này.'
    embed = Embed(title=f"Điểm danh — {saved['code']} — {day}", description=summary, color=0x276749)
    if not absent:
        embed.description += '\nKhông có học viên vắng.'
        return [embed]
    pages, names, usernames = [], [], []

    def flush():
        embed.add_field(name='Họ và tên — Người vắng', value='\n'.join(names), inline=True)
        embed.add_field(name='Tên Discord', value='\n'.join(usernames), inline=True)
        pages.append(embed)

    for index, row in enumerate(absent, start=1):
        username = ' '.join((row.get('discord_display_name') or row['discord_username']).split())
        full_name = ' '.join((row['display_name'] or username).split())
        name_line = f'{index}. {escape_markdown(full_name)}'
        user_line = f'{index}. {escape_markdown(username)}'
        if names and (len('\n'.join(names + [name_line]).encode('utf-16-le')) // 2 > 900
                      or len('\n'.join(usernames + [user_line]).encode('utf-16-le')) // 2 > 900):
            flush()
            embed = Embed(title=f"Người vắng (tiếp) — {saved['code']}", color=0x276749)
            names, usernames = [], []
        names.append(name_line)
        usernames.append(user_line)
    flush()
    return pages
