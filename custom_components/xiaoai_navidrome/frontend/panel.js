/* XiaoAI Navidrome native Home Assistant panel. No build step or third-party runtime. */

const WS_PREFIX = "xiaoai_navidrome/";
const PAGE_SIZE = 30;
const COVER_CACHE_ITEMS = 640;
const COVER_CACHE_BYTES = 32 * 1024 * 1024;
const COVER_CONCURRENCY = 6;
const COVER_DPR_LIMIT = 1.5;
const COVER_SIZE_BUCKETS = Object.freeze([64, 96, 128, 160, 192, 256, 320, 384]);
const VOLUME_CONFIRM_TIMEOUT = 10000;
const STATIC_VERSION = new URL(import.meta.url).search;
let stylesheetPromise;
const EVENT_LISTENERS = Symbol("xiaoaiEventListeners");
export const PANEL_TEXT = Object.freeze({
  en: Object.freeze({
    defaultTitle: "XiaoAI Music",
    connecting: "Connecting",
    waitingForHass: "Waiting for Home Assistant",
    missingEntry: "Panel configuration is missing entry_id",
    navidromeDisconnected: "Navidrome disconnected",
    connected: "Connected",
    unavailable: "Connection unavailable",
    syncing: "Syncing",
    connectFailed: "Unable to connect to the integration. Check its configuration.",
    liveQueueUnavailable: "Live queue updates are unavailable.",
    queueLoadFailed: "Unable to load the playback queue.",
    libraryLoadFailed: "Unable to load the library.",
    playlistsLoadFailed: "Unable to load playlists.",
    playlistTracksLoadFailed: "Unable to load playlist tracks.",
    trackDetailsLoadFailed: "Unable to load track details.",
    queueConflict: "The queue changed elsewhere. The latest state has been loaded.",
    operationFailed: "The operation did not complete.",
    music: "Music",
    coverLabel: "{name} cover",
    musicCover: "Music cover",
    close: "Close",
    openSidebar: "Open Home Assistant sidebar",
    syncLibrary: "Sync library",
    themeAuto: "Follow theme",
    themeLight: "Light theme",
    themeDark: "Dark theme",
    libraryBrowse: "Browse library",
    playlists: "Playlists",
    tracks: "Tracks",
    searchTracks: "Search tracks, artists, or albums",
    noTracks: "No tracks found.",
    untitledTrack: "Untitled track",
    unknownArtist: "Unknown artist",
    unknownAlbum: "Unknown album",
    playPlaylistFrom: "Play playlist starting with {name}",
    playTrack: "Play {name}",
    playPlaylistFromHint: "Play the full playlist starting with this track",
    playNow: "Play now",
    playNext: "Play next",
    addToQueue: "Add",
    details: "Details",
    searchPlaylists: "Search playlists",
    noPlaylists: "No playlists found.",
    untitledPlaylist: "Untitled playlist",
    myPlaylist: "My playlist",
    trackCount: "{count} tracks",
    browsePlaylist: "Browse playlist {name}",
    browsePlaylistTracks: "Browse playlist tracks",
    playlist: "Playlist",
    backToPlaylists: "Back to playlists",
    emptyPlaylist: "This playlist has no tracks.",
    pagination: "Pagination",
    previousPage: "Previous page",
    nextPage: "Next page",
    playbackQueue: "Playback queue",
    sequenceMode: "Sequence repeat",
    shuffleMode: "Shuffle",
    repeatOneMode: "Repeat one",
    previousTrack: "Previous track",
    pause: "Pause",
    play: "Play",
    nextTrack: "Next track",
    playbackMode: "Playback mode: {mode}",
    chooseMusic: "Choose music",
    startFromLibrary: "Start playback from the library or a playlist",
    musicControls: "Music controls",
    clearQueue: "Clear queue",
    emptyQueue: "The queue is empty. Select a track to start playback.",
    loading: "Loading",
    playing: "Playing",
    playbackFailed: "Playback failed",
    paused: "Paused",
    ready: "Ready",
    progress: "Playback progress",
    progressUnsupported: "Playback progress; the selected player does not support seeking",
    seekHint: "Seek within the track",
    seekUnsupported: "The selected player does not support seeking",
    volume: "Volume",
    unmute: "Unmute",
    mute: "Mute",
    player: "Playback device",
    choosePlayer: "Select a playback device",
    trackDetails: "Track details",
    loadingDetails: "Loading details…",
    duration: "Duration",
    genre: "Genre",
    year: "Year",
    trackNumber: "Track",
    discNumber: "Disc",
    format: "Format",
    bitrate: "Bitrate",
    fileSize: "File size",
    syncComplete: "Library sync completed.",
    syncFailed: "Unable to start library sync.",
  }),
  "zh-Hans": Object.freeze({
    defaultTitle: "小爱音乐",
    connecting: "正在连接",
    waitingForHass: "等待 Home Assistant",
    missingEntry: "面板配置缺少 entry_id",
    navidromeDisconnected: "Navidrome 未连接",
    connected: "已连接",
    unavailable: "连接不可用",
    syncing: "正在同步",
    connectFailed: "无法连接集成，请检查配置。",
    liveQueueUnavailable: "队列实时更新暂不可用。",
    queueLoadFailed: "无法读取播放队列。",
    libraryLoadFailed: "无法读取曲库。",
    playlistsLoadFailed: "无法读取歌单。",
    playlistTracksLoadFailed: "无法读取歌单曲目。",
    trackDetailsLoadFailed: "无法读取曲目详情。",
    queueConflict: "队列已在其他位置更新，已刷新最新状态。",
    operationFailed: "操作未完成。",
    music: "音乐",
    coverLabel: "{name}封面",
    musicCover: "音乐封面",
    close: "关闭",
    openSidebar: "打开 Home Assistant 侧边栏",
    syncLibrary: "同步曲库",
    themeAuto: "跟随主题",
    themeLight: "浅色主题",
    themeDark: "深色主题",
    libraryBrowse: "曲库浏览",
    playlists: "歌单",
    tracks: "曲目",
    searchTracks: "搜索曲目、艺术家或专辑",
    noTracks: "没有找到曲目。",
    untitledTrack: "未命名曲目",
    unknownArtist: "未知艺术家",
    unknownAlbum: "未知专辑",
    playPlaylistFrom: "从 {name} 开始播放歌单",
    playTrack: "播放 {name}",
    playPlaylistFromHint: "从此曲开始播放整个歌单",
    playNow: "立即播放",
    playNext: "下一首",
    addToQueue: "加入",
    details: "详情",
    searchPlaylists: "搜索歌单",
    noPlaylists: "没有找到歌单。",
    untitledPlaylist: "未命名歌单",
    myPlaylist: "我的歌单",
    trackCount: "{count} 首",
    browsePlaylist: "浏览歌单 {name}",
    browsePlaylistTracks: "浏览歌单曲目",
    playlist: "歌单",
    backToPlaylists: "返回歌单",
    emptyPlaylist: "歌单中没有曲目。",
    pagination: "分页",
    previousPage: "上一页",
    nextPage: "下一页",
    playbackQueue: "播放队列",
    sequenceMode: "顺序循环",
    shuffleMode: "随机播放",
    repeatOneMode: "单曲循环",
    previousTrack: "上一首",
    pause: "暂停",
    play: "播放",
    nextTrack: "下一首",
    playbackMode: "播放模式：{mode}",
    chooseMusic: "选择一首音乐",
    startFromLibrary: "从曲库或歌单开始播放",
    musicControls: "音乐控制",
    clearQueue: "清空队列",
    emptyQueue: "队列为空。选择曲目即可开始播放。",
    loading: "正在加载",
    playing: "正在播放",
    playbackFailed: "播放失败",
    paused: "已暂停",
    ready: "准备播放",
    progress: "播放进度",
    progressUnsupported: "播放进度，当前播放设备不支持拖动",
    seekHint: "拖动播放进度",
    seekUnsupported: "当前播放设备不支持进度跳转",
    volume: "音量",
    unmute: "取消静音",
    mute: "静音",
    player: "播放设备",
    choosePlayer: "选择播放设备",
    trackDetails: "曲目详情",
    loadingDetails: "正在读取详情…",
    duration: "时长",
    genre: "流派",
    year: "年份",
    trackNumber: "曲目",
    discNumber: "唱片",
    format: "格式",
    bitrate: "码率",
    fileSize: "文件大小",
    syncComplete: "曲库同步已完成。",
    syncFailed: "无法启动曲库同步。",
  }),
});

