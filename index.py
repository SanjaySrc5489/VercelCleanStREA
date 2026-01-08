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

# ============================================================================
# UTILS & WRAPPERS
# ============================================================================

class TelegramStreamWrapper:
    """Helper to stream Telegram chunks to FastAPI response"""
    def __init__(self, client, iterator):
        self.client = client
        self.iterator = iterator
    async def __aiter__(self):
        try:
            async for chunk in self.iterator:
                yield chunk
        except Exception as e:
            print(f"📡 Stream Interrupted: {e}")
        finally:
            # We don't disconnect here because we use a GLOBAL_CLIENT pool
            pass

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

# Global Client for Reuse (Helps with Vercel warm starts)
GLOBAL_CLIENT = None

async def get_client():
    global GLOBAL_CLIENT
    if GLOBAL_CLIENT is None or not GLOBAL_CLIENT.is_connected():
        try:
            GLOBAL_CLIENT = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await GLOBAL_CLIENT.connect()
        except Exception as e:
            print(f"⚠️ Initial Connect Failed: {e}")
    return GLOBAL_CLIENT

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

            # Step 3: Generate links & Meta Detection
            encoded_id = encode_id(new_msg_id)
            download_link = f"{BASE_URL}/f/{encoded_id}"
            
            # Detect Content Type (Media vs File)
            filename = "file"
            if not is_dict:
                if message.document:
                    for attr in message.document.attributes:
                        if hasattr(attr, "file_name") and attr.file_name:
                            filename = attr.file_name
                            break
                elif message.video:
                    filename = getattr(message.video, 'file_name', 'video.mp4')
                elif message.audio:
                    filename = getattr(message.audio, 'file_name', 'audio.mp3')
            else:
                doc = message.get('document') or message.get('video') or message.get('audio')
                if doc:
                    filename = doc.get('file_name', 'media')

            # List of media extensions for smart detection
            media_exts = ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.3gp', '.flv', '.ogv', '.mp3', '.wav', '.ogg', '.flac', '.m4a')
            is_media = filename.lower().endswith(media_exts)
            if is_dict:
                is_media = is_media or any(k in message for k in ['video', 'audio', 'video_note'])
            else:
                is_media = is_media or message.video or message.audio or message.voice

            if is_media:
                landing_page = f"{BASE_URL}/v/{encoded_id}"
                main_action = f"🎬 <b>WATCH YOUR VIDEO:</b>\n👉 {landing_page}"
                tip = "✨ <i>Tip: The player supports multi-audio, subtitles, and PIP!</i>"
            else:
                landing_page = f"{BASE_URL}/f/{encoded_id}"
                main_action = f"📥 <b>DOWNLOAD YOUR FILE:</b>\n👉 {landing_page}"
                tip = "✨ <i>Tip: High-speed cloud download available!</i>"

            response = (
                f"✅ <b>Host Successful!</b>\n\n"
                f"{main_action}\n\n"
                f"📁 <b>File ID:</b> <code>{encoded_id}</code>\n"
                f"⬇️ <b>Fast Download:</b> {download_link}\n\n"
                f"{tip}\n\n"
                f"⚡ <b>Made by:</b> @Sanjay_Src"
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


@app.get("/v/{encoded_id}")
async def video_landing_page(encoded_id: str):
    """Premium Cinema Player for Videos"""
    stream_url = f"{BASE_URL}/stream/{encoded_id}"
    download_url = f"{BASE_URL}/download/{encoded_id}"
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎬 TeleFileStream Cinema</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎬</text></svg>">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
    <script src="https://cdn.jsdelivr.net/npm/artplayer/dist/artplayer.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{
            --primary: #6366f1;
            --primary-glow: rgba(99, 102, 241, 0.4);
            --accent: #22d3ee;
            --bg-dark: #0a0a0f;
            --bg-card: rgba(255, 255, 255, 0.03);
            --border: rgba(255, 255, 255, 0.08);
            --text: #f8fafc;
            --text-muted: rgba(248, 250, 252, 0.5);
        }}
        
        body {{
            background: var(--bg-dark);
            color: var(--text);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
        }}
        
        /* Animated Background */
        .bg-effects {{
            position: fixed;
            inset: 0;
            z-index: -1;
            overflow: hidden;
        }}
        .bg-effects::before {{
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: 
                radial-gradient(circle at 20% 80%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 80% 20%, rgba(34, 211, 238, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 40% 40%, rgba(168, 85, 247, 0.08) 0%, transparent 30%);
            animation: bgPulse 15s ease-in-out infinite alternate;
        }}
        @keyframes bgPulse {{
            0% {{ transform: translate(0, 0) scale(1); }}
            100% {{ transform: translate(-5%, -5%) scale(1.1); }}
        }}
        
        /* Premium Header */
        .header {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 100;
            padding: 16px 24px;
            background: rgba(10, 10, 15, 0.8);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .logo {{
            display: flex;
            align-items: center;
            gap: 12px;
            text-decoration: none;
        }}
        .logo-icon {{
            width: 42px;
            height: 42px;
            background: linear-gradient(135deg, var(--primary), var(--accent));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            box-shadow: 0 4px 20px var(--primary-glow);
        }}
        .logo-text {{
            font-size: 20px;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 0%, var(--accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .logo-badge {{
            padding: 4px 10px;
            background: linear-gradient(135deg, var(--primary), #8b5cf6);
            border-radius: 20px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        /* Main Content */
        .main {{
            padding: 100px 24px 40px;
            max-width: 1200px;
            margin: 0 auto;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        
        /* Player Container */
        .player-wrapper {{
            position: relative;
            width: 100%;
            border-radius: 20px;
            overflow: hidden;
            background: #000;
            box-shadow: 
                0 0 0 1px var(--border),
                0 25px 80px -20px rgba(0, 0, 0, 0.8),
                0 0 60px -10px var(--primary-glow);
        }}
        .player-container {{
            position: relative;
            width: 100%;
            aspect-ratio: 16/9;
        }}
        #artplayer-app {{
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
        }}
        
        /* Action Bar */
        .action-bar {{
            margin-top: 32px;
            display: flex;
            justify-content: center;
            gap: 16px;
            flex-wrap: wrap;
        }}
        
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 18px 36px;
            border-radius: 16px;
            font-size: 16px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            border: none;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }}
        
        .btn-primary {{
            background: linear-gradient(135deg, var(--primary) 0%, #8b5cf6 100%);
            color: white;
            box-shadow: 0 8px 32px var(--primary-glow);
        }}
        .btn-primary:hover {{
            transform: translateY(-4px);
            box-shadow: 0 16px 48px var(--primary-glow);
        }}
        .btn-primary::before {{
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, transparent 0%, rgba(255,255,255,0.2) 50%, transparent 100%);
            transform: translateX(-100%);
            transition: transform 0.6s;
        }}
        .btn-primary:hover::before {{
            transform: translateX(100%);
        }}
        
        .btn-icon {{
            font-size: 20px;
            animation: bounce 2s infinite;
        }}
        @keyframes bounce {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-4px); }}
        }}
        
        /* File Info Card */
        .info-card {{
            margin-top: 24px;
            padding: 20px 28px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 24px;
            flex-wrap: wrap;
        }}
        .info-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--text-muted);
            font-size: 14px;
        }}
        .info-item span {{
            color: var(--text);
            font-weight: 500;
        }}
        
        /* Footer */
        .footer {{
            margin-top: auto;
            padding-top: 48px;
            text-align: center;
        }}
        .footer-text {{
            color: var(--text-muted);
            font-size: 13px;
        }}
        .footer-text a {{
            color: var(--accent);
            text-decoration: none;
            font-weight: 500;
        }}
        .footer-text a:hover {{
            text-decoration: underline;
        }}
        
        /* Mobile Responsive */
        @media (max-width: 768px) {{
            .header {{ padding: 12px 16px; }}
            .logo-text {{ font-size: 16px; }}
            .logo-badge {{ display: none; }}
            .main {{ padding: 80px 16px 24px; }}
            .btn {{ width: 100%; padding: 16px 24px; }}
            .info-card {{ padding: 16px; gap: 16px; }}
        }}
    </style>
