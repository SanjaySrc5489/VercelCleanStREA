"""
StreamGobhar - Telegram File Streaming Service
Production-ready for Vercel deployment
"""

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo
import os
import traceback
import httpx
from dotenv import load_dotenv

load_dotenv()

# Configuration from environment
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BIN_CHANNEL = int(os.getenv("BIN_CHANNEL", "0"))
SESSION_STRING = os.getenv("SESSION_STRING", "")
SECRET_KEY = int(os.getenv("SECRET_KEY", "742658931"))

# Auto-detect base URL
VERCEL_URL = os.getenv("VERCEL_URL", "")
BASE_URL = f"https://{VERCEL_URL}" if VERCEL_URL else os.getenv("BASE_URL", "http://localhost:9090")

app = FastAPI(title="StreamGobhar API", version="2.0.0")


def encode_id(msg_id: int) -> str:
    """Encode message ID using XOR for obfuscation"""
    obfuscated = msg_id ^ SECRET_KEY
    return hex(obfuscated)[2:]  # Remove '0x' prefix


def decode_id(encoded_id: str) -> int:
    """Decode obfuscated ID back to message ID"""
    try:
        obfuscated = int(encoded_id, 16)
        return obfuscated ^ SECRET_KEY
    except ValueError:
        raise ValueError(f"Invalid ID format: {encoded_id}")


class TelegramStreamWrapper:
    """Wrapper to keep client alive during streaming"""
    def __init__(self, client, iterator):
        self.client = client
        self.iterator = iterator
    
    async def __aiter__(self):
        try:
            async for chunk in self.iterator:
                yield chunk
        finally:
            await self.client.disconnect()


def get_filename(msg):
    """Extract filename from message"""
    for attr in msg.document.attributes:
        if hasattr(attr, "file_name"):
            return attr.file_name
    return f"file_{msg.document.id}"


# ============================================================================
# BOT LOGIC (COMMON)
# ============================================================================

async def setup_bot():
    """Shared bot setup logic"""
    try:
        if not API_ID or not API_HASH or not BOT_TOKEN:
            raise ValueError(f"Missing Essential Config: API_ID={bool(API_ID)}, API_HASH={bool(API_HASH)}, BOT_TOKEN={bool(BOT_TOKEN)}")
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.start(bot_token=BOT_TOKEN)
        return client
    except Exception as e:
        print(f"❌ Failed to setup bot: {e}")
        traceback.print_exc()
        raise e

async def handle_update_logic(bot, message):
    """Core logic to handle a message (used by both polling and webhook)"""
    try:
        # 1. Extract chat_id
        is_dict = isinstance(message, dict)
        chat_id = message.get('chat', {}).get('id') if is_dict else message.chat_id
        if not chat_id:
            print("⚠️ Could not extract chat_id")
            return

        # 2. Extract text/command
        text = (message.get('text') or message.get('caption') or "") if is_dict else (message.text or message.caption or "")
        print(f"📩 Processing message from {chat_id}: '{text[:20]}...'")

        # 3. Handle /start
        if text.startswith('/start'):
            await bot.send_message(
                chat_id, 
                "👋 **StreamGobhar is Active!**\n\n"
                "I am now running on Vercel 24/7.\n"
                "**How to use:** Send me any file or video, and I'll host it for you!"
            )
            print(f"✅ Sent welcome to {chat_id}")
            return

        # 4. Handle Media
        # If it's a dict (Webhook mode), we need to fetch it via MTProto to get the media object
        if is_dict:
            if any(k in message for k in ['document', 'video', 'photo', 'audio']):
                msg_id = message['message_id']
                print(f"🔄 Fetching MTProto message for ID {msg_id}...")
                full_msg = await bot.get_messages(chat_id, ids=msg_id)
                media = full_msg.media if full_msg else None
            else:
                media = None
        else:
            media = message.media

        if media:
            print(f"📤 Uploading media to storage channel...")
            sent_msg = await bot.send_file(BIN_CHANNEL, media)
            encoded_id = encode_id(sent_msg.id)
            
            # Generate links
            stream_link = f"{BASE_URL}/stream/{encoded_id}"
            download_link = f"{BASE_URL}/download/{encoded_id}"
            
            response = (
                f"✅ **File Hosted Successfully!**\n\n"
                f"📋 **File ID:** `{encoded_id}`\n\n"
                f"▶️ **Stream:** {stream_link}\n"
                f"⬇️ **Download:** {download_link}"
            )
            await bot.send_message(chat_id, response)
            print(f"🔥 Successfully sent hosted links to {chat_id}")
        else:
            if not text.startswith('/'):
                await bot.send_message(chat_id, "ℹ️ Please send a **file** or **video** to get a link!")
            
    except Exception as e:
        print(f"❌ Error in handle_update_logic: {e}")
        traceback.print_exc()

# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {
        "status": "running",
        "mode": "vercel/webhook",
        "url": BASE_URL,
        "config": {
            "api_id": bool(API_ID),
            "api_hash": bool(API_HASH),
            "bot_token": bool(BOT_TOKEN),
            "bin_channel": bool(BIN_CHANNEL),
            "session_string": bool(SESSION_STRING)
        }
    }

@app.get("/env_check")
async def env_check():
    """Check if environment variables are loaded correctly"""
    return {
        "API_ID": "✅ Set" if API_ID else "❌ NOT SET",
        "API_HASH": "✅ Set" if API_HASH else "❌ NOT SET",
        "BOT_TOKEN": "✅ Set" if BOT_TOKEN else "❌ NOT SET",
        "BIN_CHANNEL": "✅ Set" if BIN_CHANNEL else "❌ NOT SET",
        "SESSION_STRING": "✅ Set" if SESSION_STRING else "❌ NOT SET",
        "SECRET_KEY": "✅ Set" if SECRET_KEY else "❌ NOT SET",
        "VERCEL_URL": os.getenv("VERCEL_URL", "NOT SET"),
        "BASE_URL": BASE_URL
    }

@app.get("/test_bot")
async def test_bot():
    """Test bot credentials and channel access"""
    try:
        bot = await setup_bot()
        me = await bot.get_me()
        
        # Test channel access
        test_msg = await bot.send_message(BIN_CHANNEL, "🔧 **Vercel Deployment Test**\nIf you see this, the bot has correct permissions!")
        
        await bot.disconnect()
        return {
            "status": "success",
            "bot": f"@{me.username}",
            "channel_test": "Message sent to BIN_CHANNEL!",
            "note": "Credentials and Permissions are GOOD!"
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "details": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/set_webhook")
async def set_webhook():
    import httpx
    webhook_url = f"{BASE_URL}/webhook"
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    async with httpx.AsyncClient() as client:
        r = await client.post(telegram_url, data={"url": webhook_url})
        return r.json()

@app.post("/webhook")
async def webhook(request: Request):
    """Telegram Webhook entry point"""
    try:
        update = await request.json()
        print(f"� Webhook Received: {list(update.keys())}")
        
        # Check for message or channel post
        msg = update.get('message') or update.get('channel_post') or update.get('edited_message')
        
        if msg:
            print(f"🎯 Valid update found, starting bot session...")
            bot = await setup_bot()
            try:
                await handle_update_logic(bot, msg)
            finally:
                await bot.disconnect()
                print("💤 Bot session closed.")
        else:
            print("ℹ️ No 'message' or 'channel_post' in update payload.")
            
    except Exception as e:
        print(f"❌ Webhook Critical Error: {e}")
        traceback.print_exc()
    
    return {"ok": True}


# ============================================================================
# LOCAL POLLING MODE (Only runs if you do: python index.py)
# ============================================================================

if __name__ == "__main__":
    from telethon import events
    print("🚀 Starting StreamGobhar in POLLING mode (Local)...")
    
    bot = TelegramClient('local_session', API_ID, API_HASH)
    
    @bot.on(events.NewMessage)
    async def local_handler(event):
        await handle_update_logic(bot, event.message)

    print(f"📁 Channel: {BIN_CHANNEL}")
    print(f"🌐 Using Base URL: {BASE_URL}")
    bot.start(bot_token=BOT_TOKEN)
    bot.run_until_disconnected()


# ============================================================================
# STREAM ENDPOINT
# ============================================================================

@app.get("/stream/{encoded_id}")
async def stream_video(encoded_id: str, request: Request):
    """Stream video with range request support"""
    
    # Decode message ID
    try:
        msg_id = decode_id(encoded_id)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid ID",
                "details": str(e)
            }
        )
    
    # Check environment variables
    if not API_ID or not API_HASH:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "API_ID or API_HASH not set in environment variables"
            }
        )
    
    if not SESSION_STRING:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "SESSION_STRING not set in environment variables",
                "hint": "Add SESSION_STRING to Vercel environment variables"
            }
        )
    
    # Initialize client
    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)
    
    try:
        await client.start()
        
        # Get message
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        
        if not msg:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Message Not Found",
                    "details": f"Message ID {msg_id} not found in channel {BIN_CHANNEL}",
                    "hint": "Make sure the file was uploaded through the bot first"
                }
            )
        
        if not msg.document:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not a Document",
                    "details": f"Message ID {msg_id} has no document attached"
                }
            )
        
        # File info
        size = msg.document.size
        
        # Parse range header
        range_header = request.headers.get('range', '')
        start = 0
        end = size - 1
        
        if range_header:
            range_value = range_header.replace('bytes=', '').split('-')
            start = int(range_value[0]) if range_value[0] else 0
            end = int(range_value[1]) if len(range_value) > 1 and range_value[1] else end
            end = min(end, size - 1)
        
        length = end - start + 1
        
        # Create download iterator
        download_iterator = client.iter_download(
            msg.document,
            offset=start,
            limit=length,
            chunk_size=1024 * 512
        )
        
        # Wrap to keep client alive
        stream_wrapper = TelegramStreamWrapper(client, download_iterator)
        
        # Response headers
        headers = {
            'Content-Type': 'video/mp4',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
        }
        
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status_code = 206
        else:
            status_code = 200
        
        return StreamingResponse(
            stream_wrapper,
            status_code=status_code,
            headers=headers,
            media_type='video/mp4'
        )
    
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "exception_type": type(e).__name__,
                "details": str(e),
                "traceback": traceback.format_exc()
            }
        )


