"""
Configuration loader - loads all settings from environment variables
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram credentials
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Storage channel
BIN_CHANNEL = int(os.getenv("BIN_CHANNEL", "0"))

# Session string for persistent auth
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Phone number (for session generation)
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")

# Auto-detect base URL (Vercel sets VERCEL_URL automatically)
VERCEL_URL = os.getenv("VERCEL_URL", "")
if VERCEL_URL:
    BASE_URL = f"https://{VERCEL_URL}"
else:
    BASE_URL = os.getenv("BASE_URL", "http://localhost:9090")
