import re
import os
import json
import base64
import tempfile
import random
import shutil
import subprocess
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
    """Convert bitrate to MediaInfo format (Mb/s for high, kb/s for low)"""
    if not bitrate_bps:
        return None
    
    # If it's already a formatted string with units, return as-is
    if isinstance(bitrate_bps, str):
        bitrate_str = str(bitrate_bps).strip()
        # Check if already formatted with units
        if 'kb/s' in bitrate_str.lower() or 'mb/s' in bitrate_str.lower() or 'kbps' in bitrate_str.lower() or 'mbps' in bitrate_str.lower():
            return bitrate_str
        # Try to extract numeric value from string (e.g., "4 737" or "4737")
        try:
            # Remove spaces and try to parse
            clean_str = bitrate_str.replace(' ', '').replace(',', '')
            bitrate_bps = float(clean_str)
        except:
            return bitrate_str  # Return original string if can't parse
    
    try:
        bitrate_bps = float(bitrate_bps)
        bitrate_kbps = bitrate_bps / 1000
        bitrate_mbps = bitrate_bps / 1000000
        
        # Use Mb/s for bitrates >= 1 Mb/s (typical for video)
        if bitrate_mbps >= 1:
            return f"{bitrate_mbps:.1f} Mb/s"
        # Use kb/s for lower bitrates (typical for audio)
        elif bitrate_kbps >= 1:
            # Format with space for thousands like MediaInfo does
            if bitrate_kbps >= 1000:
                return f"{bitrate_kbps:,.0f} kb/s".replace(',', ' ')
            return f"{bitrate_kbps:.0f} kb/s"
        else:
            return f"{bitrate_bps:.0f} b/s"
    except:
        return str(bitrate_bps) if bitrate_bps else None

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

def get_field_value(track, field_name):
    """
    Get field value from track with fallback to other_* variant.
    If primary field exists, return it.
    If not, try other_{field_name} and return first element if it's a list.
    """
    # Try primary field first
    if hasattr(track, field_name):
        value = getattr(track, field_name)
        if value is not None and value != '':
            return value
    
    # Try other_* variant
    other_field = f'other_{field_name}'
    if hasattr(track, other_field):
        other_value = getattr(track, other_field)
        if other_value is not None:
            # If it's a list, return the first element
            if isinstance(other_value, list) and len(other_value) > 0:
                return other_value[0]
            elif other_value != '':
                return other_value
    
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

def is_executable_available(name):
    """Return True if an executable is available on PATH."""
    return shutil.which(name) is not None


