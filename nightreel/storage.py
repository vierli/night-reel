"""Durable, thread-safe MP4 playlist storage."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


class PlaylistError(ValueError):
    """A playlist request could not be completed."""


class PlaylistStore:
    def __init__(self, manifest_path: Path, media_dir: Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.media_dir = Path(media_dir)
        self._lock = threading.RLock()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._videos: list[dict[str, Any]] = []
        self._load_and_reconcile()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(video) for video in self._videos]

    def get(self, video_id: str | None) -> dict[str, Any] | None:
        if video_id is None:
            return None
        with self._lock:
            video = next((item for item in self._videos if item["id"] == video_id), None)
            return dict(video) if video else None

    def path_for(self, video_id: str) -> Path:
        video = self.get(video_id)
        if not video:
            raise PlaylistError("Video not found")
        path = (self.media_dir / video["filename"]).resolve()
        if path.parent != self.media_dir.resolve():
            raise PlaylistError("Invalid video path")
        return path

    def add_upload(self, upload: FileStorage) -> dict[str, Any]:
        original = (upload.filename or "").strip()
        safe_name = secure_filename(original)
        if not safe_name or Path(safe_name).suffix.lower() != ".mp4":
            raise PlaylistError("Only .mp4 video files can be uploaded")

        with self._lock:
            destination = self._unique_destination(safe_name)
            temporary = self.media_dir / f".{uuid.uuid4().hex}.upload"
            try:
                upload.save(temporary)
                if temporary.stat().st_size == 0:
                    raise PlaylistError("The uploaded file is empty")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

            video = self._record_for(destination, display_name=Path(original).stem)
            self._videos.append(video)
            self._save()
            return dict(video)

    def remove(self, video_id: str) -> tuple[dict[str, Any], int]:
        with self._lock:
            index = next(
                (i for i, item in enumerate(self._videos) if item["id"] == video_id),
                -1,
            )
            if index < 0:
                raise PlaylistError("Video not found")
            video = self._videos.pop(index)
            path = (self.media_dir / video["filename"]).resolve()
            if path.parent != self.media_dir.resolve():
                raise PlaylistError("Invalid video path")
            path.unlink(missing_ok=True)
            self._save()
            return dict(video), index

    def reorder(self, ordered_ids: list[str]) -> list[dict[str, Any]]:
        with self._lock:
            current_ids = [item["id"] for item in self._videos]
            if len(ordered_ids) != len(current_ids) or set(ordered_ids) != set(current_ids):
                raise PlaylistError("The new order must contain every playlist item exactly once")
            by_id = {item["id"]: item for item in self._videos}
            self._videos = [by_id[video_id] for video_id in ordered_ids]
            self._save()
            return self.list()

    def _load_and_reconcile(self) -> None:
        with self._lock:
            changed = False
            if self.manifest_path.exists():
                try:
                    payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                    self._videos = payload.get("videos", [])
                except (json.JSONDecodeError, OSError, AttributeError):
                    corrupt_path = self.manifest_path.with_suffix(".corrupt.json")
                    os.replace(self.manifest_path, corrupt_path)
                    self._videos = []
                    changed = True

            valid: list[dict[str, Any]] = []
            known_names: set[str] = set()
            for video in self._videos:
                filename = video.get("filename", "")
                path = self.media_dir / filename
                if filename and path.is_file() and path.suffix.lower() == ".mp4":
                    video["size_bytes"] = path.stat().st_size
                    valid.append(video)
                    known_names.add(filename.casefold())
                else:
                    changed = True
            self._videos = valid

            for path in sorted(self.media_dir.glob("*.mp4"), key=lambda item: item.name.casefold()):
                if path.name.casefold() not in known_names:
                    self._videos.append(self._record_for(path))
                    changed = True

            if changed or not self.manifest_path.exists():
                self._save()

    def _record_for(self, path: Path, display_name: str | None = None) -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "filename": path.name,
            "name": (display_name or path.stem).strip() or path.stem,
            "size_bytes": path.stat().st_size,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }

    def _unique_destination(self, safe_name: str) -> Path:
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix.lower()
        candidate = self.media_dir / f"{stem}{suffix}"
        number = 2
        while candidate.exists():
            candidate = self.media_dir / f"{stem}-{number}{suffix}"
            number += 1
        return candidate

    def _save(self) -> None:
        temporary = self.manifest_path.with_suffix(".tmp")
        payload = {"version": 1, "videos": self._videos}
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.manifest_path)

