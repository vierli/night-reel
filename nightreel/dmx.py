"""Integrated DMX512 output adapted from the DMX Test project."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


class DMXError(RuntimeError):
    """A DMX configuration or action could not be completed."""


class SerialPort(Protocol):
    break_condition: bool

    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class FixtureConfig:
    id: int
    name: str
    address: int
    red: int
    green: int
    blue: int
    dimmer: int | None = None
    dimmer_on: int = 255
    fixed_channels: tuple[tuple[int, int], ...] = ()

    @property
    def highest_channel(self) -> int:
        offsets = [self.red, self.green, self.blue]
        if self.dimmer is not None:
            offsets.append(self.dimmer)
        offsets.extend(offset for offset, _ in self.fixed_channels)
        return self.address + max(offsets)


@dataclass(frozen=True)
class DMXSettings:
    port: str
    refresh_hz: float
    simulation: bool
    fixtures: tuple[FixtureConfig, ...]

    @property
    def universe_size(self) -> int:
        return max(fixture.highest_channel for fixture in self.fixtures)


@dataclass
class FixtureState:
    enabled: bool = False
    color: str = "#ffffff"


def parse_hex_color(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lower()
    if len(normalized) != 7 or not normalized.startswith("#"):
        raise DMXError("Color must use the format #RRGGBB")
    try:
        return tuple(
            int(normalized[index : index + 2], 16) for index in (1, 3, 5)
        )  # type: ignore[return-value]
    except ValueError as exc:
        raise DMXError("Color must use the format #RRGGBB") from exc


def load_dmx_settings(
    fixture_path: Path,
    *,
    port: str = "/dev/ttyAMA0",
    refresh_hz: float = 30,
    simulation: bool = False,
) -> DMXSettings:
    try:
        raw = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DMXError(f"Could not read DMX fixture configuration: {exc}") from exc

    fixtures: list[FixtureConfig] = []
    ids: set[int] = set()
    occupied: set[int] = set()
    try:
        raw_fixtures = raw.get("fixtures", [])
        for item in raw_fixtures:
            channels = item["channels"]
            fixed_channels = tuple(
                (int(offset), int(value))
                for offset, value in item.get("fixed_channels", {}).items()
            )
            fixture = FixtureConfig(
                id=int(item["id"]),
                name=str(item["name"]),
                address=int(item["address"]),
                red=int(channels["red"]),
                green=int(channels["green"]),
                blue=int(channels["blue"]),
                dimmer=(int(channels["dimmer"]) if "dimmer" in channels else None),
                dimmer_on=int(item.get("dimmer_on", 255)),
                fixed_channels=fixed_channels,
            )
            if fixture.id in ids:
                raise DMXError(f"Fixture ID {fixture.id} is duplicated")
            if not 1 <= fixture.address <= 512:
                raise DMXError(f"DMX address {fixture.address} must be between 1 and 512")
            if fixture.highest_channel > 512:
                raise DMXError(f"{fixture.name} uses a channel above 512")
            offsets = [fixture.red, fixture.green, fixture.blue]
            if fixture.dimmer is not None:
                offsets.append(fixture.dimmer)
            offsets.extend(offset for offset, _ in fixture.fixed_channels)
            if min(offsets) < 0 or len(offsets) != len(set(offsets)):
                raise DMXError(f"Invalid channel mapping for {fixture.name}")
            if not 0 <= fixture.dimmer_on <= 255 or any(
                not 0 <= value <= 255 for _, value in fixture.fixed_channels
            ):
                raise DMXError(f"DMX values for {fixture.name} must be between 0 and 255")
            fixture_channels = {fixture.address + offset for offset in offsets}
            if occupied & fixture_channels:
                raise DMXError(f"DMX channels for {fixture.name} overlap")
            occupied |= fixture_channels
            ids.add(fixture.id)
            fixtures.append(fixture)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DMXError(f"Invalid DMX fixture configuration: {exc}") from exc

    if not fixtures:
        raise DMXError("At least one DMX fixture must be configured")
    if not 1 <= refresh_hz <= 44:
        raise DMXError("DMX refresh rate must be between 1 and 44 Hz")
    return DMXSettings(
        port=str(port),
        refresh_hz=float(refresh_hz),
        simulation=bool(simulation),
        fixtures=tuple(fixtures),
    )


class DMXUniverse:
    def __init__(self, fixtures: tuple[FixtureConfig, ...], size: int):
        self.fixtures = {fixture.id: fixture for fixture in fixtures}
        self.states = {fixture.id: FixtureState() for fixture in fixtures}
        self.size = size
        self.blackout = False
        self._lock = threading.Lock()

    def update_fixture(
        self, fixture_id: int, *, enabled: bool | None = None, color: str | None = None
    ) -> None:
        with self._lock:
            if fixture_id not in self.states:
                raise DMXError(f"DMX fixture {fixture_id} was not found")
            state = self.states[fixture_id]
            if enabled is not None:
                state.enabled = enabled
            if color is not None:
                parse_hex_color(color)
                state.color = color.lower()

    def set_all(self, enabled: bool, color: str | None = None) -> None:
        if color is not None:
            parse_hex_color(color)
        with self._lock:
            for state in self.states.values():
                state.enabled = enabled
                if color is not None:
                    state.color = color.lower()

    def set_blackout(self, enabled: bool) -> None:
        with self._lock:
            self.blackout = enabled

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "blackout": self.blackout,
                "fixtures": [
                    {
                        "id": fixture.id,
                        "name": fixture.name,
                        "address": fixture.address,
                        "last_channel": fixture.highest_channel,
                        "enabled": self.states[fixture.id].enabled,
                        "color": self.states[fixture.id].color,
                    }
                    for fixture in self.fixtures.values()
                ],
            }

    def frame(self, force_blackout: bool = False) -> bytes:
        channels = bytearray(self.size + 1)
        with self._lock:
            blackout = self.blackout or force_blackout
            for fixture_id, fixture in self.fixtures.items():
                state = self.states[fixture_id]
                active = state.enabled and not blackout
                for offset, value in fixture.fixed_channels:
                    channels[fixture.address + offset] = value if not blackout else 0
                red, green, blue = parse_hex_color(state.color) if active else (0, 0, 0)
                channels[fixture.address + fixture.red] = red
                channels[fixture.address + fixture.green] = green
                channels[fixture.address + fixture.blue] = blue
                if fixture.dimmer is not None:
                    channels[fixture.address + fixture.dimmer] = (
                        fixture.dimmer_on if active else 0
                    )
        return bytes(channels)


class DMXController:
    """Continuously transmits DMX512 frames over a UART-backed RS-485 adapter."""

    def __init__(
        self,
        settings: DMXSettings,
        universe: DMXUniverse,
        serial_factory: Callable[[str], SerialPort] | None = None,
    ) -> None:
        self.settings = settings
        self.universe = universe
        self._serial_factory = serial_factory or self._open_serial
        self._serial: SerialPort | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._status_lock = threading.Lock()
        self._connected = settings.simulation
        self._last_error: str | None = None

    @staticmethod
    def _open_serial(port: str) -> SerialPort:
        import serial

        return serial.Serial(
            port=port,
            baudrate=250_000,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=0,
            write_timeout=0.5,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dmx-output", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._serial:
            try:
                for _ in range(3):
                    self._send_frame(self.universe.frame(force_blackout=True))
            except Exception:
                pass
            self._serial.close()
            self._serial = None

    def status(self) -> dict:
        with self._status_lock:
            return {
                "connected": self._connected,
                "mode": "simulation" if self.settings.simulation else "hardware",
                "port": self.settings.port,
                "refresh_hz": self.settings.refresh_hz,
                "last_error": self._last_error,
            }

    def _set_status(self, connected: bool, error: str | None = None) -> None:
        with self._status_lock:
            self._connected = connected
            self._last_error = error

    def _send_frame(self, frame: bytes) -> None:
        assert self._serial is not None
        self._serial.break_condition = True
        time.sleep(0.0001)
        self._serial.break_condition = False
        time.sleep(0.000012)
        self._serial.write(frame)

    def _run(self) -> None:
        interval = 1 / self.settings.refresh_hz
        if self.settings.simulation:
            while not self._stop.wait(interval):
                pass
            return

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                if self._serial is None:
                    self._serial = self._serial_factory(self.settings.port)
                self._send_frame(self.universe.frame())
                self._set_status(True)
            except Exception as exc:
                self._set_status(False, str(exc))
                if self._serial is not None:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None
                self._stop.wait(2)
                continue
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                self._stop.wait(remaining)


class DMXRuntime:
    """Owns DMX output and applies timed or unlimited cue changes."""

    def __init__(self, controller: DMXController, universe: DMXUniverse) -> None:
        self.controller = controller
        self.universe = universe
        self._lock = threading.RLock()
        self._timers: dict[int, threading.Timer] = {}
        self._closed = False

    def start(self) -> None:
        self.controller.start()

    def apply(self, config: dict) -> str:
        target = config["target"]
        if target == "fixture":
            fixture_ids = [int(config["fixture_id"])]
        else:
            fixture_ids = list(self.universe.fixtures)
        if not fixture_ids or any(
            fixture_id not in self.universe.fixtures for fixture_id in fixture_ids
        ):
            raise DMXError("The selected DMX fixture is not configured")

        enabled = bool(config["enabled"])
        color = str(config["color"])
        duration_ms = int(config.get("duration_ms", 0))
        with self._lock:
            if self._closed:
                raise DMXError("DMX output is shutting down")
            self._cancel_timers_locked(fixture_ids)
            if target == "all":
                self.universe.set_all(enabled, color if enabled else None)
                target_label = "All fixtures"
            else:
                self.universe.update_fixture(
                    fixture_ids[0], enabled=enabled, color=color if enabled else None
                )
                target_label = f"Fixture {fixture_ids[0]}"
            if enabled and duration_ms > 0:
                self._schedule_off_locked(fixture_ids, duration_ms)

        if enabled and duration_ms == 0:
            return f"{target_label} on until next change"
        if enabled:
            return f"{target_label} on for {duration_ms} ms"
        return f"{target_label} off"

    def status(self) -> dict:
        return {
            **self.controller.status(),
            "universe": self.universe.snapshot(),
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            timers = set(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        self.controller.stop()

    def _cancel_timers_locked(self, fixture_ids: list[int]) -> None:
        for fixture_id in fixture_ids:
            timer = self._timers.pop(fixture_id, None)
            if timer is not None:
                timer.cancel()

    def _schedule_off_locked(self, fixture_ids: list[int], duration_ms: int) -> None:
        for fixture_id in fixture_ids:
            def turn_off(target_id: int = fixture_id) -> None:
                active_timer = threading.current_thread()
                with self._lock:
                    if self._closed or self._timers.get(target_id) is not active_timer:
                        return
                    self._timers.pop(target_id, None)
                    self.universe.update_fixture(target_id, enabled=False)

            timer = threading.Timer(duration_ms / 1000, turn_off)
            timer.daemon = True
            self._timers[fixture_id] = timer
            timer.start()
