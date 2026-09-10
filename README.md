# Night Reel

Night Reel is a local MP4 loop player for a Raspberry Pi 5. VLC renders video on the Pi's attached display while any phone, tablet, or computer on the same network can control playback from a web browser.

The control screen shows the current file and live timecode, supports start, pause, stop, next, fullscreen/windowed display modes, a persistent black-screen output, and VLC audio controls. It also lets you upload, reorder, play, or permanently delete MP4 files. The playlist order survives restarts and automatically wraps back to the first video.

The action track schedules persistent timecode cues for every video. A cue can pulse the relay from the `ESP32_Relais_Webservice` project or control one/all RGB fixtures through the integrated DMX512 output adapted from the `DMX Test` project.

## Raspberry Pi 5 setup

Night Reel targets the current 64-bit Raspberry Pi OS with the desktop. Connect the Pi to the display and open a terminal in the graphical desktop session.

```bash
git clone https://github.com/vierli/night-reel.git
cd night-reel
chmod +x install-pi.sh
./install-pi.sh
```

The installer adds VLC and DMX support, creates an isolated Python environment, gives the current user access to the serial port, and starts a per-user service. If the separate `dmx-controller.service` from the old project exists, the installer disables it so only Night Reel owns the DMX UART. Reboot once if the installer asks you to activate the new group permission.

It prints the controller URL when it finishes. From another device on the same network, open either:

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
| `NIGHTREEL_ACTION_TIMEOUT` | `4` | Network timeout in seconds for ESP32 relay requests |
| `NIGHTREEL_DMX_PORT` | `/dev/ttyAMA0` | UART used for integrated DMX512 output |
| `NIGHTREEL_DMX_REFRESH_HZ` | `30` | DMX frames sent per second (1–44) |
| `NIGHTREEL_DMX_FIXTURES_FILE` | `./config/fixtures.json` | Fixture addresses and channel mappings |
| `NIGHTREEL_DMX_SIMULATION` | `0` | Set to `1` for testing without DMX hardware |

Browser uploads are saved in `data/media/`. You can also copy MP4 files directly into `media/`, including subfolders. Night Reel scans both locations while it runs, and extension matching is case-insensitive (`.mp4` and `.MP4` both work).

## Loop selection

Every video in the media list has a loop marker. Active markers determine which videos play automatically and their order follows the visible list. An unmarked video can still be clicked for one manual play; when it ends, Night Reel continues with the next marked video. The marker state and order survive restarts.

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

DMX runs inside Night Reel; no separate DMX web application or service is required. A cue can turn one configured fixture or all fixtures on/off and set an RGB color. Choose one of two duration modes:

- **Until next change** keeps the light on without a timer.
- **Timed** switches it off after the configured number of milliseconds.

If a later cue changes a fixture, Night Reel cancels any older pending off timer for that fixture. The current fixture states and UART connection status are shown in the application status used by the action editor.

### DMX hardware setup

The included `config/fixtures.json` uses the original two 7-channel RGB fixtures at DMX addresses 1 and 8. Connect Raspberry Pi GPIO 14 / physical pin 8 to the VMA432 `input`, pin 2 (5 V) to `+5V`, and pin 6 (GND) to `GND`. The lights require their own power supply.

Enable UART0 on the Raspberry Pi 5 in `/boot/firmware/config.txt`:

```ini
enable_uart=1
dtoverlay=uart0-pi5
```

Disable the serial login shell and enable the UART in `sudo raspi-config`, then reboot. Night Reel continuously transmits the configured DMX universe at 30 Hz. Relay network calls and DMX cue changes run outside the playback monitor so they do not block VLC. Timing is intended for show control, not safety-critical automation.

## Notes

- Upload and delete access is intentionally unauthenticated for simple trusted-LAN use. Do not expose port 8080 directly to the public internet.
- Deleting a video removes the underlying MP4 from the Pi and cannot be undone.
- If the active video ends, Night Reel starts the next marked item automatically. The final marked item wraps to the first.
- If the active video is deleted, playback continues with the next available item.
- Deleting a video also removes its saved timecode cues.
- **Black screen** stops playlist playback and keeps VLC's video output open on a generated black frame. Press Start or select a video to resume playback.
- The ESP32 relay service is unauthenticated. Keep it on a trusted LAN and do not forward its port to the internet.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```
