FROM ubuntu:20.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 LANGUAGE=en_US:en TZ=Asia/Kolkata

WORKDIR /usr/src/app

# Update package list and install basic dependencies first
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    wget \
    curl \
    git \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Install multimedia libraries step by step
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Add MediaArea repository for MediaInfo
RUN wget -qO- https://mediaarea.net/repo/deb/ubuntu/pubkey.gpg | apt-key add - \
    && echo "deb https://mediaarea.net/repo/deb/ubuntu focal main" > /etc/apt/sources.list.d/mediaarea.list

# Install MediaInfo packages from official repository
RUN apt-get update && apt-get install -y \
    libzen0v5 \
    libmediainfo0v5 \
    libmediainfo-dev \
    mediainfo \
    && rm -rf /var/lib/apt/lists/*

# Set timezone
RUN ln -snf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && echo Asia/Kolkata > /etc/timezone

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for Render
EXPOSE 10000

# Health check to verify MediaInfo installation
RUN mediainfo --version || echo "MediaInfo installation check failed"

# Start the application
CMD ["python3", "-m", "gunicorn", "--bind", "0.0.0.0:10000", "--workers", "2", "app:app"]
