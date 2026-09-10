# Night Reel

Night Reel is a local MP4 loop player for a Raspberry Pi 5. VLC renders video on the Pi's attached display while any phone, tablet, or computer on the same network can control playback from a web browser.

The control screen shows the current file and live timecode, supports start, pause, stop, next, fullscreen/windowed display modes, a persistent black-screen output, and VLC audio controls. It also lets you upload, reorder, play, or permanently delete MP4 files. The playlist order survives restarts and automatically wraps back to the first video.

The action track schedules persistent timecode cues for every video. A cue can pulse the relay from the `ESP32_Relais_Webservice` project or control one/all RGB fixtures through the REST API from the `DMX-LED-steuerung` / DMX Desk project.

## Raspberry Pi 5 setup

Night Reel targets the current 64-bit Raspberry Pi OS with the desktop. Connect the Pi to the display and open a terminal in the graphical desktop session.

```bash
git clone https://github.com/vierli/night-reel.git nightreel
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
| `NIGHTREEL_MEDIA_DIR` | `./media` | Folder scanned recursively for manually copied MP4 files |
| `NIGHTREEL_MAX_UPLOAD_GB` | `8` | Maximum total size of one upload request |
| `NIGHTREEL_FULLSCREEN` | `1` | Open VLC video in fullscreen mode |
| `NIGHTREEL_AUDIO_OUTPUT` | empty | Optional VLC audio-output module |
| `NIGHTREEL_VIDEO_OUTPUT` | empty | Optional VLC video-output module |
| `NIGHTREEL_PLAYER_BACKEND` | `vlc` | Use `mock` only for development without VLC |
| `NIGHTREEL_ACTION_TIMEOUT` | `4` | Network timeout in seconds for relay and DMX action requests |

Browser uploads are saved in `data/media/`. You can also copy MP4 files directly into `media/`, including subfolders. Night Reel scans both locations while it runs, and extension matching is case-insensitive (`.mp4` and `.MP4` both work).

## Audio controls

The player panel contains a volume slider, a mute button, and an **Audio output** selector. The selector is populated with the devices reported by VLC, such as HDMI, USB, analog, or Bluetooth outputs. Some VLC output modules only report their device list while a video with audio is playing; if only **System default** is initially visible, start a video and wait a few seconds. The selected device, volume, and mute state are retained when the playlist moves to the next video.

## Timecode actions

Select a video in the **Action track** at the bottom of the controller. **Add action** creates a cue at a typed `HH:MM:SS.mmm` timecode; **At playhead** uses the current displayed time. Existing cues can be tested immediately, edited, or deleted from the cue list. They are stored in `data/cues.json` and survive restarts.

Night Reel checks VLC's millisecond time while playback is active. An action fires once when playback crosses its timecode. It is rearmed when the video starts again or the loop returns to it. Pausing and resuming does not fire an action twice.

### ESP32 relay action

Enter the ESP32 base address, for example `http://esp32-relay.local`, and a duration from 1 to 30,000 milliseconds. Night Reel calls the existing service as follows:

```http
POST /api/relay
Content-Type: application/json

{"duration_ms":1500}
```

### DMX action

The DMX Desk project must be running separately. If it runs on the same Pi, use `http://127.0.0.1:8000`; otherwise enter that controller's LAN address. A cue can turn one fixture (by ID) or all fixtures on/off and set an RGB color. An optional duration automatically sends an off command after the configured number of milliseconds.

Night Reel uses the existing DMX Desk endpoints:

- `PATCH /api/fixtures/{fixture_id}` for one fixture
- `POST /api/all` for all fixtures

Relay and DMX calls run asynchronously, so a slow or unreachable device does not block VLC playback. The result of the latest call is shown in the action row. Timing is intended for show control over a local network, not hard real-time or safety-critical automation.

## Notes

- Upload and delete access is intentionally unauthenticated for simple trusted-LAN use. Do not expose port 8080 directly to the public internet.
- Deleting a video removes the underlying MP4 from the Pi and cannot be undone.
- If the active video ends, Night Reel starts the next item automatically. The final item wraps to the first.
- If the active video is deleted, playback continues with the next available item.
- Deleting a video also removes its saved timecode cues.
- **Black screen** stops playlist playback and keeps VLC's video output open on a generated black frame. Press Start or select a video to resume playback.
- The relay and DMX services are unauthenticated local-network devices. Keep all three applications on a trusted LAN and do not forward their ports to the internet.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```
