import os
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
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        downloaded = 0
        max_size = 5 * 1024 * 1024  # 5MB
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                downloaded += len(chunk)
                if downloaded >= max_size:
                    break
        
        temp_file.close()
        
        # Parse with pymediainfo
        media_info = MediaInfo.parse(temp_file.name)
        
        # Get filename
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or "media_file"
        filename = unquote(filename)
        
        # Clean up temp file
        os.unlink(temp_file.name)
        
        # Build response
        if output_format == 'json':
            tracks_data = []
            for track in media_info.tracks:
                track_data = {'track_type': track.track_type}
                
                # Add key attributes
                attrs_to_include = [
                    'format', 'duration', 'file_size', 'overall_bit_rate',
                    'width', 'height', 'frame_rate', 'bit_rate',
                    'channel_s', 'sampling_rate', 'codec_id'
                ]
                
                for attr in attrs_to_include:
                    value = getattr(track, attr, None)
                    if value is not None:
                        track_data[attr] = value
                
                tracks_data.append(track_data)
            
            result = {
                "filename": filename,
                "file_size": get_readable_bytes(response.headers.get('content-length')),
                "tracks": tracks_data
            }
            
            return jsonify(result)
        
        else:
            # Text format
            output_lines = [f"File: {filename}"]
            for track in media_info.tracks:
                output_lines.append(f"\n{track.track_type} Track:")
                if hasattr(track, 'format') and track.format:
                    output_lines.append(f"  Format: {track.format}")
                if hasattr(track, 'duration') and track.duration:
                    output_lines.append(f"  Duration: {track.duration}")
                if hasattr(track, 'width') and track.width:
                    output_lines.append(f"  Resolution: {track.width}x{track.height}")
            
            return '\n'.join(output_lines), 200, {'Content-Type': 'text/plain'}
    
    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
