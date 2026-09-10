"""Durable, thread-safe MP4 playlist storage."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


class PlaylistError(ValueError):
    """A playlist request could not be completed."""


class PlaylistStore:
    def __init__(
        self,
        manifest_path: Path,
        media_dir: Path,
        library_dirs: Iterable[Path] | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.media_dir = Path(media_dir).resolve()
        self._roots: dict[str, Path] = {"uploads": self.media_dir}
        self._lock = threading.RLock()
        self._last_scan_at = 0.0

        for index, directory in enumerate(library_dirs or []):
            resolved = Path(directory).resolve()
            if resolved in self._roots.values():
                continue
            key = "media" if index == 0 else f"media_{index + 1}"
            self._roots[key] = resolved

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        for root in self._roots.values():
            root.mkdir(parents=True, exist_ok=True)

        self._videos: list[dict[str, Any]] = []
        self._load_manifest()
        self.refresh(force=True)

    def list(self) -> list[dict[str, Any]]:
        self.refresh()
        with self._lock:
            return [dict(video) for video in self._videos]

    def refresh(self, *, force: bool = False) -> bool:
        """Discover MP4s copied into either media folder while the app is running."""
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_scan_at < 1.0:
                return False
            self._last_scan_at = now
            changed = self._reconcile_files()
            if changed or not self.manifest_path.exists():
                self._save()
            return changed

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
        path = self._path_for_record(video)
        if path is None:
            raise PlaylistError("Video file not found")
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

            video = self._record_for(
                destination,
                "uploads",
                display_name=Path(original).stem,
            )
            self._videos.append(video)
            self._save()
            return dict(video)

    def remove(self, video_id: str) -> tuple[dict[str, Any], int]:
        self.refresh(force=True)
        with self._lock:
            index = next(
                (i for i, item in enumerate(self._videos) if item["id"] == video_id),
                -1,
            )
            if index < 0:
                raise PlaylistError("Video not found")
            video = self._videos[index]
            path = self._path_for_record(video)
            if path is None:
                raise PlaylistError("Video file not found")
            self._videos.pop(index)
            path.unlink(missing_ok=True)
            self._save()
            return dict(video), index

    def reorder(self, ordered_ids: list[str]) -> list[dict[str, Any]]:
        self.refresh(force=True)
        with self._lock:
            current_ids = [item["id"] for item in self._videos]
            if len(ordered_ids) != len(current_ids) or set(ordered_ids) != set(current_ids):
                raise PlaylistError("The new order must contain every playlist item exactly once")
            by_id = {item["id"]: item for item in self._videos}
            self._videos = [by_id[video_id] for video_id in ordered_ids]
            self._save()
            return [dict(video) for video in self._videos]

    def set_loop_enabled(self, video_id: str, enabled: bool) -> dict[str, Any]:
        self.refresh(force=True)
        with self._lock:
            video = next((item for item in self._videos if item["id"] == video_id), None)
            if video is None:
                raise PlaylistError("Video not found")
            video["loop_enabled"] = bool(enabled)
            self._save()
            return dict(video)

    def _load_manifest(self) -> None:
        if not self.manifest_path.exists():
            return
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            videos = payload.get("videos", [])
            self._videos = videos if isinstance(videos, list) else []
        except (json.JSONDecodeError, OSError, AttributeError):
            corrupt_path = self.manifest_path.with_suffix(".corrupt.json")
            os.replace(self.manifest_path, corrupt_path)
            self._videos = []

    def _reconcile_files(self) -> bool:
        changed = False
        valid: list[dict[str, Any]] = []
        known_files: set[tuple[str, str]] = set()

        for existing in self._videos:
            if not isinstance(existing, dict):
                changed = True
                continue
            located = self._locate_record(existing)
            if located is None:
                changed = True
                continue
            storage, path, relative_name = located
            file_key = (storage, relative_name.casefold())
            if file_key in known_files:
                changed = True
                continue

            video = dict(existing)
            updates = {
                "storage": storage,
                "filename": relative_name,
                "size_bytes": path.stat().st_size,
                "source": "media" if storage != "uploads" else "uploads",
            }
            if any(video.get(key) != value for key, value in updates.items()):
                changed = True
            video.update(updates)
            video.setdefault("id", uuid.uuid4().hex)
            video.setdefault("name", path.stem)
            video.setdefault("uploaded_at", datetime.now(timezone.utc).isoformat())
            if not isinstance(video.get("loop_enabled"), bool):
                video["loop_enabled"] = True
                changed = True
            valid.append(video)
            known_files.add(file_key)

        self._videos = valid
        for storage, root in self._roots.items():
            try:
                candidates = sorted(
                    (
                        path
                        for path in root.rglob("*")
                        if path.is_file() and path.suffix.lower() == ".mp4"
                    ),
                    key=lambda path: path.relative_to(root).as_posix().casefold(),
                )
            except OSError:
                continue
            for path in candidates:
                relative_name = path.relative_to(root).as_posix()
                file_key = (storage, relative_name.casefold())
                if file_key not in known_files:
                    self._videos.append(self._record_for(path, storage))
                    known_files.add(file_key)
                    changed = True
        return changed

    def _locate_record(self, video: dict[str, Any]) -> tuple[str, Path, str] | None:
        filename = str(video.get("filename", ""))
        if not filename:
            return None

        requested_storage = video.get("storage")
        storage_order = []
        if requested_storage in self._roots:
            storage_order.append(requested_storage)
        storage_order.extend(key for key in self._roots if key not in storage_order)

        for storage in storage_order:
            root = self._roots[storage]
            path = self._safe_file(root, filename)
            if path is not None:
                return storage, path, path.relative_to(root).as_posix()
        return None

    def _path_for_record(self, video: dict[str, Any]) -> Path | None:
        storage = video.get("storage", "uploads")
        root = self._roots.get(storage)
        if root is None:
            return None
        return self._safe_file(root, str(video.get("filename", "")))

    @staticmethod
    def _safe_file(root: Path, filename: str) -> Path | None:
        try:
            path = (root / filename).resolve()
            path.relative_to(root)
        except (OSError, ValueError):
            return None
        if path.is_file() and path.suffix.lower() == ".mp4":
            return path
        return None

    def _record_for(
        self,
        path: Path,
        storage: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        root = self._roots[storage]
        return {
            "id": uuid.uuid4().hex,
            "storage": storage,
            "filename": path.relative_to(root).as_posix(),
            "name": (display_name or path.stem).strip() or path.stem,
            "size_bytes": path.stat().st_size,
            "source": "media" if storage != "uploads" else "uploads",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "loop_enabled": True,
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
        payload = {"version": 3, "videos": self._videos}
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.manifest_path)
