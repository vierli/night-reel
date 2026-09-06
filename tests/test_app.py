from __future__ import annotations

import io
import time

import pytest

from nightreel import create_app
from nightreel.player import MockEngine
from nightreel.storage import PlaylistStore


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATA_DIR": tmp_path,
            "PLAYER_BACKEND": "mock",
            "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,
        }
    )
    yield application
    application.extensions["nightreel_player"].shutdown()


@pytest.fixture()
def client(app):
    return app.test_client()


def upload(client, name="opening.mp4", payload=b"fake mp4 bytes"):
    return client.post(
        "/api/videos",
        data={"files": (io.BytesIO(payload), name)},
        content_type="multipart/form-data",
    )


def test_empty_status_and_health(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"Night Reel" in page.data
    assert b"display-mode-button" in page.data
    assert client.get("/health").get_json() == {"ok": True}
    status = client.get("/api/status").get_json()
    assert status["playlist"] == []
    assert status["player"]["state"] == "stopped"
    assert status["player"]["loop"] is True
    assert status["player"]["engine_elapsed_ms"] == 0
    assert status["player"]["fallback_elapsed_ms"] == 0
    assert status["player"]["fullscreen"] is True
    assert status["player"]["black_screen"] is False


def test_switches_between_fullscreen_and_windowed(client):
    windowed = client.post(
        "/api/control",
        json={"action": "display_mode", "fullscreen": False},
    )
    assert windowed.status_code == 200
    assert windowed.get_json()["player"]["fullscreen"] is False

    fullscreen = client.post(
        "/api/control",
        json={"action": "display_mode", "fullscreen": True},
    )
    assert fullscreen.get_json()["player"]["fullscreen"] is True

    invalid = client.post(
        "/api/control",
        json={"action": "display_mode", "fullscreen": "yes"},
    )
    assert invalid.status_code == 400


def test_black_screen_works_without_a_playlist(client, app, tmp_path):
    black_frame = tmp_path / "black-screen.png"
    assert black_frame.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    active = client.post(
        "/api/control",
        json={"action": "black_screen", "enabled": True},
    )
    assert active.status_code == 200
    assert active.get_json()["player"]["state"] == "black"
    assert active.get_json()["player"]["black_screen"] is True
    assert active.get_json()["player"]["current"] is None

    inactive = client.post(
        "/api/control",
        json={"action": "black_screen", "enabled": False},
    )
    assert inactive.get_json()["player"]["state"] == "stopped"
    assert inactive.get_json()["player"]["black_screen"] is False

    invalid = client.post(
        "/api/control",
        json={"action": "black_screen", "enabled": 1},
    )
    assert invalid.status_code == 400


def test_playing_a_video_exits_black_screen(client):
    video = upload(client, "after-black.mp4").get_json()["added"][0]
    client.post("/api/control", json={"action": "black_screen", "enabled": True})

    playing = client.post(
        "/api/control",
        json={"action": "play", "video_id": video["id"]},
    ).get_json()
    assert playing["player"]["state"] == "playing"
    assert playing["player"]["black_screen"] is False


def test_upload_play_pause_stop_and_delete(client):
    uploaded = upload(client).get_json()
    video = uploaded["added"][0]
    assert video["name"] == "opening"

    playing = client.post("/api/control", json={"action": "play"}).get_json()
    assert playing["player"]["state"] == "playing"
    assert playing["player"]["current_id"] == video["id"]

    paused = client.post("/api/control", json={"action": "pause"}).get_json()
    assert paused["player"]["state"] == "paused"

    stopped = client.post("/api/control", json={"action": "stop"}).get_json()
    assert stopped["player"]["state"] == "stopped"

    deleted = client.delete(f"/api/videos/{video['id']}").get_json()
    assert deleted["playlist"] == []
    assert client.get("/api/status").get_json()["player"]["current"] is None


def test_reorder_and_duplicate_filenames(client):
    first = upload(client, "loop.mp4").get_json()["added"][0]
    second = upload(client, "loop.mp4").get_json()["added"][0]
    assert first["filename"] == "loop.mp4"
    assert second["filename"] == "loop-2.mp4"

    reordered = client.put(
        "/api/playlist/order",
        json={"ordered_ids": [second["id"], first["id"]]},
    ).get_json()
    assert [item["id"] for item in reordered["playlist"]] == [second["id"], first["id"]]


def test_rejects_non_mp4_and_bad_commands(client):
    response = upload(client, "notes.txt")
    assert response.status_code == 400
    assert "Only .mp4" in response.get_json()["error"]

    response = client.post("/api/control", json={"action": "rewind"})
    assert response.status_code == 400


def test_finished_video_automatically_advances(tmp_path):
    engine = MockEngine()
    application = create_app(
        {
            "TESTING": True,
            "DATA_DIR": tmp_path,
            "PLAYER_ENGINE": engine,
        }
    )
    client = application.test_client()
    first = upload(client, "first.mp4").get_json()["added"][0]
    second = upload(client, "second.mp4").get_json()["added"][0]
    client.post("/api/control", json={"action": "play", "video_id": first["id"]})

    engine._state = "ended"
    time.sleep(0.3)

    status = client.get("/api/status").get_json()
    assert status["player"]["state"] == "playing"
    assert status["player"]["current_id"] == second["id"]
    application.extensions["nightreel_player"].shutdown()


def test_timecode_advances_when_engine_reports_zero(tmp_path):
    class ZeroTimeEngine(MockEngine):
        def elapsed_ms(self):
            return 0

    application = create_app(
        {
            "TESTING": True,
            "DATA_DIR": tmp_path,
            "PLAYER_ENGINE": ZeroTimeEngine(),
        }
    )
    client = application.test_client()
    upload(client, "clock-test.mp4")
    client.post("/api/control", json={"action": "play"})

    time.sleep(0.03)

    status = client.get("/api/status").get_json()
    assert status["player"]["elapsed_ms"] >= 20
    assert status["player"]["engine_elapsed_ms"] == 0
    assert status["player"]["fallback_elapsed_ms"] >= 20
    application.extensions["nightreel_player"].shutdown()


def test_discovers_all_mp4s_from_both_media_folders(tmp_path):
    uploads = tmp_path / "data" / "media"
    library = tmp_path / "media"
    nested = library / "season-one"
    uploads.mkdir(parents=True)
    nested.mkdir(parents=True)
    (uploads / "uploaded.mp4").write_bytes(b"uploaded")
    (library / "opening.MP4").write_bytes(b"opening")
    (nested / "finale.mp4").write_bytes(b"finale")
    (library / "ignore.txt").write_text("not a video", encoding="utf-8")

    store = PlaylistStore(
        tmp_path / "data" / "playlist.json",
        uploads,
        library_dirs=[library],
    )

    videos = store.list()
    assert {video["filename"] for video in videos} == {
        "uploaded.mp4",
        "opening.MP4",
        "season-one/finale.mp4",
    }
    assert {video["source"] for video in videos} == {"uploads", "media"}
    for video in videos:
        assert store.path_for(video["id"]).is_file()

    (library / "added-while-running.MP4").write_bytes(b"new")
    assert store.refresh(force=True) is True
    assert len(store.list()) == 4