# ============================================================================
# DOWNLOAD ENDPOINT
# ============================================================================

@app.get("/download/{encoded_id}")
async def download_file(encoded_id: str, request: Request):
    """Download file with proper headers"""
    
    # Decode message ID
    try:
        msg_id = decode_id(encoded_id)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid ID",
                "details": str(e)
            }
        )
    
    # Check environment variables
    if not API_ID or not API_HASH:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "API_ID or API_HASH not set"
            }
        )
    
    if not SESSION_STRING:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "SESSION_STRING not set",
                "hint": "Add SESSION_STRING to Vercel environment variables"
            }
        )
    
    # Initialize client
    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)
    
    try:
        await client.start()
        
        # Get message
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        
        if not msg:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Message Not Found",
                    "details": f"Message ID {msg_id} not found"
                }
            )
        
        if not msg.document:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not a Document",
                    "details": "Message has no document attached"
                }
            )
        
        # File info
        size = msg.document.size
        filename = get_filename(msg)
        
        # Parse range header
        range_header = request.headers.get('range', '')
        start = 0
        end = size - 1
        
        if range_header:
            range_value = range_header.replace('bytes=', '').split('-')
            start = int(range_value[0]) if range_value[0] else 0
            end = int(range_value[1]) if len(range_value) > 1 and range_value[1] else end
            end = min(end, size - 1)
        
        length = end - start + 1
        
        # Create download iterator
        download_iterator = client.iter_download(
            msg.document,
            offset=start,
            limit=length,
            chunk_size=1024 * 512
        )
        
        # Wrap to keep client alive
        stream_wrapper = TelegramStreamWrapper(client, download_iterator)
        
        # Response headers
        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
        }
        
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status_code = 206
        else:
            status_code = 200
        
        return StreamingResponse(
            stream_wrapper,
            status_code=status_code,
            headers=headers,
            media_type='application/octet-stream'
        )
    
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "exception_type": type(e).__name__,
                "details": str(e),
                "traceback": traceback.format_exc()
            }
        )
