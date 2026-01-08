"""
StreamGobhar - Telegram File Streaming Service
Optimized for Vercel Serverless & Robust Bot Support
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo
import os
import traceback
import httpx
from dotenv import load_dotenv

load_dotenv()

# Helper for safe int conversion
def safe_int(val, default=0):
    try:
        if not val: return default
        return int(str(val).strip())
    except:
        return default

# Configuration
API_ID = safe_int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BIN_CHANNEL = safe_int(os.getenv("BIN_CHANNEL"))
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()
SECRET_KEY = safe_int(os.getenv("SECRET_KEY"), 742658931)

# Auto-detect base URL (Manual env takes priority)
MANUAL_BASE_URL = os.getenv("BASE_URL", "").strip()
VERCEL_URL = os.getenv("VERCEL_URL", "")

if MANUAL_BASE_URL:
    BASE_URL = MANUAL_BASE_URL
else:
    BASE_URL = f"https://{VERCEL_URL}" if VERCEL_URL else "http://localhost:9090"

if BASE_URL.endswith('/'): BASE_URL = BASE_URL[:-1]

app = FastAPI(title="StreamGobhar API", version="3.0.0")

# Global for simple diagnostics
LAST_LOG = "No events yet"
FLOOD_WAIT_UNTIL = 0  # Timestamp when we can try again
STARTUP_TIME = int(__import__('time').time()) # Ignore messages before this

def get_now():
    import time
    return int(time.time())


def encode_id(msg_id: int) -> str:
    """Encode message ID using XOR for obfuscation"""
    obfuscated = msg_id ^ SECRET_KEY
    return hex(obfuscated)[2:]


def decode_id(encoded_id: str) -> int:
    """Decode obfuscated ID back to message ID"""
    try:
        obfuscated = int(encoded_id, 16)
        return obfuscated ^ SECRET_KEY
    except ValueError:
        raise ValueError(f"Invalid ID format: {encoded_id}")


async def send_text_fast(chat_id, text):
    """Instant reply using Bot API (No connection delays)"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
            return True
    except Exception as e:
        print(f"⚠️ Fast reply failed: {e}")
        return False


async def setup_bot():
    """Start MTProto Client using existing SESSION_STRING to avoid login loops"""
    global FLOOD_WAIT_UNTIL
    
    now = get_now()
    if now < FLOOD_WAIT_UNTIL:
        wait_rem = FLOOD_WAIT_UNTIL - now
        raise Exception(f"FloodWait Active: Please wait {wait_rem}s before trying again.")

    try:
        # Use SESSION_STRING if available to avoid login loops
        session = StringSession(SESSION_STRING) if SESSION_STRING else StringSession()
        client = TelegramClient(session, API_ID, API_HASH)
        
        # start() with bot_token will only log in if the session is empty
        await client.start(bot_token=BOT_TOKEN)
        return client
    except Exception as e:
        if "wait of" in str(e).lower():
            import re
            seconds = re.search(r'wait of (\d+)', str(e).lower())
            if seconds:
                FLOOD_WAIT_UNTIL = get_now() + int(seconds.group(1))
        print(f"❌ MTProto Start Error: {e}")
        raise e


