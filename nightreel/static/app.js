const dom = {
  connection: document.querySelector("#connection"),
  connectionLabel: document.querySelector("#connection-label"),
  statePill: document.querySelector("#state-pill"),
  screen: document.querySelector("#screen"),
  screenKicker: document.querySelector("#screen-kicker"),
  currentTitle: document.querySelector("#current-title"),
  currentFile: document.querySelector("#current-file"),
  elapsed: document.querySelector("#elapsed-time"),
  duration: document.querySelector("#duration-time"),
  timelineFill: document.querySelector("#timeline-fill"),
  timelineStatus: document.querySelector("#timeline-status"),
  loopStatus: document.querySelector("#loop-status"),
  play: document.querySelector("#play-button"),
  pause: document.querySelector("#pause-button"),
  stop: document.querySelector("#stop-button"),
  displayMode: document.querySelector("#display-mode-button"),
  displayModeIcon: document.querySelector("#display-mode-icon"),
  blackScreen: document.querySelector("#black-screen-button"),
  next: document.querySelector("#next-button"),
  count: document.querySelector("#queue-count"),
  list: document.querySelector("#queue-list"),
  empty: document.querySelector("#empty-state"),
  dropzone: document.querySelector("#dropzone"),
  fileInput: document.querySelector("#file-input"),
  uploadProgress: document.querySelector("#upload-progress"),
  uploadProgressFill: document.querySelector("#upload-progress-fill"),
  controllerAddress: document.querySelector("#controller-address"),
  backend: document.querySelector("#backend-label"),
  toast: document.querySelector("#toast"),
  cueVideo: document.querySelector("#cue-video-select"),
  cueScaleLabel: document.querySelector("#cue-scale-label"),
  cuePlayhead: document.querySelector("#cue-playhead"),
  cueMarkers: document.querySelector("#cue-markers"),
  cueList: document.querySelector("#cue-list"),
  cueEmpty: document.querySelector("#cue-empty"),
  addCue: document.querySelector("#add-cue"),
  addCurrentCue: document.querySelector("#add-current-cue"),
  cueDialog: document.querySelector("#cue-dialog"),
  cueForm: document.querySelector("#cue-form"),
  cueDialogTitle: document.querySelector("#cue-dialog-title"),
  cueDialogClose: document.querySelector("#cue-dialog-close"),
  cueCancel: document.querySelector("#cue-cancel"),
  cueId: document.querySelector("#cue-id"),
  cueTime: document.querySelector("#cue-time"),
  cueType: document.querySelector("#cue-type"),
  cueLabel: document.querySelector("#cue-label"),
  relayFields: document.querySelector("#relay-fields"),
  relayUrl: document.querySelector("#relay-url"),
  relayDuration: document.querySelector("#relay-duration"),
  dmxFields: document.querySelector("#dmx-fields"),
  dmxStatus: document.querySelector("#dmx-status"),
  dmxTarget: document.querySelector("#dmx-target"),
  dmxFixtureField: document.querySelector("#dmx-fixture-field"),
  dmxFixture: document.querySelector("#dmx-fixture"),
  dmxEnabled: document.querySelector("#dmx-enabled"),
  dmxColorField: document.querySelector("#dmx-color-field"),
  dmxColor: document.querySelector("#dmx-color"),
  dmxDurationSettings: document.querySelector("#dmx-duration-settings"),
  dmxDurationMode: document.querySelector("#dmx-duration-mode"),
  dmxDurationField: document.querySelector("#dmx-duration-field"),
  dmxDuration: document.querySelector("#dmx-duration"),
  audioDevice: document.querySelector("#audio-device"),
  volumeSlider: document.querySelector("#volume-slider"),
  volumeValue: document.querySelector("#volume-value"),
  muteButton: document.querySelector("#mute-button"),
  muteIcon: document.querySelector("#mute-icon"),
};

