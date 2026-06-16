"""Telegram Bot Integration for Network Engineer Agent.

Runs Telegram bot polling in a background thread alongside the
HTTP server. Handles /start, /help, /sessions, and /logs commands.
"""

import os
import asyncio
import logging
import json
import redis
from markdown_converter import markdown_to_telegram_html

logger = logging.getLogger(__name__)

# Redis setup for accessing session states
REDIS_HOST = os.environ.get("REDIS_HOST", "49.213.77.222")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True
    )
except Exception as e:
    logger.error(f"Redis connection failed in Telegram Bot: {e}")
    redis_client = None


def start_telegram_bot(process_message_fn, bot_token: str):
    """Run Telegram bot polling in a background thread."""
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        filters,
    )

    logger.info("Starting Telegram bot...")

    async def cmd_start(update: Update, context) -> None:
        """Handle /start command."""
        welcome = (
            "🔧 *NOC Supervisor Telegram Bot*\n\n"
            "Xin chào! Tôi là Network Engineer AI.\n"
            "Bạn có thể tương tác với tôi hoặc tra cứu session logs bằng các lệnh sau:\n\n"
            "• `/sessions` — Liệt kê danh sách các phiên xử lý sự cố (sessions) đang hoạt động\n"
            "• `/logs <session_id>` — Xem chi tiết logs chẩn đoán của một session\n"
            "• `/help` — Hướng dẫn chi tiết\n\n"
            "Gửi tin nhắn bình thường để bắt đầu một phiên chẩn đoán mới! 🚀"
        )
        await update.message.reply_text(welcome, parse_mode="Markdown")

    async def cmd_help(update: Update, context) -> None:
        """Handle /help command."""
        help_text = (
            "📖 *Hướng dẫn sử dụng bot NOC*\n\n"
            "*Tra cứu log chẩn đoán:*\n"
            "• Dùng lệnh `/sessions` để lấy danh sách session ID.\n"
            "• Dùng lệnh `/logs <session_id>` để xem toàn bộ logs chẩn đoán của session đó.\n\n"
            "*Tương tác trực tiếp:*\n"
            "• Gửi yêu cầu bằng tiếng Việt hoặc tiếng Anh (ví dụ: `kiểm tra link flapping trên srx-core-01`).\n"
            "• Hệ thống sẽ tự tạo session và điều phối xử lý tự động.\n\n"
            "*Lệnh có sẵn:*\n"
            "/start — Bắt đầu\n"
            "/sessions — Liệt kê các session\n"
            "/logs <session_id> — Lấy log session\n"
            "/help — Hướng dẫn"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def cmd_sessions(update: Update, context) -> None:
        """Handle /sessions command to list active sessions."""
        if not redis_client:
            await update.message.reply_text("❌ Lỗi: Không thể kết nối tới cơ sở dữ liệu Redis.")
            return

        try:
            keys = redis_client.keys("state:*")
            if not keys:
                await update.message.reply_text("📭 Hiện tại không có session nào đang hoạt động.")
                return

            sessions_info = []
            # Sort keys to show the most recent sessions
            keys.sort(reverse=True)
            for key in keys[:15]:  # limit to 15 to avoid telegram message size limit
                session_id = key.split("state:", 1)[1]
                data = redis_client.get(key)
                if data:
                    try:
                        state_data = json.loads(data)
                        symptoms = state_data.get("symptoms", "No details")[:50]
                        jira = state_data.get("jira_issue_key", "None")
                        assignee = state_data.get("current_assignee", "unknown")
                        sessions_info.append(f"🔹 *ID*: `{session_id}`\n  • Assignee: `{assignee}`\n  • Jira: `{jira}`\n  • Symptoms: {symptoms}")
                    except Exception:
                        sessions_info.append(f"🔹 *ID*: `{session_id}` (Lỗi parse data)")
            
            msg = "📋 *Danh sách 15 Session gần nhất:*\n\n" + "\n\n".join(sessions_info)
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            await update.message.reply_text(f"❌ Có lỗi xảy ra: {e}")

    async def cmd_logs(update: Update, context) -> None:
        """Handle /logs <session_id> command."""
        if not redis_client:
            await update.message.reply_text("❌ Lỗi: Không thể kết nối tới cơ sở dữ liệu Redis.")
            return

        if not context.args:
            await update.message.reply_text("⚠️ Vui lòng cung cấp session ID. Ví dụ: `/logs email:user@example.com` hoặc `/logs user-report-1`")
            return

        session_id = " ".join(context.args).strip()
        try:
            data = redis_client.get(f"state:{session_id}")
            if not data:
                await update.message.reply_text(f"🔍 Không tìm thấy session nào với ID `{session_id}`")
                return

            state_data = json.loads(data)
            logs = state_data.get("diagnostic_logs", [])
            symptoms = state_data.get("symptoms", "No details")
            jira = state_data.get("jira_issue_key", "None")
            assignee = state_data.get("current_assignee", "Finished" if state_data.get("current_assignee") == "FINISH" else state_data.get("current_assignee", "unknown"))

            log_text = f"📋 *Session Logs for `{session_id}`*\n"
            log_text += f"━━━━━━━━━━━━━━━━━━━\n"
            log_text += f"▪️ *Symptoms*: {symptoms}\n"
            log_text += f"▪️ *Jira Ticket*: `{jira}`\n"
            log_text += f"▪️ *Current Assignee*: `{assignee}`\n"
            log_text += f"━━━━━━━━━━━━━━━━━━━\n\n"

            if not logs:
                log_text += "_Chưa có logs chẩn đoán nào được ghi nhận._"
            else:
                log_text += "*Diagnostic History:*\n"
                for idx, log_entry in enumerate(logs, 1):
                    log_text += f"{idx}. {log_entry}\n"

            # Check message length
            if len(log_text) <= 4096:
                await update.message.reply_text(log_text, parse_mode="Markdown")
            else:
                # Split and send
                parts = []
                current = ""
                for line in log_text.split("\n"):
                    if len(current) + len(line) + 1 > 4000:
                        parts.append(current)
                        current = line
                    else:
                        current = current + "\n" + line if current else line
                if current:
                    parts.append(current)
                for part in parts:
                    await update.message.reply_text(part, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error retrieving logs for session {session_id}: {e}")
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi lấy logs: {e}")

    async def handle_message(update: Update, context) -> None:
        """Handle incoming text messages to run the supervisor loop."""
        if not update.message or not update.message.text:
            return

        user = update.effective_user
        user_id = f"tg-{user.id}"
        chat_id = f"tg-chat-{update.effective_chat.id}"
        message = update.message.text

        logger.info(f"Telegram msg from {user.first_name} ({user.id}): {message[:80]}...")

        try:
            await update.message.chat.send_action("typing")
        except Exception as te:
            logger.warning(f"Failed to send typing indicator: {te}")

        try:
            response = await asyncio.to_thread(process_message_fn, message, user_id, chat_id)
            html_response = markdown_to_telegram_html(response)

            if len(html_response) <= 4096:
                await update.message.reply_text(html_response, parse_mode="HTML")
            else:
                parts = []
                current = ""
                for line in html_response.split("\n"):
                    if len(current) + len(line) + 1 > 4000:
                        parts.append(current)
                        current = line
                    else:
                        current = current + "\n" + line if current else line
                if current:
                    parts.append(current)
                for part in parts:
                    await update.message.reply_text(part, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error processing Telegram message: {e}", exc_info=True)
            await update.message.reply_text(
                f"⚠️ Có lỗi xảy ra khi xử lý tin nhắn.\nVui lòng thử lại sau."
            )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("sessions", cmd_sessions))
    application.add_handler(CommandHandler("logs", cmd_logs))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def _run_polling():
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started!")
        while True:
            await asyncio.sleep(3600)

    logger.info("Starting Telegram bot async polling...")
    loop.run_until_complete(_run_polling())
