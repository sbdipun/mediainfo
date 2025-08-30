import re
import os
import json
import tempfile
import subprocess
from flask import Flask, request, jsonify
from urllib.parse import unquote, urlparse
import requests
from pymediainfo import MediaInfo

app = Flask(__name__)

def get_readable_bytes(size_bytes):
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def get_readable_bitrate(bitrate_bps):
    """Convert bitrate to human readable format"""
    if bitrate_bps < 1000:
        return f"{bitrate_bps:.0f} bps"
    elif bitrate_bps < 1000000:
        return f"{bitrate_bps/1000:.1f} Kbps"
    else:
        return f"{bitrate_bps/1000000:.1f} Mbps"

def is_gdrive_url(url):
    """Check if URL is a Google Drive link"""
    return "drive.google.com" in url or "docs.google.com" in url

def extract_gdrive_id(url):
    """Extract file ID from Google Drive URL"""
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

def download_sample(url, max_size=10*1024*1024):  # 10MB max
    """Download a sample of the file for mediainfo analysis"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        if is_gdrive_url(url):
            file_id = extract_gdrive_id(url)
            if not file_id:
                raise Exception("Invalid Google Drive URL")
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        else:
            download_url = url
        
        response = requests.get(download_url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        downloaded = 0
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                downloaded += len(chunk)
                if downloaded >= max_size:
                    break
        
        temp_file.close()
        return temp_file.name, response.headers.get('content-length')
        
    except Exception as e:
        raise Exception(f"Download failed: {str(e)}")

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "MediaInfo API",
        "usage": "GET /?url=<media_url>&format=<json|text>",
        "example": "/?url=https://example.com/video.mp4&format=json"
    })

@app.route('/', methods=['GET'])
def get_mediainfo():
    url = request.args.get('url')
    output_format = request.args.get('format', 'json').lower()
    
    if not url:
        return jsonify({"error": "URL parameter is required"}), 400
    
    try:
        # Download sample of the file
        temp_path, content_length = download_sample(url)
        
        try:
            # Parse with pymediainfo
            media_info = MediaInfo.parse(temp_path)
            
            # Get filename from URL
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path) or "unknown_file"
            filename = unquote(filename)
            
            if output_format == 'json':
                # Return JSON format
                tracks_data = []
                for track in media_info.tracks:
                    track_data = {
                        'track_type': track.track_type,
                        'track_id': track.track_id,
                    }
                    
                    # Add all available attributes
                    for attr_name in dir(track):
                        if not attr_name.startswith('_') and attr_name not in ['track_type', 'track_id']:
                            attr_value = getattr(track, attr_name, None)
                            if attr_value is not None and not callable(attr_value):
                                track_data[attr_name] = attr_value
                    
                    tracks_data.append(track_data)
                
                result = {
                    "filename": filename,
                    "file_size": get_readable_bytes(int(content_length)) if content_length else "Unknown",
                    "tracks": tracks_data
                }
                
                return jsonify(result)
            
            else:
                # Return text format (similar to mediainfo command output)
                text_output = []
                
                for track in media_info.tracks:
                    if track.track_type == 'General':
                        text_output.append("General")
                        text_output.append(f"Complete name                            : {filename}")
                        if content_length:
                            text_output.append(f"File size                                : {get_readable_bytes(int(content_length))}")
                        if track.duration:
                            text_output.append(f"Duration                                 : {track.duration}")
                        if track.format:
                            text_output.append(f"Format                                   : {track.format}")
                        if track.overall_bit_rate:
                            text_output.append(f"Overall bit rate                         : {get_readable_bitrate(float(track.overall_bit_rate))}")
                    
                    elif track.track_type == 'Video':
                        text_output.append("\nVideo")
                        if track.format:
                            text_output.append(f"Format                                   : {track.format}")
                        if track.width and track.height:
                            text_output.append(f"Width                                    : {track.width} pixels")
                            text_output.append(f"Height                                   : {track.height} pixels")
                        if track.frame_rate:
                            text_output.append(f"Frame rate                               : {track.frame_rate} FPS")
                        if track.bit_rate:
                            text_output.append(f"Bit rate                                 : {get_readable_bitrate(float(track.bit_rate))}")
                    
                    elif track.track_type == 'Audio':
                        text_output.append("\nAudio")
                        if track.format:
                            text_output.append(f"Format                                   : {track.format}")
                        if track.channel_s:
                            text_output.append(f"Channel(s)                               : {track.channel_s}")
                        if track.sampling_rate:
                            text_output.append(f"Sampling rate                            : {track.sampling_rate} Hz")
                        if track.bit_rate:
                            text_output.append(f"Bit rate                                 : {get_readable_bitrate(float(track.bit_rate))}")
                
                return "\n".join(text_output), 200, {'Content-Type': 'text/plain'}
        
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except:
                pass
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
