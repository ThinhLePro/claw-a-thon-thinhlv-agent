"""Telegram Bot Integration for DC Network Engineer Agent.

Runs Telegram bot polling in a background thread alongside the
HTTP server. Handles /start, /help commands and text messages.
"""

import os
import asyncio
import logging

from markdown_converter import markdown_to_telegram_html

logger = logging.getLogger(__name__)


def start_telegram_bot(process_message_fn, bot_token: str):
    """Run Telegram bot polling in a background thread.

    Args:
        process_message_fn: Callable(message: str, user_id: str, session_id: str) -> str
            The agent's message processing function.
        bot_token: Telegram bot API token.
    """
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
            "🔧 *DC Network Engineer Bot*\n\n"
            "Xin chào! Tôi là Senior DC Network Engineer AI.\n"
            "Hãy hỏi tôi bất kỳ câu hỏi nào về:\n\n"
            "• EVPN-VXLAN & IP Fabric\n"
            "• Juniper Junos CLI\n"
            "• DC Infrastructure & Cabling\n"
            "• BGP, OSPF, IS-IS Routing\n"
            "• MC-LAG & Firewall Filters\n"
            "• DDoS Protection (Arbor)\n"
            "• Troubleshooting & Operations\n\n"
            "Gửi tin nhắn để bắt đầu! 🚀"
        )
        await update.message.reply_text(welcome, parse_mode="Markdown")

    async def cmd_help(update: Update, context) -> None:
        """Handle /help command."""
        help_text = (
            "📖 *Hướng dẫn sử dụng*\n\n"
            "Gửi câu hỏi bằng tiếng Việt hoặc tiếng Anh.\n\n"
            "*Ví dụ:*\n"
            "• `Giải thích EVPN route type 5`\n"
            "• `Config BGP trên QFX5100`\n"
            "• `Troubleshoot VXLAN tunnel down`\n"
            "• `So sánh ToR vs EoR`\n"
            "• `Tính oversubscription ratio`\n\n"
            "*Lệnh:*\n"
            "/start — Bắt đầu\n"
            "/help — Hướng dẫn\n"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def handle_message(update: Update, context) -> None:
        """Handle incoming text messages."""
        if not update.message or not update.message.text:
            return

        user = update.effective_user
        user_id = f"tg-{user.id}"
        chat_id = f"tg-chat-{update.effective_chat.id}"
        message = update.message.text

        logger.info(f"Telegram msg from {user.first_name} ({user.id}): {message[:80]}...")

        # Send "typing" indicator safely
        try:
            await update.message.chat.send_action("typing")
        except Exception as te:
            logger.warning(f"Failed to send typing indicator: {te}")

        try:
            response = await asyncio.to_thread(process_message_fn, message, user_id, chat_id)
            html_response = markdown_to_telegram_html(response)

            # Telegram has 4096 char limit per message — split if needed
            if len(html_response) <= 4096:
                await update.message.reply_text(html_response, parse_mode="HTML")
            else:
                # Split on double newlines to avoid breaking HTML tags
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

    # Build the Telegram application
    # NOTE: run_polling() cannot be used in a non-main thread because it
    # tries to register signal handlers. Instead, manually manage the
    # async lifecycle on a dedicated event loop.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def _run_polling():
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started!")
        # Keep running forever
        while True:
            await asyncio.sleep(3600)

    logger.info("Starting Telegram bot async polling...")
    loop.run_until_complete(_run_polling())
