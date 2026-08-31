/* XiaoAI Navidrome native Home Assistant panel. No build step or third-party runtime. */

const WS_PREFIX = "xiaoai_navidrome/";
const PAGE_SIZE = 30;
const COVER_CACHE_ITEMS = 48;
const COVER_CACHE_BYTES = 32 * 1024 * 1024;
const COVER_CONCURRENCY = 6;
const STATIC_VERSION = new URL(import.meta.url).search;
let stylesheetPromise;

/** Convert library-provided text to a short, control-character-free display string. */
export function voiceSafeText(value, fallback = "") {
  const text = value === null || value === undefined ? "" : String(value);
  const clean = text
    .replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return clean || fallback;
}

/** Collapse queue flags into the three playback modes presented by the panel. */
export function playbackMode(queue) {
  if (queue?.repeat === "one") return "one";
  return queue?.shuffle ? "shuffle" : "sequence";
}

/** Return one atomic queue-options update for the next playback mode. */
export function nextPlaybackMode(mode) {
  return ({
    sequence: { shuffle: true, repeat: "all" },
    shuffle: { shuffle: false, repeat: "one" },
    one: { shuffle: false, repeat: "all" },
  })[mode] || { shuffle: false, repeat: "all" };
}

/**
 * Cancels obsolete work and lets a caller verify that its response is current.
 * The gate deliberately does not retry requests: mutations must never be replayed.
 */
export class RequestGate {
  constructor() {
    this._number = 0;
    this._controller = null;
  }

  begin() {
    if (this._controller) this._controller.abort();
    const controller = new AbortController();
    this._controller = controller;
    const number = ++this._number;
    return Object.freeze({
      id: number,
      signal: controller.signal,
      isCurrent: () => number === this._number && !controller.signal.aborted,
    });
  }

  cancel() {
    this._number += 1;
    if (this._controller) this._controller.abort();
    this._controller = null;
  }
}

export function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

/** Return the relative authenticated Home Assistant cover endpoint. */
export function coverApiPath(entryId, coverId) {
  return `/api/xiaoai_navidrome/cover/${encodeURIComponent(String(entryId))}/${encodeURIComponent(String(coverId))}`;
}

/** Compose a specialized cover class without dropping the shared crop rules. */
export function coverClassNames(className = "") {
  return ["cover", className, "cover-placeholder"].filter(Boolean).join(" ");
}

function abortable(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      signal.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    }),
  ]);
}

function isAbort(error) {
  return error?.name === "AbortError";
}

function isConflict(error) {
  return error?.code === 409 || error?.status === 409 || /\b409\b|conflict|revision/i.test(String(error?.message || error));
}

export function responseItems(response) {
  return Array.isArray(response?.items) ? response.items : [];
}

export function queueStatus(response) {
  return response && typeof response === "object" && Array.isArray(response.items)
    ? response
    : null;
}

/** Map a track's main click target to its context-specific playback mutation. */
export function trackPrimaryCommand(context, trackId, playlistId = "") {
  const id = String(trackId || "");
  if (!id) return null;
  if (context === "playlist") {
    const listId = String(playlistId || "");
    if (!listId) return null;
    return {
      command: "queue_playlist",
      fields: { playlist_id: listId, position: "replace", start_track_id: id },
    };
  }
  return {
    command: "queue_add",
    fields: { track_ids: [id], position: "replace" },
  };
}

function responseTotal(response) {
  const number = Number(response?.total);
  return Number.isFinite(number) ? number : 0;
}

function makeElement(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = voiceSafeText(options.text);
  if (options.title) node.title = voiceSafeText(options.title);
  if (options.type) node.type = options.type;
  if (options.value !== undefined) node.value = String(options.value);
  if (options.min !== undefined) node.min = String(options.min);
  if (options.max !== undefined) node.max = String(options.max);
  if (options.step !== undefined) node.step = String(options.step);
  if (options.disabled !== undefined) node.disabled = Boolean(options.disabled);
  if (options.checked !== undefined) node.checked = Boolean(options.checked);
  if (options.placeholder) node.placeholder = voiceSafeText(options.placeholder);
  if (options.role) node.setAttribute("role", options.role);
  if (options.label) node.setAttribute("aria-label", voiceSafeText(options.label));
  if (options.pressed !== undefined) node.setAttribute("aria-pressed", String(Boolean(options.pressed)));
  if (options.selectedState !== undefined) node.setAttribute("aria-selected", String(Boolean(options.selectedState)));
  if (options.tabIndex !== undefined) node.tabIndex = Number(options.tabIndex);
  if (options.selected !== undefined) node.selected = Boolean(options.selected);
  if (options.dataset) {
    for (const [key, value] of Object.entries(options.dataset)) node.dataset[key] = String(value);
  }
  if (options.on) {
    for (const [event, listener] of Object.entries(options.on)) node.addEventListener(event, listener);
  }
  node.append(...children.filter(Boolean));
  return node;
}

