#!/bin/bash
# Update package list
apt-get update

# Install MediaInfo library
apt-get install -y libmediainfo0v5 libmediainfo-dev mediainfo

# Install Python dependencies
pip install -r requirements.txt
