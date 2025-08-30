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
        
        # Convert to GiB, MiB, etc. for proper MediaInfo format
        if size_bytes >= 1024**3:
            return f"{size_bytes / (1024**3):.1f} GiB"
        elif size_bytes >= 1024**2:
            return f"{size_bytes / (1024**2):.1f} MiB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f} KiB"
        else:
            return f"{size_bytes} B"
    except:
        return "Unknown"

def get_readable_bitrate(bitrate_bps):
    """Convert bitrate to MediaInfo format"""
    if not bitrate_bps:
        return "Unknown"
    try:
        bitrate_bps = float(bitrate_bps)
        if bitrate_bps >= 1000000:
            return f"{bitrate_bps/1000000:.1f} Mb/s"
        elif bitrate_bps >= 1000:
            return f"{bitrate_bps/1000:.0f} kb/s"
        else:
            return f"{bitrate_bps:.0f} b/s"
    except:
        return "Unknown"

def format_duration(duration_ms):
    """Convert duration to MediaInfo format (e.g., '1 h 35 min')"""
    if not duration_ms:
        return "Unknown"
    try:
        duration_sec = float(duration_ms) / 1000
        hours = int(duration_sec // 3600)
        minutes = int((duration_sec % 3600) // 60)
        seconds = int(duration_sec % 60)
        
        if hours > 0:
            if minutes > 0:
                return f"{hours} h {minutes} min"
            else:
                return f"{hours} h"
        elif minutes > 0:
            if seconds > 0:
                return f"{minutes} min {seconds} s"
            else:
                return f"{minutes} min"
        else:
            return f"{seconds} s"
    except:
        return "Unknown"

def format_frame_rate(frame_rate):
    """Format frame rate to MediaInfo style"""
    if not frame_rate:
        return "Unknown"
    try:
        fr = float(frame_rate)
        if abs(fr - 23.976) < 0.01:
            return "23.976 (24000/1001) FPS"
        elif abs(fr - 29.97) < 0.01:
            return "29.970 (30000/1001) FPS"
        else:
            return f"{fr:.3f} FPS"
    except:
        return str(frame_rate)

def format_pixel_dimensions(width, height):
    """Format pixel dimensions with proper spacing"""
    try:
        # Add spaces for thousands like MediaInfo does
        width_str = f"{int(width):,}".replace(",", " ")
        height_str = f"{int(height):,}".replace(",", " ")
        return width_str, height_str
    except:
        return str(width), str(height)

def format_boolean_field(track, field_name, display_name):
    """Format boolean fields properly"""
    if not hasattr(track, field_name):
        return None
    
    value = getattr(track, field_name)
    
    # Skip if None or empty
    if value is None or value == '':
        return None
    
    # Handle different boolean representations from MediaInfo
    if isinstance(value, str):
        value_lower = value.lower().strip()
        if value_lower in ['yes', '1', 'true']:
            return f"{display_name}                                  : Yes"
        elif value_lower in ['no', '0', 'false']:
            return f"{display_name}                                  : No"
    elif isinstance(value, bool):
        return f"{display_name}                                  : {'Yes' if value else 'No'}"
    elif isinstance(value, (int, float)):
        if value == 1:
            return f"{display_name}                                  : Yes"
        elif value == 0:
            return f"{display_name}                                  : No"
    
    return None

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
    """Download sample using multiple fallback methods for Google Drive"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        if is_gdrive_url(url):
            file_id = extract_gdrive_id(url)
            if not file_id:
                raise Exception("Could not extract Google Drive file ID")
            
            # Multiple fallback URLs for Google Drive (no credentials needed)
            gdrive_methods = [
                f"https://drive.usercontent.google.com/download?id={file_id}&export=download",
                f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t",
                f"https://docs.google.com/uc?export=download&id={file_id}",
            ]
            
            for gdrive_url in gdrive_methods:
                try:
                    response = requests.get(gdrive_url, headers=headers, stream=True, timeout=30, allow_redirects=True)
                    
                    # Skip if we get HTML (error page)
                    content_type = response.headers.get('content-type', '').lower()
                    if 'text/html' in content_type and response.status_code != 200:
                        continue
                    
                    response.raise_for_status()
                    break
                except:
                    continue
            else:
                raise Exception("All Google Drive download methods failed - file may be private or restricted")
        else:
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
        
        # Download sample
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
    output_format = request.args.get('format', 'text').lower()
    
    if not url:
        return jsonify({
            "message": "MediaInfo API - Full Version",
            "status": "online",
            "usage": "GET /?url=<media_url>&format=<json|text>",
            "examples": {
                "text_format": "/?url=https://example.com/video.mp4&format=text",
                "json_format": "/?url=https://example.com/video.mp4&format=json",
                "gdrive_link": "/?url=https://drive.google.com/file/d/FILE_ID/view&format=text"
            },
            "note": "Default format is 'text' (MediaInfo style output)"
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
                # Build JSON response
                tracks_data = []
                
                for track in media_info.tracks:
                    track_data = {
                        'track_type': track.track_type,
                        'track_id': getattr(track, 'track_id', None)
                    }
                    
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
                    "file_size": get_readable_bytes(content_length) if content_length else "Unknown",
                    "tracks": tracks_data,
                    "api_version": "Full MediaInfo v1.0"
                }
                
                return jsonify(result)
            
            else:
                # Text format - MediaInfo style output
                output_lines = []
                audio_count = 0
                text_count = 0
                
                for track in media_info.tracks:
                    if track.track_type == 'General':
                        output_lines.append("General")
                        
                        # Unique ID
                        if hasattr(track, 'unique_id') and track.unique_id:
                            output_lines.append(f"Unique ID                                : {track.unique_id}")
                        
                        # Complete name
                        output_lines.append(f"Complete name                            : {filename}")
                        
                        # Format
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        # Format version
                        if hasattr(track, 'format_version') and track.format_version:
                            output_lines.append(f"Format version                           : {track.format_version}")
                        
                        # File size
                        file_size = content_length or getattr(track, 'file_size', None)
                        if file_size:
                            output_lines.append(f"File size                                : {get_readable_bytes(file_size)}")
                        
                        # Duration
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        # Overall bit rate mode
                        if hasattr(track, 'overall_bit_rate_mode') and track.overall_bit_rate_mode:
                            output_lines.append(f"Overall bit rate mode                    : {track.overall_bit_rate_mode}")
                        
                        # Overall bit rate
                        if hasattr(track, 'overall_bit_rate') and track.overall_bit_rate:
                            output_lines.append(f"Overall bit rate                         : {get_readable_bitrate(track.overall_bit_rate)}")
                        
                        # Frame rate (if available at container level)
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            output_lines.append(f"Frame rate                               : {format_frame_rate(track.frame_rate)}")
                        
                        # Title
                        if hasattr(track, 'title') and track.title:
                            output_lines.append(f"Title                                    : {track.title}")
                        
                        # Encoded date
                        if hasattr(track, 'encoded_date') and track.encoded_date:
                            output_lines.append(f"Encoded date                             : {track.encoded_date}")
                        
                        # Writing application
                        if hasattr(track, 'writing_application') and track.writing_application:
                            output_lines.append(f"Writing application                      : {track.writing_application}")
                        
                        # Writing library
                        if hasattr(track, 'writing_library') and track.writing_library:
                            output_lines.append(f"Writing library                          : {track.writing_library}")
                    
                    elif track.track_type == 'Video':
                        output_lines.append("\nVideo")
                        
                        # ID
                        if hasattr(track, 'track_id') and track.track_id:
                            output_lines.append(f"ID                                       : {track.track_id}")
                        
                        # Format
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        # Format/Info
                        if hasattr(track, 'format_info') and track.format_info:
                            output_lines.append(f"Format/Info                              : {track.format_info}")
                        
                        # Format profile
                        if hasattr(track, 'format_profile') and track.format_profile:
                            output_lines.append(f"Format profile                           : {track.format_profile}")
                        
                        # Format settings
                        if hasattr(track, 'format_settings') and track.format_settings:
                            output_lines.append(f"Format settings                          : {track.format_settings}")
                        
                        # Codec ID
                        if hasattr(track, 'codec_id') and track.codec_id:
                            output_lines.append(f"Codec ID                                 : {track.codec_id}")
                        
                        # Duration
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        # Bit rate mode
                        if hasattr(track, 'bit_rate_mode') and track.bit_rate_mode:
                            output_lines.append(f"Bit rate mode                            : {track.bit_rate_mode}")
                        
                        # Bit rate
                        if hasattr(track, 'bit_rate') and track.bit_rate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
                        
                        # Dimensions
                        if hasattr(track, 'width') and hasattr(track, 'height') and track.width and track.height:
                            width_str, height_str = format_pixel_dimensions(track.width, track.height)
                            output_lines.append(f"Width                                    : {width_str} pixels")
                            output_lines.append(f"Height                                   : {height_str} pixels")
                        
                        # Display aspect ratio
                        if hasattr(track, 'display_aspect_ratio') and track.display_aspect_ratio:
                            output_lines.append(f"Display aspect ratio                     : {track.display_aspect_ratio}")
                        elif hasattr(track, 'width') and hasattr(track, 'height') and track.width and track.height:
                            # Calculate aspect ratio
                            width, height = int(track.width), int(track.height)
                            if width == 1920 and height == 1080:
                                output_lines.append(f"Display aspect ratio                     : 16:9")
                            else:
                                ratio = width / height
                                output_lines.append(f"Display aspect ratio                     : {ratio:.3f}")
                        
                        # Frame rate mode
                        if hasattr(track, 'frame_rate_mode') and track.frame_rate_mode:
                            output_lines.append(f"Frame rate mode                          : {track.frame_rate_mode}")
                        
                        # Frame rate
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            output_lines.append(f"Frame rate                               : {format_frame_rate(track.frame_rate)}")
                        
                        # Color space
                        if hasattr(track, 'color_space') and track.color_space:
                            output_lines.append(f"Color space                              : {track.color_space}")
                        
                        # Chroma subsampling
                        if hasattr(track, 'chroma_subsampling') and track.chroma_subsampling:
                            output_lines.append(f"Chroma subsampling                       : {track.chroma_subsampling}")
                        
                        # Bit depth
                        if hasattr(track, 'bit_depth') and track.bit_depth:
                            output_lines.append(f"Bit depth                                : {track.bit_depth} bits")
                        
                        # Scan type
                        if hasattr(track, 'scan_type') and track.scan_type:
                            output_lines.append(f"Scan type                                : {track.scan_type}")
                        
                        # Stream size
                        if hasattr(track, 'stream_size') and track.stream_size:
                            stream_size = get_readable_bytes(track.stream_size)
                            output_lines.append(f"Stream size                              : {stream_size}")
                        
                        # Default and Forced (corrected)
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                    
                    elif track.track_type == 'Audio':
                        audio_count += 1
                        if audio_count == 1:
                            output_lines.append("\nAudio")
                        else:
                            output_lines.append(f"\nAudio #{audio_count}")
                        
                        # ID
                        if hasattr(track, 'track_id') and track.track_id:
                            output_lines.append(f"ID                                       : {track.track_id}")
                        
                        # Format
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        # Format/Info
                        if hasattr(track, 'format_info') and track.format_info:
                            output_lines.append(f"Format/Info                              : {track.format_info}")
                        
                        # Commercial name
                        if hasattr(track, 'commercial_name') and track.commercial_name:
                            output_lines.append(f"Commercial name                          : {track.commercial_name}")
                        
                        # Codec ID
                        if hasattr(track, 'codec_id') and track.codec_id:
                            output_lines.append(f"Codec ID                                 : {track.codec_id}")
                        
                        # Duration
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        # Bit rate mode
                        if hasattr(track, 'bit_rate_mode') and track.bit_rate_mode:
                            output_lines.append(f"Bit rate mode                            : {track.bit_rate_mode}")
                        
                        # Bit rate
                        if hasattr(track, 'bit_rate') and track.bit_rate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
                        
                        # Channel(s)
                        if hasattr(track, 'channel_s') and track.channel_s:
                            output_lines.append(f"Channel(s)                               : {track.channel_s}")
                        
                        # Channel layout
                        if hasattr(track, 'channel_layout') and track.channel_layout:
                            output_lines.append(f"Channel layout                           : {track.channel_layout}")
                        
                        # Sampling rate
                        if hasattr(track, 'sampling_rate') and track.sampling_rate:
                            sr = float(track.sampling_rate)
                            if sr >= 1000:
                                output_lines.append(f"Sampling rate                            : {sr/1000:.1f} kHz")
                            else:
                                output_lines.append(f"Sampling rate                            : {sr:.0f} Hz")
                        
                        # Frame rate
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            output_lines.append(f"Frame rate                               : {track.frame_rate} FPS")
                        
                        # Compression mode
                        if hasattr(track, 'compression_mode') and track.compression_mode:
                            output_lines.append(f"Compression mode                         : {track.compression_mode}")
                        
                        # Stream size
                        if hasattr(track, 'stream_size') and track.stream_size:
                            stream_size = get_readable_bytes(track.stream_size)
                            output_lines.append(f"Stream size                              : {stream_size}")
                        
                        # Title
                        if hasattr(track, 'title') and track.title:
                            output_lines.append(f"Title                                    : {track.title}")
                        
                        # Language
                        if hasattr(track, 'language') and track.language:
                            output_lines.append(f"Language                                 : {track.language}")
                        
                        # Default and Forced (corrected)
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                    
                    elif track.track_type == 'Text':
                        text_count += 1
                        if text_count == 1:
                            output_lines.append("\nText")
                        else:
                            output_lines.append(f"\nText #{text_count}")
                        
                        # ID
                        if hasattr(track, 'track_id') and track.track_id:
                            output_lines.append(f"ID                                       : {track.track_id}")
                        
                        # Format
                        if hasattr(track, 'format') and track.format:
                            output_lines.append(f"Format                                   : {track.format}")
                        
                        # Codec ID
                        if hasattr(track, 'codec_id') and track.codec_id:
                            output_lines.append(f"Codec ID                                 : {track.codec_id}")
                        
                        # Codec ID/Info
                        if hasattr(track, 'codec_id_info') and track.codec_id_info:
                            output_lines.append(f"Codec ID/Info                            : {track.codec_id_info}")
                        
                        # Duration
                        if hasattr(track, 'duration') and track.duration:
                            output_lines.append(f"Duration                                 : {format_duration(track.duration)}")
                        
                        # Bit rate
                        if hasattr(track, 'bit_rate') and track.bit_rate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(track.bit_rate)}")
                        
                        # Frame rate
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            output_lines.append(f"Frame rate                               : {track.frame_rate} FPS")
                        
                        # Count of elements
                        if hasattr(track, 'count_of_elements') and track.count_of_elements:
                            output_lines.append(f"Count of elements                        : {track.count_of_elements}")
                        
                        # Stream size
                        if hasattr(track, 'stream_size') and track.stream_size:
                            stream_size = get_readable_bytes(track.stream_size)
                            output_lines.append(f"Stream size                              : {stream_size}")
                        
                        # Title
                        if hasattr(track, 'title') and track.title:
                            output_lines.append(f"Title                                    : {track.title}")
                        
                        # Language
                        if hasattr(track, 'language') and track.language:
                            output_lines.append(f"Language                                 : {track.language}")
                        
                        # Default and Forced (corrected)
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                    
                    elif track.track_type == 'Menu':
                        output_lines.append("\nMenu")
                        
                        # Add chapter information if available
                        for attr_name in dir(track):
                            if not attr_name.startswith('_') and not callable(getattr(track, attr_name, None)):
                                attr_value = getattr(track, attr_name, None)
                                if attr_value is not None and 'chapter' in str(attr_value).lower():
                                    output_lines.append(f"{attr_name}                             : {attr_value}")
                
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
            "url": url
        }), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        from pymediainfo import MediaInfo
        return jsonify({
            "status": "healthy",
            "service": "mediainfo-api",
            "mediainfo_available": True
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