const ICON_PATHS = Object.freeze({
  previous: "M6 5h2v14H6zm12.5 1.5v11L10 12z",
  next: "M16 5h2v14h-2zM5.5 6.5 14 12l-8.5 5.5z",
  play: "M8 5v14l11-7z",
  pause: "M7 5h4v14H7zm6 0h4v14h-4z",
  sequence: "M7 7h11l-2.5-2.5L17 3l5 5-5 5-1.5-1.5L18 9H7a3 3 0 0 0-3 3H2a5 5 0 0 1 5-5zm10 8a3 3 0 0 0 3-3h2a5 5 0 0 1-5 5H6l2.5 2.5L7 21l-5-5 5-5 1.5 1.5L6 15z",
  shuffle: "M16.5 3.5 22 9l-5.5 5.5-1.4-1.4L18.2 10h-2.1a4 4 0 0 1-3.6-2.2l-1.1-2.2A2 2 0 0 0 9.6 4.5H3v-2h6.6a4 4 0 0 1 3.6 2.2l1.1 2.2a2 2 0 0 0 1.8 1.1h2.1l-3.1-3.1zm-7 8.7 1.4 1.4-1.7 3.3a4 4 0 0 1-3.6 2.2H3v-2h2.6a2 2 0 0 0 1.8-1.1zm7 2.3L22 20l-5.5 5.5-1.4-1.4 3.1-3.1h-2.1a4 4 0 0 1-3.6-2.2l-.6-1.2 1.4-1.4 1 1.7a2 2 0 0 0 1.8 1.1h2.1l-3.1-3.1z",
  one: "M7 7h11l-2.5-2.5L17 3l5 5-5 5-1.5-1.5L18 9H7a3 3 0 0 0-3 3H2a5 5 0 0 1 5-5zm10 8a3 3 0 0 0 3-3h2a5 5 0 0 1-5 5H6l2.5 2.5L7 21l-5-5 5-5 1.5 1.5L6 15zm-5-4h2v6h-2v-4h-1v-1z",
  volume: "M4 10v4h4l5 4V6L8 10zm11.5-.5a4 4 0 0 1 0 5l1.5 1.3a6 6 0 0 0 0-7.6zm2.8-2.7a8 8 0 0 1 0 10.4l1.5 1.3a10 10 0 0 0 0-13z",
  muted: "M4 10v4h4l5 4V6L8 10zm11.4-.8L17.2 11l1.8-1.8 1.4 1.4-1.8 1.8 1.8 1.8-1.4 1.4-1.8-1.8-1.8 1.8-1.4-1.4 1.8-1.8-1.8-1.8z",
  trash: "M8 7h8l-.6 13H8.6zM9 4h6l1 2H8zm-3 2h12v2H6z",
});

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICON_PATHS[name] || ICON_PATHS.play);
  svg.append(path);
  return svg;
}

function iconButton(iconName, label, onClick, options = {}) {
  return makeElement("button", {
    type: "button",
    className: options.className || "icon-button",
    label,
    title: label,
    disabled: options.disabled,
    pressed: options.pressed,
    dataset: options.dataset,
    on: { click: onClick },
  }, [icon(iconName)]);
}

function button(text, onClick, options = {}) {
  return makeElement("button", {
    type: "button",
    className: options.className || "control",
    text,
    label: options.label || text,
    title: options.title || options.label || text,
    disabled: options.disabled,
    pressed: options.pressed,
    role: options.role,
    selectedState: options.selectedState,
    tabIndex: options.tabIndex,
    dataset: options.dataset,
    on: { click: onClick },
  });
}

/** A bounded, de-duplicating object-URL cache for authenticated cover art. */
class CoverStore {
  constructor(owner) {
    this.owner = owner;
    this.entries = new Map();
    this.pending = new Map();
    this.jobs = [];
    this.active = 0;
    this.bytes = 0;
    this.closed = false;
  }

  get(coverId) {
    const id = String(coverId || "");
    if (!id || this.closed) return Promise.resolve(null);
    const existing = this.entries.get(id);
    if (existing) {
      this.entries.delete(id);
      this.entries.set(id, existing);
      return Promise.resolve(existing.url);
    }
    if (this.pending.has(id)) return this.pending.get(id);
    const promise = new Promise((resolve) => {
      this.jobs.push({ id, resolve });
      this._drain();
    });
    this.pending.set(id, promise);
    return promise;
  }

  _drain() {
    while (!this.closed && this.active < COVER_CONCURRENCY && this.jobs.length) {
      const job = this.jobs.shift();
      this.active += 1;
      this._load(job)
        .catch(() => job.resolve(null))
        .finally(() => {
          this.active -= 1;
          this.pending.delete(job.id);
          this._drain();
        });
    }
  }

  async _load(job) {
    let url = null;
    let size = 0;
    try {
      const entryId = this.owner.entryId;
      if (!entryId || this.closed || !this.owner.hass) {
        job.resolve(null);
        return;
      }
      const path = coverApiPath(entryId, job.id);
      const response = await this.owner.hass.fetchWithAuth(path);
      if (response.status === 404) {
        this._remember(job.id, null, 0);
        job.resolve(null);
        return;
      }
      if (!response.ok) throw new Error("Cover is unavailable");
      const blob = await response.blob();
      size = Math.max(0, Number(blob.size) || 0);
      if (size > COVER_CACHE_BYTES || this.closed) {
        job.resolve(null);
        return;
      }
      url = URL.createObjectURL(blob);
      if (this.closed) {
        URL.revokeObjectURL(url);
        job.resolve(null);
        return;
      }
      this._remember(job.id, url, size);
      job.resolve(url);
    } catch (error) {
      if (url) URL.revokeObjectURL(url);
      throw error;
    }
  }

  _remember(id, url, size) {
    const prior = this.entries.get(id);
    if (prior) {
      this.entries.delete(id);
      this.bytes -= prior.size;
      if (prior.url) URL.revokeObjectURL(prior.url);
    }
    this.entries.set(id, { url, size });
    this.bytes += size;
    while (this.entries.size > COVER_CACHE_ITEMS || this.bytes > COVER_CACHE_BYTES) {
      const [oldId, old] = this.entries.entries().next().value;
      this.entries.delete(oldId);
      this.bytes -= old.size;
      if (old.url) URL.revokeObjectURL(old.url);
    }
  }

  clear() {
    this.closed = true;
    for (const job of this.jobs.splice(0)) job.resolve(null);
    for (const entry of this.entries.values()) {
      if (entry.url) URL.revokeObjectURL(entry.url);
    }
    this.entries.clear();
    this.bytes = 0;
  }
}