let snapshot = null;
let renderedPlaylistKey = "";
let pollTimer = null;
let toastTimer = null;
let commandPending = false;
let cueVideosKey = "";
let selectedCueVideoId = null;
let cueItems = [];
let cueLoadToken = 0;
let audioDevicesKey = "";
let dmxFixturesKey = "";
let displayClock = {
  currentId: null,
  elapsedMs: 0,
  frameAt: performance.now(),
};

function icon(symbol) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${symbol}`);
  svg.append(use);
  return svg;
}

function formatTime(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor((milliseconds || 0) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map(value => String(value).padStart(2, "0")).join(":");
}

function formatCueTime(milliseconds) {
  const safe = Math.max(0, Math.floor(milliseconds || 0));
  const hours = Math.floor(safe / 3600000);
  const minutes = Math.floor((safe % 3600000) / 60000);
  const seconds = Math.floor((safe % 60000) / 1000);
  const millis = safe % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function parseCueTime(value) {
  const match = /^(\d+):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?$/.exec(value.trim());
  if (!match) throw new Error("Use timecode format HH:MM:SS.mmm");
  const millis = (match[4] || "0").padEnd(3, "0");
  return Number(match[1]) * 3600000 + Number(match[2]) * 60000 + Number(match[3]) * 1000 + Number(millis);
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "MP4 video";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function stateLabel(state) {
  return ({ playing: "Playing", paused: "Paused", loading: "Loading", black: "Black screen", error: "Error", ended: "Advancing" })[state] || "Stopped";
}

function showToast(message, isError = false) {
  clearTimeout(toastTimer);
  dom.toast.textContent = message;
  dom.toast.classList.toggle("error", isError);
  dom.toast.hidden = false;
  toastTimer = setTimeout(() => { dom.toast.hidden = true; }, 4200);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: options.body instanceof FormData ? options.headers : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function pollStatus() {
  clearTimeout(pollTimer);
  try {
    applyStatus(await api("/api/status"));
    dom.connection.className = "connection online";
    dom.connectionLabel.textContent = "Player connected";
  } catch (error) {
    dom.connection.className = "connection offline";
    dom.connectionLabel.textContent = "Player offline";
  } finally {
    pollTimer = setTimeout(pollStatus, 700);
  }
}

function applyStatus(data) {
  const previousState = snapshot?.player?.state;
  snapshot = data;
  const player = data.player;
  const current = player.current;
  const state = player.state;
  const blackScreenActive = player.black_screen;

  const videoChanged = displayClock.currentId !== player.current_id;
  const wasStopped = previousState === "stopped" && state !== "stopped";
  if (videoChanged || state === "stopped" || wasStopped || blackScreenActive) {
    displayClock.elapsedMs = player.elapsed_ms || 0;
  } else {
    displayClock.elapsedMs = Math.max(displayClock.elapsedMs, player.elapsed_ms || 0);
  }
  displayClock.currentId = player.current_id;
  displayClock.frameAt = performance.now();

  dom.statePill.dataset.state = state;
  dom.statePill.textContent = stateLabel(state);
  dom.screen.dataset.state = state;
  dom.screenKicker.textContent = blackScreenActive ? "Live on the attached display" : state === "playing" ? "Live on the attached display" : state === "paused" ? "Playback held" : "Ready when you are";
  dom.currentTitle.textContent = blackScreenActive ? "Black screen" : current?.name || "No video selected";
  dom.currentFile.textContent = blackScreenActive ? "No playlist video is playing" : current?.filename || "Add an MP4 to start the loop";
  dom.timelineStatus.textContent = blackScreenActive ? "Black screen active" : current ? `${stateLabel(state)} · ${current.name}` : "Waiting for a video";
  dom.backend.textContent = player.backend === "mock" ? "Demo playback engine" : "VLC playback engine";

  const hasVideos = data.playlist.length > 0;
  const hasLoopVideos = data.playlist.some(video => video.loop_enabled);
  const activeVideoCanResume = Boolean(current) && ["playing", "loading", "paused"].includes(state);
  dom.play.disabled = ((!hasLoopVideos && !activeVideoCanResume) || commandPending);
  dom.pause.disabled = state !== "playing" || commandPending;
  dom.stop.disabled = (((!current || state === "stopped") && !blackScreenActive) || commandPending);
  dom.displayMode.disabled = commandPending;
  dom.blackScreen.disabled = commandPending;
  dom.next.disabled = !hasLoopVideos || commandPending;
  dom.play.querySelector("span").textContent = state === "paused" ? "Resume" : "Start";
  dom.displayMode.querySelector("span").textContent = player.fullscreen ? "Windowed" : "Fullscreen";
  dom.displayModeIcon.setAttribute("href", player.fullscreen ? "#i-windowed" : "#i-fullscreen");
  dom.displayMode.setAttribute(
    "aria-label",
    player.fullscreen ? "Switch Pi display to windowed mode" : "Switch Pi display to fullscreen mode",
  );
  dom.blackScreen.querySelector("span").textContent = blackScreenActive ? "Exit black" : "Black screen";
  dom.blackScreen.setAttribute("aria-pressed", String(blackScreenActive));
  dom.loopStatus.replaceChildren(
    icon("i-loop"),
    document.createTextNode(hasLoopVideos ? `${player.loop_count} in loop` : "Loop empty"),
  );
  renderAudioControls(player.audio);
  renderDmxStatus(data.dmx);

  if (player.error) showToast(player.error, true);
  renderPlaylist(data.playlist, player.current_id);
  syncCueVideoOptions(data.playlist, player.current_id);
  renderCueTrack();
}

function renderDmxStatus(dmx) {
  if (!dmx) return;
  const fixtures = dmx.universe?.fixtures || [];
  const fixtureKey = fixtures.map(fixture => `${fixture.id}:${fixture.name}`).join("|");
  if (fixtureKey !== dmxFixturesKey) {
    const selected = dom.dmxFixture.value;
    dmxFixturesKey = fixtureKey;
    dom.dmxFixture.replaceChildren();
    fixtures.forEach(fixture => {
      const option = document.createElement("option");
      option.value = String(fixture.id);
      option.textContent = `${fixture.name} · address ${fixture.address}`;
      dom.dmxFixture.append(option);
    });
    if (fixtures.some(fixture => String(fixture.id) === selected)) {
      dom.dmxFixture.value = selected;
    }
  }
  const ready = dmx.connected || dmx.mode === "simulation";
  dom.dmxStatus.className = `dmx-inline-status ${ready ? "online" : "offline"}`;
  dom.dmxStatus.querySelector("span").textContent = dmx.mode === "simulation"
    ? "Integrated DMX simulation"
    : dmx.connected
      ? `Integrated DMX online · ${dmx.port}`
      : `DMX offline · ${dmx.last_error || dmx.port}`;
}

function renderAudioControls(audio) {
  if (!audio) return;
  const devices = Array.isArray(audio.devices) ? audio.devices : [];
  const devicesKey = devices.map(device => `${device.id}:${device.name}`).join("|");
  if (devicesKey !== audioDevicesKey) {
    audioDevicesKey = devicesKey;
    dom.audioDevice.replaceChildren();
    devices.forEach(device => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = device.name;
      dom.audioDevice.append(option);
    });
  }

  if (document.activeElement !== dom.audioDevice) {
    dom.audioDevice.value = audio.device_id || "";
  }
  if (document.activeElement !== dom.volumeSlider) {
    dom.volumeSlider.value = String(audio.volume);
  }
  dom.volumeValue.textContent = `${audio.volume}%`;
  dom.muteButton.setAttribute("aria-pressed", String(audio.muted));
  dom.muteButton.setAttribute("aria-label", audio.muted ? "Unmute audio" : "Mute audio");
  dom.muteButton.title = audio.muted ? "Unmute audio" : "Mute audio";
  dom.muteIcon.setAttribute("href", audio.muted || audio.volume === 0 ? "#i-muted" : "#i-volume");
}

function renderTimecode() {
  const now = performance.now();
  if (snapshot) {
    const player = snapshot.player;
    if (player.state === "playing" || player.state === "loading") {
      displayClock.elapsedMs += now - displayClock.frameAt;
    }
    let elapsed = displayClock.elapsedMs;
    if (player.duration_ms) {
      elapsed = Math.min(elapsed, player.duration_ms);
      displayClock.elapsedMs = elapsed;
    }
    dom.elapsed.textContent = formatTime(elapsed);
    dom.duration.textContent = formatTime(player.duration_ms);
    const percent = player.duration_ms ? (elapsed / player.duration_ms) * 100 : 0;
    dom.timelineFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    updateCuePlayhead(elapsed);
  }
  displayClock.frameAt = now;
  requestAnimationFrame(renderTimecode);
}

function syncCueVideoOptions(videos, currentId) {
  const key = videos.map(video => `${video.id}:${video.name}`).join("|");
  const availableIds = new Set(videos.map(video => video.id));
  const nextSelection = availableIds.has(selectedCueVideoId)
    ? selectedCueVideoId
    : (availableIds.has(currentId) ? currentId : videos[0]?.id || null);

  if (key !== cueVideosKey) {
    cueVideosKey = key;
    dom.cueVideo.replaceChildren();
    if (!videos.length) {
      const option = document.createElement("option");
      option.textContent = "No videos available";
      option.value = "";
      dom.cueVideo.append(option);
    } else {
      videos.forEach(video => {
        const option = document.createElement("option");
        option.value = video.id;
        option.textContent = video.name;
        dom.cueVideo.append(option);
      });
    }
  }

  if (nextSelection !== selectedCueVideoId) {
    selectedCueVideoId = nextSelection;
    cueItems = [];
    loadCues(selectedCueVideoId);
  }
  dom.cueVideo.value = selectedCueVideoId || "";
  dom.cueVideo.disabled = videos.length === 0;
  dom.addCue.disabled = videos.length === 0;
  dom.addCurrentCue.disabled = !selectedCueVideoId || currentId !== selectedCueVideoId;
}

async function loadCues(videoId) {
  const token = ++cueLoadToken;
  if (!videoId) {
    cueItems = [];
    renderCueTrack();
    return;
  }
  try {
    const data = await api(`/api/videos/${encodeURIComponent(videoId)}/cues`);
    if (token !== cueLoadToken || videoId !== selectedCueVideoId) return;
    cueItems = data.cues;
    renderCueTrack();
  } catch (error) {
    if (token === cueLoadToken) showToast(error.message, true);
  }
}

function selectCueVideo(videoId) {
  if (!videoId || videoId === selectedCueVideoId) return;
  selectedCueVideoId = videoId;
  dom.cueVideo.value = videoId;
  cueItems = [];
  renderCueTrack();
  loadCues(videoId);
}

function cueScaleDuration() {
  const playerDuration = snapshot?.player?.current_id === selectedCueVideoId
    ? snapshot.player.duration_ms || 0
    : 0;
  const latestCue = cueItems.reduce((latest, cue) => Math.max(latest, cue.time_ms), 0);
  return Math.max(playerDuration || 60000, latestCue ? latestCue + 5000 : 0);
}

function updateCuePlayhead(elapsed = 0) {
  if (!snapshot || snapshot.player.current_id !== selectedCueVideoId || snapshot.player.black_screen) {
    dom.cuePlayhead.style.opacity = "0";
    return;
  }
  const percent = Math.min(100, (Math.max(0, elapsed) / cueScaleDuration()) * 100);
  dom.cuePlayhead.style.opacity = "1";
  dom.cuePlayhead.style.left = `${percent}%`;
}

function cueSummary(cue) {
  const config = cue.config;
  if (cue.type === "relay") {
    return `${config.base_url} · ${config.duration_ms.toLocaleString()} ms`;
  }
  const target = config.target === "all" ? "All fixtures" : `Fixture ${config.fixture_id}`;
  const state = config.enabled ? `On · ${config.color.toUpperCase()}` : "Off";
  const duration = config.enabled
    ? config.duration_ms
      ? ` · ${config.duration_ms.toLocaleString()} ms`
      : " · Until next change"
    : "";
  return `${target} · ${state}${duration}`;
}

function renderCueTrack() {
  const scale = cueScaleDuration();
  dom.cueScaleLabel.textContent = `00:00:00 — ${formatTime(scale)}`;
  dom.cueMarkers.replaceChildren();
  dom.cueList.replaceChildren();
  dom.cueEmpty.hidden = cueItems.length > 0;

  cueItems.forEach(cue => {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "cue-marker";
    marker.dataset.type = cue.type;
    marker.style.left = `${Math.min(100, (cue.time_ms / scale) * 100)}%`;
    marker.title = `${formatCueTime(cue.time_ms)} · ${cue.label || (cue.type === "relay" ? "ESP32 relay" : "DMX light")}`;
    marker.setAttribute("aria-label", marker.title);
    marker.append(icon("i-bolt"));
    marker.addEventListener("click", () => openCueDialog(cue));
    dom.cueMarkers.append(marker);

    const row = document.createElement("article");
    row.className = "cue-row";

    const time = document.createElement("span");
    time.className = "cue-time";
    time.textContent = formatCueTime(cue.time_ms);

    const name = document.createElement("div");
    name.className = "cue-action-name";
    const typeIcon = document.createElement("span");
    typeIcon.className = `cue-type-icon ${cue.type}`;
    typeIcon.append(icon("i-bolt"));
    const nameCopy = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = cue.label || (cue.type === "relay" ? "ESP32 relay" : "DMX light");
    const small = document.createElement("small");
    small.textContent = cue.type === "relay" ? "Relay" : "DMX";
    nameCopy.append(strong, small);
    name.append(typeIcon, nameCopy);

    const summary = document.createElement("span");
    summary.className = "cue-summary";
    summary.textContent = cueSummary(cue);
    summary.title = summary.textContent;

    const activity = snapshot?.cue_activity?.[cue.id];
    const status = document.createElement("span");
    status.className = `cue-status ${activity?.state || "ready"}`;
    const statusDot = document.createElement("i");
    statusDot.className = "cue-status-dot";
    const statusText = document.createElement("span");
    statusText.textContent = activity?.message || "Ready";
    statusText.title = statusText.textContent;
    status.append(statusDot, statusText);

    const actions = document.createElement("div");
    actions.className = "cue-row-actions";
    actions.append(
      actionButton("i-play", "Test action now", () => testCue(cue)),
      actionButton("i-edit", "Edit action", () => openCueDialog(cue)),
      actionButton("i-trash", "Delete action", () => deleteCue(cue), "danger"),
    );

    row.append(time, name, summary, status, actions);
    dom.cueList.append(row);
  });
  updateCuePlayhead(displayClock.elapsedMs);
}

function updateCueFormVisibility() {
  const isRelay = dom.cueType.value === "relay";
  dom.relayFields.hidden = !isRelay;
  dom.dmxFields.hidden = isRelay;
  dom.relayUrl.required = isRelay;
  dom.relayDuration.required = isRelay;
  dom.dmxFixture.required = !isRelay && dom.dmxTarget.value === "fixture";
  dom.dmxFixtureField.hidden = dom.dmxTarget.value !== "fixture";
  const dmxOn = dom.dmxEnabled.value === "true";
  dom.dmxColorField.hidden = !dmxOn;
  dom.dmxDurationSettings.hidden = !dmxOn;
  dom.dmxDurationField.hidden = !dmxOn || dom.dmxDurationMode.value !== "timed";
  dom.dmxDuration.required = !isRelay && dmxOn && dom.dmxDurationMode.value === "timed";
}

function openCueDialog(cue = null, initialTimeMs = 0) {
  if (!selectedCueVideoId) return;
  dom.cueId.value = cue?.id || "";
  dom.cueDialogTitle.textContent = cue ? "Edit action" : "Add action";
  dom.cueTime.value = formatCueTime(cue?.time_ms ?? initialTimeMs);
  dom.cueType.value = cue?.type || "relay";
  dom.cueLabel.value = cue?.label || "";
  dom.relayUrl.value = cue?.type === "relay" ? cue.config.base_url : "http://esp32-relay.local";
  dom.relayDuration.value = cue?.type === "relay" ? cue.config.duration_ms : 1000;
  dom.dmxTarget.value = cue?.type === "dmx" ? cue.config.target : "fixture";
  dom.dmxFixture.value = cue?.type === "dmx" ? (cue.config.fixture_id || 1) : 1;
  dom.dmxEnabled.value = cue?.type === "dmx" ? String(cue.config.enabled) : "true";
  dom.dmxColor.value = cue?.type === "dmx" ? cue.config.color : "#ff6a24";
  const dmxDuration = cue?.type === "dmx" ? cue.config.duration_ms : 0;
  dom.dmxDurationMode.value = dmxDuration > 0 ? "timed" : "unlimited";
  dom.dmxDuration.value = dmxDuration > 0 ? dmxDuration : 1000;
  updateCueFormVisibility();
  dom.cueDialog.showModal();
  dom.cueTime.focus();
  dom.cueTime.select();
}

function closeCueDialog() {
  if (dom.cueDialog.open) dom.cueDialog.close();
}

async function saveCue(event) {
  event.preventDefault();
  if (!selectedCueVideoId) return;
  try {
    const actionType = dom.cueType.value;
    const payload = {
      time_ms: parseCueTime(dom.cueTime.value),
      type: actionType,
      label: dom.cueLabel.value.trim(),
      config: actionType === "relay"
        ? {
            base_url: dom.relayUrl.value.trim(),
            duration_ms: Number(dom.relayDuration.value),
          }
        : {
            target: dom.dmxTarget.value,
            fixture_id: Number(dom.dmxFixture.value),
            enabled: dom.dmxEnabled.value === "true",
            color: dom.dmxColor.value,
            duration_ms: dom.dmxEnabled.value === "true" && dom.dmxDurationMode.value === "timed"
              ? Number(dom.dmxDuration.value)
              : 0,
          },
    };
    const cueId = dom.cueId.value;
    if (cueId) {
      await api(`/api/cues/${encodeURIComponent(cueId)}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api(`/api/videos/${encodeURIComponent(selectedCueVideoId)}/cues`, { method: "POST", body: JSON.stringify(payload) });
    }
    closeCueDialog();
    await loadCues(selectedCueVideoId);
    showToast(cueId ? "Action updated" : "Action scheduled");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function deleteCue(cue) {
  if (!window.confirm(`Delete the action at ${formatCueTime(cue.time_ms)}?`)) return;
  try {
    await api(`/api/cues/${encodeURIComponent(cue.id)}`, { method: "DELETE" });
    await loadCues(selectedCueVideoId);
    showToast("Action deleted");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function testCue(cue) {
  try {
    await api(`/api/cues/${encodeURIComponent(cue.id)}/test`, { method: "POST", body: "{}" });
    showToast("Test action sent");
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderPlaylist(videos, currentId) {
  const key = `${currentId || ""}:${videos.map(item => `${item.id}:${item.loop_enabled}`).join(",")}`;
  if (key === renderedPlaylistKey) return;
  renderedPlaylistKey = key;
  dom.list.replaceChildren();
  const loopCount = videos.filter(video => video.loop_enabled).length;
  dom.count.textContent = `${loopCount}/${videos.length} in loop`;
  dom.empty.hidden = videos.length > 0;

  videos.forEach((video, index) => {
    const row = document.createElement("article");
    row.className = `queue-item${video.id === currentId ? " current" : ""}${video.loop_enabled ? "" : " loop-disabled"}`;

    const loopToggle = document.createElement("button");
    loopToggle.type = "button";
    loopToggle.className = "loop-toggle";
    loopToggle.setAttribute("aria-pressed", String(video.loop_enabled));
    loopToggle.setAttribute(
      "aria-label",
      video.loop_enabled ? `Remove ${video.name} from loop` : `Add ${video.name} to loop`,
    );
    loopToggle.title = video.loop_enabled ? "Included in loop" : "Not included in loop";
    loopToggle.append(icon("i-loop"));
    loopToggle.addEventListener("click", () => toggleVideoLoop(video));

    const copy = document.createElement("div");
    copy.className = "queue-copy";
    copy.tabIndex = 0;
    copy.role = "button";
    copy.title = `Play ${video.name}`;
    const title = document.createElement("strong");
    title.textContent = video.name;
    const meta = document.createElement("small");
    meta.textContent = `${String(index + 1).padStart(2, "0")} · ${formatBytes(video.size_bytes)} · ${video.loop_enabled ? "In loop" : "Not in loop"}`;
    copy.append(title, meta);
    copy.addEventListener("click", () => {
      selectCueVideo(video.id);
      sendControl("play", { video_id: video.id });
    });
    copy.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectCueVideo(video.id);
        sendControl("play", { video_id: video.id });
      }
    });

    const actions = document.createElement("div");
    actions.className = "queue-actions";
    const up = actionButton("i-chevron-up", "Move up", () => moveVideo(index, -1));
    const down = actionButton("i-chevron-down", "Move down", () => moveVideo(index, 1));
    const remove = actionButton("i-trash", `Delete ${video.name}`, () => deleteVideo(video), "danger");
    up.disabled = index === 0;
    down.disabled = index === videos.length - 1;
    actions.append(up, down, remove);
    row.append(loopToggle, copy, actions);
    dom.list.append(row);
  });
}

function actionButton(symbol, label, handler, extraClass = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `queue-action ${extraClass}`.trim();
  button.setAttribute("aria-label", label);
  button.title = label;
  button.append(icon(symbol));
  button.addEventListener("click", handler);
  return button;
}

async function sendControl(action, details = {}) {
  if (commandPending) return;
  commandPending = true;
  try {
    const body = { action, ...details };
    applyStatus(await api("/api/control", { method: "POST", body: JSON.stringify(body) }));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    commandPending = false;
    if (snapshot) applyStatus(snapshot);
  }
}

async function moveVideo(index, offset) {
  if (!snapshot) return;
  const ids = snapshot.playlist.map(item => item.id);
  const target = index + offset;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  try {
    renderedPlaylistKey = "";
    applyStatus(await api("/api/playlist/order", { method: "PUT", body: JSON.stringify({ ordered_ids: ids }) }));
  } catch (error) {
    showToast(error.message, true);
  }
}

async function toggleVideoLoop(video) {
  try {
    renderedPlaylistKey = "";
    const data = await api(`/api/videos/${encodeURIComponent(video.id)}/loop`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !video.loop_enabled }),
    });
    applyStatus(data);
    showToast(video.loop_enabled ? `${video.name} removed from loop` : `${video.name} added to loop`);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function deleteVideo(video) {
  if (!window.confirm(`Delete “${video.name}” from the Pi? This cannot be undone.`)) return;
  try {
    renderedPlaylistKey = "";
    applyStatus(await api(`/api/videos/${encodeURIComponent(video.id)}`, { method: "DELETE" }));
    showToast(`${video.name} was deleted`);
  } catch (error) {
    showToast(error.message, true);
  }
}

