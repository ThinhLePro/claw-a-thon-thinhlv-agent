"""Email Gateway Integration for Network Engineer Agent.

Runs an IMAP polling service in a background thread to receive
requests from users via Email. Includes deduplication, HTML cleaning,
loop prevention, rate limiting, and connection recovery.
"""

import os
import time
import email
from email.header import decode_header
from email.message import EmailMessage
import smtplib
import logging
from imapclient import IMAPClient
from bs4 import BeautifulSoup
from email_reply_parser import EmailReplyParser
import redis

logger = logging.getLogger(__name__)

# Setup Redis connection for deduplication and rate limiting
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
    logger.error(f"Redis connection failed in Email Gateway: {e}")
    redis_client = None

def check_rate_limit(sender: str) -> bool:
    """Return True if allowed, False if rate limited (max 5 per minute)."""
    if not redis_client:
        return True
    key = f"rate_limit:email:{sender}"
    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, 60)
    return current <= 5

def check_and_set_message_id(msg_id: str) -> bool:
    """Return True if message is NEW, False if already processed."""
    if not msg_id or not redis_client:
        return True # Process if no ID or no Redis
    key = f"processed_email:{msg_id}"
    # TTL 30 days = 30 * 24 * 3600 = 2592000
    is_new = redis_client.set(key, "1", ex=2592000, nx=True)
    return bool(is_new)

def is_auto_reply(msg) -> bool:
    """Check if email is an auto-reply or bulk."""
    auto_submitted = str(msg.get('Auto-Submitted', '')).lower()
    if auto_submitted and auto_submitted != 'no':
        return True
    
    x_autoreply = str(msg.get('X-Autoreply', '')).lower()
    if 'yes' in x_autoreply:
        return True
        
    precedence = str(msg.get('Precedence', '')).lower()
    if precedence in ['bulk', 'list', 'junk']:
        return True
        
    return False

def extract_clean_body(msg) -> str:
    """Extract and clean the email body."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                    if content_type == "text/html":
                        soup = BeautifulSoup(payload, "html.parser")
                        payload = soup.get_text(separator='\n')
                    body += payload + "\n"
                except Exception as e:
                    logger.warning(f"Failed to decode part: {e}")
    else:
        try:
            payload = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
            if msg.get_content_type() == "text/html":
                soup = BeautifulSoup(payload, "html.parser")
                payload = soup.get_text(separator='\n')
            body = payload
        except Exception as e:
            logger.warning(f"Failed to decode message payload: {e}")
            
    # Clean signature and reply history
    clean_body = EmailReplyParser.parse_reply(body)
    return clean_body.strip()

def send_email_reply(to_address: str, subject_ref: str, response_body: str, username: str, password: str):
    """Send an SMTP email reply to the user."""
    try:
        msg = EmailMessage()
        msg.set_content(response_body)
        
        # Ensure subject starts with Re:
        if not subject_ref.lower().startswith("re:"):
            subject_ref = f"Re: {subject_ref}"
            
        msg['Subject'] = subject_ref
        msg['From'] = username
        msg['To'] = to_address

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(username, password)
            server.send_message(msg)
            
        logger.info(f"Successfully sent email reply to {to_address}")
    except Exception as e:
        logger.error(f"Failed to send email reply to {to_address}: {e}", exc_info=True)

def start_email_gateway(process_message_fn):
    """Run robust Email IMAP polling in a background loop.
    
    Args:
        process_message_fn: Callable(message: str, user_id: str, session_id: str) -> str
    """
    logger.info("Starting robust Email Gateway polling...")
    username = "claw.a.thon.noc.agent.greennode01@gmail.com"
    password = os.environ.get("EMAIL_PASSWORD", "P@ssW0rd#claw-athon-01")
    imap_server = "imap.gmail.com"

    backoff = 5

    while True:
        try:
            with IMAPClient(imap_server, ssl=True, use_uid=True) as server:
                server.login(username, password)
                server.select_folder('INBOX')
                backoff = 5 # Reset backoff on success
                
                while True:
                    # Search for unseen
                    messages = server.search('UNSEEN')
                    if messages:
                        fetch_data = server.fetch(messages, ['ENVELOPE', 'RFC822'])
                        
                        for uid, msg_data in fetch_data.items():
                            raw_email = msg_data[b'RFC822']
                            msg = email.message_from_bytes(raw_email)
                            
                            # Extract Message-ID
                            msg_id = str(msg.get('Message-ID', '')).strip()
                            
                            # Deduplication check
                            if not check_and_set_message_id(msg_id):
                                logger.info(f"Skipping already processed email: {msg_id}")
                                server.add_flags(uid, [b'\\Seen'])
                                continue
                                
                            # Loop prevention
                            if is_auto_reply(msg):
                                logger.info(f"Skipping auto-reply email: {msg_id}")
                                server.add_flags(uid, [b'\\Seen'])
                                continue

                            # Extract sender
                            sender = str(msg.get("From", "unknown_sender"))
                            if '<' in sender and '>' in sender:
                                sender = sender.split('<')[1].split('>')[0] # extract pure email address
                                
                            # Rate limit check
                            if not check_rate_limit(sender):
                                logger.warning(f"Rate limit exceeded for sender: {sender}")
                                server.add_flags(uid, [b'\\Seen'])
                                continue
                                
                            # Extract subject
                            subject_header = msg["Subject"]
                            subject = ""
                            if subject_header:
                                decoded_list = decode_header(subject_header)
                                for decoded_part, encoding in decoded_list:
                                    if isinstance(decoded_part, bytes):
                                        subject += decoded_part.decode(encoding if encoding else "utf-8", errors='ignore')
                                    else:
                                        subject += str(decoded_part)

                            # Clean Body
                            body = extract_clean_body(msg)
                            
                            full_message = f"Subject: {subject}\n\n{body}"
                            logger.info(f"Processing robust email from {sender}: {subject}")
                            
                            session_id = f"email:{sender}"
                            user_id = f"email:{sender}"
                            
                            try:
                                response_text = process_message_fn(full_message, user_id, session_id)
                                if response_text:
                                    # Gửi email phản hồi
                                    send_email_reply(sender, subject, response_text, username, password)
                            except Exception as e:
                                logger.error(f"Error processing email message: {e}", exc_info=True)
                            
                            # Mark as seen
                            server.add_flags(uid, [b'\\Seen'])
                    
                    time.sleep(10)
        except Exception as e:
            logger.error(f"IMAP Connection error: {e}. Reconnecting in {backoff} seconds...", exc_info=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60) # cap at 60s
