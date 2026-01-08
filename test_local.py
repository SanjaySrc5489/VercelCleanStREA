"""
Test local API endpoints for streaming and downloading
"""

import asyncio
import httpx

async def test_endpoints():
    """Test stream and download endpoints locally"""
    
    print("🧪 Testing Local API Endpoints")
    print("=" * 50)
    print()
    
    # Get message ID from user
    msg_id = input("Enter a message ID from BIN_CHANNEL (from test_telegram.py output): ")
    
    if not msg_id or not msg_id.isdigit():
        print("❌ Invalid message ID")
        return
    
    msg_id = int(msg_id)
    
    print()
    print(f"Testing with message ID: {msg_id}")
    print()
    
    # Test stream endpoint
    print("1️⃣ Testing Stream Endpoint (http://localhost:8001/{msg_id})")
    print("-" * 50)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"http://localhost:8001/{msg_id}")
            
            if response.status_code == 200:
                print("✅ Stream endpoint working!")
                print(f"   Status: {response.status_code}")
                print(f"   Content-Type: {response.headers.get('content-type')}")
                print(f"   Content-Length: {response.headers.get('content-length')} bytes")
                print(f"   Accept-Ranges: {response.headers.get('accept-ranges')}")
            else:
                print(f"❌ Failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("⚠️  Make sure the stream endpoint is running:")
        print("   uvicorn api.stream:app --port 8001 --reload")
    
    print()
    
    # Test download endpoint
    print("2️⃣ Testing Download Endpoint (http://localhost:8002/{msg_id})")
    print("-" * 50)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"http://localhost:8002/{msg_id}")
            
            if response.status_code == 200:
                print("✅ Download endpoint working!")
                print(f"   Status: {response.status_code}")
                print(f"   Content-Type: {response.headers.get('content-type')}")
                print(f"   Content-Length: {response.headers.get('content-length')} bytes")
                print(f"   Content-Disposition: {response.headers.get('content-disposition')}")
            else:
                print(f"❌ Failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("⚠️  Make sure the download endpoint is running:")
        print("   uvicorn api.download:app --port 8002 --reload")
    
    print()
    print("=" * 50)
    print("✅ Test complete!")
    print()
    print("💡 Tips:")
    print("   - Open http://localhost:8001/{msg_id} in browser to stream video")
    print("   - Open http://localhost:8002/{msg_id} in browser to download file")

if __name__ == "__main__":
    asyncio.run(test_endpoints())