function uploadFiles(files) {
  const mp4Files = [...files].filter(file => file.name.toLowerCase().endsWith(".mp4"));
  if (!mp4Files.length) {
    showToast("Choose one or more MP4 video files", true);
    return;
  }

  const form = new FormData();
  mp4Files.forEach(file => form.append("files", file));
  const xhr = new XMLHttpRequest();
  dom.uploadProgress.hidden = false;
  dom.uploadProgressFill.style.width = "0%";
  dom.fileInput.disabled = true;

  xhr.upload.addEventListener("progress", event => {
    if (event.lengthComputable) dom.uploadProgressFill.style.width = `${(event.loaded / event.total) * 100}%`;
  });
  xhr.addEventListener("load", () => {
    dom.fileInput.disabled = false;
    setTimeout(() => { dom.uploadProgress.hidden = true; }, 500);
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch (_) { /* response handled below */ }
    if (xhr.status >= 200 && xhr.status < 300) {
      renderedPlaylistKey = "";
      applyStatus(data);
      showToast(`${data.added.length} ${data.added.length === 1 ? "video" : "videos"} added to the loop`);
      dom.fileInput.value = "";
    } else {
      showToast(data.error || "Upload failed", true);
    }
  });
  xhr.addEventListener("error", () => {
    dom.fileInput.disabled = false;
    dom.uploadProgress.hidden = true;
    showToast("The upload connection was interrupted", true);
  });
  xhr.open("POST", "/api/videos");
  xhr.send(form);
}

