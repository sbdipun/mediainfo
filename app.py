import re
import os
import json
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from urllib.parse import unquote, urlparse
import requests
from pymediainfo import MediaInfo
import pycountry

app = Flask(__name__, static_folder='.')

def get_full_language_name(lang_code):
    """Convert ISO language code to full language name using pycountry"""
    if not lang_code:
        return None
    
    try:
        lang_code_str = str(lang_code).strip()
        
        # Try alpha_2 (2-letter code like 'en')
        if len(lang_code_str) == 2:
            lang = pycountry.languages.get(alpha_2=lang_code_str.lower())
            if lang:
                return lang.name
        
        # Try alpha_3 (3-letter code like 'eng')
        if len(lang_code_str) == 3:
            lang = pycountry.languages.get(alpha_3=lang_code_str.lower())
            if lang:
                return lang.name
        
        # Try by name (case-insensitive search)
        try:
            lang = pycountry.languages.lookup(lang_code_str)
            if lang:
                return lang.name
        except LookupError:
            pass
        
        # Return original if not found
        return lang_code
    except Exception:
        return lang_code


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
    """Convert bitrate to MediaInfo format (always kb/s)"""
    if not bitrate_bps:
        return "Unknown"
    try:
        bitrate_bps = float(bitrate_bps)
        # Always display in kb/s to match MediaInfo standard
        bitrate_kbps = bitrate_bps / 1000
        return f"{bitrate_kbps:.0f} kb/s"
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

def convert_gdrive_to_direct_link(url):
    """Convert Google Drive URL to your direct download service"""
    if is_gdrive_url(url):
        file_id = extract_gdrive_id(url)
        if file_id:
            # Convert to your direct download service
            direct_url = f"https://gdl.anshumanpm.eu.org/direct.aspx?id={file_id}"
            return direct_url
    return url

