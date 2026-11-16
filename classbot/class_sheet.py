"""Rewrite the managed class report by enrollment ID when its roster changes."""

import asyncio
from datetime import datetime

import gspread

from classbot.roster import roster_header

_locks = {}


def parse_day(value):
    for pattern in ('%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError('Tab lớp có cột không phải ngày; chưa ghi đè để bảo vệ dữ liệu.')


def report_values(report, old_headers):
    attendance = {(r['enrollment_id'], r['class_date']): r['present'] for r in report['attendance']}
    points = {(r['enrollment_id'], r['class_date']): r['total'] for r in report['points']}
    days = sorted({key[1] for key in attendance} | {key[1] for key in points}
                  | {parse_day(value) for value in old_headers[3:] if value})
    values = [roster_header(old_headers) + [day.strftime('%d-%m-%Y') for day in days]]
    for row in report['rows']:
        values.append([
            row['display_name'], row['discord_display_name'] or row['discord_username'],
            str(row['discord_uid']),
            *[float(points.get((row['id'], day), 0))
              if (row['id'], day) in points or (row['id'], day) in attendance else '' for day in days],
        ])
    return values, days, attendance


async def load_class_report(pool, class_id):
    async with pool.acquire() as conn:
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            metadata = await conn.fetchrow('''SELECT c.id,c.class_code,c.spreadsheet_id,
                c.attendance_sheet_id,s.data_version FROM classes c
                JOIN sheet_sync s ON s.class_id=c.id WHERE c.id=$1''', class_id)
            if metadata is None:
                raise ValueError('Không tìm thấy lớp để đồng bộ')
            rows = await conn.fetch('''SELECT id,discord_uid,discord_username,discord_display_name,display_name
                FROM enrollments WHERE class_id=$1 AND active=TRUE ORDER BY id''', class_id)
            attendance = await conn.fetch('''SELECT enrollment_id,class_date,present
                FROM attendance WHERE class_id=$1''', class_id)
            points = await conn.fetch('''SELECT enrollment_id,class_date,SUM(points) AS total
                FROM (
                    SELECT enrollment_id,class_date,points FROM point_transactions WHERE class_id=$1
                    UNION ALL
                    SELECT enrollment_id,class_date,points FROM reaction_awards WHERE class_id=$1
                ) p GROUP BY enrollment_id,class_date''', class_id)
    return {**dict(metadata), 'rows': [dict(r) for r in rows],
            'attendance': [dict(r) for r in attendance], 'points': [dict(r) for r in points]}


def write_class_report(credentials_path, report):
    from classbot.attendance import attendance_formats, column_name

    book = gspread.service_account(filename=credentials_path).open_by_key(report['spreadsheet_id'])
    worksheet = None
    if report['attendance_sheet_id'] is not None:
        worksheet = book.get_worksheet_by_id(report['attendance_sheet_id'])
    if worksheet is None:
        try:
            worksheet = book.worksheet(f"{report['class_code']} - Diem danh")
        except gspread.WorksheetNotFound:
            worksheet = book.add_worksheet(title=f"{report['class_code']} - Diem danh",
                                          rows=max(100, len(report['rows'])+1), cols=30)
    old_values = worksheet.get_all_values()
    headers = old_values[0] if old_values else []
    known_days = {r['class_date'] for r in report['attendance']} | {r['class_date'] for r in report['points']}
    for col, header in enumerate(headers[3:], start=3):
        if header and parse_day(header) not in known_days:
            if any(len(row)>col and row[col] != '' for row in old_values[1:]):
                raise ValueError('Có dữ liệu ngày trên Sheet chưa lưu trong DB; chưa thay danh sách để tránh mất lịch sử.')
    values, days, attendance = report_values(report, headers)
    width = len(values[0])
    height = len(values)
    if worksheet.col_count < width or worksheet.row_count < height:
        worksheet.resize(rows=max(height, worksheet.row_count), cols=max(width, worksheet.col_count))
    end = column_name(width)
    worksheet.update(values, range_name=f'A1:{end}{height}', raw=True)
    clear = []
    if len(old_values) > height:
        clear.append(f'A{height+1}:{column_name(max(width,len(headers)))}{len(old_values)}')
    if len(headers) > width:
        clear.append(f'{column_name(width+1)}1:{column_name(len(headers))}{max(height,len(old_values))}')
    if clear:
        worksheet.batch_clear(clear)
    if width > 3 and max(height, len(old_values)) > 1:
        formats = [{
            'range': f'D2:{column_name(max(width,len(headers)))}{max(height,len(old_values))}',
            'format': {'backgroundColor': {'red':1,'green':1,'blue':1}},
        }]
        for col, day in enumerate(days, start=4):
            states = [{'present': attendance.get((row['id'], day))} for row in report['rows']]
            formats.extend(attendance_formats(column_name(col), states))
        worksheet.batch_format(formats)
    worksheet.freeze(rows=1)
    return worksheet.id


async def sync_class_sheet(pool, *, credentials_path, class_id):
    async with _locks.setdefault(class_id, asyncio.Lock()):
        report = await load_class_report(pool, class_id)
        sheet_id = await asyncio.to_thread(write_class_report, credentials_path, report)
        async with pool.acquire() as conn:
            await conn.execute('UPDATE classes SET attendance_sheet_id=$2 WHERE id=$1', class_id, sheet_id)
            await conn.execute('''UPDATE sheet_sync SET synced_version=GREATEST(synced_version,$2)
                WHERE class_id=$1''', class_id, report['data_version'])
        return sheet_id
