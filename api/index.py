import os
import tempfile
import subprocess
import json
from flask import Flask, request, jsonify
from urllib.parse import unquote, urlparse
import requests

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

def analyze_with_ffprobe(file_path):
    """Use ffprobe (part of ffmpeg) to analyze media file"""
    try:
        cmd = [
            'ffprobe', 
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise Exception(f"ffprobe failed: {result.stderr}")
        
        return json.loads(result.stdout)
    except Exception as e:
        raise Exception(f"Media analysis failed: {str(e)}")

@app.route('/', methods=['GET'])
def mediainfo_api():
    url = request.args.get('url')
    output_format = request.args.get('format', 'json').lower()
    
    if not url:
        return jsonify({
            "message": "MediaInfo API",
            "usage": "GET /?url=<media_url>&format=<json|text>",
            "example": "/?url=https://example.com/video.mp4&format=json"
        })
    
    try:
        # Download first 5MB for analysis
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Create temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tmp')
        downloaded = 0
        max_size = 5 * 1024 * 1024  # 5MB
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                downloaded += len(chunk)
                if downloaded >= max_size:
                    break
        
        temp_file.close()
        
        # Analyze with ffprobe
        media_data = analyze_with_ffprobe(temp_file.name)
        
        # Get filename
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or "media_file"
        filename = unquote(filename)
        
        # Clean up temp file
        os.unlink(temp_file.name)
        
        # Build response
        if output_format == 'json':
            # Extract key information
            format_info = media_data.get('format', {})
            streams = media_data.get('streams', [])
            
            tracks_data = []
            
            # General track
            general_track = {
                'track_type': 'General',
                'format': format_info.get('format_name'),
                'duration': format_info.get('duration'),
                'size': format_info.get('size'),
                'bit_rate': format_info.get('bit_rate')
            }
            tracks_data.append(general_track)
            
            # Process streams
            for stream in streams:
                if stream['codec_type'] == 'video':
                    video_track = {
                        'track_type': 'Video',
                        'format': stream.get('codec_name'),
                        'width': stream.get('width'),
                        'height': stream.get('height'),
                        'frame_rate': stream.get('r_frame_rate'),
                        'bit_rate': stream.get('bit_rate'),
                        'duration': stream.get('duration')
                    }
                    tracks_data.append(video_track)
                
                elif stream['codec_type'] == 'audio':
                    audio_track = {
                        'track_type': 'Audio',
                        'format': stream.get('codec_name'),
                        'channels': stream.get('channels'),
                        'sample_rate': stream.get('sample_rate'),
                        'bit_rate': stream.get('bit_rate'),
                        'duration': stream.get('duration')
                    }
                    tracks_data.append(audio_track)
            
            result = {
                "filename": filename,
                "file_size": get_readable_bytes(response.headers.get('content-length')),
                "tracks": tracks_data
            }
            
            return jsonify(result)
        
        else:
            # Text format
            output_lines = [f"File: {filename}"]
            format_info = media_data.get('format', {})
            
            output_lines.append(f"Format: {format_info.get('format_name', 'Unknown')}")
            if format_info.get('duration'):
                output_lines.append(f"Duration: {format_info.get('duration')} seconds")
            
            for stream in media_data.get('streams', []):
                if stream['codec_type'] == 'video':
                    output_lines.append(f"\nVideo Track:")
                    output_lines.append(f"  Codec: {stream.get('codec_name')}")
                    if stream.get('width'):
                        output_lines.append(f"  Resolution: {stream.get('width')}x{stream.get('height')}")
                    if stream.get('r_frame_rate'):
                        output_lines.append(f"  Frame Rate: {stream.get('r_frame_rate')}")
                
                elif stream['codec_type'] == 'audio':
                    output_lines.append(f"\nAudio Track:")
                    output_lines.append(f"  Codec: {stream.get('codec_name')}")
                    if stream.get('channels'):
                        output_lines.append(f"  Channels: {stream.get('channels')}")
                    if stream.get('sample_rate'):
                        output_lines.append(f"  Sample Rate: {stream.get('sample_rate')} Hz")
            
            return '\n'.join(output_lines), 200, {'Content-Type': 'text/plain'}
    
    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