export function normalizePanelLanguage(value) {
  return value === "zh-Hans" ? "zh-Hans" : "en";
}

export function panelText(language, key, values = {}) {
  const template = PANEL_TEXT[normalizePanelLanguage(language)][key] || PANEL_TEXT.en[key] || key;
  return Object.entries(values).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    template,
  );
}
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

/** Return a clamped percentage for a custom range-track fill. */
export function rangeFillPercent(value, maximum) {
  const max = Math.max(0, Number(maximum) || 0);
  if (!max) return 0;
  return Math.max(0, Math.min(100, ((Number(value) || 0) / max) * 100));
}

/** Keep an optimistic volume until HA confirms it or the bounded wait expires. */
export function reconcilePendingVolume(pending, reported, now = Date.now()) {
  if (!pending || now >= Number(pending.expiresAt || 0)) return null;
  const actual = reported === null || reported === undefined ? NaN : Number(reported);
  if (Number.isFinite(actual) && Math.abs(actual - Number(pending.value)) <= 0.005) return null;
  return pending;
}

function updateRangeFill(range) {
  range.style.setProperty("--range-progress", `${rangeFillPercent(range.value, range.max)}%`);
}

/** Select a bounded density-aware transfer size for one visual cover context. */
export function coverPixelSize(className = "", devicePixelRatio = globalThis.devicePixelRatio || 1) {
  const cssPixels = ({
    "disc-cover": 96,
    "detail-cover": 144,
    "playlist-cover": 240,
  })[className] || 48;
  const density = Math.max(1, Math.min(COVER_DPR_LIMIT, Number(devicePixelRatio) || 1));
  const required = cssPixels * density;
  return COVER_SIZE_BUCKETS.find((size) => size >= required)
    || COVER_SIZE_BUCKETS[COVER_SIZE_BUCKETS.length - 1];
}

