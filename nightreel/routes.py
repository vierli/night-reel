"""Web UI and JSON API routes."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from .actions import CueError, CueStore
from .player import PlaybackController, PlaybackError
from .storage import PlaylistError

web = Blueprint("web", __name__)


def player() -> PlaybackController:
    return current_app.extensions["nightreel_player"]


def cues() -> CueStore:
    return current_app.extensions["nightreel_cues"]


@web.after_app_request
def api_cache_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@web.get("/")
def index():
    return render_template("index.html")


@web.get("/health")
def health():
    return jsonify(ok=True)


@web.get("/api/status")
def status():
    return jsonify(player().status())


@web.post("/api/control")
def control():
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")
    if action == "play":
        result = player().play(payload.get("video_id"))
    elif action == "pause":
        result = player().pause()
    elif action == "stop":
        result = player().stop()
    elif action == "next":
        result = player().next()
    elif action == "display_mode":
        fullscreen = payload.get("fullscreen")
        if not isinstance(fullscreen, bool):
            return jsonify(error="fullscreen must be true or false"), 400
        result = player().set_fullscreen(fullscreen)
    elif action == "audio_volume":
        volume = payload.get("volume")
        if (
            isinstance(volume, bool)
            or not isinstance(volume, int)
            or not 0 <= volume <= 100
        ):
            return jsonify(error="volume must be an integer between 0 and 100"), 400
        result = player().set_volume(volume)
    elif action == "audio_mute":
        muted = payload.get("muted")
        if not isinstance(muted, bool):
            return jsonify(error="muted must be true or false"), 400
        result = player().set_muted(muted)
    elif action == "audio_device":
        device_id = payload.get("device_id")
        if not isinstance(device_id, str):
            return jsonify(error="device_id must be a string"), 400
        result = player().set_audio_device(device_id)
    elif action == "black_screen":
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return jsonify(error="enabled must be true or false"), 400
        result = player().set_black_screen(enabled)
    else:
        return jsonify(error="Unknown playback command"), 400
    return jsonify(result)


@web.post("/api/videos")
def upload_videos():
    uploads = request.files.getlist("files")
    if not uploads or all(not item.filename for item in uploads):
        return jsonify(error="Choose at least one MP4 file"), 400

    added = []
    for upload in uploads:
        if upload.filename:
            added.append(player().store.add_upload(upload))
    return jsonify(added=added, **player().status()), 201


@web.delete("/api/videos/<video_id>")
def delete_video(video_id: str):
    return jsonify(player().remove_video(video_id))


@web.put("/api/playlist/order")
def reorder_playlist():
    payload = request.get_json(silent=True) or {}
    ordered_ids = payload.get("ordered_ids")
    if not isinstance(ordered_ids, list) or not all(
        isinstance(item, str) for item in ordered_ids
    ):
        return jsonify(error="ordered_ids must be a list of video IDs"), 400
    return jsonify(player().reorder(ordered_ids))


@web.get("/api/videos/<video_id>/cues")
def list_cues(video_id: str):
    if player().store.get(video_id) is None:
        raise CueError("Video not found")
    return jsonify(cues=cues().list_for(video_id))


@web.post("/api/videos/<video_id>/cues")
def create_cue(video_id: str):
    if player().store.get(video_id) is None:
        raise CueError("Video not found")
    cue = cues().add(video_id, request.get_json(silent=True))
    return jsonify(cue=cue), 201


@web.put("/api/cues/<cue_id>")
def update_cue(cue_id: str):
    return jsonify(cue=cues().update(cue_id, request.get_json(silent=True)))


@web.delete("/api/cues/<cue_id>")
def delete_cue(cue_id: str):
    return jsonify(removed=cues().remove(cue_id))


@web.post("/api/cues/<cue_id>/test")
def test_cue(cue_id: str):
    cue = cues().get(cue_id)
    if cue is None:
        raise CueError("Cue not found")
    player().action_dispatcher.dispatch(cue)
    return jsonify(ok=True), 202


@web.app_errorhandler(PlaylistError)
@web.app_errorhandler(PlaybackError)
@web.app_errorhandler(CueError)
def handle_expected_error(error):
    return jsonify(error=str(error)), 404 if "not found" in str(error).lower() else 400


@web.app_errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    limit_gb = current_app.config["MAX_CONTENT_LENGTH"] / 1024 / 1024 / 1024
    return jsonify(error=f"Upload is larger than the {limit_gb:g} GB limit"), 413


@web.app_errorhandler(500)
def handle_server_error(error):
    current_app.logger.exception("Unhandled request error", exc_info=error)
    return jsonify(error="The player encountered an unexpected error"), 500
