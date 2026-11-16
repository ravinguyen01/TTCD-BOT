# Nghiệm thu bản bot hiện hành

Ngày: **16-11-2026**. Kết quả được cập nhật sau khi chạy bộ nghiệm thu phát hành; đây không phải chứng nhận toàn bộ tương tác người dùng trên Discord.

## Phạm vi

Nghiệm thu code bằng database PostgreSQL tách biệt mang tên `classbot_acceptance_<timestamp>`. Áp dụng schema và toàn bộ migration. Dữ liệu học viên/Discord/Sheet trong bài thử là giả; mỗi bài tích hợp hoàn tác transaction, script ngoài cùng xóa database thử sau khi chạy.

| Nhóm | Kiểm tra |
| --- | --- |
| Mô phỏng offline | Lớp độc lập, điểm danh cập nhật trong ngày, giao dịch chống lặp, mất role/quay lại và lịch sử |
| Thông báo và điểm | Sĩ số đúng, hai cột tên, fallback, lớp trống, tin dài Unicode, mọi màu da, đúng ID emoji tùy chỉnh, giới hạn điểm âm/lẻ |
| Xác minh | Định dạng thông tin, checkbox mặc định tắt/bắt buộc, cập nhật không trùng, persistent view, chờ nội quy, cấp role/lỗi quyền, dữ liệu Sheet |
| Tên hiển thị | Tên xác minh/server/global/username, trùng username, cập nhật tên và thành viên, tiêu đề tab cũ/mới |
| Danh sách và Sheet | Thêm/xóa, quét lại trong ngày, giữ ngày trước, không lệch điểm/màu khi xóa dòng, xóa dòng thừa, lớp trống, quay lại lấy lịch sử, chặn dữ liệu không có nguồn DB |
| Liên kết nick | Liên kết/gỡ/lặp, chống vòng/xung đột, tách server, gộp người, chính/phụ/cả hai/vắng, điểm chung/chống lặp/tự cộng, dữ liệu cũ |

## Chạy lại

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/acceptance.ps1
```

Điều kiện: Docker hoạt động, `.env` tồn tại theo `.env.example`. Token/ID có thể để trống khi chỉ chạy bài thử: runner không khởi động bot thật và không kết nối Discord/Google. Script build image, dùng PostgreSQL service hiện có nhưng tạo database thử riêng. Không restart bot đang phục vụ.

Runner từ chối `DATABASE_URL` không có tên database thử đúng mẫu. Fail một nhóm sẽ dừng và trả mã khác 0. Script PowerShell vẫn dọn database thử trong `finally`.

## Kết quả đợt này

- Tự động: **PASS, 6 nhóm**. Gồm 5 bài unittest mô phỏng, 7 bài unittest thông báo/emoji/giới hạn điểm và 4 nhóm tích hợp PostgreSQL (xác minh, tên, danh sách/Sheet, liên kết nick). Schema mới và 7 migration chạy thành công. Database thử được xóa sau nghiệm thu.
- Bot thật, kiểm tra chỉ đọc: **PASS**. Discord có đúng 12 lệnh; bot đang online và không có lỗi khởi động trong log đã lọc. Google Sheets truy cập được và 5 tab lớp có đúng ba cột định danh hỗ trợ. Không còn database nghiệm thu sau khi dọn.
- Nội dung Git: **PASS, 44 file UTF-8 staged** tại thời điểm kiểm tra, không có credential theo các mẫu đã kiểm tra; `.env`, khóa Google, SQLite và `plebot/` bị loại bằng Git ignore. Công cụ quét mẫu không bảo đảm phát hiện mọi loại dữ liệu nhạy cảm, cần giữ quy tắc chỉ stage source/tài liệu.

Kiểm tra lại file chuẩn bị commit bằng `python scripts/check_publish.py` và `git diff --cached --check`. Các kiểm tra này đọc đúng nội dung staged, không in giá trị có thể là token.

## Checklist tương tác người dùng cần admin xác nhận

- [ ] Tài khoản chưa có role nhìn thấy đúng kênh xác minh.
- [ ] Form mở trên thiết bị thực tế; không tick thì không gửi được; dữ liệu hợp lệ nhận role và lên đúng dòng Sheet.
- [ ] Gửi lại form cập nhật dòng cũ; nút tiếp tục hoạt động sau restart bot.
- [ ] Role sau xác minh xem được kênh giới thiệu; role lớp chỉ mở các kênh lớp phù hợp.
- [ ] `/diemdanh` trong voice lớp công bố đúng sĩ số/danh sách vắng trong kênh gọi; gọi lại cập nhật người vào trễ.
- [ ] Emoji và `/cong` âm/lẻ thông báo công khai, cập nhật cùng cột ngày, không cộng lại khi gỡ/thả cùng emoji.
- [ ] Liên kết hai nick của học viên đã được admin xác nhận, thử hiện diện bằng nick phụ.

Checklist chưa được đánh dấu không có nghĩa code thất bại; nghĩa là phiên nghiệm thu này chưa thao tác bằng tài khoản học viên thực tế để chứng minh điều đó.

## Giới hạn còn lại

Chưa nghiệm thu chạy 24/7 trên VPS, mất điện/mạng kéo dài, backup định kỳ/phục hồi thực tế và worker retry tab lớp. Các mục đó tiếp tục được theo dõi trong [plan](../plan.md), không được tính hoàn thành chỉ vì test code đã qua.
