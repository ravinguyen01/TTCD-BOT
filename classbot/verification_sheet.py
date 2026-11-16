"""One managed verification tab; full refreshes are safe to retry."""

import asyncio
from datetime import datetime, timezone, timedelta

import gspread

TITLE = 'Xác minh'
HEADER = ['Họ và tên', 'Tên Discord', 'Discord UID', 'Số điện thoại',
          'Facebook', 'Đã đọc và đồng ý', 'Trạng thái cấp role', 'Cập nhật lúc']


def sheet_values(rows):
    values = [HEADER]
    for row in rows:
        updated = row['updated_at'].astimezone(timezone(timedelta(hours=7)))
        # Sheets serial date: display dd-mm-yyyy but retain sortable numeric values.
        serial = (updated.replace(tzinfo=None) - datetime(1899, 12, 30)).total_seconds() / 86400
        values.append([
            row['full_name'], row['username'], str(row['discord_uid']), row['phone'],
            row['facebook_url'], bool(row['consented_at']),
            'Đã cấp' if row['role_status'] == 'granted' else 'Chờ cấp', serial,
        ])
    return values


def write_profiles(credentials_path, spreadsheet_id, sheet_id, rows):
    book = gspread.service_account(filename=credentials_path).open_by_key(spreadsheet_id)
    worksheet = book.get_worksheet_by_id(sheet_id) if sheet_id is not None else None
    if worksheet is None:
        try:
            worksheet = book.worksheet(TITLE)
        except gspread.WorksheetNotFound:
            worksheet = book.add_worksheet(title=TITLE, rows=max(100, len(rows)+1), cols=8)
        else:
            if worksheet.row_values(1) != HEADER:
                raise ValueError('Tab Xác minh trùng tên với tab không do bot quản lý')
    if worksheet.row_values(1) not in ([], HEADER):
        raise ValueError('Tiêu đề tab Xác minh đã thay đổi')
    if worksheet.row_count < len(rows)+1:
        worksheet.resize(rows=len(rows)+1)
    values = sheet_values(rows)
    worksheet.update(values, range_name=f'A1:H{len(values)}', raw=True)
    # Clear only obsolete managed rows, preserving other tabs.
    old_count = len(worksheet.col_values(3))
    if old_count > len(values):
        worksheet.batch_clear([f'A{len(values)+1}:H{old_count}'])
    worksheet.freeze(rows=1)
    worksheet.batch_format([
        {'range': 'A1:H1', 'format': {
            'backgroundColor': {'red': 0.12, 'green': 0.29, 'blue': 0.42},
            'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'wrapStrategy': 'WRAP'}},
        {'range': 'C2:D', 'format': {'numberFormat': {'type': 'TEXT'}}},
        {'range': 'H2:H', 'format': {'numberFormat': {'type': 'DATE_TIME', 'pattern': 'dd-mm-yyyy hh:mm'}}},
    ])
    book.batch_update({'requests': [
        {'updateDimensionProperties': {
            'range': {'sheetId': worksheet.id, 'dimension': 'COLUMNS',
                      'startIndex': start, 'endIndex': start+1},
            'properties': {'pixelSize': width}, 'fields': 'pixelSize'}}
        for start, width in enumerate([200, 160, 180, 150, 280, 170, 170, 170])
    ]})
    return worksheet.id


async def sync_profiles(pool, *, guild_id, spreadsheet_id, credentials_path, force=False):
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO verification_sync(guild_id) VALUES ($1) ON CONFLICT DO NOTHING', guild_id)
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            sync = await conn.fetchrow('SELECT * FROM verification_sync WHERE guild_id=$1', guild_id)
            if not force and sync['sheet_id'] is not None and sync['data_version'] <= sync['synced_version']:
                return sync['sheet_id']
            rows = await conn.fetch('''SELECT * FROM profiles WHERE guild_id=$1
                                       AND consented_at IS NOT NULL ORDER BY discord_uid''', guild_id)
    sheet_id = await asyncio.to_thread(write_profiles, credentials_path, spreadsheet_id,
                                       sync['sheet_id'], rows)
    async with pool.acquire() as conn:
        await conn.execute('''UPDATE verification_sync SET sheet_id=$2,
            synced_version=GREATEST(synced_version,$3) WHERE guild_id=$1''',
                           guild_id, sheet_id, sync['data_version'])
    return sheet_id
