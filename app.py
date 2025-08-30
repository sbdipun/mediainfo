import re
import os
import json
import tempfile
from flask import Flask, request, jsonify
from urllib.parse import unquote, urlparse
import requests
from pymediainfo import MediaInfo

app = Flask(__name__)

def get_readable_bytes(size_bytes):
    if not size_bytes:
        return "Unknown"
    size_bytes = int(size_bytes)
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def get_readable_bitrate(bitrate_bps):
    if not bitrate_bps:
        return "Unknown"
    bitrate_bps = float(bitrate_bps)
    if bitrate_bps < 1000:
        return f"{bitrate_bps:.0f} bps"
    elif bitrate_bps < 1000000:
        return f"{bitrate_bps/1000:.1f} Kbps"
    else:
        return f"{bitrate_bps/1000000:.1f} Mbps"

def is_gdrive_url(url):
    return "drive.google.com" in url or "docs.google.com" in url

def extract_gdrive_id(url):
    patterns = [
        r'/file/d/([a-zA-Z0-9-_]+)',
        r'id=([a-zA-Z0-9-_]+)',
        r'/open\?id=([a-zA-Z0-9-_]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

@app.route('/', methods=['GET'])
def mediainfo_api():
    url = request.args.get('url')
    output_format = request.args.get('format', 'json').lower()
    
    if not url:
        return jsonify({
            "message": "MediaInfo API - Full Version on Render",
            "usage": "GET /?url=<media_url>&format=<json|text>",
            "example": "/?url=https://example.com/video.mp4&format=json",
            "features": ["Full MediaInfo support", "Google Drive links", "Direct download links"]
        })
    
    try:
        # Handle Google Drive URLs
        if is_gdrive_url(url):
            file_id = extract_gdrive_id(url)
            if file_id:
                url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        # Download sample for analysis
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tmp')
        downloaded = 0
        max_size = 10 * 1024 * 1024  # 10MB sample
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                downloaded += len(chunk)
                if downloaded >= max_size:
                    break
        
        temp_file.close()
        
        # Parse with MediaInfo
        media_info = MediaInfo.parse(temp_file.name)
        
        # Get filename
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or "media_file"
        filename = unquote(filename)
        
        # Clean up temp file
        os.unlink(temp_file.name)
        
        if output_format == 'json':
            # Build detailed JSON response
            tracks_data = []
            
            for track in media_info.tracks:
                track_data = {
                    'track_type': track.track_type,
                    'track_id': getattr(track, 'track_id', None)
                }
                
                # Add all available attributes
                for attr_name in dir(track):
                    if (not attr_name.startswith('_') and 
                        attr_name not in ['track_type', 'track_id'] and
                        not callable(getattr(track, attr_name, None))):
                        
                        attr_value = getattr(track, attr_name, None)
                        if attr_value is not None:
                            track_data[attr_name] = attr_value
                
                tracks_data.append(track_data)
            
            result = {
                "filename": filename,
                "file_size": get_readable_bytes(response.headers.get('content-length')),
                "tracks": tracks_data,
                "api_version": "Full MediaInfo on Render"
            }
            
            return jsonify(result)
        
        else:
            # Text format (MediaInfo style)
            output_lines = []
            
            for track in media_info.tracks:
                if track.track_type == 'General':
                    output_lines.append("General")
                    output_lines.append(f"Complete name                            : {filename}")
                    
                    file_size = response.headers.get('content-length')
                    if file_size:
                        output_lines.append(f"File size                                : {get_readable_bytes(file_size)}")
                    
                    if hasattr(track, 'format') and track.format:
                        output_lines.append(f"Format                                   : {track.format}")
                    
                    if hasattr(track, 'duration') and track.duration:
                        duration_ms = float(track.duration)
                        duration_sec = duration_ms / 1000
                        hours = int(duration_sec // 3600)
                        minutes = int((duration_sec % 3600) // 60)
                        seconds = int(duration_sec % 60)
                        output_lines.append(f"Duration                                 : {hours:02d}:{minutes:02d}:{seconds:02d}")
                    
                    if hasattr(track, 'overall_bit_rate') and track.overall_bit_rate:
                        output_lines.append(f"Overall bit rate                         : {get_readable_bitrate(track.overall_bit_rate)}")
                
                elif track.track_type == 'Video':
                    output_lines.append("\nVideo")
                    
                    if hasattr(track, 'format') and track.format:
                        output_lines.append(f"Format                                   : {track.format}")
                    
                    if hasattr(track, 'width') and hasattr(track, 'height'):
                        output_lines.append(f"Width                                    : {track.width} pixels")
                        output_lines.append(f"Height                                   : {track.height} pixels")
                        output_lines.append(f"Display aspect ratio                     : {track.width}:{track.height}")
                    
                    if hasattr(track, 'frame_rate') and track.frame_rate:
                        output_lines.append(f"Frame rate                               : {track.frame_rate} FPS")
                    
                    if hasattr(track, 'bit_rate') and track.bit_rate:
                        output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
                
                elif track.track_type == 'Audio':
                    output_lines.append("\nAudio")
                    
                    if hasattr(track, 'format') and track.format:
                        output_lines.append(f"Format                                   : {track.format}")
                    
                    if hasattr(track, 'channel_s') and track.channel_s:
                        output_lines.append(f"Channel(s)                               : {track.channel_s}")
                    
                    if hasattr(track, 'sampling_rate') and track.sampling_rate:
                        output_lines.append(f"Sampling rate                            : {track.sampling_rate} Hz")
                    
                    if hasattr(track, 'bit_rate') and track.bit_rate:
                        output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
            
            return '\n'.join(output_lines), 200, {'Content-Type': 'text/plain'}
    
    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
