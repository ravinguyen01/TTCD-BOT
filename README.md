# Bot quản lý lớp học Trung tâm Chí Dũng

Bot Discord dùng Python 3.11, discord.py, PostgreSQL và Google Sheets. PostgreSQL giữ dữ liệu gốc; Sheets hiển thị báo cáo. Bot hiện chạy bằng Docker Compose trên máy cá nhân, chưa được chuyển lên VPS.

## Lệnh và quyền

| Lệnh | Chức năng | Quyền người dùng |
| --- | --- | --- |
| `/kiemtra` | Kiểm tra kết nối trong kênh đã cấu hình | Mọi người trong kênh đó |
| `/sheetcheck` | Kiểm tra kết nối Google Sheet | Manage Server |
| `/add role` | Cấp role cho người đang cùng voice | Manage Roles |
| `/taodanhsach role` | Tạo/cập nhật danh sách theo role | Manage Roles |
| `/diemdanh role` | Cập nhật danh sách, quét voice và công bố kết quả | Manage Roles |
| `/cong role hoc_vien diem` | Cộng/trừ điểm ngày hiện tại | Role giáo viên hoặc Manage Roles |
| `/ganrole role` | Gắn kênh text/chat voice với lớp để nhận emoji | Manage Roles |
| `/gankenh role` | Tên gọi khác của `/ganrole` | Manage Roles |
| `/goganrole` | Gỡ liên kết của kênh hiện tại | Manage Roles |
| `/setupxacminh kenh role [chinh_sach]` | Đặt nút xác minh và chọn role tự cấp | Manage Roles |
| `/lienketnick chinh phu` | Liên kết hai tài khoản cùng học viên | Manage Roles |
| `/golienketnick phu` | Gỡ liên kết tài khoản phụ | Manage Roles |

Bot kiểm tra quyền trong lúc xử lý. Role giáo viên được nhận diện bằng `TEACHER_ROLE_ID`; đổi tên role không ảnh hưởng. Hiện giáo viên có thể cộng điểm cho mọi lớp đã cấu hình, chưa giới hạn theo lớp phụ trách.

## Cài đặt trên Windows

1. Cài Docker Desktop, mở Docker và chờ engine chạy.
2. Sao chép `.env.example` thành `.env`, tự điền trên máy:

   ```powershell
   Copy-Item .env.example .env
   ```

   | Biến | Giá trị cần điền |
   | --- | --- |
   | `BOT_TOKEN` | Token bot Discord |
   | `APPLICATION_ID` | Application ID của bot |
   | `GUILD_ID` | Server Discord |
   | `BOT_TEST_CHANNEL_ID` | Kênh cho `/kiemtra` |
   | `TEACHER_ROLE_ID` | Role giáo viên được cộng điểm |
   | `SPREADSHEET_ID` | ID file Google Sheets đích |

3. Lưu khóa service account Google vào `secrets/google.json`, bật Google Sheets API và chia sẻ file Sheet cho email service account với quyền Editor. Khóa được mount chỉ đọc, không nằm trong image.
4. Bật **Server Members Intent** trong Discord Developer Portal. Bot cần View Channel, Read Message History, Send Messages; thêm Embed Links để thông báo có hai cột. Để cấp role, bot cần Manage Roles và role cao hơn role được cấp. Người dùng cần quyền dùng Application Commands trong kênh.
5. Khởi động:

   ```powershell
   docker compose --profile online up -d --build bot
   docker compose --profile online ps
   ```

6. Dùng `/kiemtra` trong kênh đã cấu hình, rồi `/sheetcheck`.

Database mới được tạo từ `classbot/schema.sql` ở lần tạo volume đầu. Database cũ không tự chạy lại schema; xem [migration và vận hành](docs/operations.md). Dependency đã được khóa trong `requirements.txt`. Máy chủ Linux dùng Docker Engine và Compose.

Compose dùng mật khẩu PostgreSQL mẫu cho mạng Docker cục bộ và chỉ mở cổng database trên `127.0.0.1`. Khi chuyển VPS cần cấu hình lại mật khẩu, lưu trữ và sao lưu trước khi sử dụng thực tế.

## Danh sách và điểm danh

`/taodanhsach role:@Lớp` quét toàn server, kể cả người offline. Mỗi lần gọi thêm người mới, cập nhật tên và đưa người mất role ra khỏi danh sách hoạt động cùng tab lớp. Lớp hết thành viên vẫn cập nhật được về bảng trống. Lịch sử người rời lớp vẫn trong database và được lấy lại nếu tài khoản đó quay lại.

Tên được ưu tiên: **họ tên xác minh → biệt danh server → tên hiển thị Discord → username**. Cột `Tên Discord` dùng tên hiển thị; username lưu riêng trong DB. Discord UID là khóa đối chiếu, không gộp người chỉ vì trùng tên.

Admin vào voice và gọi `/diemdanh role:@Lớp`. Mỗi lần gọi đều cập nhật danh sách và điểm danh **ngày hiện tại theo giờ Việt Nam** theo voice lúc nhận lệnh. Gọi lại trong ngày thay kết quả hôm nay; các ngày trước và giao dịch điểm không thay đổi. Bot công bố sĩ số, hiện diện, vắng và hai cột họ tên/tên Discord của người vắng tại kênh gọi lệnh. Danh sách dài chia nhiều tin, không ping hàng loạt.

