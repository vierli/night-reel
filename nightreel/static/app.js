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
  play: document.querySelector("#play-button"),
  pause: document.querySelector("#pause-button"),
  stop: document.querySelector("#stop-button"),
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
};

let snapshot = null;
let renderedPlaylistKey = "";
let pollTimer = null;
let toastTimer = null;
let commandPending = false;
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

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "MP4 video";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function stateLabel(state) {
  return ({ playing: "Playing", paused: "Paused", loading: "Loading", error: "Error", ended: "Advancing" })[state] || "Stopped";
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

  const videoChanged = displayClock.currentId !== player.current_id;
  const wasStopped = previousState === "stopped" && state !== "stopped";
  if (videoChanged || state === "stopped" || wasStopped) {
    displayClock.elapsedMs = player.elapsed_ms || 0;
  } else {
    displayClock.elapsedMs = Math.max(displayClock.elapsedMs, player.elapsed_ms || 0);
  }
  displayClock.currentId = player.current_id;
  displayClock.frameAt = performance.now();

  dom.statePill.dataset.state = state;
  dom.statePill.textContent = stateLabel(state);
  dom.screen.dataset.state = state;
  dom.screenKicker.textContent = state === "playing" ? "Live on the attached display" : state === "paused" ? "Playback held" : "Ready when you are";
  dom.currentTitle.textContent = current?.name || "No video selected";
  dom.currentFile.textContent = current?.filename || "Add an MP4 to start the loop";
  dom.timelineStatus.textContent = current ? `${stateLabel(state)} · ${current.name}` : "Waiting for a video";
  dom.backend.textContent = player.backend === "mock" ? "Demo playback engine" : "VLC playback engine";

  const hasVideos = data.playlist.length > 0;
  dom.play.disabled = !hasVideos || commandPending;
  dom.pause.disabled = state !== "playing" || commandPending;
  dom.stop.disabled = !current || state === "stopped" || commandPending;
  dom.next.disabled = !hasVideos || commandPending;
  dom.play.querySelector("span").textContent = state === "paused" ? "Resume" : "Start";

  if (player.error) showToast(player.error, true);
  renderPlaylist(data.playlist, player.current_id);
}

function renderTimecode() {
  if (!snapshot) return;
  const player = snapshot.player;
  const now = performance.now();
  if (player.state === "playing" || player.state === "loading") {
    displayClock.elapsedMs += now - displayClock.frameAt;
  }
  displayClock.frameAt = now;
  let elapsed = displayClock.elapsedMs;
  if (player.duration_ms) {
    elapsed = Math.min(elapsed, player.duration_ms);
    displayClock.elapsedMs = elapsed;
  }
  dom.elapsed.textContent = formatTime(elapsed);
  dom.duration.textContent = formatTime(player.duration_ms);
  const percent = player.duration_ms ? (elapsed / player.duration_ms) * 100 : 0;
  dom.timelineFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  requestAnimationFrame(renderTimecode);
}

function renderPlaylist(videos, currentId) {
  const key = `${currentId || ""}:${videos.map(item => item.id).join(",")}`;
  if (key === renderedPlaylistKey) return;
  renderedPlaylistKey = key;
  dom.list.replaceChildren();
  dom.count.textContent = `${videos.length} ${videos.length === 1 ? "video" : "videos"}`;
  dom.empty.hidden = videos.length > 0;

  videos.forEach((video, index) => {
    const row = document.createElement("article");
    row.className = `queue-item${video.id === currentId ? " current" : ""}`;

    const number = document.createElement("span");
    number.className = "queue-number";
    number.textContent = String(index + 1).padStart(2, "0");

    const copy = document.createElement("div");
    copy.className = "queue-copy";
    copy.tabIndex = 0;
    copy.role = "button";
    copy.title = `Play ${video.name}`;
    const title = document.createElement("strong");
    title.textContent = video.name;
    const meta = document.createElement("small");
    meta.textContent = `${formatBytes(video.size_bytes)} · MP4`;
    copy.append(title, meta);
    copy.addEventListener("click", () => sendControl("play", video.id));
    copy.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        sendControl("play", video.id);
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
    row.append(number, copy, actions);
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

async function sendControl(action, videoId = null) {
  if (commandPending) return;
  commandPending = true;
  try {
    const body = videoId ? { action, video_id: videoId } : { action };
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
dom.next.addEventListener("click", () => sendControl("next"));
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

dom.controllerAddress.textContent = window.location.origin;
requestAnimationFrame(renderTimecode);
pollStatus();
