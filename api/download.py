"""
File Download Endpoint - FastAPI serverless function
File path: api/download.py -> becomes /api/download endpoint
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


def get_filename(msg):
    """Extract filename from message"""
    for attr in msg.document.attributes:
        if hasattr(attr, "file_name"):
            return attr.file_name
    return f"file_{msg.document.id}"


@app.get("/{msg_id}")
async def download_file(msg_id: int, request: Request):
    """Download file with proper headers"""
    
    # Debug: Check environment variables
    if not API_ID or not API_HASH:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Configuration Error",
                "details": "API_ID or API_HASH not set in environment variables"
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
    
    # Initialize client
    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)
    
    try:
        await client.start()
        
        # Get message
        msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        
        if not msg:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Message Not Found",
                    "details": f"Message ID {msg_id} not found in channel {BIN_CHANNEL}"
                }
            )
        
        if not msg.document:
            await client.disconnect()
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not a Document",
                    "details": f"Message ID {msg_id} has no document attached"
                }
            )
        
        # File info
        size = msg.document.size
        filename = get_filename(msg)
        
        # Parse range header
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
            chunk_size=1024 * 512  # 512KB chunks
        )
        
        # Wrap iterator to keep client alive during stream
        stream_wrapper = TelegramStreamWrapper(client, download_iterator)
        
        # Response headers
        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
        }
        
        if range_header:
            headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            status_code = 206
        else:
            status_code = 200
        
        return StreamingResponse(
            stream_wrapper,
            status_code=status_code,
            headers=headers,
            media_type='application/octet-stream'
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