def download_sample(url, max_size=10*1024*1024):
    """Download sample from direct URL (including converted Google Drive links)"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        # Convert Google Drive URLs to your direct download service
        original_url = url
        if is_gdrive_url(url):
            url = convert_gdrive_to_direct_link(url)
            print(f"Converted Google Drive URL: {original_url} -> {url}")
        
        # Download from the (possibly converted) URL
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        # Extract filename from Content-Disposition header
        filename = None
        content_disposition = response.headers.get('Content-Disposition', '')
        if content_disposition:
            # Try to extract filename from Content-Disposition header
            # Format: attachment; filename="example.mkv" or filename*=UTF-8''example.mkv
            import re
            matches = re.findall(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', content_disposition)
            if matches:
                filename = unquote(matches[0].strip())
        
        # Fallback to URL parsing if Content-Disposition doesn't have filename
        if not filename:
            parsed_url = urlparse(original_url)  # Use original URL for better filename
            filename = os.path.basename(parsed_url.path)
            if filename:
                filename = unquote(filename)
        
        # If still no good filename, use a generic name
        if not filename or filename in ['direct.aspx', '']:
            filename = 'media_file'
        
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
        return temp_file.name, response.headers.get('content-length'), filename
        
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
            "features": [
                "Google Drive links automatically converted to direct download",
                "MediaInfo-style text output",
                "JSON format support",
                "10MB sample analysis for large files"
            ],
            "note": "Google Drive links are converted to gdl.anshumanpm.eu.org direct links"
        })
    
    try:
        # Download sample of the file (returns temp_path, content_length, filename)
        temp_path, content_length, filename = download_sample(url)
        
        try:
            # Parse with MediaInfo
            media_info = MediaInfo.parse(temp_path)
            
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
                    "original_url": url,
                    "download_url": convert_gdrive_to_direct_link(url) if is_gdrive_url(url) else url,
                    "tracks": tracks_data,
                    "api_version": "Full MediaInfo v1.1"
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
                        
                        # Overall bit rate - use MediaInfo value or calculate from file size
                        overall_bitrate = None
                        if hasattr(track, 'overall_bit_rate') and track.overall_bit_rate:
                            overall_bitrate = track.overall_bit_rate
                        # Fallback: calculate from file size and duration
                        elif content_length and hasattr(track, 'duration') and track.duration:
                            try:
                                file_size_bits = int(content_length) * 8
                                duration_seconds = float(track.duration) / 1000
                                if duration_seconds > 0:
                                    overall_bitrate = file_size_bits / duration_seconds
                            except:
                                pass
                        
                        if overall_bitrate:
                            output_lines.append(f"Overall bit rate                         : {get_readable_bitrate(overall_bitrate)}")

                        
                        # Frame rate (if available at container level)
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            output_lines.append(f"Frame rate                               : {format_frame_rate(track.frame_rate)}")
                        
                        # Movie name (alternative title)
                        if hasattr(track, 'movie_name') and track.movie_name:
                            output_lines.append(f"Movie name                               : {track.movie_name}")
                        
                        # Encoded date
                        if hasattr(track, 'encoded_date') and track.encoded_date:
                            output_lines.append(f"Encoded date                             : {track.encoded_date}")
                        
                        # Writing application
                        if hasattr(track, 'writing_application') and track.writing_application:
                            output_lines.append(f"Writing application                      : {track.writing_application}")
                        
                        # Writing library
                        if hasattr(track, 'writing_library') and track.writing_library:
                            output_lines.append(f"Writing library                          : {track.writing_library}")
                        
                        # Cover (attachment indicator)
                        if hasattr(track, 'cover') and track.cover:
                            output_lines.append(f"Cover                                    : {track.cover}")
                        
                        # Attachments
                        if hasattr(track, 'attachments') and track.attachments:
                            output_lines.append(f"Attachments                              : {track.attachments}")
                        
                        # ErrorDetectionType
                        if hasattr(track, 'extra'):
                            extra = track.extra
                            if hasattr(extra, 'ErrorDetectionType') and extra.ErrorDetectionType:
                                output_lines.append(f"ErrorDetectionType                       : {extra.ErrorDetectionType}")
                            if hasattr(extra, 'FileExtension_Invalid') and extra.FileExtension_Invalid:
                                output_lines.append(f"FileExtension_Invalid                    : {extra.FileExtension_Invalid}")
                    
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
                        
                        # Format settings (Muxing mode may be included here)
                        if hasattr(track, 'muxing_mode') and track.muxing_mode:
                            output_lines.append(f"Muxing mode                              : {track.muxing_mode}")
                        
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
                        
                        # Bit rate - use MediaInfo value or calculate from stream size
                        video_bitrate = None
                        if hasattr(track, 'bit_rate') and track.bit_rate:
                            try:
                                video_bitrate = float(track.bit_rate)
                            except:
                                pass
                        # Calculate from stream size if bitrate not available or seems wrong
                        if not video_bitrate or video_bitrate < 100:  # Suspiciously low
                            if hasattr(track, 'stream_size') and track.stream_size and hasattr(track, 'duration') and track.duration:
                                try:
                                    stream_size_bits = int(track.stream_size) * 8
                                    duration_seconds = float(track.duration) / 1000
                                    if duration_seconds > 0:
                                        video_bitrate = stream_size_bits / duration_seconds
                                except:
                                    pass
                        
                        if video_bitrate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(video_bitrate)}")

                        
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
                        
                        # Bits/(Pixel*Frame)
                        if hasattr(track, 'bits__pixel_frame') and track.bits__pixel_frame:
                            output_lines.append(f"Bits/(Pixel*Frame)                       : {track.bits__pixel_frame}")
                        
                        # Scan type
                        if hasattr(track, 'scan_type') and track.scan_type:
                            output_lines.append(f"Scan type                                : {track.scan_type}")
                        
                        # Stream size (with percentage if file size available)
                        if hasattr(track, 'stream_size') and track.stream_size:
                            stream_size = get_readable_bytes(track.stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(track.stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size}{percentage_str}")
                        
                        # Writing library
                        if hasattr(track, 'writing_library') and track.writing_library:
                            output_lines.append(f"Writing library                          : {track.writing_library}")
                        
                        # Encoding settings
                        if hasattr(track, 'encoding_settings') and track.encoding_settings:
                            output_lines.append(f"Encoding settings                        : {track.encoding_settings}")
                        
                        # Default and Forced (corrected)
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                        
                        # Color range
                        if hasattr(track, 'color_range') and track.color_range:
                            output_lines.append(f"Color range                              : {track.color_range}")
                        
                        # Color primaries
                        if hasattr(track, 'color_primaries') and track.color_primaries:
                            output_lines.append(f"Color primaries                          : {track.color_primaries}")
                        
                        # Transfer characteristics
                        if hasattr(track, 'transfer_characteristics') and track.transfer_characteristics:
                            output_lines.append(f"Transfer characteristics                 : {track.transfer_characteristics}")
                        
                        # Matrix coefficients
                        if hasattr(track, 'matrix_coefficients') and track.matrix_coefficients:
                            output_lines.append(f"Matrix coefficients                      : {track.matrix_coefficients}")
                    
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
                        
                        # Frame rate (with SPF if available)
                        if hasattr(track, 'frame_rate') and track.frame_rate:
                            fr_str = f"{track.frame_rate} FPS"
                            # Add SPF (Samples Per Frame) if we have sampling rate
                            if hasattr(track, 'sampling_rate') and track.sampling_rate:
                                try:
                                    spf = int(float(track.sampling_rate) / float(track.frame_rate))
                                    fr_str += f" ({spf} SPF)"
                                except:
                                    pass
                            output_lines.append(f"Frame rate                               : {fr_str}")
                        
                        # Compression mode
                        if hasattr(track, 'compression_mode') and track.compression_mode:
                            output_lines.append(f"Compression mode                         : {track.compression_mode}")
                        
                        # Delay relative to video
                        if hasattr(track, 'delay_relative_to_video') and track.delay_relative_to_video:
                            delay_val = track.delay_relative_to_video
                            try:
                                delay_ms = int(delay_val)
                                output_lines.append(f"Delay relative to video                  : {delay_ms} ms")
                            except:
                                output_lines.append(f"Delay relative to video                  : {delay_val}")
                        
                        # Stream size (with percentage if file size available)
                        if hasattr(track, 'stream_size') and track.stream_size:
                            stream_size = get_readable_bytes(track.stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(track.stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size}{percentage_str}")
                        
                        # Title
                        if hasattr(track, 'title') and track.title:
                            output_lines.append(f"Title                                    : {track.title}")
                        
                        # Language
                        if hasattr(track, 'language') and track.language:
                            lang_full = get_full_language_name(track.language) or track.language
                            output_lines.append(f"Language                                 : {lang_full}")
                        
                        # Service kind
                        if hasattr(track, 'service_kind') and track.service_kind:
                            output_lines.append(f"Service kind                             : {track.service_kind}")
                        
                        # Default and Forced (corrected)
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                        
                        # Dialog Normalization - add dB unit
                        if hasattr(track, 'dialogue_normalization') and track.dialogue_normalization:
                            dialval = str(track.dialogue_normalization)
                            if not dialval.endswith('dB') and not dialval.endswith(' dB'):
                                dialval = f"{dialval} dB"
                            output_lines.append(f"Dialog Normalization                     : {dialval}")
                        
                        # Compression parameters (AC-3/EAC-3)
                        if hasattr(track, 'compr') and track.compr:
                            val = str(track.compr)
                            output_lines.append(f"compr                                    : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'dynrng') and track.dynrng:
                            val = str(track.dynrng)
                            output_lines.append(f"dynrng                                   : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'cmixlev') and track.cmixlev:
                            val = str(track.cmixlev)
                            output_lines.append(f"cmixlev                                  : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'surmixlev') and track.surmixlev:
                            val = str(track.surmixlev)
                            output_lines.append(f"surmixlev                                : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'ltrtcmixlev') and track.ltrtcmixlev:
                            val = str(track.ltrtcmixlev)
                            output_lines.append(f"ltrtcmixlev                              : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'ltrtsurmixlev') and track.ltrtsurmixlev:
                            val = str(track.ltrtsurmixlev)
                            output_lines.append(f"ltrtsurmixlev                            : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'lorocmixlev') and track.lorocmixlev:
                            val = str(track.lorocmixlev)
                            output_lines.append(f"lorocmixlev                              : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'lorosurmixlev') and track.lorosurmixlev:
                            val = str(track.lorosurmixlev)
                            output_lines.append(f"lorosurmixlev                            : {val if 'dB' in val else val + ' dB'}")
                        
                        # Dialog normalization statistics
                        if hasattr(track, 'dialnorm_average') and track.dialnorm_average:
                            val = str(track.dialnorm_average)
                            output_lines.append(f"dialnorm_Average                         : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'dialnorm_minimum') and track.dialnorm_minimum:
                            val = str(track.dialnorm_minimum)
                            output_lines.append(f"dialnorm_Minimum                         : {val if 'dB' in val else val + ' dB'}")
                        if hasattr(track, 'dialnorm_maximum') and track.dialnorm_maximum:
                            val = str(track.dialnorm_maximum)
                            output_lines.append(f"dialnorm_Maximum                         : {val if 'dB' in val else val + ' dB'}")
                    
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
                        
                        # Muxing mode
                        if hasattr(track, 'muxing_mode') and track.muxing_mode:
                            output_lines.append(f"Muxing mode                              : {track.muxing_mode}")
                        
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
                        
                        # Stream size (with percentage if file size available)
                        if hasattr(track, 'stream_size') and track.stream_size:
                            stream_size = get_readable_bytes(track.stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(track.stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size}{percentage_str}")
                        
                        # Title
                        if hasattr(track, 'title') and track.title:
                            output_lines.append(f"Title                                    : {track.title}")
                        
                        # Language
                        if hasattr(track, 'language') and track.language:
                            lang_full = get_full_language_name(track.language) or track.language
                            output_lines.append(f"Language                                 : {lang_full}")
                        
                        # Default and Forced (corrected)
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                    
                    elif track.track_type == 'Menu':
                        output_lines.append("\nMenu")
                        
                        # Extract chapter information
                        # MediaInfo stores chapters as attributes like "00_00_00000" (HH_MM_SSmmm)
                        chapters = []
                        
                        # Filter out technical menu attributes
                        skip_attrs = {
                            'track_type', 'track_id', 'count', 'count_of_stream_of_this_kind',
                            'kind_of_stream', 'other_kind_of_stream', 'stream_identifier',
                            'chapters_pos_begin', 'chapters_pos_end'
                        }
                        
                        # Get all attributes from the menu track
                        all_attrs = {}
                        for attr_name in dir(track):
                            if not attr_name.startswith('_') and not callable(getattr(track, attr_name, None)):
                                if attr_name.lower() not in skip_attrs:
                                    attr_value = getattr(track, attr_name, None)
                                    if attr_value is not None:
                                        all_attrs[attr_name] = attr_value
                        
                        # Look for chapter patterns - timestamps like "00_00_00000" (HH_MM_SSmmm)
                        timestamp_pattern = re.compile(r'^(\d{2}_\d{2}_\d{5})$')
                        
                        for attr_name, attr_value in sorted(all_attrs.items()):
                            # Check if attribute name is a timestamp
                            if timestamp_pattern.match(attr_name):
                                # Convert from "HH_MM_SSmmm" to "HH:MM:SS.mmm"
                                parts = attr_name.split('_')
                                if len(parts) == 3:  # HH, MM, SSmmm
                                    hh = parts[0]
                                    mm = parts[1]
                                    ss_ms = parts[2]  # SSmmm format (5 digits)
                                    ss = ss_ms[:2]
                                    ms = ss_ms[2:]
                                    timestamp = f"{hh}:{mm}:{ss}.{ms}"
                                    # Extract chapter name, skip "en:" prefix if present
                                    chapter_name = str(attr_value) if attr_value else ""
                                    if chapter_name.startswith('en:'):
                                        chapter_name = chapter_name[3:]  # Remove "en:" prefix
                                    chapters.append((timestamp, chapter_name))
                        
                        # Display chapters
                        if chapters:
                            for timestamp, name in chapters:
                                # Format: "HH:MM:SS.mmm                             : :Chapter Name"
                                output_lines.append(f"{timestamp}                             : :{name}")
                
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
        "version": "1.1",
        "description": "Extract detailed media information from video and audio files",
        "endpoints": {
            "/": "Main MediaInfo analysis endpoint",
            "/ui": "Web interface",
            "/health": "Health check",
            "/info": "API information"
        },
        "supported_url_types": [
            "Direct download links",
            "Google Drive links (auto-converted to gdl.anshumanpm.eu.org)",
            "HTTP/HTTPS URLs"
        ],
        "output_formats": ["json", "text"],
        "max_sample_size": "10MB",
        "gdrive_conversion": "Google Drive URLs are automatically converted to gdl.anshumanpm.eu.org direct links",
        "deployment": "Render with Docker"
    })

@app.route('/ui')
def web_interface():
    """Serve the web interface"""
    return send_from_directory('.', 'index.html')

@app.route('/styles.css')
def serve_css():
    """Serve CSS file"""
    return send_from_directory('.', 'styles.css')

@app.route('/script.js')
def serve_js():
    """Serve JavaScript file"""
    return send_from_directory('.', 'script.js')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
