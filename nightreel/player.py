"""VLC playback engine and looping playlist controller."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Protocol

from .storage import PlaylistError, PlaylistStore


class PlaybackError(RuntimeError):
    """A playback command could not be completed."""


class PlaybackEngine(Protocol):
    backend_name: str

    def load(self, path: Path) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def state(self) -> str: ...
    def elapsed_ms(self) -> int: ...
    def duration_ms(self) -> int: ...
    def close(self) -> None: ...


class VLCEngine:
    backend_name = "vlc"

    def __init__(
        self,
        *,
        fullscreen: bool = True,
        audio_output: str = "",
        video_output: str = "",
    ) -> None:
        try:
            import vlc  # type: ignore
        except (ImportError, OSError) as exc:
            raise RuntimeError(
                "python-vlc or the native VLC libraries could not be loaded. "
                "Install VLC and run `pip install -r requirements.txt`."
            ) from exc

        options = ["--quiet", "--no-video-title-show", "--no-osd", "--avcodec-hw=any"]
        self._fullscreen = fullscreen
        if fullscreen:
            options.append("--fullscreen")
        if audio_output:
            options.append(f"--aout={audio_output}")
        if video_output:
            options.append(f"--vout={video_output}")

        self._vlc = vlc
        try:
            self._instance = vlc.Instance(*options)
            if self._instance is None:
                raise RuntimeError("VLC could not create a playback instance")
            self._player = self._instance.media_player_new()
        except Exception as exc:
            raise RuntimeError(f"VLC could not be initialized: {exc}") from exc

    def load(self, path: Path) -> None:
        media = self._instance.media_new_path(os.fspath(path))
        self._player.set_media(media)

    def play(self) -> None:
        result = self._player.play()
        if result == -1:
            raise PlaybackError("VLC could not start this video")
        if self._fullscreen:
            self._player.set_fullscreen(True)

    def pause(self) -> None:
        self._player.set_pause(1)

    def stop(self) -> None:
        self._player.stop()

    def state(self) -> str:
        mapping = {
            self._vlc.State.NothingSpecial: "stopped",
            self._vlc.State.Opening: "loading",
            self._vlc.State.Buffering: "loading",
            self._vlc.State.Playing: "playing",
            self._vlc.State.Paused: "paused",
            self._vlc.State.Stopped: "stopped",
            self._vlc.State.Ended: "ended",
            self._vlc.State.Error: "error",
        }
        return mapping.get(self._player.get_state(), "stopped")

    def elapsed_ms(self) -> int:
        return max(0, int(self._player.get_time()))

    def duration_ms(self) -> int:
        return max(0, int(self._player.get_length()))

    def close(self) -> None:
        self.stop()
        self._player.release()
        self._instance.release()


class MockEngine:
    """Small in-memory engine used for development and automated tests."""

    backend_name = "mock"

    def __init__(self, duration_ms: int = 180_000) -> None:
        self._duration = duration_ms
        self._elapsed = 0
        self._started_at = 0.0
        self._state = "stopped"
        self.path: Path | None = None

    def load(self, path: Path) -> None:
        self.path = path
        self._elapsed = 0
        self._state = "stopped"

    def play(self) -> None:
        if self.path is None:
            raise PlaybackError("No video is loaded")
        if self._state != "playing":
            self._started_at = time.monotonic() - self._elapsed / 1000
        self._state = "playing"

    def pause(self) -> None:
        self._elapsed = self.elapsed_ms()
        self._state = "paused"

    def stop(self) -> None:
        self._elapsed = 0
        self._state = "stopped"

    def state(self) -> str:
        if self._state == "playing" and self.elapsed_ms() >= self._duration:
            self._state = "ended"
            self._elapsed = self._duration
        return self._state

    def elapsed_ms(self) -> int:
        if self._state == "playing":
            return min(self._duration, int((time.monotonic() - self._started_at) * 1000))
        return self._elapsed

    def duration_ms(self) -> int:
        return self._duration if self.path else 0

    def close(self) -> None:
        self.stop()


class PlaybackController:
    def __init__(self, store: PlaylistStore, engine: PlaybackEngine) -> None:
        self.store = store
        self.engine = engine
        self._lock = threading.RLock()
        self._current_id: str | None = None
        self._loaded_id: str | None = None
        self._last_error: str | None = None
        self._clock_elapsed_ms = 0
        self._clock_started_at: float | None = None
        self._closing = threading.Event()
        self._monitor = threading.Thread(
            target=self._monitor_playback,
            name="nightreel-playback-monitor",
            daemon=True,
        )
        self._monitor.start()

    def status(self) -> dict:
        with self._lock:
            videos = self.store.list()
            current = self.store.get(self._current_id)
            state = self.engine.state() if self._loaded_id else "stopped"
            engine_elapsed = self.engine.elapsed_ms() if self._loaded_id else 0
            elapsed = max(engine_elapsed, self._clock_value(state)) if self._loaded_id else 0
            duration = self.engine.duration_ms() if self._loaded_id else 0
            elapsed = min(elapsed, duration) if duration else elapsed
            return {
                "player": {
                    "state": state,
                    "current_id": self._current_id,
                    "current": current,
                    "elapsed_ms": elapsed,
                    "duration_ms": duration,
                    "loop": True,
                    "backend": self.engine.backend_name,
                    "error": self._last_error,
                },
                "playlist": videos,
            }

    def play(self, video_id: str | None = None) -> dict:
        with self._lock:
            videos = self.store.list()
            if not videos:
                raise PlaybackError("Upload an MP4 before starting playback")

            target_id = video_id or self._current_id or videos[0]["id"]
            if not self.store.get(target_id):
                raise PlaybackError("Video not found")

            engine_state = self.engine.state() if self._loaded_id else "stopped"
            should_load = self._loaded_id != target_id or engine_state in {
                "stopped",
                "ended",
                "error",
            }
            if should_load:
                self.engine.load(self.store.path_for(target_id))
                self._loaded_id = target_id
                self._clock_elapsed_ms = 0
                self._clock_started_at = None
            self._current_id = target_id
            self._last_error = None
            self.engine.play()
            if self._clock_started_at is None:
                self._clock_started_at = time.monotonic()
            return self.status()

    def pause(self) -> dict:
        with self._lock:
            if self._loaded_id and self.engine.state() == "playing":
                self._clock_elapsed_ms = max(
                    self.engine.elapsed_ms(),
                    self._clock_value("playing"),
                )
                self._clock_started_at = None
                self.engine.pause()
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            if self._loaded_id:
                self.engine.stop()
            self._clock_elapsed_ms = 0
            self._clock_started_at = None
            return self.status()

    def next(self) -> dict:
        with self._lock:
            self._advance_locked()
            return self.status()

    def remove_video(self, video_id: str) -> dict:
        with self._lock:
            was_active = self._current_id == video_id
            was_playing = was_active and self.engine.state() in {"playing", "loading", "paused"}
            _, removed_index = self.store.remove(video_id)
            remaining = self.store.list()
            if was_active:
                self.engine.stop()
                self._loaded_id = None
                self._current_id = None
                self._clock_elapsed_ms = 0
                self._clock_started_at = None
                if remaining:
                    next_index = min(removed_index, len(remaining) - 1)
                    self._current_id = remaining[next_index]["id"]
                    if was_playing:
                        self.play(self._current_id)
            return self.status()

    def reorder(self, ordered_ids: list[str]) -> dict:
        with self._lock:
            self.store.reorder(ordered_ids)
            return self.status()

    def shutdown(self) -> None:
        if self._closing.is_set():
            return
        self._closing.set()
        with self._lock:
            self.engine.close()

    def _advance_locked(self) -> None:
        videos = self.store.list()
        if not videos:
            raise PlaybackError("The playlist is empty")
        ids = [item["id"] for item in videos]
        if self._current_id in ids:
            target = ids[(ids.index(self._current_id) + 1) % len(ids)]
        else:
            target = ids[0]
        self._loaded_id = None
        self.play(target)

    def _clock_value(self, state: str) -> int:
        elapsed = self._clock_elapsed_ms
        if self._clock_started_at is not None and state in {"playing", "loading"}:
            elapsed += int((time.monotonic() - self._clock_started_at) * 1000)
        return max(0, elapsed)

    def _monitor_playback(self) -> None:
        while not self._closing.wait(0.25):
            with self._lock:
                if not self._loaded_id:
                    continue
                state = self.engine.state()
                if state == "ended":
                    try:
                        self._advance_locked()
                    except (PlaybackError, PlaylistError, OSError) as exc:
                        self._last_error = str(exc)
                elif state == "error":
                    self._last_error = "VLC reported a playback error"