</head>
<body>
    <div class="bg-effects"></div>
    
    <header class="header">
        <a href="/" class="logo">
            <div class="logo-icon">🎬</div>
            <span class="logo-text">TeleFileStream</span>
            <span class="logo-badge">Cinema</span>
        </a>
    </header>
    
    <main class="main">
        <div class="player-wrapper">
            <div class="player-container">
                <div id="artplayer-app"></div>
            </div>
        </div>
        
        <div class="action-bar">
            <a href="{download_url}" class="btn btn-primary">
                <span class="btn-icon">⬇️</span>
                Download Video Now
            </a>
        </div>
        
        <div class="info-card">
            <div class="info-item">🎥 <span>Original Quality</span></div>
            <div class="info-item">⚡ <span>High-Speed Stream</span></div>
            <div class="info-item">🔒 <span>Secure & Private</span></div>
        </div>
        
        <footer class="footer">
            <p class="footer-text">
                Powered by <a href="#">TeleFileStream</a> • Made with ❤️ by <a href="#">@Sanjay_Src</a>
            </p>
        </footer>
    </main>
    
    <script>
        var art = new Artplayer({{
            container: '#artplayer-app',
            url: '{stream_url}',
            type: 'mp4',
            autoplay: true,
            aspectRatio: true,
            setting: true,
            pip: true,
            screenshot: true,
            fullscreen: true,
            fullscreenWeb: true,
            playbackRate: true,
            theme: '#6366f1',
            volume: 0.8,
            muted: false,
            autoMini: true,
            mutex: true,
            backdrop: true,
            playsInline: true,
            autoPlayback: true,
            moreVideoAttr: {{
                crossOrigin: 'anonymous',
                preload: 'metadata',
                'webkit-playsinline': true,
                playsinline: true,
            }},
            icons: {{
                loading: '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%"><div style="width:50px;height:50px;border:3px solid rgba(255,255,255,0.1);border-top-color:#6366f1;border-radius:50%;animation:spin 1s linear infinite"></div></div>',
                state: '<svg width="80" height="80" viewBox="0 0 80 80"><circle cx="40" cy="40" r="38" fill="rgba(0,0,0,0.6)" stroke="rgba(255,255,255,0.2)" stroke-width="2"/><path d="M32 25 L58 40 L32 55 Z" fill="white"/></svg>'
            }}
        }});
        
        // Custom loading spinner keyframes
        const style = document.createElement('style');
        style.textContent = '@keyframes spin {{ to {{ transform: rotate(360deg); }} }}';
        document.head.appendChild(style);
        
        art.on('ready', () => {{
            const video = art.video;
            if (video.videoHeight > video.videoWidth) {{
                // Portrait video - adjust container
                document.querySelector('.player-container').style.aspectRatio = '9/16';
                document.querySelector('.player-wrapper').style.maxWidth = '400px';
                document.querySelector('.player-wrapper').style.margin = '0 auto';
            }}
        }});
        
        art.on('error', (err) => {{
            console.error('Stream Error:', err);
            art.notice.show = '⏳ Reconnecting...';
            setTimeout(() => {{ art.url = art.url; }}, 2000);
        }});
    </script>
