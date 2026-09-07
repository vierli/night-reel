from __future__ import annotations

import io
import time

import pytest

from nightreel import create_app
from nightreel.actions import ActionDispatcher, CueStore
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
    assert b"Action track" in page.data
    assert b"cue-dialog" in page.data
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


def test_cues_can_be_created_updated_deleted_and_reloaded(client, app, tmp_path):
    video = upload(client, "cue-video.mp4").get_json()["added"][0]
    created = client.post(
        f"/api/videos/{video['id']}/cues",
        json={
            "time_ms": 12_500,
            "type": "relay",
            "label": "Door relay",
            "config": {
                "base_url": "http://esp32-relay.local/",
                "duration_ms": 1500,
            },
        },
    )
    assert created.status_code == 201
    cue = created.get_json()["cue"]
    assert cue["time_ms"] == 12_500
    assert cue["config"] == {
        "base_url": "http://esp32-relay.local",
        "duration_ms": 1500,
    }

    listed = client.get(f"/api/videos/{video['id']}/cues").get_json()["cues"]
    assert [item["id"] for item in listed] == [cue["id"]]

    updated = client.put(
        f"/api/cues/{cue['id']}",
        json={
            "time_ms": 9000,
            "type": "dmx",
            "label": "Red flash",
            "config": {
                "base_url": "http://127.0.0.1:8000",
                "target": "fixture",
                "fixture_id": 2,
                "enabled": True,
                "color": "#FF2000",
                "duration_ms": 750,
            },
        },
    ).get_json()["cue"]
    assert updated["config"]["color"] == "#ff2000"
    assert CueStore(tmp_path / "cues.json").get(cue["id"]) == updated

    removed = client.delete(f"/api/cues/{cue['id']}")
    assert removed.status_code == 200
    assert client.get(f"/api/videos/{video['id']}/cues").get_json()["cues"] == []


def test_invalid_action_configuration_is_rejected(client):
    video = upload(client, "validation.mp4").get_json()["added"][0]
    bad_duration = client.post(
        f"/api/videos/{video['id']}/cues",
        json={
            "time_ms": 0,
            "type": "relay",
            "config": {"base_url": "http://esp32-relay.local", "duration_ms": 30_001},
        },
    )
    assert bad_duration.status_code == 400
    assert "duration_ms" in bad_duration.get_json()["error"]

    bad_url = client.post(
        f"/api/videos/{video['id']}/cues",
        json={
            "time_ms": 0,
            "type": "dmx",
            "config": {
                "base_url": "not-an-address",
                "target": "all",
                "enabled": False,
                "color": "#ffffff",
                "duration_ms": 0,
            },
        },
    )
    assert bad_url.status_code == 400


def test_action_dispatcher_uses_existing_relay_and_dmx_apis():
    dispatcher = ActionDispatcher()
    requests = []
    dispatcher._request = lambda url, method, payload: requests.append((url, method, payload)) or {}

    relay_message = dispatcher._execute(
        {
            "id": "relay-cue",
            "type": "relay",
            "config": {"base_url": "http://relay.local", "duration_ms": 5000},
        }
    )
    dmx_message = dispatcher._execute(
        {
            "id": "dmx-cue",
            "type": "dmx",
            "config": {
                "base_url": "http://127.0.0.1:8000",
                "target": "fixture",
                "fixture_id": 2,
                "enabled": True,
                "color": "#102030",
                "duration_ms": 0,
            },
        }
    )
    dmx_all_message = dispatcher._execute(
        {
            "id": "dmx-all-cue",
            "type": "dmx",
            "config": {
                "base_url": "http://127.0.0.1:8000",
                "target": "all",
                "enabled": False,
                "color": "#ffffff",
                "duration_ms": 0,
            },
        }
    )
    dispatcher.close()

    assert relay_message == "Relay active for 5000 ms"
    assert dmx_message == "Fixture 2 on"
    assert dmx_all_message == "All fixtures off"
    assert requests == [
        ("http://relay.local/api/relay", "POST", {"duration_ms": 5000}),
        (
            "http://127.0.0.1:8000/api/fixtures/2",
            "PATCH",
            {"enabled": True, "color": "#102030"},
        ),
        ("http://127.0.0.1:8000/api/all", "POST", {"enabled": False}),
    ]


def test_cue_fires_once_per_run_and_rearms_after_stop_or_loop(tmp_path):
    class ManualEngine(MockEngine):
        def __init__(self):
            super().__init__(duration_ms=10_000)

        def elapsed_ms(self):
            return self._elapsed

    class RecordingDispatcher:
        def __init__(self):
            self.dispatched = []
            self.closed = False

        def dispatch(self, cue):
            self.dispatched.append(cue["id"])

        def activity(self):
            return {}

        def close(self):
            self.closed = True

    def wait_for_count(dispatcher, expected):
        deadline = time.monotonic() + 1.5
        while len(dispatcher.dispatched) < expected and time.monotonic() < deadline:
            time.sleep(0.02)

    engine = ManualEngine()
    dispatcher = RecordingDispatcher()
    application = create_app(
        {
            "TESTING": True,
            "DATA_DIR": tmp_path,
            "PLAYER_ENGINE": engine,
            "ACTION_DISPATCHER": dispatcher,
        }
    )
    client = application.test_client()
    video = upload(client, "timed-action.mp4").get_json()["added"][0]
    cue = client.post(
        f"/api/videos/{video['id']}/cues",
        json={
            "time_ms": 500,
            "type": "relay",
            "label": "Once",
            "config": {"base_url": "http://relay.local", "duration_ms": 100},
        },
    ).get_json()["cue"]

    client.post("/api/control", json={"action": "play", "video_id": video["id"]})
    engine._elapsed = 600
    wait_for_count(dispatcher, 1)
    assert dispatcher.dispatched == [cue["id"]]
    time.sleep(0.3)
    assert dispatcher.dispatched == [cue["id"]]

    client.post("/api/control", json={"action": "stop"})
    client.post("/api/control", json={"action": "play", "video_id": video["id"]})
    engine._elapsed = 600
    wait_for_count(dispatcher, 2)
    assert dispatcher.dispatched == [cue["id"], cue["id"]]

    engine._elapsed = engine._duration
    engine._state = "ended"
    time.sleep(0.35)
    assert engine.state() == "playing"
    engine._elapsed = 600
    wait_for_count(dispatcher, 3)
    assert dispatcher.dispatched == [cue["id"], cue["id"], cue["id"]]
    application.extensions["nightreel_player"].shutdown()
    assert dispatcher.closed is True


def test_deleting_video_also_deletes_its_cues(client):
    video = upload(client, "temporary.mp4").get_json()["added"][0]
    client.post(
        f"/api/videos/{video['id']}/cues",
        json={
            "time_ms": 1000,
            "type": "relay",
            "config": {"base_url": "http://relay.local", "duration_ms": 100},
        },
    )
    client.delete(f"/api/videos/{video['id']}")
    assert client.get(f"/api/videos/{video['id']}/cues").status_code == 404
