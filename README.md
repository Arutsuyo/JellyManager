# JellyManager
For anyone who hosts their own media server, or is interested in archiving media, I uploaded my Jellyfin Manager that I've been working on for a couple weeks now. The goal was to process media into AV1-SVT and an optimized mp3 format. I have a LOT of Lossless media, and I needed to start saving space and optimizing for streaming my own media server, so I've been working on this encoder wrapper for a while now!

Features:
- Take Source/Dest directories and encode everything inside into the prefered format
- Cleanly break from FFMPEG (ctrl+c) and clean up the partially encoded file
- Process and rename series of episodes to match Jellyfins (and maybe Plex) naming scheme, including metadata tags
- Extra: Wrap a CLI Crunchyroll Downloader to automatically download episodes and move them into a source folder (My personal fork: [CRDL](https://github.com/Arutsuyo/wrapped-crunchyroll-downloader.git))


## ENV Dependencies:
Requires ffmpeg + ffprobe to be in your PATH, with libav1svt + libopus + libmp3

### Python Requirements
```
python3 -m pip install --user send2trash
python3 -m pip install --user ffmpeg-python
```
