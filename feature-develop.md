## YÊU CẦU:
Trong công việc thực tế, một NOC Engineer thực thụ không chỉ ngồi nhìn màn hình giám sát (Prometheus/Grafina alerts) mà còn giao tiếp và xử lý các yêu cầu (Requests) đến từ con người (Khách hàng, đối tác, đội dự án nội bộ) qua Email, Slack, Telegram, Microsoft Teams...

## PHÂN TÍCH:
Để hệ thống Hierarchical Multi-Agent NOC đáp ứng được bài toán thực tế này, cần nâng cấp hệ thống từ cơ chế "Chờ kích hoạt" (Reactive - dựa trên alert) sang cơ chế "Chủ động đón nhận" (Inbound Gateways).
Dưới đây là kiến trúc giải pháp và các bước cụ thể cần thực hiện để tích hợp các kênh giao tiếp này vào hệ thống Agent hiện tại:

1. Kiến trúc luồng xử lý Request từ Khách hàng
Khi có yêu cầu từ Group Chat hoặc Email, luồng xử lý sẽ được chuyển đổi như sau:
Inbound Gateways (Webhook/Polling): Nhận tin nhắn từ Telegram/Slack hoặc Email.
LLM Parser (Nằm trong Supervisor): Trích xuất thông tin (Intent, Tên thiết bị, Khách hàng, Mức độ ưu tiên).
Jira Lifecycle: Tự động tạo Ticket loại Service Request thay vì Incident.
Worker Orchestration: Supervisor điều phối đúng Agent (Ví dụ: Yêu cầu kiểm tra cấu hình -> Expert Agent; Yêu cầu báo cáo -> Customer Advisory Agent).
2. Kiến trúc luồng xử lý Alert có phân loại
Mô phỏng Công cụ Phân tích Yêu cầu khách hàng (Interactive Request Parser)
Mô phỏng cách hệ thống Agent xử lý các tin nhắn từ group chat/email của khách hàng, công cụ dưới đây mô phỏng quá trình Intent Routing (Phân loại ý định) và Entity Extraction (Trích xuất thực thể) của Supervisor Agent trước khi tạo Jira Task.
{
"component": "LlmGeneratedComponent",
"props": {
"height": "600px",
"prompt": "Mục tiêu: Mô phỏng bộ phân tích tin nhắn yêu cầu của khách hàng (NOC Request Parser) dành cho Supervisor Agent để chuyển đổi ngôn ngữ tự nhiên thành dữ liệu có cấu trúc cho hệ thống NOC.\n\nTrạng thái dữ liệu ban đầu:\n- Cung cấp sẵn 3 kịch bản tin nhắn mẫu thực tế của NOC:\n  1. "Hi team, nhờ check giúp link peering giữa srx-core-01 và đối tác bên VNG đang bị loss gói từ 9h sáng nay."\n  2. "Nhờ NOC dump cấu hình interface ge-0/0/1 của switch qfx-leaf-02 ra file text gửi qua email giúp mình nhé, cần gấp để audit."\n  3. "Bên em mới gửi phiếu yêu cầu hỗ trợ tạo ticket bảo trì định kỳ cho cụm EX-Switch vào đêm nay, mã phiếu #1102."\n\nChiến lược giao diện: Form Layout kết hợp bảng phân tích kết quả.\n\nCác điều khiển đầu vào:\n- Ô nhập văn bản (TextArea) để người dùng tự nhập hoặc chọn từ kịch bản mẫu.\n- Danh sách thả chọn (Dropdown) để chọn nhanh 3 kịch bản mẫu nêu trên.\n- Nút bấm "Phân tích Request" để kích hoạt quá trình mô phỏng LLM Parser.\n\nHành vi và logic tương tác:\n- Khi người dùng chọn một kịch bản mẫu, tự động điền nội dung vào ô nhập văn bản.\n- Khi bấm "Phân tích Request", hệ thống mô phỏng LLM sẽ bóc tách và hiển thị kết quả ở bên dưới bao gồm:\n  + Intent (Ý định): Xác định xem đây là Triage/Analytics (Sự cố Link/Loss), Expert (Yêu cầu cấu hình/Dump config), hay Customer Advisory (Thủ tục/Bảo trì).\n  + Target Device (Thiết bị đích): Trích xuất tên thiết bị (Ví dụ: srx-core-01, qfx-leaf-02).\n  + Priority (Mức độ ưu tiên): Thấp, Trung bình, Cao, Khẩn cấp (dựa trên từ khóa như 'gấp', 'loss gói').\n  + Đề xuất Worker Agent chịu trách nhiệm chính.\n  + Bản nháp tiêu đề và nội dung để gọi công cụ create_jira_task.\n- Thiết kế giao diện rõ ràng, phân định phần nhập liệu và phần kết quả phân tích trực quan."
}
}
3. Những việc cần làm cụ thể trong Code để đạt yêu cầu này
Để đưa tính năng này vào dự án chạy thực tế, cần triển khai 3 cấu phần sau:

Bước A: Mở rộng supervisor-network-engineer-agent/main.py (Multi-Channel Gateways)
Hiện tại Supervisor chỉ có Telegram Long-polling. Cần mở rộng cổng nhận tin nhắn (Inbound):
Slack Webhook / Events API: Tạo một endpoint /webhook/slack bằng FastAPI để nhận payload khi có người tag agent hoặc chat trong group.
Email Inbound Gateway (IMAP/Mailgun): Viết một script nhỏ (hoặc dùng dịch vụ như Mailgun Webhook) để lắng nghe hòm thư claw.a.thon.noc.agent.greennode01@gmail.com. Khi có email mới, parse nội dung Email (Subject, Body) thành một chuỗi văn bản và gửi vào API của Supervisor.

Bước B: Cập nhật system_prompt.py của Supervisor Agent
Cần dạy cho Supervisor cách phân biệt giữa Alert tự động và Request từ con người.
Bổ sung vào phần Intent Routing Guidelines góc nhìn sau:
Nếu nội dung bắt đầu bằng định dạng Alert (Prometheus...) -> Chuyển cho analytics-network-engineer-agent để đối chiếu trạng thái hạ tầng.
Nếu nội dung là yêu cầu tra cứu thông tin, lấy log, kiểm tra cấu hình từ khách hàng -> Chuyển trực tiếp sang expert-engineer-agent để lấy dữ liệu thời gian thực qua MCP.
Nếu nội dung là yêu cầu làm báo cáo, giải trình, thủ tục bảo trì -> Chuyển cho customer-advisory-agent.
Bước C: Thiết lập cấu trúc Jira Task linh hoạt hơn
Trong file agent_tools.py của các Worker, hàm create_jira_task cần bổ sung tham số issue_type:
Incident: Dành cho Alert hệ thống bị lỗi.
Service Request: Dành cho khách hàng yêu cầu hỗ trợ (Ví dụ: Mở port, xin cấu hình, kiểm tra IP).
Change Request: Dành cho các yêu cầu thay đổi cấu hình thiết bị có rủi ro cao.