async def copy_to_bin(from_chat_id, message_id):
    """Use Bot API to copy message to channel - No MTProto needed, zero latency!"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json={
                "chat_id": BIN_CHANNEL,
                "from_chat_id": from_chat_id,
                "message_id": message_id
            }, timeout=15)
            res = r.json()
            if res.get("ok"):
                return res["result"]["message_id"]
            else:
                print(f"❌ Copy API Error: {res}")
                return None
    except Exception as e:
        print(f"⚠️ Copy failed: {e}")
        return None


async def handle_update_logic(message):
    """Process message logic using BOTH Bot API and MTProto fallback if needed"""
    global LAST_LOG
    try:
        # 1. Extract Info
        is_dict = isinstance(message, dict)
        chat_id = message.get('chat', {}).get('id') if is_dict else message.chat_id
        msg_id = message.get('message_id') if is_dict else message.id
        date = message.get('date') if is_dict else (message.date.timestamp() if hasattr(message.date, 'timestamp') else 0)
        text = (message.get('text') or message.get('caption') or "") if is_dict else (message.text or message.caption or "")

        # 🕒 Backlog Filter: Ignore old messages
        if date < STARTUP_TIME:
            print(f"⏩ Ignoring old msg {msg_id}")
            return

        LAST_LOG = f"Received {msg_id} from {chat_id}"
        print(f"📩 {LAST_LOG}")

        # 2. Handle Commands
        if text.startswith('/start'):
            welcome = "👋 **StreamGobhar v5.0 (Ultra-Stable)**\n\nI am now running on **Bot-API First** architecture. Send me any file or video!"
            await send_text_fast(chat_id, welcome)
            return

        # 3. Handle Media (The fast way)
        has_media = any(k in message for k in ['document', 'video', 'audio', 'photo']) if is_dict else (message.media is not None)
        
        if has_media:
            # Step 1: Tell user we are working
            await send_text_fast(chat_id, "📤 **Processing your file...**")
            
            # Step 2: Use Bot API to copy to channel (INSTANT)
            new_msg_id = await copy_to_bin(chat_id, msg_id)
            
            if not new_msg_id:
                await send_text_fast(chat_id, "❌ **Error:** Could not host file. (Bot must be admin in channel!)")
                return

            # Step 3: Generate links
            encoded_id = encode_id(new_msg_id)
            stream_link = f"{BASE_URL}/stream/{encoded_id}"
            download_link = f"{BASE_URL}/download/{encoded_id}"
            
            response = (
                f"✅ **Host Successful!**\n\n"
                f"📋 **File ID:** `{encoded_id}`\n\n"
                f"▶️ **Stream:** {stream_link}\n"
                f"⬇️ **Download:** {download_link}"
            )
            await send_text_fast(chat_id, response)
            print(f"🎉 Success for {chat_id}")
        else:
            if not text.startswith('/'):
                await send_text_fast(chat_id, "ℹ️ Please send a **file** or **video**!")

    except Exception as e:
        err = f"❌ Logic Error: {e}"
        print(err)
        LAST_LOG = err
        traceback.print_exc()


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "mode": "production/serverless",
        "bot_id": BOT_TOKEN.split(':')[0] if BOT_TOKEN else None,
        "url": BASE_URL,
        "last_event": LAST_LOG
    }

@app.get("/debug")
async def debug_info():
    """Deep diagnostics for the bot state"""
    import telethon
    now = get_now()
    flood_status = "Inactive" if now >= FLOOD_WAIT_UNTIL else f"Active (Wait {FLOOD_WAIT_UNTIL - now}s)"
    
    return {
        "telethon_version": telethon.__version__,
        "flood_wait": flood_status,
        "config_check": {
            "api_id": bool(API_ID),
            "api_hash_len": len(API_HASH),
            "bot_token_valid": ":" in BOT_TOKEN,
            "bin_channel": BIN_CHANNEL,
            "session_string_len": len(SESSION_STRING)
        },
        "url_check": {
            "vercel_url": VERCEL_URL,
            "base_url": BASE_URL
        },
        "last_log": LAST_LOG
    }

@app.get("/set_webhook")
async def set_webhook():
    webhook_url = f"{BASE_URL}/webhook"
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    async with httpx.AsyncClient() as client:
        # Added drop_pending_updates to clear the 170+ stuck messages
        r = await client.post(telegram_url, data={
            "url": webhook_url,
            "drop_pending_updates": True
        }, timeout=10)
        return r.json()

@app.get("/delete_webhook")
async def delete_webhook():
    """Manual endpoint to clear webhook if stuck"""
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    async with httpx.AsyncClient() as client:
        r = await client.post(telegram_url, data={"drop_pending_updates": True}, timeout=10)
        return r.json()

@app.get("/check_webhook")
async def check_webhook():
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
    async with httpx.AsyncClient() as client:
        r = await client.get(telegram_url, timeout=10)
        return r.json()

@app.get("/test_bot")
async def test_bot():
    """Verify MTProto Connection and Channel Access"""
    try:
        bot = await setup_bot()
        me = await bot.get_me()
        await bot.send_message(BIN_CHANNEL, "🔧 **Vercel Connection Test** - Bot is Working!")
        await bot.disconnect()
        return {"status": "success", "bot": me.username, "channel": "Message sent!"}
    except Exception as e:
        return {"status": "error", "details": str(e), "traceback": traceback.format_exc()}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        # ⚡ Webhook is now 100% MTProto-FREE! No more loops or waits.
        update = await request.json()
        
        msg = update.get('message') or update.get('channel_post') or update.get('edited_message')
        if not msg:
            return {"ok": True}
            
        chat_id = msg.get('chat', {}).get('id')
        
        # 1. Ignore loops
        if chat_id == BIN_CHANNEL:
            return {"ok": True, "info": "loop_ignored"}
            
        # 2. Process logic (Will use Bot API for everything)
        await handle_update_logic(msg)
        
        return {"ok": True}
    except Exception as e:
        print(f"🔥 Webhook Crash: {e}")
        return JSONResponse({"ok": True}, status_code=200) # Always 200 to stop retries


# ============================================================================
# STREAMING & DOWNLOAD
# ============================================================================

class TelegramStreamWrapper:
    def __init__(self, client, iterator):
        self.client = client
        self.iterator = iterator
    async def __aiter__(self):
        try:
            async for chunk in self.iterator: yield chunk
        finally:
            await self.client.disconnect()

@app.get("/stream/{encoded_id}")
async def stream_video(encoded_id: str, request: Request):
    try:
        msg_id = decode_id(encoded_id)
        if not SESSION_STRING: return JSONResponse({"error": "SESSION_STRING missing"}, status_code=500)
        
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not msg or not msg.document:
            await client.disconnect()
            return JSONResponse({"error": "File not found"}, status_code=404)
        
        size = msg.document.size
        range_header = request.headers.get('range', '')
        start, end = 0, size - 1
        
        if range_header:
            rv = range_header.replace('bytes=', '').split('-')
            start = int(rv[0]) if rv[0] else 0
            end = int(rv[1]) if len(rv) > 1 and rv[1] else end
            end = min(end, size - 1)
        
        length = end - start + 1
        dl_iter = client.iter_download(msg.document, offset=start, limit=length, chunk_size=1024*512)
        
        headers = {
            'Content-Type': 'video/mp4',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
        }
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status = 206
        else:
            status = 200
            
        return StreamingResponse(TelegramStreamWrapper(client, dl_iter), status_code=status, headers=headers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download/{encoded_id}")
async def download_file(encoded_id: str, request: Request):
    try:
        msg_id = decode_id(encoded_id)
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not msg or not msg.document:
            await client.disconnect()
            return JSONResponse({"error": "File not found"}, status_code=404)
            
        filename = "file"
        for attr in msg.document.attributes:
            if hasattr(attr, "file_name"): filename = attr.file_name
            
        dl_iter = client.iter_download(msg.document, chunk_size=1024*512)
        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(msg.document.size),
        }
        return StreamingResponse(TelegramStreamWrapper(client, dl_iter), headers=headers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================================
# RUN (LOCAL ONLY)
# ============================================================================

if __name__ == "__main__":
    from telethon import events
    print("🚀 Running in POLLING mode (Local)...")
    bot_client = TelegramClient('local_bot', API_ID, API_HASH)
    
    @bot_client.on(events.NewMessage)
    async def local_handler(event):
        await handle_update_logic(bot_client, event.message)
        
    bot_client.start(bot_token=BOT_TOKEN)
    bot_client.run_until_disconnected()
