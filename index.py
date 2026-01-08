"""
StreamGobhar - Telegram File Streaming Service
Optimized for Vercel Serverless & Robust Bot Support
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, RedirectResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo
import os
import traceback
import httpx
import mimetypes
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
PROD_URL = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "")
DEPLOY_URL = os.getenv("VERCEL_URL", "")

if MANUAL_BASE_URL:
    BASE_URL = MANUAL_BASE_URL
elif PROD_URL:
    BASE_URL = f"https://{PROD_URL}"
else:
    BASE_URL = f"https://{DEPLOY_URL}" if DEPLOY_URL else "http://localhost:9090"

if BASE_URL.endswith('/'): BASE_URL = BASE_URL[:-1]

app = FastAPI(title="StreamGobhar API", version="3.0.0")

# Global for simple diagnostics
LAST_LOG = "No events yet"
FLOOD_WAIT_UNTIL = 0  # Timestamp when we can try again
# Removed STARTUP_TIME - It causes issues on Vercel cold starts

def get_now():
    import time
    return int(time.time())

# Global Exception Handler for easier Vercel debugging
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    err = f"🔥 Global Exception: {str(exc)}\n{traceback.format_exc()}"
    print(err)
    return JSONResponse(status_code=500, content={"error": "Internal Server Error", "details": str(exc), "trace": traceback.format_exc()})


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
            r = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=10)
            res = r.json()
            if not res.get("ok"):
                print(f"❌ Bot API Response Error: {res}")
            return res.get("ok")
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

        # 🕒 Backlog Filter: Only ignore VERY old messages (older than 1 hour)
        # This prevents the startup filter from breaking Vercel cold starts.
        now = get_now()
        if date < (now - 3600):
            print(f"⏩ Ignoring very old msg {msg_id}")
            return

        LAST_LOG = f"Received {msg_id} from {chat_id}"
        print(f"📩 {LAST_LOG}")

        # 2. Handle Commands
        cmd = text.lower().split()[0] if text else ""
        if cmd.startswith('/start'):
            welcome = (
                "🚀 <b>Welcome to TeleFileStream!</b>\n\n"
                "The most powerful file hosting and streaming bot on Telegram. Send any file or video to get instant High-Speed Stream & Download links.\n\n"
                "💎 <b>Features:</b>\n"
                "• <b>Instant Hosting</b>: Direct copy to cloud channel.\n"
                "• <b>Unlimited Stream</b>: Play videos directly in player.\n"
                "• <b>Fast Download</b>: Get direct high-speed links.\n"
                "• <b>Zero Latency</b>: Powered by Bot-API v5.5.\n\n"
                "📢 <b>Bot:</b> @TeleFileStream_bot\n"
                "🌐 <b>Web:</b> <a href='https://telestream.vercel.app'>telestream.vercel.app</a>\n\n"
                "✨ <i>Send a file to begin!</i>"
            )
            await send_text_fast(chat_id, welcome)
            return

        # 3. Handle Media (The fast way)
        has_media = any(k in message for k in ['document', 'video', 'audio', 'photo']) if is_dict else (message.media is not None)
        
        if has_media:
            # Step 1: Tell user we are working
            await send_text_fast(chat_id, "📤 <b>Hosting your file...</b>")
            
            # Step 2: Use Bot API to copy to channel (INSTANT)
            new_msg_id = await copy_to_bin(chat_id, msg_id)
            
            if not new_msg_id:
                await send_text_fast(chat_id, "❌ <b>Error:</b> Could not host file. (Bot must be admin in channel!)")
                return

            # Step 3: Generate links
            encoded_id = encode_id(new_msg_id)
            landing_page = f"{BASE_URL}/v/{encoded_id}"
            stream_link = f"{BASE_URL}/stream/{encoded_id}"
            download_link = f"{BASE_URL}/download/{encoded_id}"
            
            response = (
                f"✅ <b>Host Successful!</b>\n\n"
                f"🎬 <b>ACCESS YOUR FILE:</b>\n"
                f"👉 {landing_page}\n\n"
                f"📁 <b>File ID:</b> <code>{encoded_id}</code>\n"
                f"🔗 <b>Direct Stream:</b> {stream_link}\n"
                f"⬇️ <b>Fast Download:</b> {download_link}\n\n"
                f"✨ <i>Tip: The link above works for both watching online and downloading!</i>"
            )
            await send_text_fast(chat_id, response)
            print(f"🎉 Success for {chat_id}")
        else:
            if not text.startswith('/'):
                await send_text_fast(chat_id, "ℹ️ Please send a <b>file</b> or <b>video</b>!")

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
        # Added drop_pending_updates to clear the backlog
        r = await client.post(telegram_url, data={
            "url": webhook_url,
            "drop_pending_updates": True
        }, timeout=10)
        res = r.json()
        res["target_url_used"] = webhook_url
        return res

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

@app.get("/watch/{encoded_id}")
async def old_watch_redirect(encoded_id: str):
    """Fallback for old watch links"""
    return RedirectResponse(url=f"/v/{encoded_id}")

@app.get("/v/{encoded_id}")
async def universal_landing_page(encoded_id: str):
    """The Ultimate Universal Landing Page for all Files"""
    stream_url = f"{BASE_URL}/stream/{encoded_id}"
    download_url = f"{BASE_URL}/download/{encoded_id}"
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TeleFileStream | Premium Access</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap">
    <script src="https://cdn.jsdelivr.net/npm/artplayer/dist/artplayer.js"></script>
    <style>
        :root {{
            --primary: #3498db;
            --bg: #05070a;
            --accent: #2ecc71;
            --glass: rgba(255, 255, 255, 0.03);
            --border: rgba(255, 255, 255, 0.08);
        }}
        body {{ background: var(--bg); margin: 0; padding: 0; color: #fff; font-family: 'Outfit', sans-serif; overflow-x: hidden; }}
        .bg-glow {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
            background: radial-gradient(circle at 50% 50%, #1e3a8a 0%, transparent 50%), radial-gradient(circle at 80% 20%, #1e1b4b 0%, transparent 30%);
            opacity: 0.3; z-index: -1; animation: pulse 10s infinite alternate; 
        }}
        @keyframes pulse {{ from {{ transform: scale(1); }} to {{ transform: scale(1.1); }} }}
        .navbar {{ padding: 20px 5%; display: flex; align-items: center; justify-content: space-between; background: var(--glass); backdrop-filter: blur(15px); border-bottom: 1px solid var(--border); }}
        .logo {{ font-weight: 600; font-size: 22px; color: var(--primary); text-decoration: none; }}
        .logo span {{ color: #fff; }}
        .main-container {{ max-width: 1200px; margin: 40px auto; padding: 0 20px; text-align: center; }}
        
        /* Player & Display Section */
        .content-card {{ position: relative; border-radius: 20px; overflow: hidden; box-shadow: 0 40px 100px rgba(0,0,0,0.8); border: 1px solid var(--border); background: #000; min-height: 200px; }}
        .player-view {{ height: 65vh; width: 100%; display:none; }}
        .file-view {{ padding: 60px 20px; display:block; }}
        .file-icon {{ font-size: 80px; margin-bottom: 20px; display: block; }}
        
        .action-container {{ margin-top: 30px; display: flex; flex-direction: column; align-items: center; gap: 15px; }}
        .btn {{ 
            padding: 16px 40px; border-radius: 50px; font-weight: 600; font-size: 16px; 
            text-decoration: none; transition: all 0.3s ease; display: inline-flex; align-items: center; gap: 10px;
            box-shadow: 0 10px 20px rgba(0,0,0,0.2); border: none; cursor: pointer;
        }}
        .btn-primary {{ background: linear-gradient(135deg, #3498db, #2980b9); color: #fff; }}
        .btn-primary:hover {{ transform: translateY(-3px); box-shadow: 0 15px 30px rgba(52, 152, 219, 0.4); }}
        .btn-outline {{ background: var(--glass); color: #fff; border: 1px solid var(--border); }}
        .btn-outline:hover {{ background: rgba(255,255,255,0.08); }}

        @media (max-width: 768px) {{ .player-view {{ height: 35vh; }} .btn {{ width: 100%; justify-content: center; box-sizing: border-box; }} }}
    </style>
</head>
<body>
    <div class="bg-glow"></div>
    <nav class="navbar">
        <a href="#" class="logo">🚀 TeleFile<span>Stream</span></a>
    </nav>

    <div class="main-container">
        <div class="content-card">
            <div id="player-view" class="player-view">
                <div id="art-app" style="width:100%; height:100%;"></div>
            </div>
            <div id="file-view" class="file-view">
                <span class="file-icon">📁</span>
                <h2 id="file-title">Detecting File...</h2>
                <p style="color:rgba(255,255,255,0.5)">This is a direct cloud-hosted file. Click below to download at full speed.</p>
            </div>
        </div>

        <div class="action-container">
            <a href="{download_url}" class="btn btn-primary">
                <span>⬇️</span> Download File Now
            </a>
            <a href="https://t.me/TeleFileStream_bot" class="btn btn-outline">
                <span>🤖</span> Return to Bot
            </a>
        </div>
    </div>

    <script>
        const streamUrl = "{stream_url}";
        const isVideo = streamUrl.match(/\.(mp4|mkv|mov|avi|webm|m4v)$|stream/i);

        if (isVideo) {{
            document.getElementById('player-view').style.display = 'block';
            document.getElementById('file-view').style.display = 'none';
            
            var art = new Artplayer({{
                container: '#art-app',
                url: streamUrl,
                autoplay: true,
                setting: true,
                pip: true,
                screenshot: true,
                fullscreen: true,
                theme: '#3498db',
                icons: {{
                    loading: '<img width="60" src="https://artplayer.org/assets/img/ploading.gif">',
                    state: '<img width="100" src="https://artplayer.org/assets/img/state.svg">',
                }},
            }});
        }} else {{
            document.getElementById('file-title').innerText = "File Ready for Download";
        }}
    </script>
</body>
</html>
""")

