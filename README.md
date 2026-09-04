# Night Reel

Night Reel is a local MP4 loop player for a Raspberry Pi 5. VLC renders video on the Pi's attached display while any phone, tablet, or computer on the same network can control playback from a web browser.

The control screen shows the current file and live timecode, supports start, pause, stop, and next, and lets you upload, reorder, play, or permanently delete MP4 files. The playlist order survives restarts and automatically wraps back to the first video.

## Raspberry Pi 5 setup

Night Reel targets the current 64-bit Raspberry Pi OS with the desktop. Connect the Pi to the display and open a terminal in the graphical desktop session.

```bash
git clone <your-repository-url> nightreel
cd nightreel
chmod +x install-pi.sh
./install-pi.sh
```

The installer adds VLC, creates an isolated Python environment, and starts a per-user service. It prints the controller URL when it finishes. From another device on the same network, open either:

```text
http://raspberrypi.local:8080
http://<the-pi-ip-address>:8080
```

The Pi should remain logged into its desktop account so VLC has access to the HDMI display. To inspect or restart the service:

```bash
systemctl --user status nightreel
systemctl --user restart nightreel
journalctl --user -u nightreel -f
```

## Run manually

```bash
sudo apt-get install -y vlc python3-venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

Then open `http://localhost:8080` on the Pi or use the Pi's network address from another device.

For interface development on a computer without VLC, use:

```bash
python run.py --mock-player
```

## Configuration

Configuration is supplied as environment variables, either in a terminal or in `deploy/nightreel.service.template` before installation.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NIGHTREEL_DATA_DIR` | `./data` | Playlist manifest and uploaded MP4 directory |
| `NIGHTREEL_MAX_UPLOAD_GB` | `8` | Maximum total size of one upload request |
| `NIGHTREEL_FULLSCREEN` | `1` | Open VLC video in fullscreen mode |
| `NIGHTREEL_AUDIO_OUTPUT` | empty | Optional VLC audio-output module |
| `NIGHTREEL_VIDEO_OUTPUT` | empty | Optional VLC video-output module |
| `NIGHTREEL_PLAYER_BACKEND` | `vlc` | Use `mock` only for development without VLC |

You can also copy MP4 files directly into `data/media/`; Night Reel discovers them the next time it starts.

## Notes

- Upload and delete access is intentionally unauthenticated for simple trusted-LAN use. Do not expose port 8080 directly to the public internet.
- Deleting a video removes the underlying MP4 from the Pi and cannot be undone.
- If the active video ends, Night Reel starts the next item automatically. The final item wraps to the first.
- If the active video is deleted, playback continues with the next available item.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