def probe_duration(url):
    """Probe remote media duration using ffprobe."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise Exception('ffprobe is not installed or not available on PATH')

    command = [
        ffprobe,
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        url
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=40)
    if result.returncode != 0:
        raise Exception(f'ffprobe failed: {result.stderr.strip() or result.stdout.strip()}')

    duration_text = result.stdout.strip()
    if not duration_text:
        raise Exception('Unable to determine video duration')

    try:
        return float(duration_text)
    except ValueError:
        raise Exception('Invalid duration returned by ffprobe')


def extract_thumbnails_from_url(url, count=3):
    """Extract random thumbnails from a remote URL using ffmpeg."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise Exception('ffmpeg is not installed or not available on PATH')

    original_url = url
    if is_gdrive_url(url):
        url = convert_gdrive_to_direct_link(url)

    duration = None
    try:
        duration = probe_duration(url)
    except Exception:
        duration = None

    if duration is None or duration <= 0:
        duration = 12.0

    # Limit count to a reasonable maximum
    count = max(1, min(int(count), 8))
    random_timestamps = set()
    while len(random_timestamps) < count:
        timestamp = random.uniform(0, max(0.5, duration - 0.5))
        random_timestamps.add(round(timestamp, 2))

    thumbnails = []
    for timestamp in sorted(random_timestamps):
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        output_file.close()

        ffmpeg_args = [
            ffmpeg,
            '-hide_banner',
            '-loglevel', 'error',
            '-ss', str(timestamp),
            '-i', url,
            '-frames:v', '1',
            '-q:v', '3',
            '-vf', 'scale=640:-2',
            '-y',
            output_file.name
        ]

        result = subprocess.run(ffmpeg_args, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or not os.path.exists(output_file.name):
            try:
                os.unlink(output_file.name)
            except Exception:
                pass
            raise Exception(f'ffmpeg extraction failed at {timestamp}s: {result.stderr.strip() or result.stdout.strip()}')

        try:
            with open(output_file.name, 'rb') as f:
                image_data = f.read()
            encoded = base64.b64encode(image_data).decode('utf-8')
            thumbnails.append(f'data:image/jpeg;base64,{encoded}')
        finally:
            try:
                os.unlink(output_file.name)
            except Exception:
                pass

    return thumbnails


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
                image_count = 0
                
                for track in media_info.tracks:
                    if track.track_type == 'General':
                        output_lines.append("General")
                        
                        # Unique ID
                        unique_id = get_field_value(track, 'unique_id')
                        if unique_id:
                            output_lines.append(f"Unique ID                                : {unique_id}")
                        
                        # Complete name - prefer filename from HTTP header over MediaInfo
                        if filename and filename not in ['media_file', '']:
                            output_lines.append(f"Complete name                            : {filename}")
                        else:
                            complete_name = get_field_value(track, 'complete_name') or get_field_value(track, 'file_name')
                            if complete_name:
                                output_lines.append(f"Complete name                            : {complete_name}")
                        
                        # Format
                        format_val = get_field_value(track, 'format')
                        if format_val:
                            output_lines.append(f"Format                                   : {format_val}")
                        
                        # Format version
                        format_version = get_field_value(track, 'format_version')
                        if format_version:
                            output_lines.append(f"Format version                           : {format_version}")
                        
                        # File size - prefer Content-Length from HTTP response for actual file size
                        if content_length:
                            try:
                                file_size = get_readable_bytes(int(content_length))
                                if file_size:
                                    output_lines.append(f"File size                                : {file_size}")
                            except:
                                pass
                        else:
                            # Fallback to MediaInfo file size (will only be sample size)
                            file_size_val = get_field_value(track, 'file_size')
                            if file_size_val:
                                if isinstance(file_size_val, (int, float)) or (isinstance(file_size_val, str) and file_size_val.isdigit()):
                                    file_size = get_readable_bytes(file_size_val)
                                else:
                                    file_size = str(file_size_val)
                                if file_size:
                                    output_lines.append(f"File size                                : {file_size}")
                        
                        # Duration
                        duration = get_field_value(track, 'duration')
                        if duration:
                            output_lines.append(f"Duration                                 : {format_duration(duration)}")
                        
                        # Overall bit rate mode
                        overall_bit_rate_mode = get_field_value(track, 'overall_bit_rate_mode')
                        if overall_bit_rate_mode:
                            output_lines.append(f"Overall bit rate mode                    : {overall_bit_rate_mode}")
                        
                        # Overall bit rate - calculate from actual file size (Content-Length) and duration
                        overall_bitrate = None
                        duration_val = get_field_value(track, 'duration')
                        
                        # FIRST: Calculate from real file size and duration
                        if content_length and duration_val:
                            try:
                                file_size_bits = int(content_length) * 8
                                duration_seconds = float(duration_val) / 1000
                                if duration_seconds > 0:
                                    overall_bitrate = file_size_bits / duration_seconds
                            except:
                                pass
                        
                        # Fallback: use MediaInfo's value if calculation failed
                        if not overall_bitrate:
                            track_bitrate = get_field_value(track, 'overall_bit_rate')
                            if track_bitrate:
                                overall_bitrate = track_bitrate
                        
                        if overall_bitrate:
                            output_lines.append(f"Overall bit rate                         : {get_readable_bitrate(overall_bitrate)}")

                        
                        # Frame rate (if available at container level)
                        frame_rate = get_field_value(track, 'frame_rate')
                        if frame_rate:
                            output_lines.append(f"Frame rate                               : {format_frame_rate(frame_rate)}")
                        
                        # Movie name (alternative title)
                        movie_name = get_field_value(track, 'movie_name')
                        if movie_name:
                            output_lines.append(f"Movie name                               : {movie_name}")
                        
                        # Encoded date
                        encoded_date = get_field_value(track, 'encoded_date')
                        if encoded_date:
                            output_lines.append(f"Encoded date                             : {encoded_date}")
                        
                        # Writing application
                        writing_application = get_field_value(track, 'writing_application')
                        if writing_application:
                            output_lines.append(f"Writing application                      : {writing_application}")
                        
                        # Writing library
                        writing_library = get_field_value(track, 'writing_library')
                        if writing_library:
                            output_lines.append(f"Writing library                          : {writing_library}")
                        
                        # Cover (attachment indicator)
                        cover = get_field_value(track, 'cover')
                        if cover:
                            output_lines.append(f"Cover                                    : {cover}")
                        
                        # Cover description
                        cover_desc = get_field_value(track, 'cover_description')
                        if cover_desc:
                            output_lines.append(f"Cover description                        : {cover_desc}")
                        
                        # Cover type
                        cover_type = get_field_value(track, 'cover_type')
                        if cover_type:
                            output_lines.append(f"Cover type                               : {cover_type}")
                        
                        # Attachments
                        attachments = get_field_value(track, 'attachments')
                        if attachments:
                            output_lines.append(f"Attachments                              : {attachments}")
                        
                        # IMDB
                        imdb = get_field_value(track, 'imdb')
                        if imdb:
                            output_lines.append(f"IMDB                                     : {imdb}")
                        
                        # TMDB
                        tmdb = get_field_value(track, 'tmdb')
                        if tmdb:
                            output_lines.append(f"TMDB                                     : {tmdb}")
                        
                        # ErrorDetectionType and FileExtension_Invalid
                        if hasattr(track, 'extra'):
                            extra = track.extra
                            if hasattr(extra, 'ErrorDetectionType') and extra.ErrorDetectionType:
                                output_lines.append(f"ErrorDetectionType                       : {extra.ErrorDetectionType}")
                            if hasattr(extra, 'FileExtension_Invalid') and extra.FileExtension_Invalid:
                                output_lines.append(f"FileExtension_Invalid                    : {extra.FileExtension_Invalid}")
                            # Also check for IMDB/TMDB in extra
                            if not imdb and hasattr(extra, 'imdb') and extra.imdb:
                                output_lines.append(f"IMDB                                     : {extra.imdb}")
                            if not tmdb and hasattr(extra, 'tmdb') and extra.tmdb:
                                output_lines.append(f"TMDB                                     : {extra.tmdb}")
                    
                    elif track.track_type == 'Video':
                        output_lines.append("\nVideo")
                        
                        # ID
                        track_id = get_field_value(track, 'track_id')
                        if track_id:
                            output_lines.append(f"ID                                       : {track_id}")
                        
                        # Format
                        format_val = get_field_value(track, 'format')
                        if format_val:
                            output_lines.append(f"Format                                   : {format_val}")
                        
                        # Format/Info
                        format_info = get_field_value(track, 'format_info')
                        if format_info:
                            output_lines.append(f"Format/Info                              : {format_info}")
                        
                        # Format profile
                        format_profile = get_field_value(track, 'format_profile')
                        if format_profile:
                            output_lines.append(f"Format profile                           : {format_profile}")
                        
                        # Format settings (Muxing mode may be included here)
                        muxing_mode = get_field_value(track, 'muxing_mode')
                        if muxing_mode:
                            output_lines.append(f"Muxing mode                              : {muxing_mode}")
                        
                        # Format settings
                        format_settings = get_field_value(track, 'format_settings')
                        if format_settings:
                            output_lines.append(f"Format settings                          : {format_settings}")
                        
                        # Format settings, CABAC
                        format_cabac = get_field_value(track, 'format_settings__cabac')
                        if format_cabac:
                            output_lines.append(f"Format settings, CABAC                   : {format_cabac}")
                        
                        # Format settings, Reference frames
                        ref_frames = get_field_value(track, 'format_settings__reference_frames')
                        if ref_frames:
                            output_lines.append(f"Format settings, Reference frames        : {ref_frames}")
                        
                        # Format settings, GOP
                        format_gop = get_field_value(track, 'format_settings__gop')
                        if format_gop:
                            output_lines.append(f"Format settings, GOP                     : {format_gop}")
                        
                        # Format settings, Slice count
                        slice_count = get_field_value(track, 'format_settings__slice_count')
                        if slice_count:
                            output_lines.append(f"Format settings, Slice count             : {slice_count}")
                        
                        # Codec ID
                        codec_id = get_field_value(track, 'codec_id')
                        if codec_id:
                            output_lines.append(f"Codec ID                                 : {codec_id}")
                        
                        # Duration
                        duration = get_field_value(track, 'duration')
                        if duration:
                            output_lines.append(f"Duration                                 : {format_duration(duration)}")
                        
                        # Bit rate mode
                        bit_rate_mode = get_field_value(track, 'bit_rate_mode')
                        if bit_rate_mode:
                            output_lines.append(f"Bit rate mode                            : {bit_rate_mode}")
                        
                        # Bit rate - try multiple approaches to get video bitrate
                        video_bitrate = None
                        video_bitrate_display = None
                        
                        # Try primary bit_rate field
                        bit_rate = get_field_value(track, 'bit_rate')
                        if bit_rate:
                            video_bitrate_display = get_readable_bitrate(bit_rate)
                        
                        # Try other_bit_rate if primary didn't work
                        if not video_bitrate_display:
                            other_bit_rate = getattr(track, 'other_bit_rate', None)
                            if other_bit_rate:
                                if isinstance(other_bit_rate, list) and len(other_bit_rate) > 0:
                                    video_bitrate_display = other_bit_rate[0]
                                elif other_bit_rate:
                                    video_bitrate_display = str(other_bit_rate)
                        
                        # Calculate from stream size proportion if still no bitrate
                        # Use the stream_size from sample to estimate proportion of overall bitrate
                        if not video_bitrate_display:
                            stream_size = get_field_value(track, 'stream_size')
                            duration_val = get_field_value(track, 'duration')
                            
                            if stream_size and duration_val:
                                try:
                                    stream_size_bits = int(stream_size) * 8
                                    duration_seconds = float(duration_val) / 1000
                                    if duration_seconds > 0:
                                        video_bitrate = stream_size_bits / duration_seconds
                                        video_bitrate_display = get_readable_bitrate(video_bitrate)
                                except:
                                    pass
                        
                        if video_bitrate_display:
                            output_lines.append(f"Bit rate                                 : {video_bitrate_display}")
                        
                        # Nominal bit rate
                        nominal_bit_rate = get_field_value(track, 'nominal_bit_rate')
                        if nominal_bit_rate:
                            output_lines.append(f"Nominal bit rate                         : {get_readable_bitrate(nominal_bit_rate)}")

                        
                        # Dimensions
                        width = get_field_value(track, 'width')
                        height = get_field_value(track, 'height')
                        
                        if width and height:
                            width_str, height_str = format_pixel_dimensions(width, height)
                            output_lines.append(f"Width                                    : {width_str} pixels")
                            output_lines.append(f"Height                                   : {height_str} pixels")
                        
                        # Display aspect ratio
                        display_aspect_ratio = get_field_value(track, 'display_aspect_ratio')
                        if display_aspect_ratio:
                            output_lines.append(f"Display aspect ratio                     : {display_aspect_ratio}")
                        elif width and height:
                            # Calculate aspect ratio
                            try:
                                w, h = int(width), int(height)
                                if w == 1920 and h == 1080:
                                    output_lines.append(f"Display aspect ratio                     : 16:9")
                                else:
                                    ratio = w / h
                                    output_lines.append(f"Display aspect ratio                     : {ratio:.3f}")
                            except:
                                pass
                        
                        # Frame rate mode
                        frame_rate_mode = get_field_value(track, 'frame_rate_mode')
                        if frame_rate_mode:
                            output_lines.append(f"Frame rate mode                          : {frame_rate_mode}")
                        
                        # Frame rate
                        frame_rate = get_field_value(track, 'frame_rate')
                        if frame_rate:
                            output_lines.append(f"Frame rate                               : {format_frame_rate(frame_rate)}")
                        
                        # Color space
                        color_space = get_field_value(track, 'color_space')
                        if color_space:
                            output_lines.append(f"Color space                              : {color_space}")
                        
                        # Chroma subsampling
                        chroma_subsampling = get_field_value(track, 'chroma_subsampling')
                        if chroma_subsampling:
                            output_lines.append(f"Chroma subsampling                       : {chroma_subsampling}")
                        
                        # Bit depth
                        bit_depth = get_field_value(track, 'bit_depth')
                        if bit_depth:
                            output_lines.append(f"Bit depth                                : {bit_depth} bits")
                        
                        # Scan type
                        scan_type = get_field_value(track, 'scan_type')
                        if scan_type:
                            output_lines.append(f"Scan type                                : {scan_type}")
                        
                        # Bits/(Pixel*Frame) - Calculate this
                        if video_bitrate and width and height and frame_rate:
                            try:
                                w = float(width)
                                h = float(height)
                                fr_str = format_frame_rate(frame_rate)
                                # Extract number from "23.976 (24000/1001) FPS" -> 23.976
                                match = re.search(r"([\d\.]+)", fr_str)
                                if match:
                                    fr = float(match.group(1))
                                    if fr > 0:
                                        bpp = video_bitrate / (w * h * fr)
                                        output_lines.append(f"Bits/(Pixel*Frame)                   : {bpp:.3f}")
                            except:
                                pass

                        # Time code of first frame
                        time_code = get_field_value(track, 'time_code_of_first_frame')
                        if time_code:
                            output_lines.append(f"Time code of first frame                 : {time_code}")
                            
                        # Stream size (with percentage if file size available)
                        stream_size = get_field_value(track, 'stream_size')
                        if stream_size:
                            stream_size_str = get_readable_bytes(stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size_str}{percentage_str}")
                        
                        # Writing library
                        writing_library = get_field_value(track, 'writing_library')
                        if writing_library:
                            output_lines.append(f"Writing library                          : {writing_library}")
                        
                        # Encoding settings
                        encoding_settings = get_field_value(track, 'encoding_settings')
                        if encoding_settings:
                            output_lines.append(f"Encoding settings                        : {encoding_settings}")
                        
                        # Default and Forced
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                        
                        # Color range
                        color_range = get_field_value(track, 'color_range')
                        if color_range:
                            output_lines.append(f"Color range                              : {color_range}")
                        
                        # Color primaries
                        color_primaries = get_field_value(track, 'color_primaries')
                        if color_primaries:
                            output_lines.append(f"Color primaries                          : {color_primaries}")
                        
                        # Transfer characteristics
                        transfer_characteristics = get_field_value(track, 'transfer_characteristics')
                        if transfer_characteristics:
                            output_lines.append(f"Transfer characteristics                 : {transfer_characteristics}")
                        
                        # Matrix coefficients
                        matrix_coefficients = get_field_value(track, 'matrix_coefficients')
                        if matrix_coefficients:
                            output_lines.append(f"Matrix coefficients                      : {matrix_coefficients}")
                    
                    elif track.track_type == 'Audio':
                        audio_count += 1
                        if audio_count == 1:
                            output_lines.append("\nAudio")
                        else:
                            output_lines.append(f"\nAudio #{audio_count}")
                        
                        # ID
                        track_id = get_field_value(track, 'track_id')
                        if track_id:
                            output_lines.append(f"ID                                       : {track_id}")
                        
                        # ID in the original source medium
                        original_source_medium_id = get_field_value(track, 'original_source_medium_id')
                        if original_source_medium_id:
                            output_lines.append(f"ID in the original source medium         : {original_source_medium_id}")
                        
                        # Format
                        format_val = get_field_value(track, 'format')
                        if format_val:
                            output_lines.append(f"Format                                   : {format_val}")
                        
                        # Format/Info
                        format_info = get_field_value(track, 'format_info')
                        if format_info:
                            output_lines.append(f"Format/Info                              : {format_info}")
                        
                        # Commercial name
                        commercial_name = get_field_value(track, 'commercial_name')
                        if commercial_name:
                            output_lines.append(f"Commercial name                          : {commercial_name}")
                        
                        # Format settings
                        format_settings = get_field_value(track, 'format_settings')
                        if format_settings:
                            output_lines.append(f"Format settings                          : {format_settings}")
                        
                        # Codec ID
                        codec_id = get_field_value(track, 'codec_id')
                        if codec_id:
                            output_lines.append(f"Codec ID                                 : {codec_id}")
                        
                        # Duration
                        duration = get_field_value(track, 'duration')
                        if duration:
                            output_lines.append(f"Duration                                 : {format_duration(duration)}")
                        
                        # Bit rate mode
                        bit_rate_mode = get_field_value(track, 'bit_rate_mode')
                        if bit_rate_mode:
                            output_lines.append(f"Bit rate mode                            : {bit_rate_mode}")
                        
                        # Bit rate - try multiple sources for TrueHD and other variable bitrate codecs
                        bit_rate = get_field_value(track, 'bit_rate')
                        bit_rate_display = get_readable_bitrate(bit_rate) if bit_rate else None
                        
                        # Try other_bit_rate if primary bit_rate didn't work
                        if not bit_rate_display:
                            other_bit_rate = getattr(track, 'other_bit_rate', None)
                            if other_bit_rate:
                                if isinstance(other_bit_rate, list) and len(other_bit_rate) > 0:
                                    bit_rate_display = other_bit_rate[0]
                                elif other_bit_rate:
                                    bit_rate_display = str(other_bit_rate)
                        
                        if bit_rate_display:
                            output_lines.append(f"Bit rate                                 : {bit_rate_display}")
                        
                        # Maximum bit rate
                        max_bit_rate = get_field_value(track, 'maximum_bit_rate')
                        max_bit_rate_display = get_readable_bitrate(max_bit_rate) if max_bit_rate else None
                        
                        # Try other_maximum_bit_rate if primary didn't work
                        if not max_bit_rate_display:
                            other_max_bit_rate = getattr(track, 'other_maximum_bit_rate', None)
                            if other_max_bit_rate:
                                if isinstance(other_max_bit_rate, list) and len(other_max_bit_rate) > 0:
                                    max_bit_rate_display = other_max_bit_rate[0]
                                elif other_max_bit_rate:
                                    max_bit_rate_display = str(other_max_bit_rate)
                        
                        if max_bit_rate_display:
                            output_lines.append(f"Maximum bit rate                         : {max_bit_rate_display}")
                        
                        # Channel(s)
                        channels = get_field_value(track, 'channel_s')
                        if channels:
                            output_lines.append(f"Channel(s)                               : {channels}")
                        
                        # Channel layout
                        channel_layout = get_field_value(track, 'channel_layout')
                        if channel_layout:
                            output_lines.append(f"Channel layout                           : {channel_layout}")
                        
                        # Sampling rate
                        sampling_rate = get_field_value(track, 'sampling_rate')
                        if sampling_rate:
                            try:
                                sr = float(sampling_rate)
                                if sr >= 1000:
                                    output_lines.append(f"Sampling rate                            : {sr/1000:.1f} kHz")
                                else:
                                    output_lines.append(f"Sampling rate                            : {sr:.0f} Hz")
                            except:
                                output_lines.append(f"Sampling rate                            : {sampling_rate}")
                        
                        # Frame rate (with SPF if available)
                        frame_rate = get_field_value(track, 'frame_rate')
                        if frame_rate:
                            fr_str = f"{frame_rate} FPS"
                            # Add SPF (Samples Per Frame) if we have sampling rate
                            if sampling_rate:
                                try:
                                    spf = int(float(sampling_rate) / float(frame_rate))
                                    fr_str += f" ({spf} SPF)"
                                except:
                                    pass
                            output_lines.append(f"Frame rate                               : {fr_str}")
                        
                        # Bit depth
                        bit_depth = get_field_value(track, 'bit_depth')
                        if bit_depth:
                            output_lines.append(f"Bit depth                                : {bit_depth} bits")
                        
                        # Compression mode
                        compression_mode = get_field_value(track, 'compression_mode')
                        if compression_mode:
                            output_lines.append(f"Compression mode                         : {compression_mode}")
                        
                        # Number of dynamic objects (object-based audio)
                        num_dynamic_objects = get_field_value(track, 'number_of_dynamic_objects')
                        if num_dynamic_objects:
                            output_lines.append(f"Number of dynamic objects                : {num_dynamic_objects}")
                        
                        # Bed channel count (object-based audio)
                        bed_channel_count = get_field_value(track, 'bed_channel_count')
                        if bed_channel_count:
                            output_lines.append(f"Bed channel count                        : {bed_channel_count}")
                        
                        # Bed channel configuration (object-based audio)
                        bed_channel_config = get_field_value(track, 'bed_channel_configuration')
                        if bed_channel_config:
                            output_lines.append(f"Bed channel configuration                : {bed_channel_config}")
                        
                        # Delay relative to video
                        delay_relative_to_video = get_field_value(track, 'delay_relative_to_video')
                        if delay_relative_to_video:
                            # Try to parse numeric value
                            try:
                                # Sometimes it's like "12 ms" or just "12"
                                delay_val = str(delay_relative_to_video).lower().replace('ms', '').strip()
                                delay_ms = int(float(delay_val))
                                output_lines.append(f"Delay relative to video                  : {delay_ms} ms")
                            except:
                                output_lines.append(f"Delay relative to video                  : {delay_relative_to_video}")
                        
                        # Stream size (with percentage if file size available)
                        stream_size = get_field_value(track, 'stream_size')
                        if stream_size:
                            stream_size_str = get_readable_bytes(stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size_str}{percentage_str}")
                        
                        # Title
                        title = get_field_value(track, 'title')
                        if title:
                            output_lines.append(f"Title                                    : {title}")
                        
                        # Language
                        language = get_field_value(track, 'language')
                        if language:
                            # Try to get full language name if it's a code
                            lang_full = get_full_language_name(language) or language
                            output_lines.append(f"Language                                 : {lang_full}")
                        
                        # Service kind
                        service_kind = get_field_value(track, 'service_kind')
                        if service_kind:
                            output_lines.append(f"Service kind                             : {service_kind}")
                        
                        # Default and Forced
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)
                        
                        # Original source medium
                        original_source_medium = get_field_value(track, 'original_source_medium')
                        if original_source_medium:
                            output_lines.append(f"Original source medium                   : {original_source_medium}")
                        
                        # Dialog Normalization - add dB unit
                        dialogue_normalization = get_field_value(track, 'dialogue_normalization')
                        if dialogue_normalization:
                            dialval = str(dialogue_normalization)
                            if not dialval.endswith('dB') and not dialval.endswith(' dB'):
                                dialval = f"{dialval} dB"
                            output_lines.append(f"Dialog Normalization                     : {dialval}")
                        
                        # Compression parameters (AC-3/EAC-3)
                        compr = get_field_value(track, 'compr')
                        if compr:
                            val = str(compr)
                            output_lines.append(f"compr                                    : {val if 'dB' in val else val + ' dB'}")
                            
                        dynrng = get_field_value(track, 'dynrng')
                        if dynrng:
                            val = str(dynrng)
                            output_lines.append(f"dynrng                                   : {val if 'dB' in val else val + ' dB'}")
                            
                        cmixlev = get_field_value(track, 'cmixlev')
                        if cmixlev:
                            val = str(cmixlev)
                            output_lines.append(f"cmixlev                                  : {val if 'dB' in val else val + ' dB'}")
                            
                        surmixlev = get_field_value(track, 'surmixlev')
                        if surmixlev:
                            val = str(surmixlev)
                            output_lines.append(f"surmixlev                                : {val if 'dB' in val else val + ' dB'}")
                            
                        ltrtcmixlev = get_field_value(track, 'ltrtcmixlev')
                        if ltrtcmixlev:
                            val = str(ltrtcmixlev)
                            output_lines.append(f"ltrtcmixlev                              : {val if 'dB' in val else val + ' dB'}")
                            
                        ltrtsurmixlev = get_field_value(track, 'ltrtsurmixlev')
                        if ltrtsurmixlev:
                            val = str(ltrtsurmixlev)
                            output_lines.append(f"ltrtsurmixlev                            : {val if 'dB' in val else val + ' dB'}")
                            
                        lorocmixlev = get_field_value(track, 'lorocmixlev')
                        if lorocmixlev:
                            val = str(lorocmixlev)
                            output_lines.append(f"lorocmixlev                              : {val if 'dB' in val else val + ' dB'}")
                            
                        lorosurmixlev = get_field_value(track, 'lorosurmixlev')
                        if lorosurmixlev:
                            val = str(lorosurmixlev)
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
                        track_id = get_field_value(track, 'track_id')
                        if track_id:
                            output_lines.append(f"ID                                       : {track_id}")
                        
                        # Format
                        format_val = get_field_value(track, 'format')
                        if format_val:
                            output_lines.append(f"Format                                   : {format_val}")
                        
                        # Format/Info
                        format_info = get_field_value(track, 'format_info')
                        if format_info:
                            output_lines.append(f"Format/Info                              : {format_info}")
                        
                        # Muxing mode
                        muxing_mode = get_field_value(track, 'muxing_mode')
                        if muxing_mode:
                            output_lines.append(f"Muxing mode                              : {muxing_mode}")
                        
                        # Codec ID
                        codec_id = get_field_value(track, 'codec_id')
                        if codec_id:
                            output_lines.append(f"Codec ID                                 : {codec_id}")
                        
                        # Codec ID/Info
                        codec_id_info = get_field_value(track, 'codec_id_info')
                        if codec_id_info:
                            output_lines.append(f"Codec ID/Info                            : {codec_id_info}")
                        
                        # Duration
                        duration = get_field_value(track, 'duration')
                        if duration:
                            output_lines.append(f"Duration                                 : {format_duration(duration)}")
                        
                        # Bit rate
                        bit_rate = get_field_value(track, 'bit_rate')
                        if bit_rate:
                            output_lines.append(f"Bit rate                                 : {get_readable_bitrate(bit_rate)}")
                        
                        # Frame rate (with SPF if available)
                        frame_rate = get_field_value(track, 'frame_rate')
                        if frame_rate:
                            output_lines.append(f"Frame rate                               : {format_frame_rate(frame_rate)}")
                        
                        # Count of elements
                        element_count = get_field_value(track, 'element_count')
                        if element_count:
                            output_lines.append(f"Count of elements                        : {element_count}")
                        
                        # Stream size
                        stream_size = get_field_value(track, 'stream_size')
                        if stream_size:
                            stream_size_str = get_readable_bytes(stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size_str}{percentage_str}")
                        
                        # Title
                        title = get_field_value(track, 'title')
                        if title:
                            output_lines.append(f"Title                                    : {title}")
                        
                        # Language
                        language = get_field_value(track, 'language')
                        if language:
                            # Try to get full language name if it's a code
                            lang_full = get_full_language_name(language) or language
                            output_lines.append(f"Language                                 : {lang_full}")
                        
                        # Default and Forced
                        default_line = format_boolean_field(track, 'default', 'Default')
                        if default_line:
                            output_lines.append(default_line)
                        
                        forced_line = format_boolean_field(track, 'forced', 'Forced')
                        if forced_line:
                            output_lines.append(forced_line)

                    elif track.track_type == 'Image':
                        image_count += 1
                        if image_count == 1:
                            output_lines.append("\nImage")
                        else:
                            output_lines.append(f"\nImage #{image_count}")
                        
                        # ID
                        track_id = get_field_value(track, 'track_id')
                        if track_id:
                            output_lines.append(f"ID                                       : {track_id}")
                            
                        # Format
                        format_val = get_field_value(track, 'format')
                        if format_val:
                            output_lines.append(f"Format                                   : {format_val}")
                            
                        # Format/Info
                        format_info = get_field_value(track, 'format_info')
                        if format_info:
                            output_lines.append(f"Format/Info                              : {format_info}")
                            
                        # Muxing mode
                        muxing_mode = get_field_value(track, 'muxing_mode')
                        if muxing_mode:
                            output_lines.append(f"Muxing mode                              : {muxing_mode}")
                            
                        # Codec ID
                        codec_id = get_field_value(track, 'codec_id')
                        if codec_id:
                            output_lines.append(f"Codec ID                                 : {codec_id}")
                            
                        # Codec ID/Info
                        codec_id_info = get_field_value(track, 'codec_id_info')
                        if codec_id_info:
                            output_lines.append(f"Codec ID/Info                            : {codec_id_info}")
                            
                        # Width
                        width = get_field_value(track, 'width')
                        if width:
                            output_lines.append(f"Width                                    : {width} pixels")
                            
                        # Height
                        height = get_field_value(track, 'height')
                        if height:
                            output_lines.append(f"Height                                   : {height} pixels")
                            
                        # Color space
                        color_space = get_field_value(track, 'color_space')
                        if color_space:
                            output_lines.append(f"Color space                              : {color_space}")
                            
                        # Chroma subsampling
                        chroma_subsampling = get_field_value(track, 'chroma_subsampling')
                        if chroma_subsampling:
                            output_lines.append(f"Chroma subsampling                       : {chroma_subsampling}")
                            
                        # Bit depth
                        bit_depth = get_field_value(track, 'bit_depth')
                        if bit_depth:
                            output_lines.append(f"Bit depth                                : {bit_depth} bits")
                            
                        # Compression mode
                        compression_mode = get_field_value(track, 'compression_mode')
                        if compression_mode:
                            output_lines.append(f"Compression mode                         : {compression_mode}")
                            
                        # Stream size
                        stream_size = get_field_value(track, 'stream_size')
                        if stream_size:
                            stream_size_str = get_readable_bytes(stream_size)
                            percentage_str = ""
                            if content_length:
                                try:
                                    percentage = (int(stream_size) / int(content_length)) * 100
                                    percentage_str = f" ({percentage:.0f}%)"
                                except:
                                    pass
                            output_lines.append(f"Stream size                              : {stream_size_str}{percentage_str}")
                            
                        # Title
                        title = get_field_value(track, 'title')
                        if title:
                            output_lines.append(f"Title                                    : {title}")
                            
                        # Language
                        language = get_field_value(track, 'language')
                        if language:
                            lang_full = get_full_language_name(language) or language
                            output_lines.append(f"Language                                 : {lang_full}")
                            
                        # Color range
                        color_range = get_field_value(track, 'color_range')
                        if color_range:
                            output_lines.append(f"Color range                              : {color_range}")
                            
                        # Color primaries
                        color_primaries = get_field_value(track, 'color_primaries')
                        if color_primaries:
                            output_lines.append(f"Color primaries                          : {color_primaries}")
                            
                        # Transfer characteristics
                        transfer_characteristics = get_field_value(track, 'transfer_characteristics')
                        if transfer_characteristics:
                            output_lines.append(f"Transfer characteristics                 : {transfer_characteristics}")
                            
                        # Matrix coefficients
                        matrix_coefficients = get_field_value(track, 'matrix_coefficients')
                        if matrix_coefficients:
                            output_lines.append(f"Matrix coefficients                      : {matrix_coefficients}")

                        # ColorSpace_ICC
                        if hasattr(track, 'colorspace_icc') and track.colorspace_icc:
                             output_lines.append(f"ColorSpace_ICC                       : {track.colorspace_icc}")
                        
                        # colour_primaries_ICC_Description
                        if hasattr(track, 'colour_primaries_icc_description') and track.colour_primaries_icc_description:
                             output_lines.append(f"colour_primaries_ICC_Description     : {track.colour_primaries_icc_description}")
                    
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
                                    # Keep chapter name as-is (including en: prefix if present)
                                    chapter_name = str(attr_value) if attr_value else ""
                                    chapters.append((timestamp, chapter_name))
                        
                        # Display chapters
                        if chapters:
                            for timestamp, name in chapters:
                                # Format: "HH:MM:SS.mmm                             : en:Chapter Name"
                                output_lines.append(f"{timestamp}                             : {name}")
                
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

@app.route('/compare-thumbnails')
def compare_thumbnails():
    url1 = request.args.get('url1')
    url2 = request.args.get('url2')
    count = request.args.get('count', '3')

    if not url1 or not url2:
        return jsonify({
            "error": "Both url1 and url2 are required for thumbnail comparison"
        }), 400

    try:
        count_value = int(count)
    except ValueError:
        count_value = 3

    count_value = max(1, min(count_value, 8))

    try:
        sources = []
        for source_url in [url1, url2]:
            thumbnails = extract_thumbnails_from_url(source_url, count=count_value)
            sources.append({
                "url": source_url,
                "thumbnails": thumbnails
            })

        return jsonify({
            "sources": sources,
            "count": count_value,
            "message": "Thumbnail comparison generated successfully"
        })
    except Exception as e:
        return jsonify({
            "error": f"Thumbnail comparison failed: {str(e)}"
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
            "/compare-thumbnails": "Compare thumbnails between two remote media URLs",
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
