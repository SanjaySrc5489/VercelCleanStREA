"""
Test script to verify Telegram client can access messages
Run this locally to ensure session string works
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH, BIN_CHANNEL, SESSION_STRING

async def test_telegram_access():
    """Test if we can connect and access messages from BIN_CHANNEL"""
    
    print("🔍 Testing Telegram Connection...")
    print(f"API_ID: {API_ID}")
    print(f"API_HASH: {API_HASH[:10]}..." if API_HASH else "Missing!")
    print(f"BIN_CHANNEL: {BIN_CHANNEL}")
    print(f"SESSION_STRING: {'✅ Present' if SESSION_STRING else '❌ Missing'}")
    print()
    
    # Initialize client with session string
    session = StringSession(SESSION_STRING) if SESSION_STRING else StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    
    try:
        print("📡 Connecting to Telegram...")
        await client.start()
        print("✅ Connected successfully!")
        print()
        
        # Get account info
        me = await client.get_me()
        print(f"👤 Logged in as: {me.first_name} ({me.phone})")
        print()
        
        # Try to get messages from BIN_CHANNEL
        print(f"📬 Fetching messages from channel {BIN_CHANNEL}...")
        messages = await client.get_messages(BIN_CHANNEL, limit=5)
        
        if messages:
            print(f"✅ Found {len(messages)} messages!")
            print("\nRecent messages:")
            for msg in messages:
                if msg.document:
                    size_mb = msg.document.size / (1024 * 1024)
                    print(f"  - ID {msg.id}: {msg.document.mime_type} ({size_mb:.2f} MB)")
                elif msg.message:
                    preview = msg.message[:50] + "..." if len(msg.message) > 50 else msg.message
                    print(f"  - ID {msg.id}: {preview}")
                else:
                    print(f"  - ID {msg.id}: [No content]")
            print()
            
            # Test downloading first message with a file
            for msg in messages:
                if msg.document:
                    print(f"🧪 Testing download access for message {msg.id}...")
                    # Just test that we can iterate (don't actually download)
                    chunk_count = 0
                    async for chunk in client.iter_download(msg.document, chunk_size=1024, limit=1024*10):  # Only first 10kb
                        chunk_count += 1
                    print(f"✅ Successfully accessed {chunk_count} chunks!")
                    break
        else:
            print("⚠️ No messages found in channel. Upload a file using your bot first!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.disconnect()
        print("\n✅ Test complete!")

if __name__ == "__main__":
    asyncio.run(test_telegram_access())
