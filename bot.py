#!/usr/bin/env python3
"""
StreamGobhar Bot - Local Testing
Run this for local development. For Vercel, the bot runs via webhook in index.py
"""

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeVideo
from dotenv import load_dotenv
import os

load_dotenv()

# Configuration
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BIN_CHANNEL = int(os.getenv("BIN_CHANNEL", "0"))
SECRET_KEY = int(os.getenv("SECRET_KEY", "742658931"))

# Base URL for local testing
BASE_URL = os.getenv("BASE_URL", "https://vercel-clean-st-rea.vercel.app")

bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)


def encode_id(msg_id: int) -> str:
    """Encode message ID using XOR for obfuscation"""
    obfuscated = msg_id ^ SECRET_KEY
    return hex(obfuscated)[2:]


@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    await event.reply(
        "👋 **Welcome to StreamGobhar Bot!**\n\n"
        "Send me any file or video, and I'll give you:\n"
        "▶️ Stream link\n"
        "⬇️ Download link\n\n"
        "Ready when you are!"
    )


@bot.on(events.NewMessage)
async def handle_file(event):
    """Handle file uploads"""
    
    if not event.file:
        return
    
    try:
        processing_msg = await event.reply("📤 Uploading to server...")
        
        # Upload to channel
        msg = await bot.send_file(BIN_CHANNEL, event.message.media)
        
        # Encode ID
        msg_id = msg.id
        encoded_id = encode_id(msg_id)
        
        # Generate links
        download_link = f"{BASE_URL}/download/{encoded_id}"
        
        # Check if video
        is_video = any(isinstance(attr, DocumentAttributeVideo) for attr in msg.document.attributes)
        
        if is_video:
            stream_link = f"{BASE_URL}/stream/{encoded_id}"
            response = (
                f"✅ **File uploaded successfully!**\n\n"
                f"📋 **File ID:** `{encoded_id}`\n\n"
                f"▶️ **Stream:** {stream_link}\n"
                f"⬇️ **Download:** {download_link}"
            )
        else:
            response = (
                f"✅ **File uploaded successfully!**\n\n"
                f"📋 **File ID:** `{encoded_id}`\n\n"
                f"⬇️ **Download:** {download_link}"
            )
        
        await processing_msg.delete()
        await event.reply(response)
        
        print(f"✅ Uploaded! Msg ID: {msg_id} → Encoded: {encoded_id}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        await event.reply(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    print("🤖 StreamGobhar Bot - Local Mode")
    print(f"📁 Channel: {BIN_CHANNEL}")
    print(f"🌐 Base URL: {BASE_URL}")
    print("⚠️  Make sure bot is admin in the channel!")
    print()
    print("For Vercel deployment, use index.py with webhook")
    print()
    bot.run_until_disconnected()
