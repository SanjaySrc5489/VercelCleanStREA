"""
Generate a valid Telegram session string for user authentication
Run this script to login and get a session string for .env file
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH, PHONE_NUMBER

async def generate_session():
    """Login to Telegram and generate session string"""
    
    print("🔐 Session String Generator")
    print("=" * 50)
    print()
    
    # Check if credentials are configured
    if not API_ID or API_ID == 0:
        print("❌ API_ID not found! Please set it in .env file")
        return
    
    if not API_HASH:
        print("❌ API_HASH not found! Please set it in .env file")
        return
    
    phone = PHONE_NUMBER
    if not phone:
        print("⚠️ PHONE_NUMBER not found in .env, prompting for it...")
        phone = input("Enter your phone number (with country code, e.g., +1234567890): ")
    
    print(f"📱 Phone: {phone}")
    print(f"🔑 API_ID: {API_ID}")
    print()
    
    # Initialize client with empty StringSession
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    try:
        print("📡 Connecting to Telegram...")
        await client.start(phone=phone)
        
        print("✅ Successfully logged in!")
        print()
        
        # Get account info
        me = await client.get_me()
        print(f"👤 Account: {me.first_name}")
        print(f"📞 Phone: {me.phone}")
        print()
        
        # Generate session string
        session_string = client.session.save()
        
        print("=" * 50)
        print("✅ SESSION STRING GENERATED!")
        print("=" * 50)
        print()
        print("Copy this to your .env file as SESSION_STRING:")
        print()
        print(f"SESSION_STRING={session_string}")
        print()
        print("=" * 50)
        
        # Save to a file as well
        with open("session_string.txt", "w") as f:
            f.write(f"SESSION_STRING={session_string}\n")
        
        print()
        print("✅ Also saved to session_string.txt")
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.disconnect()
        print("✅ Done!")

if __name__ == "__main__":
    print()
    print("⚠️  IMPORTANT:")
    print("   You will receive an OTP code on Telegram.")
    print("   Enter it when prompted to complete login.")
    print()
    asyncio.run(generate_session())
