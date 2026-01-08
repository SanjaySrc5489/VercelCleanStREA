# StreamGobhar - Telegram File Streaming Bot

Telegram bot that uploads files to a channel and provides direct streaming & download links. Fully compatible with Vercel serverless deployment!

## ✨ Features

- 📤 Upload files via Telegram bot
- ▶️ Direct video streaming with range support
- ⬇️ File downloads with resume capability
- 🔒 Session string authentication (no repeated logins)
- ☁️ Vercel serverless deployment ready
- 🌐 Auto URL detection on Vercel

## 🚀 Quick Setup

### 1. Get New Bot Token

Your old bot token has expired. Get a new one:
1. Open Telegram → Search `@BotFather`
2. Send `/mybots`
3. Select your bot → **API Token**
4. Copy the new token

### 2. Configure Environment

```bash
# Copy template to create .env file
cp .env.example .env

# Edit .env and update BOT_TOKEN with your new token
# Everything else is already filled in!
```

### 3. Deploy to Vercel

```bash
# Install Vercel CLI (optional)
npm install -g vercel

# Deploy
vercel
```

Or push to GitHub and import to Vercel dashboard.

### 4. Add Environment Variables on Vercel

Go to your Vercel project → Settings → Environment Variables:

| Variable | Value (from your .env) |
|----------|------------------------|
| `API_ID` | `29269836` |
| `API_HASH` | `4547cf93e5e9907e849dfe7691e6e302` |
| `BOT_TOKEN` | Your new token from BotFather |
| `BIN_CHANNEL` | `-1002466349953` |
| `SESSION_STRING` | The long string from .env |

### 5. Set Telegram Webhook

After deployment, set webhook (replace with your Vercel URL):

```
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-project.vercel.app/api/webhook
```

## 📝 Usage

1. Send `/start` to your bot
2. Send any video/file
3. Get streaming & download links instantly!

## 🏗️ Project Structure

```
vercel_clean/
├── api/
│   ├── index.py       # Root endpoint
│   ├── webhook.py     # Bot webhook handler
│   ├── stream.py      # Video streaming
│   └── download.py    # File downloads
├── config.py          # Configuration loader
├── requirements.txt   # Python dependencies
├── vercel.json        # Vercel config
├── .env              # Local environment (create from .env.example)
├── .env.example      # Environment template
└── README.md         # This file
```

## 🔧 Local Testing (Optional)

You can test locally before deploying:

```bash
# Install dependencies
pip install -r requirements.txt

# Run webhook endpoint
uvicorn api.webhook:app --port 8000

# In another terminal, run stream endpoint
uvicorn api.stream:app --port 8001
```

Note: For local testing, you'll need to use a tool like `ngrok` to expose your localhost to the internet for Telegram webhooks.

## 🌐 Endpoints

After deployment:
- **Webhook**: `https://your-project.vercel.app/api/webhook`
- **Stream**: `https://your-project.vercel.app/api/stream/{msg_id}`
- **Download**: `https://your-project.vercel.app/api/download/{msg_id}`

## 🔐 Security

- ✅ All credentials in environment variables
- ✅ `.env` file gitignored
- ✅ Session string for persistent auth
- ✅ No sensitive data in code

## ❓ Troubleshooting

**Bot not responding?**
- Verify you updated `BOT_TOKEN` with a new token
- Check webhook is set correctly
- Verify all environment variables on Vercel

**Session expired?**
- Session string is already in `.env.example`
- Just copy it to your `.env` file

**Files not found?**
- Upload files through your bot first
- Use the message IDs from bot responses

## 📄 License

MIT License - Free to use and modify!

---

**Need help?** Check that:
1. ✅ You got a new `BOT_TOKEN` from @BotFather
2. ✅ All environment variables are set on Vercel
3. ✅ Webhook URL is set correctly
4. ✅ Bot is admin in the storage channel
