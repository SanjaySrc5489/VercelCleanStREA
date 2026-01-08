"""
StreamGobhar - Telegram File Streaming Service
All endpoints in one file for Vercel deployment
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo
import os
import traceback

# Load config
from dotenv import load_dotenv
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BIN_CHANNEL = int(os.getenv("BIN_CHANNEL", "0"))
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Auto-detect base URL (Vercel)
VERCEL_URL = os.getenv("VERCEL_URL", "")
if VERCEL_URL:
    BASE_URL = f"https://{VERCEL_URL}"
else:
    BASE_URL = os.getenv("BASE_URL", "http://localhost:9090")

# Secret key for ID obfuscation (XOR encoding)
SECRET_KEY = int(os.getenv("SECRET_KEY", "742658931"))

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
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
async def root():
    """API root - show available endpoints"""
    return JSONResponse({
        "status": "ok",
        "message": "StreamGobhar API - Telegram File Streaming Service",
        "version": "2.0.0",
        "endpoints": {
            "webhook": "/webhook",
            "stream": "/stream/{msg_id}",
            "download": "/download/{msg_id}"
        }
    })


@app.get("/health")
async def health():
    """Health check"""
    return JSONResponse({"status": "healthy"})


# ============================================================================
# WEBHOOK ENDPOINT
# ============================================================================

@app.post("/webhook")
async def webhook(request: Request):
    """Handle Telegram webhook updates"""
    try:
        update_data = await request.json()
        await process_update(update_data, request)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/webhook")
async def webhook_info():
    """Webhook health check"""
    return JSONResponse({"status": "ok", "message": "Webhook endpoint active"})


async def process_update(update_data: dict, request: Request):
    """Process Telegram bot update"""
    
    # Get base URL
    vercel_url = os.getenv("VERCEL_URL", "")
    if vercel_url:
        base_url = f"https://{vercel_url}"
    else:
        host = request.headers.get("host", "localhost:9090")
        protocol = request.headers.get("x-forwarded-proto", "http")
        base_url = f"{protocol}://{host}"
    
    # Initialize bot
    bot = TelegramClient(StringSession(), API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    
    try:
        if 'message' not in update_data:
            return
            
        message = update_data['message']
        chat_id = message['chat']['id']
        
        # Handle /start command
        if 'text' in message and message['text'] == '/start':
            await bot.send_message(
                chat_id,
                "👋 Send me any file or video.\n"
                "I'll upload it and give you streaming & download links!"
            )
            return
        
        # Handle file/video uploads
        if 'document' in message or 'video' in message:
            msg_id = message['message_id']
            msg = await bot.get_messages(chat_id, ids=msg_id)
            
            if msg and msg.file:
                # Upload to storage channel
                uploaded_msg = await bot.send_file(BIN_CHANNEL, msg.media)
                # Generate links with obfuscated ID
                msg_id = uploaded_msg.id
                encoded_id = encode_id(msg_id)
                download_link = f"{base_url}/download/{encoded_id}"
                
                # Check if video
                is_video = any(
                    isinstance(attr, DocumentAttributeVideo)
                    for attr in uploaded_msg.document.attributes
                )
                
                if is_video:
                    stream_link = f"{base_url}/stream/{encoded_id}"
                    await bot.send_message(
                        chat_id,
                        f"✅ File uploaded!\n\n"
                        f"🔗 Download: {download_link}\n"
                        f"▶️ Stream: {stream_link}"
                    )
                else:
                    await bot.send_message(
                        chat_id,
                        f"✅ File uploaded!\n\n"
                        f"🔗 Download: {download_link}"
                    )
            else:
                await bot.send_message(chat_id, "❌ Please send a valid file.")
    
    finally:
        await bot.disconnect()


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
