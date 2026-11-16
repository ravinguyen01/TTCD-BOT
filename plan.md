# Kế hoạch và trạng thái bot lớp học

Cập nhật **16-11-2026**, theo code hiện hành trong `classbot/`. Tài liệu này thay các đề xuất cũ đã được điều chỉnh trong quá trình chạy thử.

## Đã triển khai

| Nhóm | Hành vi hiện tại |
| --- | --- |
| Nền tảng | Python 3.11, discord.py 2.7.1, PostgreSQL 16, Docker Compose; dependency khóa phiên bản |
| Danh sách | Quét role toàn server; thêm người mới, bỏ người mất role khỏi danh sách hoạt động/Sheet; hỗ trợ lớp trống |
| Tên | Ưu tiên họ tên xác minh, biệt danh server, tên hiển thị Discord, username; khóa đối chiếu là UID |
| Điểm danh | Cập nhật danh sách và quét voice của admin; gọi lại thay kết quả ngày hiện tại, giữ ngày trước |
| Công khai | Sĩ số/hiện diện/vắng; người vắng có họ tên và tên Discord; chia tin dài, không ping |
| Điểm | Số âm/lẻ; transaction ID chống tính lặp; lệnh và emoji vào cùng cột ngày |
| Emoji | 👍 +0.1; 🫰 +0.2, mọi màu da; ⭐ +0.5; emoji server `:1000:` +1 |
| Kênh | `/ganrole` hoặc `/gankenh` trong text/chat voice; `/goganrole` để gỡ |
| Hai nick | `/lienketnick`, `/golienketnick`; một học viên, nick nào ở voice cũng tính có mặt; điểm mới về nick chính |
| Xác minh | Form riêng tư ba trường + checkbox; cập nhật hồ sơ/cấp role; thử lại lỗi; persistent button |
| Sheets | Tab Xác minh riêng; mỗi lớp một tab danh sách/điểm danh/điểm; ngày dd-mm-yyyy, có mặt xanh/vắng đỏ; đồng bộ theo ID khi xóa dòng |

Lịch sử người mất role giữ trong PostgreSQL để lấy lại khi quay về lớp. Nick phụ không tạo thêm học viên hoạt động. Liên kết không tự cộng gộp giao dịch cũ. Hồ sơ xác minh là tự khai; bot kiểm tra định dạng, không xác minh quyền sở hữu Facebook/điện thoại.

## Nghiệm thu

Các nhóm kiểm tra: xác minh/đồng ý/cấp role; tên hiển thị; thêm/xóa người; quét lại trong ngày; điểm giao dịch; liên kết nick; dữ liệu/màu Sheet; thông báo dài. Chạy trên PostgreSQL thử riêng, Discord/Sheets dùng doubles. Kết quả và cách chạy lại ở [biên bản nghiệm thu](docs/acceptance.md).

Kiểm tra bot thật khi phát hành chỉ đọc trạng thái, lệnh và kết nối. Checklist tương tác bằng tài khoản học viên thật được ghi riêng; test tự động không được tính là đã nghiệm thu giao diện Discord.

## Còn thiếu trước vận hành ổn định

| Ưu tiên | Công việc | Điều kiện hoàn thành |
| --- | --- | --- |
| 1 | Đồng bộ nền tab lớp khi Sheets lỗi | Chờ cập nhật qua restart, tự thử lại có backoff, không tạo điểm mới |
| 1 | Backup định kỳ và phục hồi | Sao lưu ngoài máy chạy bot; thử khôi phục trên DB riêng |
| 1 | Chạy 24/7 | Có VPS; chuyển DB/secret; kiểm tra sau reboot; chỉ một bot chính |
| 2 | Báo lỗi tập trung | Log/cảnh báo không lộ token hoặc hồ sơ |
| 2 | Nghiệm thu người dùng | Thử tài khoản học viên thật, quyền kênh trước/sau xác minh và sau restart |
| 2 | Quản trị hồ sơ | Chốt người được đọc, thời gian lưu, đầu mối sửa/xóa, chính sách của Trung tâm |

Hướng dẫn backup thủ công không đồng nghĩa đã có backup tự động. `restart: unless-stopped` không giữ bot online khi máy cá nhân hoặc Docker tắt. Chưa triển khai lên VPS.

## Đã bàn, chưa triển khai

- Tự đổi biệt danh server theo họ tên xác minh.
- Menu lớp miễn phí/có phí và yêu cầu tư vấn.
- Chăm sóc trước/sau buổi đầu, nhắc theo lựa chọn của người dùng.
- Phân quyền giáo viên theo từng lớp; hiện dùng một role giáo viên chung.

## Bảo toàn dữ liệu

PostgreSQL là dữ liệu chuẩn; các tab lớp được dựng lại theo UID. Tab Xác minh phản chiếu hồ sơ đã đồng ý. Không tự nhận sửa tay trên Sheet thành giao dịch điểm hay hồ sơ chuẩn. Không xóa giao dịch khi gỡ emoji/nick hoặc mất role. Không đưa credential, dump hoặc hồ sơ học viên vào Git.

`plebot/` chỉ là tham khảo cũ tại máy, không thuộc source mới được xuất bản.