@app.get("/watch/{encoded_id}")
async def watch_player(encoded_id: str):
    """Instant-Load Cinematic Web Player (ArtPlayer)"""
    stream_url = f"{BASE_URL}/stream/{encoded_id}"
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TeleFileStream | Premium Cinema</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap">
    <script src="https://cdn.jsdelivr.net/npm/artplayer/dist/artplayer.js"></script>
    <style>
        :root {{
            --primary: #3498db;
            --bg: #05070a;
            --accent: #2ecc71;
        }}
        body {{ 
            background: var(--bg);
            margin: 0; padding: 0; 
            color: #fff; 
            font-family: 'Outfit', sans-serif;
            overflow-x: hidden;
        }}
        /* Animated Background */
        .bg-glow {{
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: radial-gradient(circle at 50% 50%, #1e3a8a 0%, transparent 50%),
                        radial-gradient(circle at 80% 20%, #1e1b4b 0%, transparent 30%);
            opacity: 0.3; z-index: -1; animation: pulse 10s infinite alternate;
        }}
        @keyframes pulse {{ from {{ transform: scale(1); }} to {{ transform: scale(1.1); }} }}

        .navbar {{ 
            padding: 20px 5%; display: flex; align-items: center; justify-content: space-between;
            background: rgba(255,255,255,0.03); backdrop-filter: blur(15px);
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .logo {{ font-weight: 600; font-size: 22px; color: var(--primary); text-decoration: none; display: flex; align-items: center; gap: 10px; }}
        .logo span {{ color: #fff; }}

        .main-container {{ 
            max-width: 1200px; margin: 40px auto; padding: 0 20px;
        }}
        
        .player-wrapper {{
            position: relative; border-radius: 20px; overflow: hidden;
            box-shadow: 0 40px 100px rgba(0,0,0,0.8);
            border: 1px solid rgba(255,255,255,0.1);
            background: #000; height: 65vh;
        }}
        .artplayer-app {{ width: 100%; height: 100%; }}

        .info-card {{
            margin-top: 30px; padding: 25px;
            background: rgba(255,255,255,0.03); border-radius: 20px;
            backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.05);
        }}
        .info-card h2 {{ margin: 0; font-size: 24px; color: #fff; }}
        .info-card p {{ color: rgba(255,255,255,0.6); line-height: 1.6; margin: 10px 0 0; }}
        
        .badge {{
            display: inline-block; padding: 5px 12px; border-radius: 20px;
            font-size: 12px; background: rgba(52, 152, 219, 0.2);
            color: var(--primary); border: 1px solid rgba(52, 152, 219, 0.3);
            margin-bottom: 10px;
        }}

        @media (max-width: 768px) {{ .player-wrapper {{ height: 35vh; }} }}
    </style>
</head>
<body>
    <div class="bg-glow"></div>
    <nav class="navbar">
        <a href="#" class="logo">🚀 TeleFile<span>Stream</span></a>
        <div style="font-size: 14px; color: rgba(255,255,255,0.5);">Pro Cinema Mode</div>
    </nav>

    <div class="main-container">
        <div class="badge">Direct Cloud Link</div>
        <div class="player-wrapper">
            <div class="artplayer-app"></div>
        </div>

        <div class="info-card">
            <h2>Ready to Play</h2>
            <p>Your content is served directly from Telegram servers with zero buffering. Use the settings icon in the player to toggle Audio tracks and Subtitles.</p>
        </div>
    </div>

    <script>
        var art = new Artplayer({{
            container: '.artplayer-app',
            url: '{stream_url}',
            title: 'Cinematic Stream',
            poster: 'https://telestream.vercel.app/logo.png',
            volume: 0.7,
            isLive: false,
            muted: false,
            autoplay: true,
            pip: true,
            autoSize: true,
            autoMini: true,
            screenshot: true,
            setting: true,
            loop: true,
            flip: true,
            playbackRate: true,
            aspectRatio: true,
            fullscreen: true,
            fullscreenWeb: true,
            miniProgressBar: true,
            mutex: true,
            backdrop: true,
            playsInline: true,
            autoPlayback: true,
            airplay: true,
            theme: '#3498db',
            lang: 'en',
            icons: {{
                loading: '<img width="60" src="https://artplayer.org/assets/img/ploading.gif">',
                state: '<img width="100" src="https://artplayer.org/assets/img/state.svg">',
            }},
            moreVideoAttr: {{
                crossOrigin: 'anonymous',
            }},
        }});

        art.on('ready', () => {{
            console.info("Player ready and streaming...");
        }});
    </script>
</body>
</html>
""")

@app.get("/stream/{encoded_id}")
async def stream_file(encoded_id: str, request: Request):
    """Stream any supportable file (Videos, Audios, etc)"""
    try:
        msg_id = decode_id(encoded_id)
        if not SESSION_STRING: return JSONResponse({"error": "SESSION_STRING missing"}, status_code=500)
        
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not msg or not msg.document:
            await client.disconnect()
            return JSONResponse({"error": "File or Document not found in channel"}, status_code=404)
        
        # Determine filename and MIME type
        filename = "file"
        for attr in msg.document.attributes:
            if hasattr(attr, "file_name") and attr.file_name:
                filename = attr.file_name
                break
        
        # Use mimetypes to guess correctly for all extensions
        mime, _ = mimetypes.guess_type(filename)
        if not mime:
            mime = msg.document.mime_type or "application/octet-stream"
        
        # Force video/mp4 if it's likely a video for the player
        if "video" in mime or filename.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
            mime = "video/mp4"
            
        size = msg.document.size
        range_header = request.headers.get('range', '')
        start, end = 0, size - 1
        
        if range_header:
            rv = range_header.replace('bytes=', '').split('-')
            start = int(rv[0]) if rv[0] else 0
            end = int(rv[1]) if len(rv) > 1 and rv[1] else end
            end = min(end, size - 1)
        
        length = end - start + 1
        dl_iter = client.iter_download(msg.document, offset=start, limit=length, chunk_size=1024*1024)
        
        headers = {
            'Content-Type': mime,
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': 'inline', # FORCE INLINE FOR BROWSER PLAYBACK
        }
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status = 206
        else:
            status = 200
            
        return StreamingResponse(TelegramStreamWrapper(client, dl_iter), status_code=status, headers=headers)
    except Exception as e:
        print(f"🔥 Stream Error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download/{encoded_id}")
async def download_file(encoded_id: str, request: Request):
    """Download any file type (Zip, PDF, APK, etc)"""
    try:
        msg_id = decode_id(encoded_id)
        if not SESSION_STRING: return JSONResponse({"error": "SESSION_STRING missing"}, status_code=500)

        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not msg or not msg.document:
            await client.disconnect()
            return JSONResponse({"error": "File not found in channel"}, status_code=404)
            
        # Extract Filename properly
        filename = "file"
        for attr in msg.document.attributes:
            if hasattr(attr, "file_name") and attr.file_name:
                filename = attr.file_name
                break
        
        # Guess MIME type for download
        mime, _ = mimetypes.guess_type(filename)
        if not mime:
            mime = msg.document.mime_type or 'application/octet-stream'
            
        dl_iter = client.iter_download(msg.document, chunk_size=1024*1024)
        headers = {
            'Content-Type': mime,
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(msg.document.size),
        }
        return StreamingResponse(TelegramStreamWrapper(client, dl_iter), headers=headers)
    except Exception as e:
        print(f"🔥 Download Error: {e}")
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
        # handle_update_logic only takes 1 arg since v5.0
        await handle_update_logic(event.message)
        
    bot_client.start(bot_token=BOT_TOKEN)
    bot_client.run_until_disconnected()
