"""
Telegram Bot Webhook Handler - FastAPI serverless function
File path: api/webhook.py -> becomes /api/webhook endpoint
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo
from telethon.sessions import StringSession
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import API_ID, API_HASH, BOT_TOKEN, BIN_CHANNEL

app = FastAPI()


@app.post("/")
async def webhook(request: Request):
    """Handle Telegram webhook updates"""
    try:
        update_data = await request.json()
        await process_update(update_data, request)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/")
async def webhook_info():
    """Health check"""
    return JSONResponse({"status": "ok", "message": "Webhook endpoint active"})


async def process_update(update_data: dict, request: Request):
    """Process Telegram bot update"""
    
    # Get base URL from Vercel environment or request headers
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
                
                # Generate links
                download_link = f"{base_url}/api/download/{uploaded_msg.id}"
                
                # Check if video
                is_video = any(
                    isinstance(attr, DocumentAttributeVideo)
                    for attr in uploaded_msg.document.attributes
                )
                
                if is_video:
                    stream_link = f"{base_url}/api/stream/{uploaded_msg.id}"
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