</body>
</html>
""")

@app.get("/f/{encoded_id}")
async def file_landing_page(encoded_id: str):
    """Premium File Download Portal with Smart Type Detection"""
    download_url = f"{BASE_URL}/download/{encoded_id}"
    
    # Try to get file metadata for smart icon/theming
    file_icon = "📦"
    file_type = "File"
    accent_color = "#6366f1"
    accent_glow = "rgba(99, 102, 241, 0.4)"
    btn_gradient = "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)"
    btn_text = "Download Now"
    
    try:
        msg_id = decode_id(encoded_id)
        client = await get_client()
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if msg and msg.document:
            filename = "file"
            filesize = msg.document.size
            for attr in msg.document.attributes:
                if hasattr(attr, "file_name") and attr.file_name:
                    filename = attr.file_name
                    break
            
            # Smart file type detection
            ext = filename.lower().split('.')[-1] if '.' in filename else ''
            
            if ext == 'apk':
                file_icon = "🤖"
                file_type = "Android App"
                accent_color = "#3DDC84"
                accent_glow = "rgba(61, 220, 132, 0.4)"
                btn_gradient = "linear-gradient(135deg, #3DDC84 0%, #00C853 100%)"
                btn_text = "Install APK"
            elif ext in ('zip', 'rar', '7z', 'tar', 'gz'):
                file_icon = "🗜️"
                file_type = "Archive"
                accent_color = "#f59e0b"
                accent_glow = "rgba(245, 158, 11, 0.4)"
                btn_gradient = "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)"
                btn_text = "Download Archive"
            elif ext == 'pdf':
                file_icon = "📕"
                file_type = "PDF Document"
                accent_color = "#ef4444"
                accent_glow = "rgba(239, 68, 68, 0.4)"
                btn_gradient = "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)"
                btn_text = "Download PDF"
            elif ext in ('doc', 'docx'):
                file_icon = "📝"
                file_type = "Word Document"
                accent_color = "#2563eb"
                accent_glow = "rgba(37, 99, 235, 0.4)"
                btn_gradient = "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)"
                btn_text = "Download Document"
            elif ext in ('xls', 'xlsx', 'csv'):
                file_icon = "📊"
                file_type = "Spreadsheet"
                accent_color = "#22c55e"
                accent_glow = "rgba(34, 197, 94, 0.4)"
                btn_gradient = "linear-gradient(135deg, #22c55e 0%, #16a34a 100%)"
                btn_text = "Download Spreadsheet"
            elif ext in ('ppt', 'pptx'):
                file_icon = "📽️"
                file_type = "Presentation"
                accent_color = "#f97316"
                accent_glow = "rgba(249, 115, 22, 0.4)"
                btn_gradient = "linear-gradient(135deg, #f97316 0%, #ea580c 100%)"
                btn_text = "Download Presentation"
            elif ext in ('exe', 'msi'):
                file_icon = "💿"
                file_type = "Windows App"
                accent_color = "#0ea5e9"
                accent_glow = "rgba(14, 165, 233, 0.4)"
                btn_gradient = "linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)"
                btn_text = "Download Installer"
            elif ext in ('dmg', 'pkg'):
                file_icon = "🍎"
                file_type = "Mac App"
                accent_color = "#a855f7"
                accent_glow = "rgba(168, 85, 247, 0.4)"
                btn_gradient = "linear-gradient(135deg, #a855f7 0%, #9333ea 100%)"
                btn_text = "Download for Mac"
            elif ext in ('iso', 'img'):
                file_icon = "💽"
                file_type = "Disk Image"
                accent_color = "#64748b"
                accent_glow = "rgba(100, 116, 139, 0.4)"
                btn_gradient = "linear-gradient(135deg, #64748b 0%, #475569 100%)"
                btn_text = "Download Image"
            elif ext in ('ttf', 'otf', 'woff', 'woff2'):
                file_icon = "🔤"
                file_type = "Font File"
                accent_color = "#ec4899"
                accent_glow = "rgba(236, 72, 153, 0.4)"
                btn_gradient = "linear-gradient(135deg, #ec4899 0%, #db2777 100%)"
                btn_text = "Download Font"
            elif ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'):
                file_icon = "🖼️"
                file_type = "Image"
                accent_color = "#14b8a6"
                accent_glow = "rgba(20, 184, 166, 0.4)"
                btn_gradient = "linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)"
                btn_text = "Download Image"
            elif ext == 'json':
                file_icon = "📋"
                file_type = "JSON Data"
                accent_color = "#84cc16"
                accent_glow = "rgba(132, 204, 22, 0.4)"
                btn_gradient = "linear-gradient(135deg, #84cc16 0%, #65a30d 100%)"
                btn_text = "Download JSON"
            elif ext in ('txt', 'log', 'md'):
                file_icon = "📄"
                file_type = "Text File"
                accent_color = "#6b7280"
                accent_glow = "rgba(107, 114, 128, 0.4)"
                btn_gradient = "linear-gradient(135deg, #6b7280 0%, #4b5563 100%)"
                btn_text = "Download Text"
            else:
                file_icon = "📦"
                file_type = f".{ext.upper()} File" if ext else "File"
            
            # Format file size
            if filesize < 1024:
                size_str = f"{filesize} B"
            elif filesize < 1024*1024:
                size_str = f"{filesize/1024:.1f} KB"
            elif filesize < 1024*1024*1024:
                size_str = f"{filesize/(1024*1024):.1f} MB"
            else:
                size_str = f"{filesize/(1024*1024*1024):.2f} GB"
    except:
        filename = "file"
        size_str = "Unknown"
        pass
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🚀 {file_type} Download | TeleFileStream</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📦</text></svg>">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{
            --primary: {accent_color};
            --primary-glow: {accent_glow};
            --accent: #22d3ee;
            --bg-dark: #0a0a0f;
            --bg-card: rgba(255, 255, 255, 0.03);
            --border: rgba(255, 255, 255, 0.08);
            --text: #f8fafc;
            --text-muted: rgba(248, 250, 252, 0.5);
        }}
        
        body {{
            background: var(--bg-dark);
            color: var(--text);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
        }}
        
        /* Animated Background */
        .bg-effects {{
            position: fixed;
            inset: 0;
            z-index: -1;
            overflow: hidden;
        }}
        .bg-effects::before {{
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: 
                radial-gradient(circle at 20% 80%, var(--primary-glow) 0%, transparent 40%),
                radial-gradient(circle at 80% 20%, rgba(34, 211, 238, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 50% 50%, rgba(168, 85, 247, 0.08) 0%, transparent 30%);
            animation: bgPulse 15s ease-in-out infinite alternate;
        }}
        @keyframes bgPulse {{
            0% {{ transform: translate(0, 0) scale(1); opacity: 0.8; }}
            100% {{ transform: translate(-5%, -5%) scale(1.1); opacity: 1; }}
        }}
        
        /* Floating Particles */
        .particles {{
            position: fixed;
            inset: 0;
            z-index: -1;
            overflow: hidden;
        }}
        .particle {{
            position: absolute;
            width: 4px;
            height: 4px;
            background: var(--primary);
            border-radius: 50%;
            opacity: 0.3;
            animation: float 20s infinite linear;
        }}
        @keyframes float {{
            0% {{ transform: translateY(100vh) rotate(0deg); opacity: 0; }}
            10% {{ opacity: 0.3; }}
            90% {{ opacity: 0.3; }}
            100% {{ transform: translateY(-100vh) rotate(720deg); opacity: 0; }}
        }}
        
        /* Premium Header */
        .header {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 100;
            padding: 16px 24px;
            background: rgba(10, 10, 15, 0.8);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .logo {{
            display: flex;
            align-items: center;
            gap: 12px;
            text-decoration: none;
        }}
        .logo-icon {{
            width: 42px;
            height: 42px;
            background: linear-gradient(135deg, var(--primary), var(--accent));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            box-shadow: 0 4px 20px var(--primary-glow);
            animation: logoGlow 3s ease-in-out infinite alternate;
        }}
        @keyframes logoGlow {{
            0% {{ box-shadow: 0 4px 20px var(--primary-glow); }}
            100% {{ box-shadow: 0 4px 40px var(--primary-glow), 0 0 60px var(--primary-glow); }}
        }}
        .logo-text {{
            font-size: 20px;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 0%, var(--accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .logo-badge {{
            padding: 4px 10px;
            background: linear-gradient(135deg, var(--primary), #8b5cf6);
            border-radius: 20px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: white;
        }}
        
        /* Main Content */
        .main {{
            padding: 120px 24px 40px;
            max-width: 600px;
            margin: 0 auto;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}
        
        /* Premium Card */
        .card {{
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 28px;
            padding: 48px 32px;
            backdrop-filter: blur(20px);
            text-align: center;
            position: relative;
            overflow: hidden;
            animation: cardEntrance 0.8s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        @keyframes cardEntrance {{
            0% {{ opacity: 0; transform: translateY(40px) scale(0.95); }}
            100% {{ opacity: 1; transform: translateY(0) scale(1); }}
        }}
        .card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--primary), transparent);
            opacity: 0.5;
        }}
        
        /* File Icon Container */
        .icon-container {{
            position: relative;
            width: 140px;
            height: 140px;
            margin: 0 auto 32px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .icon-ring {{
            position: absolute;
            inset: 0;
            border-radius: 50%;
            border: 2px solid var(--primary);
            opacity: 0.3;
            animation: ringPulse 2s ease-in-out infinite;
        }}
        .icon-ring:nth-child(2) {{
            animation-delay: 0.5s;
            transform: scale(0.8);
            opacity: 0.5;
        }}
        .icon-ring:nth-child(3) {{
            animation-delay: 1s;
            transform: scale(0.6);
            opacity: 0.7;
        }}
        @keyframes ringPulse {{
            0%, 100% {{ transform: scale(1); opacity: 0.3; }}
            50% {{ transform: scale(1.1); opacity: 0.6; }}
        }}
        .file-icon {{
            font-size: 72px;
            animation: iconFloat 3s ease-in-out infinite;
            position: relative;
            z-index: 2;
            filter: drop-shadow(0 10px 30px var(--primary-glow));
        }}
        @keyframes iconFloat {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-10px); }}
        }}
        
        /* File Type Badge */
        .type-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 20px;
            background: linear-gradient(135deg, var(--primary), rgba(var(--primary), 0.8));
            background: {btn_gradient};
            border-radius: 30px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 20px;
            box-shadow: 0 4px 20px var(--primary-glow);
        }}
        
        /* Title */
        .title {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 12px;
            background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.7) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        /* Filename */
        .filename {{
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 8px;
            word-break: break-all;
            padding: 12px 20px;
            background: rgba(255,255,255,0.03);
            border-radius: 12px;
            border: 1px solid var(--border);
            font-family: 'SF Mono', 'Fira Code', monospace;
        }}
        
        /* File Meta */
        .meta {{
            display: flex;
            justify-content: center;
            gap: 24px;
            margin: 24px 0;
            flex-wrap: wrap;
        }}
        .meta-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            color: var(--text-muted);
        }}
        .meta-item span {{
            color: var(--text);
            font-weight: 600;
        }}
        
        /* Premium Download Button */
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 14px;
            width: 100%;
            padding: 22px 40px;
            border-radius: 18px;
            font-size: 18px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            border: none;
            background: {btn_gradient};
            color: white;
            box-shadow: 0 10px 40px var(--primary-glow);
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            margin-top: 24px;
        }}
        .btn::before {{
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, transparent 0%, rgba(255,255,255,0.2) 50%, transparent 100%);
            transform: translateX(-100%);
            transition: transform 0.6s;
        }}
        .btn:hover {{
            transform: translateY(-5px) scale(1.02);
            box-shadow: 0 20px 60px var(--primary-glow);
        }}
        .btn:hover::before {{
            transform: translateX(100%);
        }}
        .btn-icon {{
            font-size: 24px;
            animation: downloadBounce 1.5s infinite;
        }}
        @keyframes downloadBounce {{
            0%, 100% {{ transform: translateY(0); }}
            30% {{ transform: translateY(4px); }}
            60% {{ transform: translateY(-2px); }}
        }}
        
        /* Speed Indicator */
        .speed-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin-top: 20px;
            padding: 10px 20px;
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid rgba(34, 197, 94, 0.3);
            border-radius: 30px;
            font-size: 13px;
            color: #22c55e;
        }}
        .speed-dot {{
            width: 8px;
            height: 8px;
            background: #22c55e;
            border-radius: 50%;
            animation: blink 1s infinite;
        }}
        @keyframes blink {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.3; }}
        }}
        
        /* Feature Pills */
        .features {{
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-top: 32px;
            flex-wrap: wrap;
        }}
        .feature {{
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 10px 18px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 30px;
            font-size: 13px;
            color: var(--text-muted);
        }}
        .feature-icon {{
            font-size: 16px;
        }}
        
        /* Footer */
        .footer {{
            margin-top: 40px;
            text-align: center;
        }}
        .footer-text {{
            color: var(--text-muted);
            font-size: 13px;
        }}
        .footer-text a {{
            color: var(--primary);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s;
        }}
        .footer-text a:hover {{
            color: var(--accent);
        }}
        
        /* Mobile Responsive */
        @media (max-width: 768px) {{
            .header {{ padding: 12px 16px; }}
            .logo-text {{ font-size: 16px; }}
            .logo-badge {{ display: none; }}
            .main {{ padding: 100px 16px 24px; }}
            .card {{ padding: 36px 24px; }}
            .icon-container {{ width: 120px; height: 120px; }}
            .file-icon {{ font-size: 56px; }}
            .title {{ font-size: 22px; }}
            .btn {{ padding: 18px 24px; font-size: 16px; }}
            .meta {{ gap: 16px; }}
            .features {{ gap: 8px; }}
        }}
    </style>
</head>
<body>
    <div class="bg-effects"></div>
    <div class="particles">
        <div class="particle" style="left: 10%; animation-delay: 0s;"></div>
        <div class="particle" style="left: 20%; animation-delay: 2s;"></div>
        <div class="particle" style="left: 30%; animation-delay: 4s;"></div>
        <div class="particle" style="left: 40%; animation-delay: 1s;"></div>
        <div class="particle" style="left: 50%; animation-delay: 3s;"></div>
        <div class="particle" style="left: 60%; animation-delay: 5s;"></div>
        <div class="particle" style="left: 70%; animation-delay: 2.5s;"></div>
        <div class="particle" style="left: 80%; animation-delay: 4.5s;"></div>
        <div class="particle" style="left: 90%; animation-delay: 1.5s;"></div>
    </div>
    
    <header class="header">
        <a href="/" class="logo">
            <div class="logo-icon">🚀</div>
            <span class="logo-text">TeleFileStream</span>
            <span class="logo-badge">Premium</span>
        </a>
    </header>
    
    <main class="main">
        <div class="card">
            <div class="icon-container">
                <div class="icon-ring"></div>
                <div class="icon-ring"></div>
                <div class="icon-ring"></div>
                <span class="file-icon">{file_icon}</span>
            </div>
            
            <div class="type-badge">
                ✨ {file_type}
            </div>
            
            <h1 class="title">Your File is Ready!</h1>
            
            <div class="filename">{filename}</div>
            
            <div class="meta">
                <div class="meta-item">📦 Size: <span>{size_str}</span></div>
                <div class="meta-item">🔒 <span>Secure</span></div>
                <div class="meta-item">✅ <span>Verified</span></div>
            </div>
            
            <a href="{download_url}" class="btn">
                <span class="btn-icon">⬇️</span>
                {btn_text}
            </a>
            
            <div class="speed-badge">
                <span class="speed-dot"></span>
                High-Speed Cloud Download
            </div>
            
            <div class="features">
                <div class="feature"><span class="feature-icon">⚡</span> Fast CDN</div>
                <div class="feature"><span class="feature-icon">🔐</span> Encrypted</div>
                <div class="feature"><span class="feature-icon">♾️</span> No Limits</div>
            </div>
        </div>
        
        <footer class="footer">
            <p class="footer-text">
                Powered by <a href="/">TeleFileStream</a> • Made with ❤️ by <a href="#">@Sanjay_Src</a>
            </p>
        </footer>
    </main>
    
    <script>
        // Add dynamic particle colors based on theme
        document.querySelectorAll('.particle').forEach(p => {{
            p.style.background = getComputedStyle(document.documentElement).getPropertyValue('--primary');
        }});
    </script>
</body>
</html>
""")