Tab lớp có `Họ và tên`, `Tên Discord`, `Discord UID`, rồi cột ngày `dd-mm-yyyy`. Ô ngày hiện **tổng điểm**, nền xanh là hiện diện, đỏ là vắng, trắng là chưa điểm danh. Đã điểm danh mà chưa có điểm thì hiện `0`. Khi thay danh sách, bot dựng lại các cột theo ID để không lệch điểm/màu. Nếu gặp dữ liệu ngày trên Sheet không có trong database, bot chặn ghi đè để tránh mất dữ liệu.

## Cộng và trừ điểm

Giáo viên hoặc người có Manage Roles vào voice và dùng `/cong role:@Lớp hoc_vien:@Bạn diem:-0.5`. Điểm từ `-100` đến `100`, khác `0`, tối đa hai số thập phân. Mỗi lệnh mới là một giao dịch mới; giao nhận lặp cùng interaction ID chỉ tính một lần.

Admin dùng `/ganrole role:@Lớp` trong kênh text hoặc chat voice. Giáo viên thả emoji vào tin nhắn học viên để cộng điểm:

| Emoji | Điểm |
| --- | ---: |
| 👍, mọi màu da | +0.1 |
| 🫰, mọi màu da | +0.2 |
| ⭐ | +0.5 |
| Emoji server `:1000:` | +1 |

ID `:1000:` nằm trong `classbot/reaction.py`, cần đổi khi chuyển server. Mỗi cặp kênh/tin nhắn/giáo viên/emoji tính một lần. Gỡ rồi thả lại không cộng thêm; gỡ emoji không trừ điểm. Không tính tin nhắn bot hoặc tự thả cho mình, kể cả bằng nick phụ. Học viên thông thường không được thả emoji cộng điểm.

Điểm từ lệnh và emoji vào cùng cột ngày; bot thông báo công khai. Nếu Sheets lỗi, điểm vẫn giữ trong DB. **Không gọi lại `/cong` chỉ để thử đồng bộ**, vì lệnh mới sẽ cộng/trừ thêm. Tab lớp chưa có bộ tự thử lại nền đầy đủ; xem [cách đồng bộ không tạo điểm mới](docs/operations.md).

## Hai tài khoản của một học viên

Admin dùng `/lienketnick chinh:@A phu:@B`, ưu tiên nick chính đã xác minh. Chạy lại danh sách/điểm danh sau thay đổi. Có role lớp trên một trong hai tài khoản thì học viên thuộc lớp; chỉ tính một người. Nick chính hoặc phụ ở voice đều tính hiện diện. Điểm mới về nick chính; giao dịch cũ không tự cộng gộp lại.

`/golienketnick phu:@B` tách hai tài khoản. Chạy lại danh sách/điểm danh để tính riêng. Bot chặn liên kết vòng và nick phụ thuộc hai nick chính. Không tự gộp theo tên/điện thoại/Facebook, không đổi role khi liên kết.

## Xác minh

`/setupxacminh kenh:#xác-minh role:@ĐãXácMinh` tạo bảng có nút **Xác minh**. Tùy chọn `chinh_sach` nhận link HTTPS. Setup lại làm bảng cũ hết hiệu lực; nút tiếp tục hoạt động sau restart.

Chat: “Chào bạn đã đến với Trung tâm Chí Dũng. Hãy bấm nút Xác minh bên dưới để tham gia server.” Form gồm họ tên, điện thoại Việt Nam (10 số hoặc +84), Facebook HTTPS và checkbox bắt buộc “Tôi đồng ý chia sẻ thông tin để được Trung tâm hỗ trợ.” Checkbox mặc định tắt.

Bot lưu hồ sơ theo Discord UID, cấp role đã chọn và hướng người dùng đến kênh giới thiệu lớp. Kênh đích hiện đặt trong `classbot/onboarding.py`, cần đổi khi chuyển server. Form và phản hồi riêng tư; thông tin liên hệ được đồng bộ lên tab **Xác minh**. Gửi lại cập nhật cùng dòng. Số điện thoại/ID giữ dạng chuỗi, ghi RAW.

Nếu cấp role lỗi hoặc người dùng chưa chấp nhận nội quy Discord, bot giữ trạng thái chờ và thử lại mỗi phút. Đồng bộ tab Xác minh cũng tự thử lại. Admin cấu hình quyền kênh: người mới thấy kênh xác minh; role sau xác minh thấy khu giới thiệu; role từng lớp mở kênh lớp. Bot không tự sửa quyền kênh và chưa tự đổi biệt danh.

## Nghiệm thu và vận hành

- [Kế hoạch và phần còn thiếu](plan.md)
- [Vận hành, migration và sao lưu thủ công](docs/operations.md)
- [Phạm vi, kết quả và checklist nghiệm thu](docs/acceptance.md)

Chạy nghiệm thu trên Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/acceptance.ps1
```

Script tạo database thử riêng, áp dụng schema/migrations, dùng dữ liệu giả rồi xóa database thử. Bộ kiểm tra không thao tác role hay gửi tin nhắn thật. Discord/Sheets doubles không thay việc thử tương tác bằng tài khoản học viên thật.

## Dữ liệu và GitHub

`.env`, `secrets/`, database/dump, log, cache và `plebot/` tham khảo không được đưa vào Git. Không đưa token/khóa Google lên issue, commit hoặc ảnh chụp. Trung tâm cần quản lý người được đọc Sheet có thông tin liên hệ, thời gian lưu và đầu mối sửa/xóa hồ sơ.

`plebot/` là source tham khảo cũ tại máy, không thuộc bản bot mới xuất bản. Không dùng dependency hoặc credential của source đó cho `classbot/`.
