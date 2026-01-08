# StreamGobhar - Telegram File Streaming Bot

🎬 Stream and download files from Telegram with direct links!

## ✨ Features

- 📤 Upload files via Telegram bot
- ▶️ Direct video streaming with range support
- ⬇️ File downloads with resume capability  
- 🔒 Session-based authentication
- ☁️ Vercel serverless deployment
- 🌐 Auto URL detection

## 🚀 Quick Start

### 1. Setup Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your credentials:
# - BOT_TOKEN (from @BotFather)
# - SESSION_STRING (generate using generate_session.py)
```

### 2. Generate Session String

```bash
python generate_session.py
```

Follow the prompts to login with your phone number and OTP. The session string will be saved to `.env` automatically.

### 3. Test Locally

#### Option A: Run as Webhook (for Vercel testing)
```bash
uvicorn index:app --port 8000
```

#### Option B: Run as Bot (for local testing)
```bash
python bot.py
```

### 4. Deploy to Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
vercel --prod
```

**Important**: Add all environment variables from `.env` to your Vercel project settings!

### 5. Set Webhook

After deploying to Vercel:

```
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-project.vercel.app/webhook
```

## 📁 Project Structure

```
vercel_clean/
├── index.py              # Main FastAPI app (webhook, stream, download)
├── bot.py                # Standalone bot for local testing
├── generate_session.py   # Session string generator
├── requirements.txt      # Python dependencies
├── vercel.json          # Vercel configuration
├── .env.example         # Environment template
└── README.md            # This file
```

## 🌐 API Endpoints

After deployment:

- `GET /` - API info
- `GET /health` - Health check
- `POST /webhook` - Telegram webhook
- `GET /stream/{msg_id}` - Stream video
- `GET /download/{msg_id}` - Download file

## 📝 Usage

### With Bot (Local)

1. Start bot: `python bot.py`
2. Send any file to your bot on Telegram
3. Get stream and download links instantly!

### With Webhook (Vercel)

1. Deploy to Vercel
2. Set webhook URL
3. Send files to bot
4. Bot responds with links

## 🔧 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `API_ID` | Telegram API ID | ✅ |
| `API_HASH` | Telegram API Hash | ✅ |
| `BOT_TOKEN` | Bot token from @BotFather | ✅ |
| `BIN_CHANNEL` | Storage channel ID | ✅ |
| `SESSION_STRING` | User session for file access | ✅ |
| `PHONE_NUMBER` | Your phone number | ⚠️ (for session generation) |
| `BASE_URL` | Your Vercel URL | ⚠️ (auto-detected on Vercel) |

## 🐛 Troubleshooting

**Bot not responding?**
- Check `BOT_TOKEN` is valid and current
- Verify webhook is set correctly
- Check Vercel function logs for errors

**Stream not working?**
- Ensure `SESSION_STRING` is set in Vercel
- Verify file was uploaded through bot
- Check message ID is correct

**"Not Found" errors?**
- Check environment variables are set on Vercel
- Verify `BIN_CHANNEL` ID is correct
- Make sure bot is admin in storage channel

## 📄 License

MIT License - Free to use and modify!

---

**Made with ❤️ for seamless Telegram file streaming**
