from __future__ import annotations

import time
from pathlib import Path

from nightreel.dmx import DMXController, DMXRuntime, DMXUniverse, load_dmx_settings


FIXTURE_FILE = Path(__file__).resolve().parents[1] / "config" / "fixtures.json"


def settings():
    return load_dmx_settings(FIXTURE_FILE, simulation=True)


def test_integrated_dmx_uses_the_original_seven_channel_fixture_mapping():
    config = settings()
    universe = DMXUniverse(config.fixtures, config.universe_size)
    universe.update_fixture(1, enabled=True, color="#123456")
    universe.update_fixture(2, enabled=True, color="#abcdef")

    assert universe.frame() == bytes(
        [
            0,
            255,
            0x12,
            0x34,
            0x56,
            0,
            0,
            0,
            255,
            0xAB,
            0xCD,
            0xEF,
            0,
            0,
            0,
        ]
    )


def test_unlimited_dmx_action_stays_on_until_the_next_change():
    config = settings()
    universe = DMXUniverse(config.fixtures, config.universe_size)
    runtime = DMXRuntime(DMXController(config, universe), universe)

    result = runtime.apply(
        {
            "target": "fixture",
            "fixture_id": 1,
            "enabled": True,
            "color": "#ff2000",
            "duration_ms": 0,
        }
    )
    time.sleep(0.06)
    fixture = universe.snapshot()["fixtures"][0]
    assert result == "Fixture 1 on until next change"
    assert fixture["enabled"] is True
    assert fixture["color"] == "#ff2000"

    runtime.apply(
        {
            "target": "fixture",
            "fixture_id": 1,
            "enabled": False,
            "color": "#ffffff",
            "duration_ms": 0,
        }
    )
    assert universe.snapshot()["fixtures"][0]["enabled"] is False
    runtime.close()


def test_new_dmx_change_cancels_an_older_timed_off_action():
    config = settings()
    universe = DMXUniverse(config.fixtures, config.universe_size)
    runtime = DMXRuntime(DMXController(config, universe), universe)

    runtime.apply(
        {
            "target": "fixture",
            "fixture_id": 2,
            "enabled": True,
            "color": "#ff0000",
            "duration_ms": 40,
        }
    )
    time.sleep(0.01)
    runtime.apply(
        {
            "target": "fixture",
            "fixture_id": 2,
            "enabled": True,
            "color": "#0000ff",
            "duration_ms": 0,
        }
    )
    time.sleep(0.07)

    fixture = universe.snapshot()["fixtures"][1]
    assert fixture["enabled"] is True
    assert fixture["color"] == "#0000ff"
    runtime.close()


def test_timed_dmx_action_switches_the_fixture_off():
    config = settings()
    universe = DMXUniverse(config.fixtures, config.universe_size)
    runtime = DMXRuntime(DMXController(config, universe), universe)
    runtime.apply(
        {
            "target": "all",
            "enabled": True,
            "color": "#00ff00",
            "duration_ms": 30,
        }
    )
    time.sleep(0.08)
    assert all(
        fixture["enabled"] is False for fixture in universe.snapshot()["fixtures"]
    )
    runtime.close()


def test_changing_one_fixture_does_not_cancel_another_fixtures_timer():
    config = settings()
    universe = DMXUniverse(config.fixtures, config.universe_size)
    runtime = DMXRuntime(DMXController(config, universe), universe)
    runtime.apply(
        {
            "target": "all",
            "enabled": True,
            "color": "#00ff00",
            "duration_ms": 40,
        }
    )
    time.sleep(0.01)
    runtime.apply(
        {
            "target": "fixture",
            "fixture_id": 1,
            "enabled": True,
            "color": "#0000ff",
            "duration_ms": 0,
        }
    )
    time.sleep(0.07)

    fixtures = universe.snapshot()["fixtures"]
    assert fixtures[0]["enabled"] is True
    assert fixtures[0]["color"] == "#0000ff"
    assert fixtures[1]["enabled"] is False
    runtime.close()
