"""Persistent timecode cues and asynchronous network action execution."""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class CueError(RuntimeError):
    """A cue could not be created, updated, or executed."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise CueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CueError("base_url is required")
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CueError("base_url must be a valid http:// or https:// address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CueError("base_url must not contain credentials, a query, or a fragment")
    return normalized


def _color(value: Any) -> str:
    if not isinstance(value, str):
        raise CueError("color must use the format #RRGGBB")
    normalized = value.strip().lower()
    if len(normalized) != 7 or normalized[0] != "#":
        raise CueError("color must use the format #RRGGBB")
    try:
        int(normalized[1:], 16)
    except ValueError as exc:
        raise CueError("color must use the format #RRGGBB") from exc
    return normalized


def _normalize_config(action_type: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CueError("config must be an object")

    if action_type == "relay":
        return {
            "base_url": _base_url(raw.get("base_url")),
            "duration_ms": _integer(raw.get("duration_ms"), "duration_ms", 1, 30_000),
        }

    if action_type == "dmx":
        target = raw.get("target")
        if target not in {"fixture", "all"}:
            raise CueError("DMX target must be fixture or all")
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            raise CueError("enabled must be true or false")
        config: dict[str, Any] = {
            "base_url": _base_url(raw.get("base_url")),
            "target": target,
            "enabled": enabled,
            "color": _color(raw.get("color", "#ffffff")),
            "duration_ms": _integer(
                raw.get("duration_ms", 0), "duration_ms", 0, 3_600_000
            ),
        }
        if target == "fixture":
            config["fixture_id"] = _integer(
                raw.get("fixture_id"), "fixture_id", 1, 512
            )
        return config

    raise CueError("type must be relay or dmx")


def normalize_cue(video_id: str, payload: Any, *, cue_id: str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise CueError("Cue body must be a JSON object")
    if not isinstance(video_id, str) or not video_id:
        raise CueError("video_id is required")
    action_type = payload.get("type")
    if action_type not in {"relay", "dmx"}:
        raise CueError("type must be relay or dmx")
    label = payload.get("label", "")
    if not isinstance(label, str):
        raise CueError("label must be text")
    label = label.strip()
    if len(label) > 80:
        raise CueError("label must not be longer than 80 characters")
    return {
        "id": cue_id or uuid.uuid4().hex,
        "video_id": video_id,
        "time_ms": _integer(payload.get("time_ms"), "time_ms", 0, 604_800_000),
        "type": action_type,
        "label": label,
        "config": _normalize_config(action_type, payload.get("config")),
    }


class CueStore:
    """Thread-safe JSON persistence for cues belonging to playlist videos."""

    def __init__(self, manifest_path: Path) -> None:
        self.path = Path(manifest_path)
        self._lock = threading.RLock()
        self._cues: list[dict] = []
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                return
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                raw_cues = payload.get("cues", []) if isinstance(payload, dict) else []
                loaded = []
                for raw in raw_cues:
                    if not isinstance(raw, dict):
                        continue
                    cue = normalize_cue(
                        str(raw.get("video_id", "")), raw, cue_id=str(raw.get("id", ""))
                    )
                    if cue["id"]:
                        cue["created_at"] = str(raw.get("created_at", _timestamp()))
                        loaded.append(cue)
                self._cues = loaded
            except (OSError, ValueError, TypeError, CueError) as exc:
                raise CueError(f"Could not read cue manifest: {exc}") from exc

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"version": 1, "cues": self._cues}
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)

    def list_for(self, video_id: str) -> list[dict]:
        with self._lock:
            return [dict(cue, config=dict(cue["config"])) for cue in sorted(
                (item for item in self._cues if item["video_id"] == video_id),
                key=lambda item: (item["time_ms"], item["created_at"], item["id"]),
            )]

    def get(self, cue_id: str) -> dict | None:
        with self._lock:
            for cue in self._cues:
                if cue["id"] == cue_id:
                    return dict(cue, config=dict(cue["config"]))
        return None

    def add(self, video_id: str, payload: Any) -> dict:
        cue = normalize_cue(video_id, payload)
        cue["created_at"] = _timestamp()
        with self._lock:
            self._cues.append(cue)
            self._save_locked()
        return dict(cue, config=dict(cue["config"]))

    def update(self, cue_id: str, payload: Any) -> dict:
        with self._lock:
            existing = next((cue for cue in self._cues if cue["id"] == cue_id), None)
            if existing is None:
                raise CueError("Cue not found")
            updated = normalize_cue(existing["video_id"], payload, cue_id=cue_id)
            updated["created_at"] = existing["created_at"]
            self._cues[self._cues.index(existing)] = updated
            self._save_locked()
            return dict(updated, config=dict(updated["config"]))

    def remove(self, cue_id: str) -> dict:
        with self._lock:
            existing = next((cue for cue in self._cues if cue["id"] == cue_id), None)
            if existing is None:
                raise CueError("Cue not found")
            self._cues.remove(existing)
            self._save_locked()
            return dict(existing, config=dict(existing["config"]))

    def remove_for_video(self, video_id: str) -> None:
        with self._lock:
            remaining = [cue for cue in self._cues if cue["video_id"] != video_id]
            if len(remaining) != len(self._cues):
                self._cues = remaining
                self._save_locked()


class ActionDispatcher:
    """Runs cue network requests without blocking VLC's playback monitor."""

    def __init__(self, timeout_seconds: float = 4.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nightreel-cue")
        self._lock = threading.RLock()
        self._activity: dict[str, dict] = {}
        self._timers: set[threading.Timer] = set()
        self._closed = False

    def dispatch(self, cue: dict) -> None:
        with self._lock:
            if self._closed:
                return
            self._activity[cue["id"]] = {
                "state": "running",
                "message": "Sending action…",
                "updated_at": _timestamp(),
            }
        future = self._executor.submit(self._execute, cue)
        future.add_done_callback(lambda completed, cue_id=cue["id"]: self._completed(cue_id, completed))

    def activity(self) -> dict[str, dict]:
        with self._lock:
            return {cue_id: dict(value) for cue_id, value in self._activity.items()}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            timers = list(self._timers)
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _completed(self, cue_id: str, future: Future[str]) -> None:
        try:
            message = future.result()
            state = "success"
        except Exception as exc:  # The failure is reported to the UI, not the monitor thread.
            message = str(exc)
            state = "error"
        with self._lock:
            self._activity[cue_id] = {
                "state": state,
                "message": message,
                "updated_at": _timestamp(),
            }

    def _execute(self, cue: dict) -> str:
        config = cue["config"]
        if cue["type"] == "relay":
            self._request(
                f"{config['base_url']}/api/relay",
                "POST",
                {"duration_ms": config["duration_ms"]},
            )
            return f"Relay active for {config['duration_ms']} ms"

        target = config["target"]
        if target == "fixture":
            url = f"{config['base_url']}/api/fixtures/{config['fixture_id']}"
            method = "PATCH"
            target_label = f"Fixture {config['fixture_id']}"
        else:
            url = f"{config['base_url']}/api/all"
            method = "POST"
            target_label = "All fixtures"
        payload: dict[str, Any] = {"enabled": config["enabled"]}
        if config["enabled"]:
            payload["color"] = config["color"]
        self._request(url, method, payload)

        duration_ms = config["duration_ms"]
        if config["enabled"] and duration_ms:
            off_payload = {"enabled": False}
            self._schedule_off(cue["id"], duration_ms, url, method, off_payload)
            return f"{target_label} active for {duration_ms} ms"
        return f"{target_label} {'on' if config['enabled'] else 'off'}"

    def _schedule_off(
        self, cue_id: str, duration_ms: int, url: str, method: str, payload: dict
    ) -> None:
        timer: threading.Timer

        def turn_off() -> None:
            try:
                self._request(url, method, payload)
            except Exception as exc:
                with self._lock:
                    self._activity[cue_id] = {
                        "state": "error",
                        "message": f"Automatic DMX off failed: {exc}",
                        "updated_at": _timestamp(),
                    }
            finally:
                with self._lock:
                    self._timers.discard(timer)

        timer = threading.Timer(duration_ms / 1000, turn_off)
        timer.daemon = True
        with self._lock:
            if self._closed:
                return
            self._timers.add(timer)
        timer.start()

    def _request(self, url: str, method: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
            raise CueError(f"Service returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise CueError(f"Service is unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise CueError("Service request timed out") from exc
        if not raw:
            return {}
        try:
            response_payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CueError("Service returned an invalid JSON response") from exc
        if isinstance(response_payload, dict) and response_payload.get("ok") is False:
            raise CueError(str(response_payload.get("error", "Service rejected the action")))
        return response_payload if isinstance(response_payload, dict) else {}