const HTMLElementBase = globalThis.HTMLElement || class {};

class XiaoAINavidromePanel extends HTMLElementBase {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panel = null;
    this._route = null;
    this._narrow = false;
    this._connected = false;
    this.entryId = "";
    this.queue = { items: [], current_index: -1, revision: 0, state: "stopped", repeat: "all", shuffle: false };
    this.config = {};
    this.players = [];
    this.tracks = [];
    this.trackTotal = 0;
    this.trackQuery = "";
    this.trackOffset = 0;
    this.playlists = [];
    this.playlistTotal = 0;
    this.playlistQuery = "";
    this.playlistOffset = 0;
    this.selectedPlaylist = null;
    this.playlistTracks = [];
    this.playlistTrackTotal = 0;
    this.playlistTrackOffset = 0;
    this._playlistReturnFocusKey = "";
    this.detail = null;
    this.libraryTab = "tracks";
    this.connectionState = "正在连接";
    this.syncing = false;
    this.notice = "";
    this.themeMode = this._readTheme();
    this._initGate = new RequestGate();
    this._tracksGate = new RequestGate();
    this._playlistsGate = new RequestGate();
    this._playlistTracksGate = new RequestGate();
    this._detailGate = new RequestGate();
    this._unsubscribeQueue = null;
    this._commandChain = Promise.resolve();
    this._queueEpoch = 0;
    this._queueReceivedAt = Date.now();
    this._progressTimer = null;
    this._seekPreview = null;
    this._initializedEntry = "";
    this._initializing = false;
    this._covers = new CoverStore(this);
    this._render();
  }

  set hass(value) {
    this._hass = value;
    if (this._connected && this._initializedEntry !== this.entryId) this._start();
  }

  get hass() {
    return this._hass;
  }

  set panel(value) {
    this._panel = value;
    const config = value?.config || value || {};
    const nextEntry = String(config.entry_id || "");
    if (nextEntry !== this.entryId) {
      this.entryId = nextEntry;
      this._initializedEntry = "";
      this._covers.clear();
      this._covers = new CoverStore(this);
      if (this._unsubscribeQueue) this._unsubscribeQueue();
      this._unsubscribeQueue = null;
      if (this._connected) this._start();
    }
  }

  get panel() {
    return this._panel;
  }

  set narrow(value) {
    this._narrow = Boolean(value);
    this.toggleAttribute("narrow", this._narrow);
    this._render();
  }

  get narrow() {
    return this._narrow;
  }

  set route(value) {
    this._route = value;
  }

  get route() {
    return this._route;
  }

  connectedCallback() {
    this._connected = true;
    if (this._covers.closed) this._covers = new CoverStore(this);
    this._loadStyles();
    this._start();
  }

  disconnectedCallback() {
    this._connected = false;
    this._initializedEntry = "";
    this._initGate.cancel();
    this._tracksGate.cancel();
    this._playlistsGate.cancel();
    this._playlistTracksGate.cancel();
    this._detailGate.cancel();
    if (this._unsubscribeQueue) this._unsubscribeQueue();
    this._unsubscribeQueue = null;
    if (this._progressTimer) clearInterval(this._progressTimer);
    this._progressTimer = null;
    this._covers.clear();
  }

  _readTheme() {
    try {
      const mode = localStorage.getItem("xiaoai_navidrome_theme");
      return ["auto", "light", "dark"].includes(mode) ? mode : "auto";
    } catch (_) {
      return "auto";
    }
  }

  _saveTheme() {
    try {
      localStorage.setItem("xiaoai_navidrome_theme", this.themeMode);
    } catch (_) {
      // Private browsing may deny storage; retain the in-memory preference.
    }
  }

  async _loadStyles() {
    if (!stylesheetPromise) {
      stylesheetPromise = fetch(new URL(`./panel.css${STATIC_VERSION}`, import.meta.url))
        .then((response) => {
          if (!response.ok) throw new Error("Panel stylesheet unavailable");
          return response.text();
        })
        .catch(() => "");
    }
    const css = await stylesheetPromise;
    if (!this._connected || !css || this.shadowRoot.querySelector("style[data-xiaoai-panel]")) return;
    const style = document.createElement("style");
    style.dataset.xiaoaiPanel = "";
    style.textContent = css;
    this.shadowRoot.prepend(style);
  }

  _start() {
    if (!this._connected) return;
    if (!this.hass) {
      this.connectionState = "等待 Home Assistant";
      this._render();
      return;
    }
    if (!this.entryId) {
      this.connectionState = "面板配置缺少 entry_id";
      this._render();
      return;
    }
    if (this._initializing || this._initializedEntry === this.entryId) return;
    this._initialize();
  }

  async _initialize() {
    this._initializing = true;
    const gate = this._initGate.begin();
    this.connectionState = "正在连接";
    this._render();
    this._subscribeQueue();
    try {
      const [config, players] = await Promise.all([
        this._call("config", {}, gate.signal),
        this._call("media_players", {}, gate.signal),
      ]);
      if (!gate.isCurrent() || !this._connected) return;
      this.config = config || {};
      this.players = responseItems(players);
      this.connectionState = this.config.connected === false ? "Navidrome 未连接" : "已连接";
      this.syncing = Boolean(this.config.index?.syncing);
      this._initializedEntry = this.entryId;
      this._render();
      await Promise.all([this._refreshQueue(), this._loadTracks(), this._loadPlaylists()]);
    } catch (error) {
      if (!isAbort(error) && gate.isCurrent()) {
        this.connectionState = "连接不可用";
        this._setNotice("无法连接集成，请检查配置。", true);
      }
    } finally {
      this._initializing = false;
    }
  }

  async _subscribeQueue() {
    if (this._unsubscribeQueue || !this.hass?.connection || !this.entryId) return;
    const subscribedEntry = this.entryId;
    try {
      const unsubscribe = await this.hass.connection.subscribeMessage(
        (event) => {
          const status = queueStatus(event);
          if (status?.items && this._connected && subscribedEntry === this.entryId) this._applyQueue(status);
        },
        { type: `${WS_PREFIX}subscribe_queue`, entry_id: subscribedEntry },
      );
      if (typeof unsubscribe === "function") {
        if (this._connected && subscribedEntry === this.entryId && !this._unsubscribeQueue) {
          this._unsubscribeQueue = unsubscribe;
        } else {
          unsubscribe();
        }
      }
    } catch (_) {
      if (this._connected && subscribedEntry === this.entryId) this._setNotice("队列实时更新暂不可用。", true);
    }
  }

  _call(command, fields = {}, signal) {
    if (!this.hass?.callWS) return Promise.reject(new Error("Home Assistant WebSocket unavailable"));
    const message = { type: `${WS_PREFIX}${command}`, entry_id: this.entryId, ...fields };
    return abortable(Promise.resolve(this.hass.callWS(message)), signal);
  }

  async _refreshQueue() {
    const before = this._queueEpoch;
    try {
      const response = await this._call("queue");
      const status = queueStatus(response);
      // A subscription event that arrived while this request was in flight is newer.
      if (status?.items && before === this._queueEpoch) this._applyQueue(status);
    } catch (error) {
      if (!isAbort(error)) this._setNotice("无法读取播放队列。", true);
    }
  }

  _applyQueue(status) {
    const incomingRevision = Number(status?.revision);
    const currentRevision = Number(this.queue?.revision);
    if (Number.isFinite(incomingRevision) && Number.isFinite(currentRevision) && incomingRevision < currentRevision) return;
    this.queue = {
      ...this.queue,
      ...status,
      items: Array.isArray(status.items) ? status.items : [],
      revision: Number.isFinite(Number(status.revision)) ? Number(status.revision) : this.queue.revision || 0,
    };
    this._queueEpoch += 1;
    this._queueReceivedAt = Date.now();
    this._seekPreview = null;
    this._render();
    this._syncProgressTimer();
  }

  async _loadTracks() {
    const gate = this._tracksGate.begin();
    try {
      const response = await this._call(
        "tracks",
        { q: this.trackQuery, offset: this.trackOffset, limit: PAGE_SIZE },
        gate.signal,
      );
      if (!gate.isCurrent() || !this._connected) return;
      this.tracks = responseItems(response);
      this.trackTotal = responseTotal(response);
      this._render();
    } catch (error) {
      if (!isAbort(error) && gate.isCurrent()) this._setNotice("无法读取曲库。", true);
    }
  }

  async _loadPlaylists() {
    const gate = this._playlistsGate.begin();
    try {
      const response = await this._call(
        "playlists",
        { q: this.playlistQuery, offset: this.playlistOffset, limit: PAGE_SIZE },
        gate.signal,
      );
      if (!gate.isCurrent() || !this._connected) return;
      this.playlists = responseItems(response);
      this.playlistTotal = responseTotal(response);
      this._render();
    } catch (error) {
      if (!isAbort(error) && gate.isCurrent()) this._setNotice("无法读取歌单。", true);
    }
  }

  async _openPlaylist(playlist) {
    const playlistId = String(playlist?.id || "");
    if (!playlistId) return;
    this._playlistReturnFocusKey = `playlist-cover:${playlistId}`;
    this.selectedPlaylist = playlist;
    this.playlistTrackOffset = 0;
    this.playlistTracks = [];
    this._render();
    this._focusByKey("playlist-back", () => String(this.selectedPlaylist?.id || "") === playlistId);
    await this._loadPlaylistTracks();
  }

  _closePlaylist() {
    const returnFocusKey = this._playlistReturnFocusKey;
    this._playlistReturnFocusKey = "";
    this.selectedPlaylist = null;
    this._playlistTracksGate.cancel();
    this._render();
    this._focusByKey(returnFocusKey, () => this.libraryTab === "playlists" && !this.selectedPlaylist);
  }

  async _loadPlaylistTracks() {
    if (!this.selectedPlaylist) return;
    const playlistId = String(this.selectedPlaylist.id || "");
    if (!playlistId) return;
    const gate = this._playlistTracksGate.begin();
    try {
      const response = await this._call(
        "playlist_tracks",
        { playlist_id: playlistId, offset: this.playlistTrackOffset, limit: PAGE_SIZE },
        gate.signal,
      );
      if (!gate.isCurrent() || !this._connected || playlistId !== String(this.selectedPlaylist?.id || "")) return;
      this.playlistTracks = responseItems(response);
      this.playlistTrackTotal = responseTotal(response);
      this._render();
    } catch (error) {
      if (!isAbort(error) && gate.isCurrent()) this._setNotice("无法读取歌单曲目。", true);
    }
  }

  async _showDetail(track) {
    const id = String(track?.id || "");
    if (!id) return;
    const gate = this._detailGate.begin();
    this.detail = { ...track, loading: true };
    this._render();
    try {
      const response = await this._call("track", { track_id: id }, gate.signal);
      if (!gate.isCurrent() || !this._connected) return;
      this.detail = { ...track, ...(response?.track || response || {}), loading: false };
      this._render();
    } catch (error) {
      if (!isAbort(error) && gate.isCurrent()) {
        this.detail = { ...track, loading: false };
        this._setNotice("无法读取曲目详情。", true);
      }
    }
  }

  _queueCommand(command, fields = {}) {
    this._commandChain = this._commandChain
      .catch(() => undefined)
      .then(async () => {
        const expectedRevision = Number(this.queue.revision);
        try {
          const result = await this._call(command, { ...fields, expected_revision: expectedRevision });
          const status = queueStatus(result);
          if (status?.items) this._applyQueue(status);
          return result;
        } catch (error) {
          if (isConflict(error)) {
            this._setNotice("队列已在其他位置更新，已刷新最新状态。", true);
            await this._refreshQueue();
            return null;
          }
          this._setNotice("操作未完成。", true);
          return null;
        }
      });
    return this._commandChain;
  }

  _setNotice(message, isError = false) {
    this.notice = { text: message, error: isError };
    this._render();
  }

  _changeTheme() {
    this.themeMode = ({ auto: "light", light: "dark", dark: "auto" })[this.themeMode];
    this._saveTheme();
    this._render();
  }

  _renderCover(coverId, label, className = "") {
    const holder = makeElement("span", { className: coverClassNames(className), label: `${voiceSafeText(label, "音乐")}封面` }, [
      makeElement("span", { text: "♫" }),
    ]);
    const key = String(coverId || "");
    if (!key) return holder;
    holder.dataset.coverKey = key;
    this._covers.get(key).then((url) => {
      if (!url || !this._connected || holder.dataset.coverKey !== key || !holder.isConnected) return;
      const image = document.createElement("img");
      image.alt = voiceSafeText(label, "音乐封面");
      image.src = url;
      image.loading = "lazy";
      image.addEventListener("error", () => image.remove());
      holder.replaceChildren(image);
      holder.classList.remove("cover-placeholder");
    });
    return holder;
  }

  _render() {
    if (!this.shadowRoot || typeof document === "undefined") return;
    const activeFocusKey = String(this.shadowRoot.activeElement?.dataset?.focusKey || "");
    const app = makeElement("main", { className: "panel", dataset: { theme: this.themeMode } });
    app.append(this._renderHeader());
    if (this.notice) {
      app.append(makeElement("div", { className: `notice ${this.notice.error ? "notice-error" : ""}`, role: "status", text: this.notice.text }, [
        button("关闭", () => { this.notice = ""; this._render(); }, { className: "notice-close" }),
      ]));
    }
    const layout = makeElement("div", { className: "layout" });
    const library = this._renderLibrary();
    const queue = this._renderQueue();
    // Grid areas in CSS place the queue first on single-column/mobile layouts.
    layout.append(library, queue);
    app.append(layout);
    if (this.detail) app.append(this._renderDetail());
    // Keep the cached async stylesheet node when replacing the application tree.
    const style = this.shadowRoot.querySelector("style[data-xiaoai-panel]");
    this.shadowRoot.replaceChildren(...(style ? [style, app] : [app]));
    this._focusByKey(activeFocusKey);
  }

  _focusByKey(focusKey, guard = () => true) {
    const key = String(focusKey || "");
    if (!key) return;
    queueMicrotask(() => {
      if (!this._connected || !this.isConnected || !guard()) return;
      const targets = this.shadowRoot?.querySelectorAll("[data-focus-key]") || [];
      for (const target of targets) {
        if (target.dataset.focusKey === key) {
          target.focus();
          return;
        }
      }
    });
  }

  _renderHeader() {
    const header = makeElement("header", { className: "header" });
    const brand = makeElement("div", { className: "brand" }, [
      makeElement("div", { className: "brand-mark", text: "♫" }),
      makeElement("div", {}, [
        makeElement("h1", { text: "XiaoAI Navidrome" }),
        makeElement("p", { className: "connection", text: `${this.connectionState}${this.syncing ? " · 正在同步" : ""}` }),
      ]),
    ]);
    const actions = makeElement("div", { className: "header-actions" }, [
      button("同步曲库", () => this._syncLibrary(), { className: "secondary", disabled: this.syncing }),
      button(this.themeMode === "auto" ? "跟随主题" : this.themeMode === "light" ? "浅色主题" : "深色主题", () => this._changeTheme(), { className: "secondary" }),
    ]);
    header.append(brand, actions);
    return header;
  }

  _renderLibrary() {
    const pane = makeElement("section", { className: "library-pane", label: "曲库浏览" });
    const tabs = makeElement("div", { className: "tabs", role: "tablist", on: { keydown: (event) => this._handleLibraryTabKey(event) } }, [
      button("曲目", () => this._selectLibraryTab("tracks"), {
        className: "tab",
        role: "tab",
        selectedState: this.libraryTab === "tracks",
        tabIndex: this.libraryTab === "tracks" ? 0 : -1,
      }),
      button("歌单", () => this._selectLibraryTab("playlists"), {
        className: "tab",
        role: "tab",
        selectedState: this.libraryTab === "playlists",
        tabIndex: this.libraryTab === "playlists" ? 0 : -1,
      }),
    ]);
    pane.append(tabs);
    if (this.libraryTab === "tracks") pane.append(this._renderTracks());
    else pane.append(this.selectedPlaylist ? this._renderPlaylistTracks() : this._renderPlaylists());
    return pane;
  }

  _selectLibraryTab(tab) {
    if (!["tracks", "playlists"].includes(tab)) return;
    this.libraryTab = tab;
    this._render();
    queueMicrotask(() => this.shadowRoot?.querySelector(".tab[aria-selected='true']")?.focus());
  }

  _handleLibraryTabKey(event) {
    const key = event?.key;
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(key)) return;
    event.preventDefault();
    let tab;
    if (key === "Home") tab = "tracks";
    else if (key === "End") tab = "playlists";
    else tab = this.libraryTab === "tracks" ? "playlists" : "tracks";
    this._selectLibraryTab(tab);
  }

  _searchBar(value, placeholder, onInput) {
    const input = makeElement("input", { className: "search", value, placeholder, label: placeholder, on: { input: onInput } });
    return makeElement("div", { className: "search-wrap" }, [makeElement("span", { className: "search-icon", text: "⌕" }), input]);
  }

  _renderTracks() {
    const section = makeElement("div", { className: "library-content" });
    section.append(this._searchBar(this.trackQuery, "搜索曲目、艺术家或专辑", (event) => {
      this.trackQuery = event.currentTarget.value;
      this.trackOffset = 0;
      this._loadTracks();
    }));
    const list = makeElement("div", { className: "track-list" });
    if (!this.tracks.length) list.append(makeElement("p", { className: "empty", text: "没有找到曲目。" }));
    for (const track of this.tracks) list.append(this._renderTrack(track, "library"));
    section.append(list, this._pager(this.trackOffset, this.trackTotal, (offset) => { this.trackOffset = offset; this._loadTracks(); }));
    return section;
  }

  _renderTrack(track, context) {
    const row = makeElement("article", { className: "track-row" });
    const label = voiceSafeText(track?.title, "未命名曲目");
    const copy = makeElement("span", { className: "track-copy" }, [
      makeElement("strong", { text: label }),
      makeElement("span", { text: `${voiceSafeText(track?.artist, "未知艺术家")} · ${voiceSafeText(track?.album, "未知专辑")}` }),
    ]);
    const meta = makeElement("span", { className: "duration", text: formatDuration(track?.duration) });
    const primary = makeElement("button", {
      type: "button",
      className: "track-primary",
      label: context === "playlist" ? `从 ${label} 开始播放歌单` : `播放 ${label}`,
      title: context === "playlist" ? "从此曲开始播放整个歌单" : "立即播放",
      on: { click: () => this._playTrackPrimary(track, context) },
    }, [this._renderCover(track?.cover_art, track?.album || label), copy, meta]);
    const action = makeElement("div", { className: "row-actions" });
    if (context !== "playlist") {
      action.append(
        button("下一首", () => this._queueCommand("queue_add", { track_ids: [String(track.id)], position: "next" }), { className: "row-button" }),
        button("加入", () => this._queueCommand("queue_add", { track_ids: [String(track.id)], position: "last" }), { className: "row-button" }),
      );
    }
    action.append(button("详情", () => this._showDetail(track), { className: "row-button" }));
    row.append(primary, action);
    return row;
  }

  _renderPlaylists() {
    const section = makeElement("div", { className: "library-content" });
    section.append(this._searchBar(this.playlistQuery, "搜索歌单", (event) => {
      this.playlistQuery = event.currentTarget.value;
      this.playlistOffset = 0;
      this._loadPlaylists();
    }));
    const grid = makeElement("div", { className: "playlist-grid" });
    if (!this.playlists.length) grid.append(makeElement("p", { className: "empty", text: "没有找到歌单。" }));
    for (const playlist of this.playlists) {
      const name = voiceSafeText(playlist?.name, "未命名歌单");
      const coverLink = makeElement("button", {
        type: "button",
        className: "playlist-cover-button",
        label: `浏览歌单 ${name}`,
        title: "浏览歌单曲目",
        dataset: { focusKey: `playlist-cover:${String(playlist?.id || "")}` },
        on: { click: () => this._openPlaylist(playlist) },
      }, [this._renderCover(playlist?.cover_art, name, "playlist-cover")]);
      const card = makeElement("article", { className: "playlist-card" }, [
        coverLink,
        makeElement("strong", { text: name }),
        makeElement("span", { text: `${Number(playlist?.song_count) || 0} 首 · ${voiceSafeText(playlist?.owner, "我的歌单")}` }),
        button("浏览曲目", () => this._openPlaylist(playlist), { className: "secondary card-button" }),
      ]);
      grid.append(card);
    }
    section.append(grid, this._pager(this.playlistOffset, this.playlistTotal, (offset) => { this.playlistOffset = offset; this._loadPlaylists(); }));
    return section;
  }

  _renderPlaylistTracks() {
    const section = makeElement("div", { className: "library-content" });
    const title = voiceSafeText(this.selectedPlaylist?.name, "歌单");
    section.append(makeElement("div", { className: "subheading" }, [
      button("返回歌单", () => this._closePlaylist(), { className: "back", dataset: { focusKey: "playlist-back" } }),
      makeElement("h2", { text: title }),
      button("播放全部", () => this._queueCommand("queue_playlist", { playlist_id: String(this.selectedPlaylist.id), position: "replace" }), { className: "primary" }),
      button("下一首播放", () => this._queueCommand("queue_playlist", { playlist_id: String(this.selectedPlaylist.id), position: "next" }), { className: "secondary" }),
      button("加入队列", () => this._queueCommand("queue_playlist", { playlist_id: String(this.selectedPlaylist.id), position: "last" }), { className: "secondary" }),
    ]));
    const list = makeElement("div", { className: "track-list" });
    if (!this.playlistTracks.length) list.append(makeElement("p", { className: "empty", text: "歌单中没有曲目。" }));
    for (const track of this.playlistTracks) list.append(this._renderTrack(track, "playlist"));
    section.append(list, this._pager(this.playlistTrackOffset, this.playlistTrackTotal, (offset) => { this.playlistTrackOffset = offset; this._loadPlaylistTracks(); }));
    return section;
  }

  _pager(offset, total, setOffset) {
    const current = Math.floor(offset / PAGE_SIZE) + 1;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    return makeElement("nav", { className: "pager", label: "分页" }, [
      button("上一页", () => setOffset(Math.max(0, offset - PAGE_SIZE)), { className: "secondary", disabled: offset <= 0 }),
      makeElement("span", { text: `${current} / ${pages}` }),
      button("下一页", () => setOffset(offset + PAGE_SIZE), { className: "secondary", disabled: offset + PAGE_SIZE >= total }),
    ]);
  }

  _renderQueue() {
    const pane = makeElement("aside", { className: "queue-pane", label: "播放队列" });
    const active = this.queue.state === "playing" || this.queue.state === "loading";
    const current = this.queue.current || this.queue.items?.[this.queue.current_index];
    const player = this.queue.player || {};
    const mode = playbackMode(this.queue);
    const modes = {
      sequence: { icon: "sequence", label: "顺序循环" },
      shuffle: { icon: "shuffle", label: "随机播放" },
      one: { icon: "one", label: "单曲循环" },
    };
    const modeInfo = modes[mode];
    const controls = makeElement("div", { className: "transport" }, [
      iconButton("previous", "上一首", () => this._queueCommand("queue_control", { action: "previous" }), {
        className: "transport-button icon-button",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "player-previous" },
      }),
      iconButton(active ? "pause" : "play", active ? "暂停" : "播放", () => this._queueCommand("queue_control", { action: active ? "stop" : "play" }), {
        className: "transport-main icon-button",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "player-toggle" },
      }),
      iconButton("next", "下一首", () => this._queueCommand("queue_control", { action: "next" }), {
        className: "transport-button icon-button",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "player-next" },
      }),
      iconButton(modeInfo.icon, `播放模式：${modeInfo.label}`, () => this._queueCommand("queue_options", nextPlaybackMode(mode)), {
        className: "mode-button icon-button",
        dataset: { mode, focusKey: "player-mode" },
      }),
    ]);
    const disc = makeElement("div", { className: `disc ${active ? "disc-spinning" : ""}` }, [
      this._renderCover(current?.cover_art, current?.album || current?.title || "音乐", "disc-cover"),
      makeElement("span", { className: "disc-hole" }),
    ]);
    const stage = makeElement("div", { className: "player-stage" }, [
      disc,
      makeElement("div", { className: "player-copy" }, [
        makeElement("span", { className: "player-state", text: this._playerStateText() }),
        makeElement("strong", { text: voiceSafeText(current?.title, "选择一首音乐") }),
        makeElement("span", { text: current ? voiceSafeText(current?.artist, "未知艺术家") : "从曲库或歌单开始播放" }),
      ]),
    ]);
    const progress = this._renderProgress(player, current);
    const volume = this._renderVolume(player);
    const playerCard = makeElement("section", { className: "player-card", label: "音乐控制" }, [stage, progress, controls, volume]);
    const heading = makeElement("div", { className: "queue-heading" }, [
      makeElement("div", {}, [makeElement("h2", { text: "播放队列" }), makeElement("span", { text: `${this.queue.items?.length || 0} 首` })]),
      iconButton("trash", "清空队列", () => this._queueCommand("queue_control", { action: "clear" }), {
        className: "danger icon-button queue-clear",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "queue-clear" },
      }),
    ]);
    const playerSelector = this._renderPlayerSelector();
    const list = makeElement("ol", { className: "queue-list" });
    if (!this.queue.items?.length) list.append(makeElement("li", { className: "empty", text: "队列为空。选择曲目即可开始播放。" }));
    this.queue.items?.forEach((track, index) => {
      const current = index === this.queue.current_index;
      const row = makeElement("li", { className: `queue-row ${current ? "current" : ""}` }, [
        makeElement("span", { className: "queue-index", text: current ? "▶" : index + 1 }),
        this._renderCover(track?.cover_art, track?.album || track?.title, "queue-cover"),
        makeElement("button", { type: "button", className: "queue-track", label: `播放 ${voiceSafeText(track?.title, "曲目")}`, on: { click: () => this._queueCommand("queue_control", { action: "jump", index }) } }, [
          makeElement("strong", { text: voiceSafeText(track?.title, "未命名曲目") }),
          makeElement("span", { text: voiceSafeText(track?.artist, "未知艺术家") }),
        ]),
        makeElement("span", { className: "duration", text: formatDuration(track?.duration) }),
      ]);
      list.append(row);
    });
    pane.append(playerCard, playerSelector, heading, list);
    return pane;
  }

  _playerStateText() {
    if (this.queue.state === "loading") return "正在加载";
    if (this.queue.state === "playing") return "正在播放";
    if (this.queue.state === "error") return "播放失败";
    if (this.queue.player?.state === "paused") return "已暂停";
    return "准备播放";
  }

  _displayPosition() {
    const duration = Math.max(0, Number(this.queue.duration || this.queue.player?.duration) || 0);
    if (this._seekPreview !== null) return Math.min(duration || this._seekPreview, this._seekPreview);
    let position = Math.max(0, Number(this.queue.position || this.queue.player?.position) || 0);
    if (this.queue.state === "playing") position += Math.max(0, Date.now() - this._queueReceivedAt) / 1000;
    return duration ? Math.min(position, duration) : position;
  }

  _renderProgress(player, current) {
    const duration = Math.max(0, Number(this.queue.duration || player?.duration || current?.duration) || 0);
    const position = this._displayPosition();
    const canSeek = Boolean(player?.supports_seek && current && duration > 0);
    const range = makeElement("input", {
      type: "range",
      className: "progress-range",
      label: "播放进度",
      min: 0,
      max: Math.max(1, Math.floor(duration)),
      step: 1,
      value: Math.min(position, duration || position),
      disabled: !canSeek,
      dataset: { focusKey: "player-progress" },
      on: {
        input: (event) => {
          this._seekPreview = Number(event.currentTarget.value);
          const elapsed = event.currentTarget.parentElement?.querySelector(".progress-elapsed");
          if (elapsed) elapsed.textContent = formatDuration(this._seekPreview);
        },
        change: (event) => {
          const target = Number(event.currentTarget.value);
          this._seekPreview = null;
          this._queueCommand("player_control", { action: "seek", position: target });
        },
        blur: () => { this._seekPreview = null; },
      },
    });
    return makeElement("div", { className: "progress-control" }, [
      range,
      makeElement("div", { className: "progress-times" }, [
        makeElement("span", { className: "progress-elapsed", text: formatDuration(position) }),
        makeElement("span", { text: formatDuration(duration) }),
      ]),
    ]);
  }

  _renderVolume(player) {
    const canSet = Boolean(player?.supports_volume_set);
    const canMute = Boolean(player?.supports_volume_mute);
    const muted = Boolean(player?.is_volume_muted);
    const volume = Math.round(Math.max(0, Math.min(1, Number(player?.volume_level) || 0)) * 100);
    const range = makeElement("input", {
      type: "range",
      className: "volume-range",
      label: "音量",
      min: 0,
      max: 100,
      step: 1,
      value: volume,
      disabled: !canSet,
      dataset: { focusKey: "player-volume" },
      on: {
        input: (event) => {
          const value = event.currentTarget.parentElement?.querySelector(".volume-value");
          if (value) value.textContent = `${event.currentTarget.value}%`;
        },
        change: (event) => this._queueCommand("player_control", {
          action: "volume_set",
          volume_level: Number(event.currentTarget.value) / 100,
        }),
      },
    });
    return makeElement("div", { className: "volume-control" }, [
      iconButton(muted ? "muted" : "volume", muted ? "取消静音" : "静音", () => this._queueCommand("player_control", {
        action: "volume_mute",
        is_volume_muted: !muted,
      }), { className: "volume-button icon-button", disabled: !canMute, pressed: muted, dataset: { focusKey: "player-mute" } }),
      range,
      makeElement("span", { className: "volume-value", text: canSet ? `${volume}%` : "--" }),
    ]);
  }

  _syncProgressTimer() {
    const shouldRun = this._connected && this.queue.state === "playing" && this._displayPosition() >= 0;
    if (!shouldRun && this._progressTimer) {
      clearInterval(this._progressTimer);
      this._progressTimer = null;
      return;
    }
    if (!shouldRun || this._progressTimer) return;
    this._progressTimer = setInterval(() => {
      const range = this.shadowRoot?.querySelector(".progress-range");
      if (!range || this._seekPreview !== null) return;
      const position = this._displayPosition();
      range.value = String(Math.min(Number(range.max) || position, position));
      const elapsed = this.shadowRoot?.querySelector(".progress-elapsed");
      if (elapsed) elapsed.textContent = formatDuration(position);
    }, 1000);
  }

  _renderPlayerSelector() {
    const select = makeElement("select", { className: "player-select", label: "播放设备", dataset: { focusKey: "player-select" }, on: { change: (event) => {
      const entityId = event.currentTarget.value;
      if (entityId) this._queueCommand("queue_player", { entity_id: entityId });
    } } });
    select.append(makeElement("option", { value: "", text: "选择播放设备", selected: !this.queue.media_player }));
    for (const player of this.players) {
      const entityId = String(player?.entity_id || player?.id || "");
      if (!entityId) continue;
      const label = voiceSafeText(player?.name || player?.friendly_name || entityId);
      select.append(makeElement("option", { value: entityId, text: label, selected: entityId === this.queue.media_player }));
    }
    return makeElement("label", { className: "player-label", text: "播放设备" }, [select]);
  }

  _renderDetail() {
    const track = this.detail;
    const dialog = makeElement("section", { className: "detail-backdrop", role: "dialog", label: "曲目详情" });
    const card = makeElement("div", { className: "detail-card" });
    card.append(button("关闭", () => { this.detail = null; this._detailGate.cancel(); this._render(); }, { className: "detail-close" }));
    card.append(this._renderCover(track?.cover_art, track?.album || track?.title, "detail-cover"));
    card.append(makeElement("h2", { text: voiceSafeText(track?.title, "未命名曲目") }));
    card.append(makeElement("p", { className: "detail-artist", text: `${voiceSafeText(track?.artist, "未知艺术家")} · ${voiceSafeText(track?.album, "未知专辑")}` }));
    if (track?.loading) card.append(makeElement("p", { className: "loading", text: "正在读取详情…" }));
    const details = [
      ["时长", track?.duration ? formatDuration(track.duration) : ""],
      ["流派", track?.genre],
      ["年份", track?.year],
      ["曲目", track?.track_number],
      ["唱片", track?.disc_number],
      ["格式", track?.suffix || track?.content_type],
      ["码率", track?.bit_rate ? `${track.bit_rate} kbps` : ""],
      ["文件大小", track?.size ? `${Math.round(Number(track.size) / 1024 / 1024 * 10) / 10} MB` : ""],
    ].filter(([, value]) => value !== "" && value !== null && value !== undefined);
    const definition = makeElement("dl", { className: "detail-list" });
    for (const [term, value] of details) definition.append(makeElement("dt", { text: term }), makeElement("dd", { text: value }));
    card.append(definition);
    dialog.append(card);
    return dialog;
  }

  _playTrackPrimary(track, context) {
    const action = trackPrimaryCommand(context, track?.id, this.selectedPlaylist?.id);
    if (action) this._queueCommand(action.command, action.fields);
  }

  async _syncLibrary() {
    if (this.syncing) return;
    this.syncing = true;
    this._render();
    try {
      const index = await this._call("sync_library");
      this.config = { ...this.config, index };
      this._setNotice("曲库同步已完成。");
      await Promise.all([this._loadTracks(), this._loadPlaylists()]);
    } catch (_) {
      this._setNotice("无法启动曲库同步。", true);
    } finally {
      this.syncing = false;
      this._render();
    }
  }
}

if (globalThis.customElements && globalThis.document && !customElements.get("xiaoai-navidrome-panel")) {
  customElements.define("xiaoai-navidrome-panel", XiaoAINavidromePanel);
}

export { XiaoAINavidromePanel, CoverStore };
