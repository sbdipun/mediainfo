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
    """Convert bytes to human readable format"""
    if not size_bytes:
        return "Unknown"
    try:
        size_bytes = int(size_bytes)
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"
    except:
        return "Unknown"

def get_readable_bitrate(bitrate_bps):
    """Convert bitrate to human readable format"""
    if not bitrate_bps:
        return "Unknown"
    try:
        bitrate_bps = float(bitrate_bps)
        if bitrate_bps < 1000:
            return f"{bitrate_bps:.0f} bps"
        elif bitrate_bps < 1000000:
            return f"{bitrate_bps/1000:.1f} Kbps"
        else:
            return f"{bitrate_bps/1000000:.1f} Mbps"
    except:
        return "Unknown"

def format_duration(duration_ms):
    """Convert duration from milliseconds to HH:MM:SS format"""
    if not duration_ms:
        return "Unknown"
    try:
        duration_sec = float(duration_ms) / 1000
        hours = int(duration_sec // 3600)
        minutes = int((duration_sec % 3600) // 60)
        seconds = int(duration_sec % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except:
        return "Unknown"

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

def download_sample(url, max_size=10*1024*1024):
    """Download a sample of the file for mediainfo analysis"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Handle Google Drive URLs
        if is_gdrive_url(url):
            file_id = extract_gdrive_id(url)
            if file_id:
                url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tmp')
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
def mediainfo_api():
    url = request.args.get('url')
    output_format = request.args.get('format', 'json').lower()
    
    if not url:
        return jsonify({
            "message": "MediaInfo API - Full Version on Render",
            "status": "online",
            "usage": "GET /?url=<media_url>&format=<json|text>",
            "examples": {
                "json_format": "/?url=https://example.com/video.mp4&format=json",
                "text_format": "/?url=https://example.com/video.mp4&format=text",
                "gdrive_link": "/?url=https://drive.google.com/file/d/FILE_ID/view&format=json"
            },
            "supported_formats": ["MP4", "AVI", "MKV", "MOV", "MP3", "WAV", "FLAC", "AAC"],
            "features": [
                "Full MediaInfo analysis",
                "Google Drive links support", 
                "Direct download links",
                "Resolution, codecs, bitrates",
                "Duration and technical specs"
            ]
        })
    
    try:
        # Download sample of the file
        temp_path, content_length = download_sample(url)
        
        try:
            # Parse with MediaInfo
            media_info = MediaInfo.parse(temp_path)
            
            # Get filename from URL
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path) or "media_file"
            filename = unquote(filename)
            
            if output_format == 'json':
                # Build detailed JSON response
                tracks_data = []
                
                for track in media_info.tracks:
                    track_data = {
                        'track_type': track.track_type,
                        'track_id': getattr(track, 'track_id', None)
                    }
                    
                    # Add all available attributes with better formatting
                    for attr_name in dir(track):
                        if (not attr_name.startswith('_') and 
                            attr_name not in ['track_type', 'track_id'] and
                            not callable(getattr(track, attr_name, None))):
                            
                            attr_value = getattr(track, attr_name, None)
                            if attr_value is not None:
                                # Format specific attributes for better readability
                                if attr_name == 'duration' and attr_value:
                                    track_data[attr_name] = attr_value
                                    track_data['duration_formatted'] = format_duration(attr_value)
                                elif attr_name in ['bit_rate', 'overall_bit_rate'] and attr_value:
                                    track_data[attr_name] = attr_value
                                    track_data[f'{attr_name}_formatted'] = get_readable_bitrate(attr_value)
                                elif attr_name == 'file_size' and attr_value:
                                    track_data[attr_name] = attr_value
                                    track_data['file_size_formatted'] = get_readable_bytes(attr_value)
                                else:
                                    track_data[attr_name] = attr_value
                    
                    tracks_data.append(track_data)
                
                result = {
                    "filename": filename,
                    "file_size": get_readable_bytes(content_length) if content_length else "Unknown",
                    "file_size_bytes": content_length,
                    "url": url,
                    "tracks": tracks_data,
                    "track_count": len(tracks_data),
                    "api_version": "Full MediaInfo v1.0",
                    "timestamp": format_duration(None),  # Current time if needed
                    "analysis_status": "complete"
                }
                
                return jsonify(result)
            
            else:
                # Text format (MediaInfo style output)
                output_lines = []
                
                for track in media_info.tracks:
                    if track.track_type == 'General':
                        output_lines.append("General")
                        output_lines.append(f"Complete name                            : {filename}")
                        
                        file_size = content_length
                        if file_size:
                            output_lines.append(f"File size                                : {get_readable_bytes(file_size)}")
                        
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        if hasattr(track, 'format_profile') and track.format_profile:
                            output_lines.append(f"Format profile                           : {track.format_profile}")
                        
                        if hasattr(track, 'codec_id') and track.codec_id:
                            output_lines.append(f"Codec ID                                 : {track.codec_id}")
                        
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        if hasattr(track, 'overall_bit_rate') and track.overall_bit_rate:
                            output_lines.append(f"Overall bit rate                         : {get_readable_bitrate(track.overall_bit_rate)}")
                        
                        if hasattr(track, 'writing_application') and track.writing_application:
                            output_lines.append(f"Writing application                      : {track.writing_application}")
                    
                    elif track.track_type == 'Video':
                        output_lines.append("\nVideo")
                        
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        if hasattr(track, 'format_profile') and track.format_profile:
                            output_lines.append(f"Format profile                           : {track.format_profile}")
                        
                        if hasattr(track, 'codec_id') and track.codec_id:
                            output_lines.append(f"Codec ID                                 : {track.codec_id}")
                        
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        if hasattr(track, 'bit_rate') and track.bit_rate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
                        
                        if hasattr(track, 'width') and hasattr(track, 'height'):
                            output_lines.append(f"Width                                    : {track.width} pixels")
                            output_lines.append(f"Height                                   : {track.height} pixels")
                            
                            # Calculate aspect ratio
                            if track.width and track.height:
                                aspect_ratio = track.width / track.height
                                output_lines.append(f"Display aspect ratio                     : {aspect_ratio:.3f}")
                        
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            output_lines.append(f"Frame rate                               : {track.frame_rate} FPS")
                        
                        if hasattr(track, 'color_space') and track.color_space:
                            output_lines.append(f"Color space                              : {track.color_space}")
                        
                        if hasattr(track, 'chroma_subsampling') and track.chroma_subsampling:
                            output_lines.append(f"Chroma subsampling                       : {track.chroma_subsampling}")
                        
                        if hasattr(track, 'bit_depth') and track.bit_depth:
                            output_lines.append(f"Bit depth                                : {track.bit_depth} bits")
                    
                    elif track.track_type == 'Audio':
                        output_lines.append("\nAudio")
                        
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        if hasattr(track, 'format_profile') and track.format_profile:
                            output_lines.append(f"Format profile                           : {track.format_profile}")
                        
                        if hasattr(track, 'codec_id') and track.codec_id:
                            output_lines.append(f"Codec ID                                 : {track.codec_id}")
                        
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        if hasattr(track, 'bit_rate_mode') and track.bit_rate_mode:
                            output_lines.append(f"Bit rate mode                            : {track.bit_rate_mode}")
                        
                        if hasattr(track, 'bit_rate') and track.bit_rate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
                        
                        if hasattr(track, 'channel_s') and track.channel_s:
                            output_lines.append(f"Channel(s)                               : {track.channel_s}")
                        
                        if hasattr(track, 'channel_layout') and track.channel_layout:
                            output_lines.append(f"Channel layout                           : {track.channel_layout}")
                        
                        if hasattr(track, 'sampling_rate') and track.sampling_rate:
                            output_lines.append(f"Sampling rate                            : {track.sampling_rate} Hz")
                        
                        if hasattr(track, 'bit_depth') and track.bit_depth:
                            output_lines.append(f"Bit depth                                : {track.bit_depth} bits")
                        
                        if hasattr(track, 'compression_mode') and track.compression_mode:
                            output_lines.append(f"Compression mode                         : {track.compression_mode}")
                
                return '\n'.join(output_lines), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except:
                pass
    
    except Exception as e:
        return jsonify({
            "error": f"Processing failed: {str(e)}",
            "url": url,
            "suggestion": "Check if the URL is accessible and points to a valid media file"
        }), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Test MediaInfo installation
        from pymediainfo import MediaInfo
        return jsonify({
            "status": "healthy",
            "service": "mediainfo-api",
            "mediainfo_available": True,
            "version": "1.0"
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "mediainfo_available": False
        }), 500

@app.route('/info')
def info():
    """API information endpoint"""
    return jsonify({
        "api_name": "MediaInfo API",
        "version": "1.0",
        "description": "Extract detailed media information from video and audio files",
        "endpoints": {
            "/": "Main MediaInfo analysis endpoint",
            "/health": "Health check",
            "/info": "API information"
        },
        "supported_url_types": [
            "Direct download links",
            "Google Drive links",
            "HTTP/HTTPS URLs"
        ],
        "output_formats": ["json", "text"],
        "max_sample_size": "10MB",
        "deployment": "Render with Docker"
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
