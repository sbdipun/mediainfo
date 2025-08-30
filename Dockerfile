FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Copy the repository file first (since you have it in your repo)
COPY repo-mediaarea_1.0-20_all.deb /tmp/

# Install system dependencies
RUN apt-get update -y && apt-get upgrade -y
RUN apt-get -y install wget ffmpeg python3-pip sox

# Install MediaArea repository from your local file
RUN dpkg -i /tmp/repo-mediaarea_1.0-20_all.deb
RUN apt-get update -y
RUN apt-get -y install mediainfo megatools

# Install Python dependencies
RUN pip3 install --upgrade \
    Flask==3.0.0 \
    gunicorn==21.2.0 \
    pymediainfo==6.1.0 \
    requests==2.31.0 \
    google-api-python-client \
    google-auth-httplib2 \
    google-auth-oauthlib \
    pycryptodomex \
    m3u8

# Copy application files
COPY . .

# Make start script executable (if you have one)
RUN chmod +x start.sh || echo "No start.sh found, using direct command"

# Clean up
RUN rm /tmp/repo-mediaarea_1.0-20_all.deb

# Expose port for Render
EXPOSE 10000

# Verify MediaInfo installation
RUN mediainfo --version

# Start command for Render
CMD ["python3", "-m", "gunicorn", "--bind", "0.0.0.0:10000", "--workers", "2", "app:app"]