/** Return the relative authenticated Home Assistant cover endpoint. */
export function coverApiPath(entryId, coverId, size = COVER_SIZE_BUCKETS[0]) {
  return `/api/xiaoai_navidrome/cover/${encodeURIComponent(String(entryId))}/${encodeURIComponent(String(coverId))}?size=${encodeURIComponent(String(size))}`;
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
export function trackPrimaryCommand(context, trackId, playlistId = "", playlistIndex = -1) {
  const id = String(trackId || "");
  if (!id) return null;
  if (context === "playlist") {
    const listId = String(playlistId || "");
    const itemIndex = Number(playlistIndex);
    if (!listId || !Number.isInteger(itemIndex) || itemIndex < 0) return null;
    return {
      command: "queue_playlist",
      fields: {
        playlist_id: listId,
        position: "replace",
        start_track_id: id,
        start_index: itemIndex,
      },
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
    node[EVENT_LISTENERS] = options.on;
    for (const [event, listener] of Object.entries(options.on)) node.addEventListener(event, listener);
  }
  node.append(...children.filter(Boolean));
  return node;
}

function syncEventListeners(current, replacement) {
  for (const [event, listener] of Object.entries(current[EVENT_LISTENERS] || {})) {
    current.removeEventListener(event, listener);
  }
  const listeners = replacement[EVENT_LISTENERS] || {};
  for (const [event, listener] of Object.entries(listeners)) {
    current.addEventListener(event, listener);
  }
  current[EVENT_LISTENERS] = listeners;
}

function syncAttributes(current, replacement) {
  const preserveEditingRange = current.localName === "input"
    && current.type === "range"
    && current.dataset.localEditing === "true"
    && !replacement.disabled;
  for (const attribute of [...current.attributes]) {
    if (preserveEditingRange && ["style", "data-local-editing"].includes(attribute.name)) continue;
    if (!replacement.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
  }
  for (const attribute of [...replacement.attributes]) {
    if (preserveEditingRange && attribute.name === "style") continue;
    if (current.getAttribute(attribute.name) !== attribute.value) {
      current.setAttribute(attribute.name, attribute.value);
    }
  }
}

function syncControlState(current, replacement) {
  const tag = current.localName;
  if (tag === "input") {
    if (replacement.disabled) delete current.dataset.localEditing;
    current.disabled = replacement.disabled;
    current.checked = replacement.checked;
    current.min = replacement.min;
    current.max = replacement.max;
    current.step = replacement.step;
    if (current.dataset.localEditing !== "true") current.value = replacement.value;
  } else if (tag === "button") {
    current.disabled = replacement.disabled;
  } else if (tag === "option") {
    current.selected = replacement.selected;
  }
}

/** Update one detached render tree into the live tree without replacing stable nodes. */
export function patchElement(current, replacement) {
  if (
    current.nodeType !== replacement.nodeType
    || (current.nodeType === Node.ELEMENT_NODE && current.localName !== replacement.localName)
  ) {
    current.replaceWith(replacement);
    return replacement;
  }
  if (current.nodeType === Node.TEXT_NODE) {
    if (current.nodeValue !== replacement.nodeValue) current.nodeValue = replacement.nodeValue;
    return current;
  }

  const currentCoverKey = current.dataset?.coverKey || "";
  const replacementCoverKey = replacement.dataset?.coverKey || "";
  if ((currentCoverKey || replacementCoverKey) && currentCoverKey !== replacementCoverKey) {
    current.replaceWith(replacement);
    return replacement;
  }
  const sameCover = current.dataset?.coverKey
    && current.dataset.coverKey === replacement.dataset?.coverKey;
  const currentImage = sameCover ? current.querySelector(":scope > img") : null;
  const replacementImage = sameCover ? replacement.querySelector(":scope > img") : null;
  if (currentImage && !replacementImage) replacement.classList.remove("cover-placeholder");
  syncAttributes(current, replacement);
  syncEventListeners(current, replacement);
  syncControlState(current, replacement);
  if (currentImage && !replacementImage) {
    currentImage.alt = replacement.dataset.coverLabel || currentImage.alt;
    return current;
  }

  const currentChildren = [...current.childNodes];
  const replacementChildren = [...replacement.childNodes];
  const shared = Math.min(currentChildren.length, replacementChildren.length);
  for (let index = 0; index < shared; index += 1) {
    patchElement(currentChildren[index], replacementChildren[index]);
  }
  for (let index = shared; index < replacementChildren.length; index += 1) {
    current.append(replacementChildren[index]);
  }
  for (let index = currentChildren.length - 1; index >= replacementChildren.length; index -= 1) {
    currentChildren[index].remove();
  }
  if (current.localName === "select") current.value = replacement.value;
  return current;
}

// Material Design Icons 7.4.47 (Apache-2.0):
// https://github.com/Templarian/MaterialDesign-JS
const ICON_PATHS = Object.freeze({
  menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
  previous: "M6,18V6H8V18H6M9.5,12L18,6V18L9.5,12Z",
  next: "M16,18H18V6H16M6,18L14.5,12L6,6V18Z",
  play: "M8,5.14V19.14L19,12.14L8,5.14Z",
  pause: "M14,19H18V5H14M6,19H10V5H6V19Z",
  sequence: "M17,17H7V14L3,18L7,22V19H19V13H17M7,7H17V10L21,6L17,2V5H5V11H7V7Z",
  shuffle: "M17,3L22.25,7.5L17,12L22.25,16.5L17,21V18H14.26L11.44,15.18L13.56,13.06L15.5,15H17V12L17,9H15.5L6.5,18H2V15H5.26L14.26,6H17V3M2,6H6.5L9.32,8.82L7.2,10.94L5.26,9H2V6Z",
  one: "M13,15V9H12L10,10V11H11.5V15M17,17H7V14L3,18L7,22V19H19V13H17M7,7H17V10L21,6L17,2V5H5V11H7V7Z",
  volume: "M14,3.23V5.29C16.89,6.15 19,8.83 19,12C19,15.17 16.89,17.84 14,18.7V20.77C18,19.86 21,16.28 21,12C21,7.72 18,4.14 14,3.23M16.5,12C16.5,10.23 15.5,8.71 14,7.97V16C15.5,15.29 16.5,13.76 16.5,12M3,9V15H7L12,20V4L7,9H3Z",
  muted: "M12,4L9.91,6.09L12,8.18M4.27,3L3,4.27L7.73,9H3V15H7L12,20V13.27L16.25,17.53C15.58,18.04 14.83,18.46 14,18.7V20.77C15.38,20.45 16.63,19.82 17.68,18.96L19.73,21L21,19.73L12,10.73M19,12C19,12.94 18.8,13.82 18.46,14.64L19.97,16.15C20.62,14.91 21,13.5 21,12C21,7.72 18,4.14 14,3.23V5.29C16.89,6.15 19,8.83 19,12M16.5,12C16.5,10.23 15.5,8.71 14,7.97V10.18L16.45,12.63C16.5,12.43 16.5,12.21 16.5,12Z",
  trash: "M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19M8,9H16V19H8V9M15.5,4L14.5,3H9.5L8.5,4H5V6H19V4H15.5Z",
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

  bind(owner) {
    if (!this.closed) this.owner = owner;
    return this;
  }

  release(owner) {
    if (this.owner === owner) this.owner = null;
  }

  peek(coverId, pixelSize = COVER_SIZE_BUCKETS[0]) {
    const id = String(coverId || "");
    const key = id ? `${pixelSize}:${id}` : "";
    const existing = key && !this.closed ? this.entries.get(key) : null;
    if (!existing) return null;
    this.entries.delete(key);
    this.entries.set(key, existing);
    return existing.url || null;
  }

  get(coverId, pixelSize = COVER_SIZE_BUCKETS[0]) {
    const id = String(coverId || "");
    if (!id || this.closed) return Promise.resolve(null);
    const key = `${pixelSize}:${id}`;
    const existing = this.entries.get(key);
    if (existing) {
      this.entries.delete(key);
      this.entries.set(key, existing);
      return Promise.resolve(existing.url);
    }
    if (this.pending.has(key)) return this.pending.get(key);
    const entryId = String(this.owner?.entryId || "");
    const fetchWithAuth = this.owner?.hass?.fetchWithAuth?.bind(this.owner.hass);
    const promise = new Promise((resolve) => {
      this.jobs.push({ id, key, pixelSize, entryId, fetchWithAuth, resolve });
      this._drain();
    });
    this.pending.set(key, promise);
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
          this.pending.delete(job.key);
          this._drain();
        });
    }
  }

  async _load(job) {
    let url = null;
    let size = 0;
    try {
      if (!job.entryId || this.closed || !job.fetchWithAuth) {
        job.resolve(null);
        return;
      }
      const path = coverApiPath(job.entryId, job.id, job.pixelSize);
      const response = await job.fetchWithAuth(path);
      if (response.status === 404) {
        this._remember(job.key, null, 0);
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
      this._remember(job.key, url, size);
      job.resolve(url);
    } catch (error) {
      if (url) URL.revokeObjectURL(url);
      throw error;
    }
  }

  _remember(key, url, size) {
    const prior = this.entries.get(key);
    if (prior) {
      this.entries.delete(key);
      this.bytes -= prior.size;
      if (prior.url) URL.revokeObjectURL(prior.url);
    }
    this.entries.set(key, { url, size });
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

const sharedCoverStores = new Map();

export function sharedCoverStore(owner) {
  const entryId = String(owner?.entryId || "");
  if (!entryId) return new CoverStore(owner);
  let store = sharedCoverStores.get(entryId);
  if (!store || store.closed) {
    store = new CoverStore(owner);
    sharedCoverStores.set(entryId, store);
  }
  return store.bind(owner);
}

export function clearSharedCoverStores() {
  for (const store of sharedCoverStores.values()) store.clear();
  sharedCoverStores.clear();
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
    this.language = "en";
    this.panelTitle = this._t("defaultTitle");
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
    this.libraryTab = "playlists";
    this._connectionStateKey = "connecting";
    this.connectionState = this._t(this._connectionStateKey);
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
    this._connectionController = new AbortController();
    this._queueEpoch = 0;
    this._queueReceivedAt = Date.now();
    this._progressTimer = null;
    this._seekPreview = null;
    this._pendingVolume = null;
    this._volumeConfirmTimer = null;
    this._initializedEntry = "";
    this._initializing = false;
    this._initializationSerial = 0;
    this._initializationPromise = null;
    this._covers = new CoverStore(this);
    this._render();
  }

  set hass(value) {
    this._hass = value;
    this.toggleAttribute("kiosk", Boolean(value?.kioskMode));
    if (this._connected && this._initializedEntry !== this.entryId) this._start();
  }

  get hass() {
    return this._hass;
  }

  set panel(value) {
    this._panel = value;
    const config = value?.config || value || {};
    const nextEntry = String(config.entry_id || "");
    const nextLanguage = normalizePanelLanguage(config.language);
    const languageChanged = nextLanguage !== this.language;
    this.language = nextLanguage;
    if (languageChanged && this._connectionStateKey) {
      this.connectionState = this._t(this._connectionStateKey);
    }
    const nextTitle = voiceSafeText(config.title, this._t("defaultTitle"));
    const titleChanged = nextTitle !== this.panelTitle;
    this.panelTitle = nextTitle;
    if (nextEntry !== this.entryId) {
      this.entryId = nextEntry;
      this._initializedEntry = "";
      this._initGate.cancel();
      this._tracksGate.cancel();
      this._playlistsGate.cancel();
      this._playlistTracksGate.cancel();
      this._detailGate.cancel();
      this._initializationSerial += 1;
      this._initializing = false;
      this._initializationPromise = null;
      this._connectionController.abort();
      this._connectionController = new AbortController();
      this._commandChain = Promise.resolve();
      this.queue = { items: [], current_index: -1, revision: 0, state: "stopped", repeat: "all", shuffle: false };
      this._queueEpoch += 1;
      this._queueReceivedAt = Date.now();
      this._seekPreview = null;
      if (this._progressTimer) clearInterval(this._progressTimer);
      this._progressTimer = null;
      this.config = {};
      this.players = [];
      this.tracks = [];
      this.trackTotal = 0;
      this.trackOffset = 0;
      this.playlists = [];
      this.playlistTotal = 0;
      this.playlistOffset = 0;
      this.selectedPlaylist = null;
      this.playlistTracks = [];
      this.playlistTrackTotal = 0;
      this.playlistTrackOffset = 0;
      this._playlistReturnFocusKey = "";
      this.libraryTab = "playlists";
      this.detail = null;
      this.notice = "";
      if (this._volumeConfirmTimer) clearTimeout(this._volumeConfirmTimer);
      this._volumeConfirmTimer = null;
      this._pendingVolume = null;
      this._covers?.release?.(this);
      this._covers = sharedCoverStore(this);
      if (this._unsubscribeQueue) this._unsubscribeQueue();
      this._unsubscribeQueue = null;
      if (this._connected) this._start();
    } else if ((titleChanged || languageChanged) && this._connected) this._render();
  }

  get panel() {
    return this._panel;
  }

  set narrow(value) {
    const next = Boolean(value);
    if (next === this._narrow) return;
    this._narrow = next;
    this.toggleAttribute("narrow", next);
    if (this.libraryTab === "playlists" && !this.selectedPlaylist) {
      this._renderLibraryOnly();
    }
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

  _t(key, values = {}) {
    return panelText(this.language, key, values);
  }

  _setConnectionState(key) {
    this._connectionStateKey = key;
    this.connectionState = this._t(key);
  }

  connectedCallback() {
    this._connected = true;
    if (this._connectionController.signal.aborted) {
      this._connectionController = new AbortController();
    }
    if (this.entryId) this._covers = sharedCoverStore(this);
    else if (this._covers.closed) this._covers = new CoverStore(this);
    this._loadStyles();
    this._start();
  }

  disconnectedCallback() {
    this._connected = false;
    this._initializedEntry = "";
    this._initializationSerial += 1;
    this._initializing = false;
    this._initializationPromise = null;
    this._connectionController.abort();
    this._commandChain = Promise.resolve();
    this._initGate.cancel();
    this._tracksGate.cancel();
    this._playlistsGate.cancel();
    this._playlistTracksGate.cancel();
    this._detailGate.cancel();
    if (this._unsubscribeQueue) this._unsubscribeQueue();
    this._unsubscribeQueue = null;
    if (this._progressTimer) clearInterval(this._progressTimer);
    this._progressTimer = null;
    if (this._volumeConfirmTimer) clearTimeout(this._volumeConfirmTimer);
    this._volumeConfirmTimer = null;
    this._pendingVolume = null;
    this._covers?.release?.(this);
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
    if (!this._connected) return Promise.resolve(false);
    if (!this.hass) {
      this._setConnectionState("waitingForHass");
      this._render();
      return Promise.resolve(false);
    }
    if (!this.entryId) {
      this._setConnectionState("missingEntry");
      this._render();
      return Promise.resolve(false);
    }
    if (this._initializedEntry === this.entryId) return Promise.resolve(true);
    if (this._initializing && this._initializationPromise) return this._initializationPromise;
    const serial = ++this._initializationSerial;
    const promise = this._initialize(serial, this.entryId);
    this._initializationPromise = promise;
    return promise;
  }

  async _initialize(serial, initializingEntry) {
    this._initializing = true;
    const gate = this._initGate.begin();
    this._setConnectionState("connecting");
    this._render();
    this._subscribeQueue();
    try {
      const queueEpoch = this._queueEpoch;
      const [config, players, queueResponse] = await Promise.all([
        this._call("config", {}, gate.signal),
        this._call("media_players", {}, gate.signal),
        this._call("queue", {}, gate.signal),
      ]);
      if (!gate.isCurrent() || !this._connected || initializingEntry !== this.entryId) return false;
      this.config = config || {};
      this.players = responseItems(players);
      const queue = queueStatus(queueResponse);
      if (queue?.items && queueEpoch === this._queueEpoch) this._applyQueue(queue);
      this._setConnectionState(
        this.config.connected === false ? "navidromeDisconnected" : "connected",
      );
      this.syncing = Boolean(this.config.index?.syncing);
      this._initializedEntry = this.entryId;
      this._render();
      void Promise.allSettled([this._loadTracks(), this._loadPlaylists()]);
      return true;
    } catch (error) {
      if (!isAbort(error) && gate.isCurrent()) {
        this._setConnectionState("unavailable");
        this._setNotice("connectFailed", true);
      }
      return false;
    } finally {
      if (serial === this._initializationSerial) {
        this._initializing = false;
        this._initializationPromise = null;
      }
    }
  }

  async _subscribeQueue() {
    if (this._unsubscribeQueue || !this.hass?.connection || !this.entryId) return;
    const subscribedEntry = this.entryId;
    const connectionSignal = this._connectionController.signal;
    try {
      const unsubscribe = await this.hass.connection.subscribeMessage(
        (event) => {
          const status = queueStatus(event);
          if (status?.items && this._connected && subscribedEntry === this.entryId) this._applyQueue(status);
        },
        { type: `${WS_PREFIX}subscribe_queue`, entry_id: subscribedEntry },
      );
      if (typeof unsubscribe === "function") {
        if (
          this._connected
          && !connectionSignal.aborted
          && subscribedEntry === this.entryId
          && !this._unsubscribeQueue
        ) {
          this._unsubscribeQueue = unsubscribe;
        } else {
          unsubscribe();
        }
      }
    } catch (_) {
      if (this._connected && !connectionSignal.aborted && subscribedEntry === this.entryId) {
        this._setNotice("liveQueueUnavailable", true);
      }
    }
  }

  _call(command, fields = {}, signal) {
    if (!this.hass?.callWS) return Promise.reject(new Error("Home Assistant WebSocket unavailable"));
    const requestSignal = signal || this._connectionController.signal;
    if (requestSignal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
    const message = { type: `${WS_PREFIX}${command}`, entry_id: this.entryId, ...fields };
    return abortable(
      Promise.resolve(this.hass.callWS(message)),
      requestSignal,
    );
  }

  async _refreshQueue() {
    const before = this._queueEpoch;
    try {
      const response = await this._call("queue");
      const status = queueStatus(response);
      // A subscription event that arrived while this request was in flight is newer.
      if (status?.items && before === this._queueEpoch) this._applyQueue(status);
    } catch (error) {
      if (!isAbort(error)) this._setNotice("queueLoadFailed", true);
    }
  }

  _applyQueue(status) {
    const incomingRevision = Number(status?.revision);
    const currentRevision = Number(this.queue?.revision);
    if (Number.isFinite(incomingRevision) && Number.isFinite(currentRevision) && incomingRevision < currentRevision) return;
    const previousIndex = Number(this.queue?.current_index);
    const previousTrackId = String(
      this.queue?.current?.id || this.queue?.items?.[previousIndex]?.id || "",
    );
    const samePlayer = !status.media_player || status.media_player === this.queue.media_player;
    const reportedVolume = status.player?.volume_pending
      ? undefined
      : status.player?.volume_level;
    this._pendingVolume = samePlayer
      ? reconcilePendingVolume(this._pendingVolume, reportedVolume)
      : null;
    if (!this._pendingVolume && this._volumeConfirmTimer) {
      clearTimeout(this._volumeConfirmTimer);
      this._volumeConfirmTimer = null;
    }
    this.queue = {
      ...this.queue,
      ...status,
      items: Array.isArray(status.items) ? status.items : [],
      revision: Number.isFinite(Number(status.revision)) ? Number(status.revision) : this.queue.revision || 0,
    };
    const nextIndex = Number(this.queue.current_index);
    const nextTrackId = String(
      this.queue.current?.id || this.queue.items?.[nextIndex]?.id || "",
    );
    if (previousIndex !== nextIndex || previousTrackId !== nextTrackId) {
      this._seekPreview = null;
      const progress = this.shadowRoot?.querySelector(".progress-range");
      if (progress) delete progress.dataset.localEditing;
    }
    this._queueEpoch += 1;
    this._queueReceivedAt = Date.now();
    this._renderQueueOnly();
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
      if (!isAbort(error) && gate.isCurrent()) this._setNotice("libraryLoadFailed", true);
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
      if (!isAbort(error) && gate.isCurrent()) this._setNotice("playlistsLoadFailed", true);
    }
  }

  async _openPlaylist(playlist) {
    const playlistId = String(playlist?.id || "");
    if (!playlistId) return;
    this._playlistReturnFocusKey = `playlist-card:${playlistId}`;
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
      if (!isAbort(error) && gate.isCurrent()) this._setNotice("playlistTracksLoadFailed", true);
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
        this._setNotice("trackDetailsLoadFailed", true);
      }
    }
  }

  _queueCommand(command, fields = {}) {
    const commandEntry = this.entryId;
    const commandSignal = this._connectionController.signal;
    this._commandChain = this._commandChain
      .catch(() => undefined)
      .then(async () => {
        if (commandSignal.aborted || commandEntry !== this.entryId) return null;
        const ready = this._initializedEntry === this.entryId || await this._start();
        if (
          !ready
          || commandSignal.aborted
          || !this._connected
          || commandEntry !== this.entryId
          || this._initializedEntry !== commandEntry
        ) return null;
        const expectedRevision = Number(this.queue.revision);
        try {
          const result = await this._call(
            command,
            { ...fields, expected_revision: expectedRevision },
            commandSignal,
          );
          if (commandSignal.aborted || commandEntry !== this.entryId) return null;
          const status = queueStatus(result);
          if (status?.items) this._applyQueue(status);
          return result;
        } catch (error) {
          if (isAbort(error) || commandSignal.aborted || commandEntry !== this.entryId) return null;
          if (isConflict(error)) {
            this._setNotice("queueConflict", true);
            await this._refreshQueue();
            return null;
          }
          this._setNotice("operationFailed", true);
          return null;
        }
      });
    return this._commandChain;
  }

  _setNotice(key, isError = false, values = {}) {
    this.notice = { key, values, error: isError };
    this._render();
  }

  _changeTheme() {
    this.themeMode = ({ auto: "light", light: "dark", dark: "auto" })[this.themeMode];
    this._saveTheme();
    this._render();
  }

  _renderCover(coverId, label, className = "") {
    const safeLabel = voiceSafeText(label, this._t("music"));
    const holder = makeElement("span", { className: coverClassNames(className), label: this._t("coverLabel", { name: safeLabel }) }, [
      makeElement("span", { text: "♫" }),
    ]);
    holder.dataset.coverLabel = safeLabel;
    const id = String(coverId || "");
    if (!id) return holder;
    const pixelSize = coverPixelSize(className);
    const coverKey = `${pixelSize}:${id}`;
    holder.dataset.coverKey = coverKey;
    const cachedUrl = this._covers.peek(id, pixelSize);
    if (cachedUrl) {
      const image = document.createElement("img");
      image.alt = voiceSafeText(label, this._t("musicCover"));
      image.src = cachedUrl;
      image.loading = "lazy";
      image.addEventListener("error", () => image.remove());
      holder.replaceChildren(image);
      holder.classList.remove("cover-placeholder");
      return holder;
    }
    this._covers.get(id, pixelSize).then((url) => {
      if (!url || !this._connected || holder.dataset.coverKey !== coverKey || !holder.isConnected) return;
      const image = document.createElement("img");
      image.alt = voiceSafeText(label, this._t("musicCover"));
      image.src = url;
      image.loading = "lazy";
      image.addEventListener("error", () => image.remove());
      holder.replaceChildren(image);
      holder.classList.remove("cover-placeholder");
    });
    return holder;
  }

  _renderQueueOnly() {
    if (!this.shadowRoot || typeof document === "undefined") return;
    const current = this.shadowRoot.querySelector(".queue-pane");
    if (!current) {
      this._render();
      return;
    }
    const activeFocusKey = String(this.shadowRoot.activeElement?.dataset?.focusKey || "");
    const replacement = this._renderQueue();
    patchElement(current, replacement);
    this._focusByKey(activeFocusKey);
  }

  _renderLibraryOnly() {
    if (!this.shadowRoot || typeof document === "undefined") return;
    const current = this.shadowRoot.querySelector(".library-pane");
    if (!current) return;
    const activeFocusKey = String(this.shadowRoot.activeElement?.dataset?.focusKey || "");
    patchElement(current, this._renderLibrary());
    this._focusByKey(activeFocusKey);
  }

  _render() {
    if (!this.shadowRoot || typeof document === "undefined") return;
    const activeFocusKey = String(this.shadowRoot.activeElement?.dataset?.focusKey || "");
    const app = makeElement("main", { className: "panel", dataset: { theme: this.themeMode } });
    app.append(this._renderHeader());
    const noticeSlot = makeElement("div", { className: "notice-slot" });
    if (this.notice) {
      noticeSlot.append(makeElement("div", { className: `notice ${this.notice.error ? "notice-error" : ""}`, role: "status", text: this._t(this.notice.key, this.notice.values) }, [
        button(this._t("close"), () => { this.notice = ""; this._render(); }, { className: "notice-close" }),
      ]));
    }
    app.append(noticeSlot);
    const layout = makeElement("div", { className: "layout" });
    const library = this._renderLibrary();
    const queue = this._renderQueue();
    // Grid areas in CSS place the queue first on single-column/mobile layouts.
    layout.append(library, queue);
    app.append(layout);
    if (this.detail) app.append(this._renderDetail());
    const current = this.shadowRoot.querySelector("main.panel");
    if (current) patchElement(current, app);
    else this.shadowRoot.append(app);
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
      iconButton("menu", this._t("openSidebar"), () => this._toggleHassMenu(), {
        className: "menu-button icon-button",
        dataset: { focusKey: "hass-menu" },
      }),
      makeElement("div", { className: "brand-mark", text: "♫" }),
      makeElement("div", {}, [
        makeElement("h1", { text: this.panelTitle }),
        makeElement("p", { className: "connection", text: `${this.connectionState}${this.syncing ? ` · ${this._t("syncing")}` : ""}` }),
      ]),
    ]);
    const actions = makeElement("div", { className: "header-actions" }, [
      button(this._t("syncLibrary"), () => this._syncLibrary(), { className: "secondary", disabled: this.syncing }),
      button(this._t(this.themeMode === "auto" ? "themeAuto" : this.themeMode === "light" ? "themeLight" : "themeDark"), () => this._changeTheme(), { className: "secondary" }),
    ]);
    header.append(brand, actions);
    return header;
  }

  _toggleHassMenu() {
    this.dispatchEvent(new CustomEvent("hass-toggle-menu", {
      bubbles: true,
      composed: true,
    }));
  }

  _renderLibrary() {
    const pane = makeElement("section", { className: "library-pane", label: this._t("libraryBrowse") });
    const tabs = makeElement("div", { className: "tabs", role: "tablist", on: { keydown: (event) => this._handleLibraryTabKey(event) } }, [
      button(this._t("playlists"), () => this._selectLibraryTab("playlists"), {
        className: "tab",
        role: "tab",
        selectedState: this.libraryTab === "playlists",
        tabIndex: this.libraryTab === "playlists" ? 0 : -1,
      }),
      button(this._t("tracks"), () => this._selectLibraryTab("tracks"), {
        className: "tab",
        role: "tab",
        selectedState: this.libraryTab === "tracks",
        tabIndex: this.libraryTab === "tracks" ? 0 : -1,
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
    if (key === "Home") tab = "playlists";
    else if (key === "End") tab = "tracks";
    else tab = this.libraryTab === "tracks" ? "playlists" : "tracks";
    this._selectLibraryTab(tab);
  }

  _searchBar(value, placeholder, onInput) {
    const input = makeElement("input", { className: "search", value, placeholder, label: placeholder, on: { input: onInput } });
    return makeElement("div", { className: "search-wrap" }, [makeElement("span", { className: "search-icon", text: "⌕" }), input]);
  }

  _renderTracks() {
    const section = makeElement("div", { className: "library-content" });
    section.append(this._searchBar(this.trackQuery, this._t("searchTracks"), (event) => {
      this.trackQuery = event.currentTarget.value;
      this.trackOffset = 0;
      this._loadTracks();
    }));
    const list = makeElement("div", { className: "track-list" });
    if (!this.tracks.length) list.append(makeElement("p", { className: "empty", text: this._t("noTracks") }));
    for (const track of this.tracks) list.append(this._renderTrack(track, "library"));
    section.append(list, this._pager(this.trackOffset, this.trackTotal, (offset) => { this.trackOffset = offset; this._loadTracks(); }));
    return section;
  }

  _renderTrack(track, context, playlistIndex = -1) {
    const row = makeElement("article", { className: "track-row" });
    const label = voiceSafeText(track?.title, this._t("untitledTrack"));
    const copy = makeElement("span", { className: "track-copy" }, [
      makeElement("strong", { text: label }),
      makeElement("span", { text: `${voiceSafeText(track?.artist, this._t("unknownArtist"))} · ${voiceSafeText(track?.album, this._t("unknownAlbum"))}` }),
    ]);
    const meta = makeElement("span", { className: "duration", text: formatDuration(track?.duration) });
    const primary = makeElement("button", {
      type: "button",
      className: "track-primary",
      label: this._t(context === "playlist" ? "playPlaylistFrom" : "playTrack", { name: label }),
      title: this._t(context === "playlist" ? "playPlaylistFromHint" : "playNow"),
      on: { click: () => this._playTrackPrimary(track, context, playlistIndex) },
    }, [this._renderCover(track?.cover_art, track?.album || label), copy, meta]);
    const action = makeElement("div", { className: "row-actions" });
    if (context !== "playlist") {
      action.append(
        button(this._t("playNext"), () => this._queueCommand("queue_add", { track_ids: [String(track.id)], position: "next" }), { className: "row-button" }),
        button(this._t("addToQueue"), () => this._queueCommand("queue_add", { track_ids: [String(track.id)], position: "last" }), { className: "row-button" }),
      );
    }
    action.append(button(this._t("details"), () => this._showDetail(track), { className: "row-button" }));
    row.append(primary, action);
    return row;
  }

  _renderPlaylists() {
    const section = makeElement("div", { className: "library-content" });
    section.append(this._searchBar(this.playlistQuery, this._t("searchPlaylists"), (event) => {
      this.playlistQuery = event.currentTarget.value;
      this.playlistOffset = 0;
      this._loadPlaylists();
    }));
    const grid = makeElement("div", { className: "playlist-grid" });
    if (!this.playlists.length) grid.append(makeElement("p", { className: "empty", text: this._t("noPlaylists") }));
    for (const playlist of this.playlists) {
      const name = voiceSafeText(playlist?.name, this._t("untitledPlaylist"));
      const children = [];
      if (!this._narrow) children.push(this._renderCover(playlist?.cover_art, name, "playlist-cover"));
      children.push(makeElement("span", { className: "playlist-copy" }, [
        makeElement("strong", { text: name }),
        makeElement("span", { text: `${this._t("trackCount", { count: Number(playlist?.song_count) || 0 })} · ${voiceSafeText(playlist?.owner, this._t("myPlaylist"))}` }),
      ]));
      const card = makeElement("button", {
        type: "button",
        className: "playlist-card",
        label: this._t("browsePlaylist", { name }),
        title: this._t("browsePlaylistTracks"),
        dataset: { focusKey: `playlist-card:${String(playlist?.id || "")}` },
        on: { click: () => this._openPlaylist(playlist) },
      }, children);
      grid.append(card);
    }
    section.append(grid, this._pager(this.playlistOffset, this.playlistTotal, (offset) => { this.playlistOffset = offset; this._loadPlaylists(); }));
    return section;
  }

  _renderPlaylistTracks() {
    const section = makeElement("div", { className: "library-content" });
    const title = voiceSafeText(this.selectedPlaylist?.name, this._t("playlist"));
    section.append(makeElement("div", { className: "subheading" }, [
      button(this._t("backToPlaylists"), () => this._closePlaylist(), { className: "back", dataset: { focusKey: "playlist-back" } }),
      makeElement("h2", { text: title }),
    ]));
    const list = makeElement("div", { className: "track-list" });
    if (!this.playlistTracks.length) list.append(makeElement("p", { className: "empty", text: this._t("emptyPlaylist") }));
    for (const [index, track] of this.playlistTracks.entries()) {
      list.append(this._renderTrack(track, "playlist", this.playlistTrackOffset + index));
    }
    section.append(list, this._pager(this.playlistTrackOffset, this.playlistTrackTotal, (offset) => { this.playlistTrackOffset = offset; this._loadPlaylistTracks(); }));
    return section;
  }

  _pager(offset, total, setOffset) {
    const current = Math.floor(offset / PAGE_SIZE) + 1;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    return makeElement("nav", { className: "pager", label: this._t("pagination") }, [
      button(this._t("previousPage"), () => setOffset(Math.max(0, offset - PAGE_SIZE)), { className: "secondary", disabled: offset <= 0 }),
      makeElement("span", { text: `${current} / ${pages}` }),
      button(this._t("nextPage"), () => setOffset(offset + PAGE_SIZE), { className: "secondary", disabled: offset + PAGE_SIZE >= total }),
    ]);
  }

  _renderQueue() {
    const pane = makeElement("aside", { className: "queue-pane", label: this._t("playbackQueue") });
    const active = this.queue.state === "playing" || this.queue.state === "loading";
    const current = this.queue.current || this.queue.items?.[this.queue.current_index];
    const player = this.queue.player || {};
    const mode = playbackMode(this.queue);
    const modes = {
      sequence: { icon: "sequence", label: this._t("sequenceMode") },
      shuffle: { icon: "shuffle", label: this._t("shuffleMode") },
      one: { icon: "one", label: this._t("repeatOneMode") },
    };
    const modeInfo = modes[mode];
    const controls = makeElement("div", { className: "transport" }, [
      iconButton("previous", this._t("previousTrack"), () => this._queueCommand("queue_control", { action: "previous" }), {
        className: "transport-button icon-button",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "player-previous" },
      }),
      iconButton(active ? "pause" : "play", this._t(active ? "pause" : "play"), () => this._queueCommand("queue_control", { action: active ? "stop" : "play" }), {
        className: "transport-main icon-button",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "player-toggle" },
      }),
      iconButton("next", this._t("nextTrack"), () => this._queueCommand("queue_control", { action: "next" }), {
        className: "transport-button icon-button",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "player-next" },
      }),
      iconButton(modeInfo.icon, this._t("playbackMode", { mode: modeInfo.label }), () => this._queueCommand("queue_options", nextPlaybackMode(mode)), {
        className: "mode-button icon-button",
        dataset: { mode, focusKey: "player-mode" },
      }),
    ]);
    const disc = makeElement("div", { className: `disc ${active ? "disc-spinning" : ""}` }, [
      this._renderCover(current?.cover_art, current?.album || current?.title || this._t("music"), "disc-cover"),
      makeElement("span", { className: "disc-hole" }),
    ]);
    const stage = makeElement("div", { className: "player-stage" }, [
      disc,
      makeElement("div", { className: "player-copy" }, [
        makeElement("span", { className: "player-state", text: this._playerStateText() }),
        makeElement("strong", { text: voiceSafeText(current?.title, this._t("chooseMusic")) }),
        makeElement("span", { text: current ? voiceSafeText(current?.artist, this._t("unknownArtist")) : this._t("startFromLibrary") }),
      ]),
    ]);
    const progress = this._renderProgress(player, current);
    const volume = this._renderVolume(player);
    const playerCard = makeElement("section", { className: "player-card", label: this._t("musicControls") }, [stage, progress, controls, volume]);
    const heading = makeElement("div", { className: "queue-heading" }, [
      makeElement("div", {}, [makeElement("h2", { text: this._t("playbackQueue") }), makeElement("span", { text: this._t("trackCount", { count: this.queue.items?.length || 0 }) })]),
      iconButton("trash", this._t("clearQueue"), () => this._queueCommand("queue_control", { action: "clear" }), {
        className: "danger icon-button queue-clear",
        disabled: !this.queue.items?.length,
        dataset: { focusKey: "queue-clear" },
      }),
    ]);
    const playerSelector = this._renderPlayerSelector();
    const list = makeElement("ol", { className: "queue-list" });
    if (!this.queue.items?.length) list.append(makeElement("li", { className: "empty", text: this._t("emptyQueue") }));
    this.queue.items?.forEach((track, index) => {
      const current = index === this.queue.current_index;
      const row = makeElement("li", { className: `queue-row ${current ? "current" : ""}` }, [
        makeElement("span", { className: "queue-index", text: current ? "▶" : index + 1 }),
        this._renderCover(track?.cover_art, track?.album || track?.title, "queue-cover"),
        makeElement("button", { type: "button", className: "queue-track", label: this._t("playTrack", { name: voiceSafeText(track?.title, this._t("tracks")) }), on: { click: () => this._queueCommand("queue_control", { action: "jump", index }) } }, [
          makeElement("strong", { text: voiceSafeText(track?.title, this._t("untitledTrack")) }),
          makeElement("span", { text: voiceSafeText(track?.artist, this._t("unknownArtist")) }),
        ]),
        makeElement("span", { className: "duration", text: formatDuration(track?.duration) }),
      ]);
      list.append(row);
    });
    pane.append(playerCard, playerSelector, heading, list);
    return pane;
  }

  _playerStateText() {
    if (this.queue.state === "loading") return this._t("loading");
    if (this.queue.state === "playing") return this._t("playing");
    if (this.queue.state === "error") return this._t("playbackFailed");
    if (this.queue.player?.state === "paused") return this._t("paused");
    return this._t("ready");
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
      label: this._t(canSeek ? "progress" : "progressUnsupported"),
      title: this._t(canSeek ? "seekHint" : "seekUnsupported"),
      min: 0,
      max: Math.max(1, Math.floor(duration)),
      step: 1,
      value: Math.min(position, duration || position),
      disabled: !canSeek,
      dataset: { focusKey: "player-progress" },
      on: {
        input: (event) => {
          event.currentTarget.dataset.localEditing = "true";
          this._seekPreview = Number(event.currentTarget.value);
          updateRangeFill(event.currentTarget);
          const elapsed = event.currentTarget.parentElement?.querySelector(".progress-elapsed");
          if (elapsed) elapsed.textContent = formatDuration(this._seekPreview);
        },
        change: (event) => {
          delete event.currentTarget.dataset.localEditing;
          const target = Number(event.currentTarget.value);
          this._seekPreview = null;
          this._queueCommand("player_control", { action: "seek", position: target });
        },
        blur: (event) => {
          delete event.currentTarget.dataset.localEditing;
          this._seekPreview = null;
        },
      },
    });
    updateRangeFill(range);
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
    const level = this._pendingVolume?.value ?? player?.volume_level;
    const volume = Math.round(Math.max(0, Math.min(1, Number(level) || 0)) * 100);
    const range = makeElement("input", {
      type: "range",
      className: "volume-range",
      label: this._t("volume"),
      min: 0,
      max: 100,
      step: 1,
      value: volume,
      disabled: !canSet,
      dataset: { focusKey: "player-volume" },
      on: {
        input: (event) => {
          event.currentTarget.dataset.localEditing = "true";
          updateRangeFill(event.currentTarget);
          const value = event.currentTarget.parentElement?.querySelector(".volume-value");
          if (value) value.textContent = `${event.currentTarget.value}%`;
        },
        change: (event) => {
          delete event.currentTarget.dataset.localEditing;
          this._setVolume(Number(event.currentTarget.value) / 100);
        },
        blur: (event) => { delete event.currentTarget.dataset.localEditing; },
      },
    });
    updateRangeFill(range);
    return makeElement("div", { className: "volume-control" }, [
      iconButton(muted ? "muted" : "volume", this._t(muted ? "unmute" : "mute"), () => this._queueCommand("player_control", {
        action: "volume_mute",
        is_volume_muted: !muted,
      }), { className: "volume-button icon-button", disabled: !canMute, pressed: muted, dataset: { focusKey: "player-mute" } }),
      range,
      makeElement("span", { className: "volume-value", text: canSet ? `${volume}%` : "--" }),
    ]);
  }

  _setVolume(volumeLevel) {
    const level = Math.max(0, Math.min(1, Number(volumeLevel) || 0));
    const pending = { value: level, expiresAt: Date.now() + VOLUME_CONFIRM_TIMEOUT };
    this._pendingVolume = pending;
    if (this._volumeConfirmTimer) clearTimeout(this._volumeConfirmTimer);
    this._volumeConfirmTimer = setTimeout(() => {
      if (this._pendingVolume !== pending) return;
      this._pendingVolume = null;
      this._volumeConfirmTimer = null;
      this._renderQueueOnly();
    }, VOLUME_CONFIRM_TIMEOUT);
    return this._queueCommand("player_control", {
      action: "volume_set",
      volume_level: level,
    }).then((result) => {
      if (result !== null || this._pendingVolume !== pending) return result;
      this._pendingVolume = null;
      if (this._volumeConfirmTimer) clearTimeout(this._volumeConfirmTimer);
      this._volumeConfirmTimer = null;
      this._renderQueueOnly();
      return result;
    });
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
      updateRangeFill(range);
      const elapsed = this.shadowRoot?.querySelector(".progress-elapsed");
      if (elapsed) elapsed.textContent = formatDuration(position);
    }, 1000);
  }

  _renderPlayerSelector() {
    const select = makeElement("select", { className: "player-select", label: this._t("player"), dataset: { focusKey: "player-select" }, on: { change: (event) => {
      const entityId = event.currentTarget.value;
      if (entityId) this._queueCommand("queue_player", { entity_id: entityId });
    } } });
    select.append(makeElement("option", { value: "", text: this._t("choosePlayer"), selected: !this.queue.media_player }));
    for (const player of this.players) {
      const entityId = String(player?.entity_id || player?.id || "");
      if (!entityId) continue;
      const label = voiceSafeText(player?.name || player?.friendly_name || entityId);
      select.append(makeElement("option", { value: entityId, text: label, selected: entityId === this.queue.media_player }));
    }
    return makeElement("label", { className: "player-label", text: this._t("player") }, [select]);
  }

  _renderDetail() {
    const track = this.detail;
    const dialog = makeElement("section", { className: "detail-backdrop", role: "dialog", label: this._t("trackDetails") });
    const card = makeElement("div", { className: "detail-card" });
    card.append(button(this._t("close"), () => { this.detail = null; this._detailGate.cancel(); this._render(); }, { className: "detail-close" }));
    card.append(this._renderCover(track?.cover_art, track?.album || track?.title, "detail-cover"));
    card.append(makeElement("h2", { text: voiceSafeText(track?.title, this._t("untitledTrack")) }));
    card.append(makeElement("p", { className: "detail-artist", text: `${voiceSafeText(track?.artist, this._t("unknownArtist"))} · ${voiceSafeText(track?.album, this._t("unknownAlbum"))}` }));
    if (track?.loading) card.append(makeElement("p", { className: "loading", text: this._t("loadingDetails") }));
    const details = [
      [this._t("duration"), track?.duration ? formatDuration(track.duration) : ""],
      [this._t("genre"), track?.genre],
      [this._t("year"), track?.year],
      [this._t("trackNumber"), track?.track_number],
      [this._t("discNumber"), track?.disc_number],
      [this._t("format"), track?.suffix || track?.content_type],
      [this._t("bitrate"), track?.bit_rate ? `${track.bit_rate} kbps` : ""],
      [this._t("fileSize"), track?.size ? `${Math.round(Number(track.size) / 1024 / 1024 * 10) / 10} MB` : ""],
    ].filter(([, value]) => value !== "" && value !== null && value !== undefined);
    const definition = makeElement("dl", { className: "detail-list" });
    for (const [term, value] of details) definition.append(makeElement("dt", { text: term }), makeElement("dd", { text: value }));
    card.append(definition);
    dialog.append(card);
    return dialog;
  }

  _playTrackPrimary(track, context, playlistIndex = -1) {
    const action = trackPrimaryCommand(
      context,
      track?.id,
      this.selectedPlaylist?.id,
      playlistIndex,
    );
    if (action) this._queueCommand(action.command, action.fields);
  }

  async _syncLibrary() {
    if (this.syncing) return;
    const ready = this._initializedEntry === this.entryId || await this._start();
    if (!ready || !this._connected || this._initializedEntry !== this.entryId) return;
    this.syncing = true;
    this._render();
    try {
      const index = await this._call("sync_library");
      this.config = { ...this.config, index };
      this._setNotice("syncComplete");
      await Promise.all([this._loadTracks(), this._loadPlaylists()]);
    } catch (error) {
      if (!isAbort(error)) this._setNotice("syncFailed", true);
    } finally {
      this.syncing = false;
      this._render();
    }
  }
}

if (globalThis.customElements && globalThis.document && !customElements.get("xiaoai-navidrome-panel")) {
  customElements.define("xiaoai-navidrome-panel", XiaoAINavidromePanel);
}
if (globalThis.addEventListener) {
  globalThis.addEventListener("pagehide", (event) => {
    if (!event.persisted) clearSharedCoverStores();
  });
}
export { XiaoAINavidromePanel, CoverStore };
