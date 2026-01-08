"""
Video Streaming Endpoint - FastAPI serverless function
File path: api/stream.py -> becomes /api/stream endpoint
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from telethon import TelegramClient
from telethon.sessions import StringSession
import os
import sys
import traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import API_ID, API_HASH, BIN_CHANNEL, SESSION_STRING

app = FastAPI()


class TelegramStreamWrapper:
    """Wrapper to keep client alive during streaming"""
    def __init__(self, client, iterator):
        self.client = client
        self.iterator = iterator
    
    async def __aiter__(self):
        try:
            async for chunk in self.iterator:
                yield chunk
        finally:
            # Disconnect after streaming is complete
            await self.client.disconnect()


@app.get("/{msg_id}")
async def stream_video(msg_id: int, request: Request):
    """Stream video with range request support"""
    
    # Debug: Check environment variables
    if not API_ID or not API_HASH:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "API_ID or API_HASH not set in environment variables",
                "api_id_set": bool(API_ID),
                "api_hash_set": bool(API_HASH)
            }
        )
    
    if not SESSION_STRING:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "SESSION_STRING not set in environment variables",
                "hint": "Add SESSION_STRING to Vercel environment variables"
            }
        )
    
    # Initialize client with session string
    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)
    
    try:
        await client.start()
        
        # Get message from storage channel
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        
        if not msg:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Message Not Found",
                    "details": f"Message ID {msg_id} not found in channel {BIN_CHANNEL}",
                    "hint": "Make sure the file was uploaded through the bot first"
                }
            )
        
        if not msg.document:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not a Document",
                    "details": f"Message ID {msg_id} exists but has no document attached",
                    "message_type": str(type(msg.media))
                }
            )
        
        # File info
        size = msg.document.size
        
        # Parse range header for partial content support
        range_header = request.headers.get('range', '')
        start = 0
        end = size - 1
        
        if range_header:
            range_value = range_header.replace('bytes=', '').split('-')
            start = int(range_value[0]) if range_value[0] else 0
            end = int(range_value[1]) if len(range_value) > 1 and range_value[1] else end
            end = min(end, size - 1)
        
        length = end - start + 1
        
        # Create iterator for downloading
        download_iterator = client.iter_download(
            msg.document,
            offset=start,
            limit=length,
            chunk_size=1024 * 512  # 512KB chunks for better performance
        )
        
        # Wrap iterator to keep client alive during stream
        stream_wrapper = TelegramStreamWrapper(client, download_iterator)
        
        # Response headers
        headers = {
            'Content-Type': 'video/mp4',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
        }
        
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status_code = 206  # Partial Content
        else:
            status_code = 200
        
        return StreamingResponse(
            stream_wrapper,
            status_code=status_code,
            headers=headers,
            media_type='video/mp4'
        )
    
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "exception_type": type(e).__name__,
                "details": str(e),
                "traceback": traceback.format_exc()
            }
        )


