"""Night Reel Flask application factory."""

from __future__ import annotations

import atexit
import os
from pathlib import Path

from flask import Flask

from .black_screen import ensure_black_frame
from .player import MockEngine, PlaybackController, VLCEngine
from .routes import web
from .storage import PlaylistStore


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.lower().strip() in {"1", "true", "yes", "on"}


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    data_dir = Path(os.environ.get("NIGHTREEL_DATA_DIR", project_root / "data"))

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        DATA_DIR=data_dir,
        MEDIA_LIBRARY_DIR=os.environ.get("NIGHTREEL_MEDIA_DIR", project_root / "media"),
        MAX_CONTENT_LENGTH=int(os.environ.get("NIGHTREEL_MAX_UPLOAD_GB", "8"))
        * 1024
        * 1024
        * 1024,
        PLAYER_BACKEND=os.environ.get("NIGHTREEL_PLAYER_BACKEND", "vlc"),
        VLC_FULLSCREEN=_as_bool(os.environ.get("NIGHTREEL_FULLSCREEN"), True),
        VLC_AUDIO_OUTPUT=os.environ.get("NIGHTREEL_AUDIO_OUTPUT", ""),
        VLC_VIDEO_OUTPUT=os.environ.get("NIGHTREEL_VIDEO_OUTPUT", ""),
    )
    if test_config:
        app.config.update(test_config)

    data_dir = Path(app.config["DATA_DIR"]).resolve()
    media_dir = data_dir / "media"
    library_dir = Path(app.config["MEDIA_LIBRARY_DIR"]).resolve()
    store = PlaylistStore(
        data_dir / "playlist.json",
        media_dir,
        library_dirs=[library_dir],
    )

    injected_engine = app.config.get("PLAYER_ENGINE")
    if injected_engine is not None:
        engine = injected_engine
    elif app.config["PLAYER_BACKEND"] == "mock":
        engine = MockEngine(fullscreen=bool(app.config["VLC_FULLSCREEN"]))
    else:
        engine = VLCEngine(
            fullscreen=bool(app.config["VLC_FULLSCREEN"]),
            audio_output=str(app.config["VLC_AUDIO_OUTPUT"]),
            video_output=str(app.config["VLC_VIDEO_OUTPUT"]),
        )

    black_screen_path = ensure_black_frame(data_dir / "black-screen.png")
    controller = PlaybackController(store, engine, black_screen_path)
    app.extensions["nightreel_store"] = store
    app.extensions["nightreel_player"] = controller
    app.register_blueprint(web)

    atexit.register(controller.shutdown)
    return app
