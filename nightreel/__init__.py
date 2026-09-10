"""Night Reel Flask application factory."""

from __future__ import annotations

import atexit
import os
from pathlib import Path

from flask import Flask

from .actions import ActionDispatcher, CueStore
from .black_screen import ensure_black_frame
from .dmx import DMXController, DMXRuntime, DMXUniverse, load_dmx_settings
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
        ACTION_TIMEOUT_SECONDS=float(os.environ.get("NIGHTREEL_ACTION_TIMEOUT", "4")),
        DMX_PORT=os.environ.get("NIGHTREEL_DMX_PORT", "/dev/ttyAMA0"),
        DMX_REFRESH_HZ=float(os.environ.get("NIGHTREEL_DMX_REFRESH_HZ", "30")),
        DMX_SIMULATION=_as_bool(os.environ.get("NIGHTREEL_DMX_SIMULATION"), False),
        DMX_FIXTURES_FILE=os.environ.get(
            "NIGHTREEL_DMX_FIXTURES_FILE", project_root / "config" / "fixtures.json"
        ),
    )
    if test_config:
        app.config.update(test_config)
    if app.config.get("TESTING") and "DMX_SIMULATION" not in (test_config or {}):
        app.config["DMX_SIMULATION"] = True

    data_dir = Path(app.config["DATA_DIR"]).resolve()
    media_dir = data_dir / "media"
    library_dir = Path(app.config["MEDIA_LIBRARY_DIR"]).resolve()
    store = PlaylistStore(
        data_dir / "playlist.json",
        media_dir,
        library_dirs=[library_dir],
    )
    cue_store = CueStore(data_dir / "cues.json")

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

    injected_dispatcher = app.config.get("ACTION_DISPATCHER")
    if injected_dispatcher is not None:
        action_dispatcher = injected_dispatcher
        dmx_runtime = getattr(injected_dispatcher, "dmx_runtime", None)
    else:
        fixture_path = Path(app.config["DMX_FIXTURES_FILE"])
        if not fixture_path.is_absolute():
            fixture_path = project_root / fixture_path
        dmx_settings = load_dmx_settings(
            fixture_path,
            port=str(app.config["DMX_PORT"]),
            refresh_hz=float(app.config["DMX_REFRESH_HZ"]),
            simulation=bool(app.config["DMX_SIMULATION"]),
        )
        dmx_universe = DMXUniverse(dmx_settings.fixtures, dmx_settings.universe_size)
        dmx_runtime = DMXRuntime(
            DMXController(dmx_settings, dmx_universe), dmx_universe
        )
        dmx_runtime.start()
        action_dispatcher = ActionDispatcher(
            timeout_seconds=float(app.config["ACTION_TIMEOUT_SECONDS"]),
            dmx_runtime=dmx_runtime,
        )

    black_screen_path = ensure_black_frame(data_dir / "black-screen.png")
    controller = PlaybackController(
        store,
        engine,
        black_screen_path,
        cue_store,
        action_dispatcher,
    )
    app.extensions["nightreel_store"] = store
    app.extensions["nightreel_cues"] = cue_store
    app.extensions["nightreel_actions"] = action_dispatcher
    app.extensions["nightreel_dmx"] = dmx_runtime
    app.extensions["nightreel_player"] = controller
    app.register_blueprint(web)

    atexit.register(controller.shutdown)
    return app
