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

# Auto-detect base URL
VERCEL_URL = os.getenv("VERCEL_URL", "")
BASE_URL = os.getenv("BASE_URL", "").strip()
if not BASE_URL:
    BASE_URL = f"https://{VERCEL_URL}" if VERCEL_URL else "http://localhost:9090"
if BASE_URL.endswith('/'): BASE_URL = BASE_URL[:-1]

app = FastAPI(title="StreamGobhar API", version="3.0.0")

# Global for simple debugging (per-instance only)
LAST_LOG = "No events yet"


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
    """Start MTProto Client for file operations"""
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.start(bot_token=BOT_TOKEN)
        return client
    except Exception as e:
        print(f"❌ MTProto Start Error: {e}")
        raise e


async def handle_update_logic(bot, message):
    """Process message logic (Polling & Webhook)"""
    global LAST_LOG
    try:
        # 1. Extract Info
        is_dict = isinstance(message, dict)
        chat_id = message.get('chat', {}).get('id') if is_dict else message.chat_id
        msg_id = message.get('message_id') if is_dict else message.id
        text = (message.get('text') or message.get('caption') or "") if is_dict else (message.text or message.caption or "")

        LAST_LOG = f"Processing msg {msg_id} from {chat_id}"
        print(f"📩 {LAST_LOG}")

        # 2. Handle Commands
        if text.startswith('/start'):
            msg = "👋 **StreamGobhar is Online!**\n\nI am running on Vercel. Send me any file or video to host it!"
            if is_dict: 
                await send_text_fast(chat_id, msg)
            else:
                await bot.send_message(chat_id, msg)
            return

        # 3. Handle Media
        media = None
        if is_dict:
            # Need to fetch media via MTProto for Webhook mode
            if any(k in message for k in ['document', 'video', 'audio', 'photo']):
                print(f"🔄 Fetching media object for {msg_id}...")
                full_msg = await bot.get_messages(chat_id, ids=msg_id)
                media = full_msg.media if full_msg else None
        else:
            media = message.media

        if media:
            # Fast response for status
            if is_dict: await send_text_fast(chat_id, "📤 **Hosting your file...**")
            
            # Forward/Send to channel
            print(f"📤 Uploading to channel {BIN_CHANNEL}...")
            sent_msg = await bot.send_file(BIN_CHANNEL, media)
            
            # Generate links
            encoded_id = encode_id(sent_msg.id)
            stream_link = f"{BASE_URL}/stream/{encoded_id}"
            download_link = f"{BASE_URL}/download/{encoded_id}"
            
            response = (
                f"✅ **Host Successful!**\n\n"
                f"📋 **File ID:** `{encoded_id}`\n\n"
                f"▶️ **Stream:** {stream_link}\n"
                f"⬇️ **Download:** {download_link}"
            )
            
            if is_dict:
                await send_text_fast(chat_id, response)
            else:
                await bot.send_message(chat_id, response)
            print(f"🎉 Success for chat {chat_id}")
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
    return {
        "telethon_version": telethon.__version__,
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
        r = await client.post(telegram_url, data={"url": webhook_url}, timeout=10)
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
    update = None
    try:
        # 1. Quick payload extraction
        update = await request.json()
        print(f"📥 Update Received: {list(update.keys())}")
        
        # 2. Extract Message
        msg = update.get('message') or update.get('channel_post') or update.get('edited_message')
        if not msg:
            return {"ok": True, "info": "no_message"}
            
        # 3. Process with Bot
        bot = None
        try:
            bot = await setup_bot()
            await handle_update_logic(bot, msg)
        except Exception as inner_e:
            err_msg = f"❌ Logic Error: {str(inner_e)}"
            print(err_msg)
            # Try to notify the user via telegram if we have a chat_id
            chat_id = msg.get('chat', {}).get('id')
            if chat_id: await send_text_fast(chat_id, f"⚠️ **Bot crashed internally:**\n`{str(inner_e)}`")
        finally:
            if bot: await bot.disconnect()
            
        return {"ok": True}
    except Exception as e:
        print(f"🔥 Webhook Critical Error: {e}")
        traceback.print_exc()
        # Even if we crash, return 200 to stop Telegram from retrying 100 times
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)


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