dom.play.addEventListener("click", () => sendControl("play"));
dom.pause.addEventListener("click", () => sendControl("pause"));
dom.stop.addEventListener("click", () => sendControl("stop"));
dom.displayMode.addEventListener("click", () => {
  if (snapshot) sendControl("display_mode", { fullscreen: !snapshot.player.fullscreen });
});
dom.blackScreen.addEventListener("click", () => {
  if (snapshot) sendControl("black_screen", { enabled: !snapshot.player.black_screen });
});
dom.next.addEventListener("click", () => sendControl("next"));
dom.volumeSlider.addEventListener("input", event => {
  dom.volumeValue.textContent = `${event.target.value}%`;
});
dom.volumeSlider.addEventListener("change", event => {
  sendControl("audio_volume", { volume: Number(event.target.value) });
});
dom.muteButton.addEventListener("click", () => {
  if (snapshot) sendControl("audio_mute", { muted: !snapshot.player.audio.muted });
});
dom.audioDevice.addEventListener("change", event => {
  sendControl("audio_device", { device_id: event.target.value });
});
dom.fileInput.addEventListener("change", event => uploadFiles(event.target.files));

["dragenter", "dragover"].forEach(name => dom.dropzone.addEventListener(name, event => {
  event.preventDefault();
  dom.dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach(name => dom.dropzone.addEventListener(name, event => {
  event.preventDefault();
  dom.dropzone.classList.remove("dragging");
}));
dom.dropzone.addEventListener("drop", event => uploadFiles(event.dataTransfer.files));

dom.cueVideo.addEventListener("change", event => selectCueVideo(event.target.value));
dom.addCue.addEventListener("click", () => openCueDialog());
dom.addCurrentCue.addEventListener("click", () => {
  const atPlayhead = snapshot?.player?.current_id === selectedCueVideoId ? displayClock.elapsedMs : 0;
  openCueDialog(null, atPlayhead);
});
dom.cueType.addEventListener("change", updateCueFormVisibility);
dom.dmxTarget.addEventListener("change", updateCueFormVisibility);
dom.dmxEnabled.addEventListener("change", updateCueFormVisibility);
dom.dmxDurationMode.addEventListener("change", updateCueFormVisibility);
dom.cueForm.addEventListener("submit", saveCue);
dom.cueDialogClose.addEventListener("click", closeCueDialog);
dom.cueCancel.addEventListener("click", closeCueDialog);
dom.cueDialog.addEventListener("click", event => {
  if (event.target === dom.cueDialog) closeCueDialog();
});

dom.controllerAddress.textContent = window.location.origin;
requestAnimationFrame(renderTimecode);
pollStatus();
