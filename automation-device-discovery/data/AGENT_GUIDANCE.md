# Network Monitor Lab - AI Agent Guidance

Tài liệu này cung cấp ngữ cảnh kỹ thuật và hướng dẫn vận hành cho AI Agent trong môi trường Lab Giám sát Mạng.

## 1. Tổng quan Kiến trúc (Network Topology)
Hệ thống được thiết kế theo mô hình Spine-Leaf kết hợp Gateway và Server layer.

### Phân lớp thiết bị:
- **Spine Layer:** Đóng vai trò Core, kết nối các Gateway và Leaf. Sử dụng dòng QFX5210.
- **Leaf Layer:** Kết nối các thiết bị đầu cuối và Server. Sử dụng dòng EX4400.
- **Gateway Layer:** 
    - *Internal Gateway (STL.GW):* Xử lý traffic nội bộ, chạy EVPN/VXLAN.
    - *Internet Gateway:* Kết nối ra ngoài thông qua ISP (VNPT).
- **Server Layer (Ubuntu):** Chạy các ứng dụng giám sát (Net-Monitor) và cổng thông tin (NOC Portal).

## 2. Danh mục Thiết bị Mục tiêu (Target Devices)

| Hostname | IP | Role | Model | Access (Primary/Fallback) |
| :--- | :--- | :--- | :--- | :--- |
| LAB-LEAF-01 | 10.116.0.158 | Leaf | EX4400 | Port 830 / 22 (SSH) |
| LAB_2BW14.30_SPN.01 | 10.116.1.102 | Spine | QFX5210 | Port 830 / 22 (SSH) |
| LAB_2BW14.27_SPN.02 | 10.116.1.103 | Spine | QFX5210 | Port 830 / 22 (SSH) |
| STL.GW.01 | 10.116.1.98 | Gateway | QFX5120 | Port 22 (SSH) |
| STL.GW.02 | 10.116.1.99 | Gateway | QFX5120 | Port 830 / 22 (SSH) |
| INTERNET-GW-01 | 10.116.0.54 | Internet GW | EX4400 | Port 830 / 22 (SSH) |
| noc-portal-app | 10.116.0.176 | Server | Ubuntu | Port 8822 / 9922 (SSH) |
| net-monitor | 10.116.0.175 | Server | Ubuntu | Port 8822 (SSH) |

## 3. Thông tin Truy cập & Bảo mật
- **User/Pass:** `root / vnd@123#` hoặc `thinhle / thinhle@123#`.
- **Phương thức:** Ưu tiên Netconf (port 830) cho Juniper, fallback về SSH (port 22). Với Linux, sử dụng các port custom (8822, 9922).

## 4. Framework Tự động hóa (Automation Scripts)
AI Agent nên sử dụng các script trong thư mục `automation/` để thực hiện nhiệm vụ:

1.  **`re_discovery.py`**: Thực hiện discovery mục tiêu, kiểm tra port và xác thực.
    - *Output:* `re_discovery_results.json`
2.  **`re_collect.py`**: Thu thập dữ liệu chi tiết (LLDP, BGP, Interface, Route).
    - *Output:* `re_topology_raw_data.json`
3.  **`summarize_results.py`**: Phân tích dữ liệu thô và xuất báo cáo Markdown.

## 5. Các lưu ý kỹ thuật (Quirks & Troubleshooting)
- **License Warning:** Dòng EX4400 thường báo lỗi "License key missing" khi chạy BGP, nhưng vẫn cho phép hoạt động trong môi trường Lab. Agent có thể bỏ qua cảnh báo này khi parse log.
- **LLDP trên Linux:** Nếu lệnh `lldptool` lỗi, server có thể chưa cài `lldpad`. Cần kiểm tra và cài đặt nếu cần thu thập topology từ server.
- **BGP Internet GW:** Thiết bị `INTERNET-GW-01` hiện không chạy BGP, định tuyến qua Static Route.

## 6. Quy trình Vận hành Chuẩn (SOP) cho Agent
1. **Bước 1:** Chạy `re_discovery.py` để cập nhật trạng thái online/offline của thiết bị.
2. **Bước 2:** Dựa vào file kết quả, chạy `re_collect.py` để lấy dữ liệu mới nhất.
3. **Bước 3:** Sử dụng `summarize_results.py` hoặc tự phân tích file JSON để trả lời các câu hỏi về Topology hoặc trạng thái Routing của người dùng.