@app.get("/watch/{encoded_id}")
async def watch_player_redirect(encoded_id: str):
    return RedirectResponse(url=f"/v/{encoded_id}")

@app.get("/v_old/{encoded_id}")
async def universal_landing_page_old(encoded_id: str):
    return RedirectResponse(url=f"/v/{encoded_id}")

@app.get("/stream/{encoded_id}")
async def stream_file(encoded_id: str, request: Request):
    """Stream any supportable file (Videos, Audios, etc)"""
    try:
        msg_id = decode_id(encoded_id)
        if not SESSION_STRING: return JSONResponse({"error": "SESSION_STRING missing"}, status_code=500)
        
        client = await get_client()
        
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
        # 🚀 Use a slightly smaller chunk (256KB) to avoid Vercel payload limits/timeouts
        dl_iter = client.iter_download(msg.document, offset=start, limit=length, chunk_size=256*1024)
        
        headers = {
            'Content-Type': mime,
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': 'inline', # FORCE INLINE FOR BROWSER PLAYBACK
            'Access-Control-Allow-Origin': '*', # Explicit CORS for the stream
            'X-Content-Type-Options': 'nosniff',
        }
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status = 206
        else:
            status = 200
            
        print(f"📦 Streaming {filename} | Range: {start}-{end} | Type: {mime}")
        return StreamingResponse(TelegramStreamWrapper(client, dl_iter), status_code=status, headers=headers)
    except Exception as e:
        print(f"🔥 Stream Error: {e}")
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download/{encoded_id}")
async def download_file(encoded_id: str, request: Request):
    """Download any file type (Zip, PDF, APK, etc)"""
    try:
        msg_id = decode_id(encoded_id)
        if not SESSION_STRING: return JSONResponse({"error": "SESSION_STRING missing"}, status_code=500)

        client = await get_client()
        
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
