# Vận hành bot

Các lệnh bên dưới chạy ở thư mục có `compose.yaml`. Hướng dẫn dùng PowerShell trên Windows, Docker Desktop đang hoạt động.

## Chạy, cập nhật và dừng

```powershell
docker compose --profile online up -d --build bot
docker compose --profile online ps
docker compose --profile online stop bot
```

Lệnh cuối chỉ dừng bot, không xóa database. Không dùng `docker compose down -v` để cập nhật: `-v` xóa volume chứa dữ liệu. Docker phải đang chạy và máy không được tắt/ngủ nếu bot phục vụ từ máy cá nhân.

Sau cập nhật, dùng `/kiemtra` và `/sheetcheck`. Khi chuyển VPS, sao lưu và chuyển database trước, chuyển secret qua kênh riêng, dừng bản bot cũ rồi mới bật bản chính ở VPS.

## Migration cho database đã tồn tại

`schema.sql` chỉ tự chạy lúc PostgreSQL tạo volume lần đầu. Trước khi cập nhật database thật, tạo bản backup. Áp dụng các migration theo thứ tự tên file:

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Get-ChildItem classbot/migrations/*.sql | Sort-Object Name | ForEach-Object {
    Get-Content -Raw -Encoding UTF8 $_.FullName |
        docker compose exec -T db psql -U classbot -d classbot -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw "Migration failed: $($_.Name)" }
}
```

Các migration hiện tại có thể chạy lại. Bộ nghiệm thu kiểm tra schema mới cùng toàn bộ migration trên database thử riêng. Không chạy SQL do nguồn không rõ cung cấp.

## Đồng bộ Sheet mà không cộng điểm mới

Hồ sơ xác minh/cấp role tự thử lại mỗi phút. Tab lớp hiện đồng bộ khi có lệnh/emoji; chưa có worker retry nền đầy đủ.

Nếu điểm đã lưu nhưng Sheet lỗi, sửa quyền/kết nối rồi chạy:

```powershell
docker compose --profile online exec -T bot python -m classbot.repaint_attendance
```

Lệnh này dựng lại các tab lớp do bot quản lý từ PostgreSQL, không cộng điểm hoặc quét lại voice. Chạy lại `/diemdanh` sẽ quét và thay kết quả hôm nay; chỉ dùng khi muốn cập nhật hiện diện/vắng.

Nếu báo có dữ liệu ngày trên Sheet chưa lưu trong DB, không xóa tùy tiện. Giữ bản sao Sheet và xác định nguồn dữ liệu trước; bot đang chặn ghi đè để tránh mất lịch sử.

Làm mới tên hiển thị của các tài khoản đã nằm trong danh sách:

```powershell
docker compose --profile online exec -T bot python -m classbot.refresh_roster_names
```

Lệnh không đổi role, điểm hoặc trạng thái điểm danh; quét Discord và dựng lại nhãn trên các tab lớp.

## Backup thủ công

Dump chứa hồ sơ cá nhân, cần lưu ở nơi chỉ người được phép truy cập. `backups/` không được đưa lên Git. Không chuyển binary dump qua toán tử `>` của PowerShell; tạo file trong container rồi sao chép ra:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$backupName = 'classbot-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
docker compose exec -T db sh -c 'pg_dump -U classbot -d classbot -Fc -f /tmp/classbot-backup.dump'
if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
docker compose cp db:/tmp/classbot-backup.dump "backups/$backupName"
if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed' }
```

Đây là backup thủ công, chưa có lịch tự động hoặc sao lưu ra máy khác. Giữ bản sao ngoài máy chạy bot để phòng hỏng ổ đĩa.

## Thử phục hồi, không ghi đè database đang chạy

Chọn một dump và đặt tên database phục hồi mới, chưa tồn tại:

```powershell
docker compose cp backups/classbot-YYYYMMDD-HHMMSS.dump db:/tmp/classbot-restore.dump
docker compose exec -T db createdb -U classbot classbot_restorecheck
docker compose exec -T db pg_restore -U classbot --exit-on-error -d classbot_restorecheck /tmp/classbot-restore.dump
```

Kiểm tra bảng, số dòng và một số báo cáo trong `classbot_restorecheck` trước khi lên kế hoạch thay database chính. Không tự trỏ bot vào bản phục hồi khi chưa kiểm tra dữ liệu. Chưa có lịch thử phục hồi định kỳ.

## Chẩn đoán

| Hiện tượng | Kiểm tra |
| --- | --- |
| Bot offline | Docker có mở không, máy có ngủ không, trạng thái `docker compose ... ps` |
| `/kiemtra` không phản hồi như mong đợi | Đúng kênh `BOT_TEST_CHANNEL_ID`, quyền Application Commands, bot online |
| Không cấp được role | Manage Roles, thứ tự role bot, role không phải role tích hợp; đã chấp nhận nội quy Discord |
| Emoji không cộng | Đúng kênh đã gắn lớp, đúng emoji, người thả có quyền, tác giả là học viên, chưa tính cặp tin nhắn/người thả/emoji |
| Tin vắng không thấy | Bot được xem/gửi tin tại kênh gọi lệnh; Embed Links cho dạng hai cột |
| Sheet không cập nhật | Service account còn quyền Editor, đúng Sheet ID, API/khóa hoạt động, không đổi tiêu đề tab do bot quản lý |

Có thể xem log bằng `docker compose --profile online logs --tail 50 bot`. Không gửi log thô lên GitHub nếu chưa kiểm tra có token, đường dẫn nhạy cảm hoặc thông tin học viên hay không.

## Tác vụ role hàng loạt

`python -m classbot.grant_existing_role ROLE_ID` chỉ kiểm tra. Thêm `--apply` để cấp, hoặc `--remove --apply` để gỡ. Tác vụ bỏ qua bot, xử lý snapshot thành viên và tuân theo giới hạn API. Không tự chạy tác vụ này lúc deploy/nghiệm thu; chỉ dùng khi admin yêu cầu rõ role và phạm vi. Không còn tác vụ cấp/gỡ role hàng loạt tự động trong luồng xác minh.
