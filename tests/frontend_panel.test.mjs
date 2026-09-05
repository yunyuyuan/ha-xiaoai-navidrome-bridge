import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const moduleUrl = new URL("../custom_components/xiaoai_navidrome/frontend/panel.js", import.meta.url);
const {
  CoverStore,
  PANEL_TEXT,
  RequestGate,
  XiaoAINavidromePanel,
  clearSharedCoverStores,
  coverApiPath,
  coverClassNames,
  coverPixelSize,
  formatDuration,
  nextPlaybackMode,
  normalizePanelLanguage,
  panelText,
  playbackMode,
  queueStatus,
  rangeFillPercent,
  reconcilePendingVolume,
  responseItems,
  sharedCoverStore,
  trackPrimaryCommand,
  voiceSafeText,
} = await import(moduleUrl);

test("voiceSafeText removes control and directional characters while preserving readable synthetic metadata", () => {
  assert.equal(voiceSafeText("  Demo\u0000 Artist\u202e  \n"), "Demo Artist");
  assert.equal(voiceSafeText(null, "Untitled"), "Untitled");
  assert.equal(voiceSafeText("\t", "Untitled"), "Untitled");
});

test("panel text supports only English and Simplified Chinese with English as default", () => {
  assert.deepEqual(Object.keys(PANEL_TEXT["zh-Hans"]).sort(), Object.keys(PANEL_TEXT.en).sort());
  assert.equal(normalizePanelLanguage(undefined), "en");
  assert.equal(normalizePanelLanguage("en"), "en");
  assert.equal(normalizePanelLanguage("zh-Hans"), "zh-Hans");
  assert.equal(normalizePanelLanguage("zh-CN"), "en");
  assert.equal(panelText("en", "playTrack", { name: "Synthetic Track" }), "Play Synthetic Track");
  assert.equal(panelText("zh-Hans", "playTrack", { name: "Synthetic Track" }), "播放 Synthetic Track");
});

test("playback mode cycles through sequence, shuffle, and repeat-one atomically", () => {
  assert.equal(playbackMode({ repeat: "all", shuffle: false }), "sequence");
  assert.equal(playbackMode({ repeat: "all", shuffle: true }), "shuffle");
  assert.equal(playbackMode({ repeat: "one", shuffle: true }), "one");
  assert.deepEqual(nextPlaybackMode("sequence"), { shuffle: true, repeat: "all" });
  assert.deepEqual(nextPlaybackMode("shuffle"), { shuffle: false, repeat: "one" });
  assert.deepEqual(nextPlaybackMode("one"), { shuffle: false, repeat: "all" });
  assert.deepEqual(nextPlaybackMode("unexpected"), { shuffle: false, repeat: "all" });
});

test("formatDuration produces stable compact timestamps", () => {
  assert.equal(formatDuration(0), "0:00");
  assert.equal(formatDuration(65.9), "1:05");
  assert.equal(formatDuration(-1), "0:00");
});

test("range fill and optimistic volume reconciliation are bounded", () => {
  assert.equal(rangeFillPercent(25, 100), 25);
  assert.equal(rangeFillPercent(200, 100), 100);
  assert.equal(rangeFillPercent(-1, 100), 0);
  assert.equal(rangeFillPercent(1, 0), 0);

  const pending = { value: 0.42, expiresAt: 2000 };
  assert.equal(reconcilePendingVolume(pending, 0.7, 1000), pending);
  assert.equal(reconcilePendingVolume(pending, undefined, 1000), pending);
  assert.equal(reconcilePendingVolume(pending, 0.4, 1000), pending);
  assert.equal(reconcilePendingVolume(pending, 0.42, 1000), null);
  assert.equal(reconcilePendingVolume(pending, 0.7, 2000), null);
  const smallChange = { value: 0.52, expiresAt: 2000 };
  assert.equal(reconcilePendingVolume(smallChange, 0.5, 1000), smallChange);
});

test("cover requests use density-aware authenticated Home Assistant paths", async () => {
  assert.equal(
    coverApiPath("entry / one", "cover / two", 384),
    "/api/xiaoai_navidrome/cover/entry%20%2F%20one/cover%20%2F%20two?size=384",
  );
  assert.equal(coverApiPath("entry-one", "cover-two").endsWith("?size=64"), true);
  assert.equal(coverPixelSize("", 1), 64);
  assert.equal(coverPixelSize("queue-cover", 1.5), 96);
  assert.equal(coverPixelSize("disc-cover", 1), 96);
  assert.equal(coverPixelSize("disc-cover", 1.5), 160);
  assert.equal(coverPixelSize("detail-cover", 1), 160);
  assert.equal(coverPixelSize("detail-cover", 2), 256);
  assert.equal(coverPixelSize("playlist-cover", 1), 256);
  assert.equal(coverPixelSize("playlist-cover", 1.5), 384);
  assert.equal(coverPixelSize("playlist-cover", 3), 384);
  const source = await readFile(moduleUrl, "utf8");
  assert.equal(source.includes("fetchWithAuth(this.owner.hass.hassUrl"), false);
  assert.equal(source.includes("fetchWithAuth(path)"), true);
});

test("specialized covers retain the shared image crop class", () => {
  assert.equal(coverClassNames(), "cover cover-placeholder");
  assert.equal(
    coverClassNames("playlist-cover"),
    "cover playlist-cover cover-placeholder",
  );
});

test("cover cache deduplicates one size while isolating higher-resolution variants", async () => {
  const requests = [];
  const owner = {
    entryId: "entry-one",
    hass: {
      fetchWithAuth: async (path) => {
        requests.push(path);
        return {
          ok: true,
          status: 200,
          blob: async () => new Blob(["synthetic-image"], { type: "image/jpeg" }),
        };
      },
    },
  };
  const store = new CoverStore(owner);
  const [smallOne, smallTwo, large] = await Promise.all([
    store.get("cover-one", 64),
    store.get("cover-one", 64),
    store.get("cover-one", 256),
  ]);
  assert.equal(smallOne, smallTwo);
  assert.notEqual(smallOne, large);
  assert.equal(requests.length, 2);
  assert.equal(requests.some((path) => path.endsWith("?size=64")), true);
  assert.equal(requests.some((path) => path.endsWith("?size=256")), true);
  assert.equal(store.peek("cover-one", 64), smallOne);
  assert.equal(store.peek("cover-one", 256), large);
  store.clear();
});

test("shared cover cache survives panel instance navigation and releases on page teardown", async () => {
  const requests = [];
  const hass = {
    fetchWithAuth: async (path) => {
      requests.push(path);
      return {
        ok: true,
        status: 200,
        blob: async () => new Blob(["synthetic-shared-image"], { type: "image/jpeg" }),
      };
    },
  };
  const firstOwner = { entryId: "entry-shared", hass };
  const firstStore = sharedCoverStore(firstOwner);
  const firstUrl = await firstStore.get("cover-shared", 96);
  firstStore.release(firstOwner);

  const secondOwner = { entryId: "entry-shared", hass };
  const secondStore = sharedCoverStore(secondOwner);
  const secondUrl = await secondStore.get("cover-shared", 96);
  assert.equal(secondStore, firstStore);
  assert.equal(secondUrl, firstUrl);
  assert.equal(requests.length, 1);

  const thirdStore = sharedCoverStore({ entryId: "entry-other", hass });
  const thirdUrl = await thirdStore.get("cover-shared", 96);
  assert.notEqual(thirdStore, firstStore);
  assert.notEqual(thirdUrl, firstUrl);
  assert.equal(requests.length, 2);

  clearSharedCoverStores();
  assert.equal(firstStore.closed, true);
  assert.equal(thirdStore.closed, true);
});

test("panel accepts only the current WebSocket response shapes", () => {
  const items = [{ id: "synthetic" }];
  const queue = { items, revision: 1 };
  assert.deepEqual(responseItems({ items }), items);
  assert.deepEqual(responseItems(items), []);
  assert.deepEqual(responseItems({ tracks: items }), []);
  assert.equal(queueStatus(queue), queue);
  assert.equal(queueStatus({ queue }), null);
  assert.equal(queueStatus({ result: queue }), null);
});

test("RequestGate invalidates and aborts obsolete responses", () => {
  const gate = new RequestGate();
  const first = gate.begin();
  assert.equal(first.isCurrent(), true);
  const second = gate.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(first.isCurrent(), false);
  assert.equal(second.isCurrent(), true);
  gate.cancel();
  assert.equal(second.signal.aborted, true);
  assert.equal(second.isCurrent(), false);
});

test("disconnect during initialization starts a fresh connection immediately", async () => {
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  let attempt = 0;
  let queueApplied = 0;
  let libraryLoads = 0;
  let releaseLibrary;
  const libraryPending = new Promise((resolve) => { releaseLibrary = resolve; });
  const gates = ["_initGate", "_tracksGate", "_playlistsGate", "_playlistTracksGate", "_detailGate"];
  Object.assign(panel, {
    _connected: true,
    _hass: {},
    entryId: "entry-one",
    _initializedEntry: "",
    _initializing: false,
    _initializationSerial: 0,
    _initializationPromise: null,
    _connectionController: new AbortController(),
    _unsubscribeQueue: null,
    _progressTimer: null,
    _volumeConfirmTimer: null,
    _pendingVolume: null,
    _queueEpoch: 0,
    _covers: { closed: false, clear() { this.closed = true; } },
    queue: { items: [], revision: 0 },
    config: {},
    players: [],
    connectionState: "正在连接",
    syncing: false,
    _render: () => undefined,
    _loadStyles: () => undefined,
    _subscribeQueue: () => undefined,
    _applyQueue: () => { queueApplied += 1; },
    _loadTracks: () => { libraryLoads += 1; return libraryPending; },
    _loadPlaylists: () => { libraryLoads += 1; return libraryPending; },
  });
  for (const key of gates) panel[key] = new RequestGate();
  panel._call = (command, _fields, signal) => {
    if (command === "config") attempt += 1;
    const currentAttempt = attempt;
    if (currentAttempt === 1) {
      return new Promise((resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    }
    if (command === "config") return Promise.resolve({ connected: true, index: {} });
    if (command === "media_players") return Promise.resolve({ items: [] });
    return Promise.resolve({ items: [], revision: 2 });
  };

  const abandoned = panel._start();
  assert.equal(panel._initializing, true);
  panel.disconnectedCallback();
  panel.connectedCallback();
  const reconnected = panel._initializationPromise;

  assert.equal(await abandoned, false);
  assert.equal(
    await Promise.race([
      reconnected,
      new Promise((resolve) => setTimeout(() => resolve("timeout"), 50)),
    ]),
    true,
  );
  assert.equal(attempt, 2);
  assert.equal(panel._initializedEntry, "entry-one");
  assert.equal(panel._initializing, false);
  assert.equal(queueApplied, 1);
  assert.equal(libraryLoads, 2);
  releaseLibrary();
});

test("an abandoned command releases the chain and a reconnect click waits for readiness", async () => {
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  let notices = 0;
  let commandCalls = 0;
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });
  Object.assign(panel, {
    _connected: true,
    entryId: "entry-one",
    _initializedEntry: "entry-one",
    _connectionController: new AbortController(),
    _commandChain: Promise.resolve(),
    queue: { items: [], revision: 4 },
    _hass: { callWS: () => new Promise(() => undefined) },
    _setNotice: () => { notices += 1; },
    _applyQueue: () => undefined,
  });

  const abandoned = panel._queueCommand("queue_control", { action: "next" });
  await Promise.resolve();
  panel._connectionController.abort();
  assert.equal(await abandoned, null);
  assert.equal(notices, 0);

  panel._connectionController = new AbortController();
  panel._initializedEntry = "";
  panel._start = () => ready;
  panel._hass = {
    callWS: async () => {
      commandCalls += 1;
      return { items: [], revision: 5 };
    },
  };
  const afterReconnect = panel._queueCommand("queue_control", { action: "next" });
  await Promise.resolve();
  assert.equal(commandCalls, 0);
  panel._initializedEntry = "entry-one";
  resolveReady(true);
  assert.notEqual(await afterReconnect, null);
  assert.equal(commandCalls, 1);
  assert.equal(notices, 0);
});

test("a queued command from the detached generation is never sent after reconnect", async () => {
  let releaseChain;
  let commandCalls = 0;
  const blockedChain = new Promise((resolve) => { releaseChain = resolve; });
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  Object.assign(panel, {
    _connected: true,
    entryId: "entry-one",
    _initializedEntry: "entry-one",
    _connectionController: new AbortController(),
    _commandChain: blockedChain,
    queue: { items: [], revision: 4 },
    _hass: {
      callWS: async () => {
        commandCalls += 1;
        return { items: [], revision: 5 };
      },
    },
    _setNotice: () => undefined,
    _applyQueue: () => undefined,
  });

  const oldController = panel._connectionController;
  const queued = panel._queueCommand("queue_control", { action: "next" });
  oldController.abort();
  panel._connectionController = new AbortController();
  panel._initializedEntry = "";
  panel._start = async () => {
    panel._initializedEntry = "entry-one";
    return true;
  };
  releaseChain();

  assert.equal(await queued, null);
  assert.equal(commandCalls, 0);
});

test("a late subscription from the detached connection cannot replace the current one", async () => {
  const pending = [];
  let staleUnsubscribed = 0;
  let currentUnsubscribed = 0;
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  Object.assign(panel, {
    _connected: true,
    entryId: "entry-one",
    _unsubscribeQueue: null,
    _connectionController: new AbortController(),
    _hass: {
      connection: {
        subscribeMessage: () => new Promise((resolve) => pending.push(resolve)),
      },
    },
    _setNotice: () => { throw new Error("an abandoned subscription must stay silent"); },
  });

  const first = panel._subscribeQueue();
  panel._connectionController.abort();
  panel._connectionController = new AbortController();
  const second = panel._subscribeQueue();
  pending[0](() => { staleUnsubscribed += 1; });
  await first;
  assert.equal(staleUnsubscribed, 1);
  assert.equal(panel._unsubscribeQueue, null);

  const currentUnsubscribe = () => { currentUnsubscribed += 1; };
  pending[1](currentUnsubscribe);
  await second;
  assert.equal(panel._unsubscribeQueue, currentUnsubscribe);
  panel._unsubscribeQueue();
  assert.equal(currentUnsubscribed, 1);
});

test("switching entries rejects a late command response and resets queue revision", async () => {
  let resolveCommand;
  let oldUnsubscribed = 0;
  const commandResponse = new Promise((resolve) => { resolveCommand = resolve; });
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  Object.assign(panel, {
    _connected: true,
    _panel: { config: { entry_id: "entry-a" } },
    entryId: "entry-a",
    _initializedEntry: "entry-a",
    _initializing: false,
    _initializationSerial: 1,
    _initializationPromise: null,
    _connectionController: new AbortController(),
    _commandChain: Promise.resolve(),
    _queueEpoch: 3,
    _queueReceivedAt: Date.now(),
    _seekPreview: null,
    _progressTimer: null,
    _volumeConfirmTimer: null,
    _pendingVolume: null,
    _unsubscribeQueue: () => { oldUnsubscribed += 1; },
    _covers: { clear: () => undefined },
    queue: { items: [{ id: "track-a" }], current_index: 0, revision: 99, state: "playing" },
    config: { connected: true },
    players: [{ entity_id: "media_player.a" }],
    tracks: [{ id: "track-a" }],
    trackTotal: 1,
    trackOffset: 0,
    playlists: [],
    playlistTotal: 0,
    playlistOffset: 0,
    selectedPlaylist: null,
    playlistTracks: [],
    playlistTrackTotal: 0,
    playlistTrackOffset: 0,
    _playlistReturnFocusKey: "",
    detail: null,
    notice: "",
    _hass: { callWS: () => commandResponse },
    _setNotice: () => undefined,
    _renderQueueOnly: () => undefined,
    _syncProgressTimer: () => undefined,
    _start: () => Promise.resolve(true),
  });
  for (const key of ["_initGate", "_tracksGate", "_playlistsGate", "_playlistTracksGate", "_detailGate"]) {
    panel[key] = new RequestGate();
  }

  const oldCommand = panel._queueCommand("queue_control", { action: "next" });
  await Promise.resolve();
  panel.panel = { config: { entry_id: "entry-b" } };
  resolveCommand({ items: [{ id: "track-a" }], current_index: 0, revision: 100 });

  assert.equal(await oldCommand, null);
  assert.equal(oldUnsubscribed, 1);
  assert.equal(panel.entryId, "entry-b");
  assert.equal(panel.queue.revision, 0);
  assert.deepEqual(panel.queue.items, []);
  assert.deepEqual(panel.tracks, []);
  assert.deepEqual(panel.players, []);
});

test("track primary targets select context-appropriate playback mutations", () => {
  assert.deepEqual(trackPrimaryCommand("library", "track-one"), {
    command: "queue_add",
    fields: { track_ids: ["track-one"], position: "replace" },
  });
  assert.deepEqual(trackPrimaryCommand("playlist", "track-two", "playlist-one", 42), {
    command: "queue_playlist",
    fields: {
      playlist_id: "playlist-one",
      position: "replace",
      start_track_id: "track-two",
      start_index: 42,
    },
  });
  assert.equal(trackPrimaryCommand("playlist", "track-two"), null);
  assert.equal(trackPrimaryCommand("playlist", "track-two", "playlist-one"), null);
  assert.equal(trackPrimaryCommand("library", ""), null);
});

test("panel defaults to playlists and exposes compact mobile playlist rows", async () => {
  const source = await readFile(moduleUrl, "utf8");
  const css = await readFile(
    new URL("../custom_components/xiaoai_navidrome/frontend/panel.css", import.meta.url),
    "utf8",
  );
  assert.equal(source.includes('className: "track-primary"'), true);
  assert.equal(source.includes('className: "playlist-card"'), true);
  assert.equal(source.includes('this.libraryTab = "playlists"'), true);
  assert.ok(source.indexOf('button(this._t("playlists")') < source.indexOf('button(this._t("tracks")'));
  assert.equal(source.includes('className: "menu-button icon-button"'), true);
  assert.equal(source.includes('makeElement("h1", { text: this.panelTitle })'), true);
  assert.equal(source.includes('new CustomEvent("hass-toggle-menu"'), true);
  assert.equal(source.includes("patchElement(current, replacement)"), true);
  assert.equal(source.includes("this.shadowRoot.replaceChildren"), false);
  assert.equal(source.includes("this.playlistTrackOffset + index"), true);
  assert.equal(source.includes('button("播放全部"'), false);
  assert.equal(source.includes('button("下一首播放"'), false);
  assert.equal(source.includes('button("加入队列"'), false);
  assert.equal(source.includes('role: "tab"'), true);
  assert.match(css, /\.tab\[aria-selected="true"\]/);
  assert.match(css, /\.track-primary:hover/);
  assert.match(css, /\.playlist-card:hover/);
  assert.match(css, /:host\(\[narrow\]\) \.playlist-grid \{ grid-template-columns: 1fr;/);
  assert.match(css, /:host\(\[narrow\]\) \.playlist-cover \{ display: none; \}/);
  assert.match(css, /:host\(\[narrow\]:not\(\[kiosk\]\)\) \.menu-button \{ display: grid/);
  assert.match(css, /\.menu-button \{[^}]+display: none/s);
  assert.match(css, /\.queue-pane \{[^}]*position: sticky;[^}]*top: 12px;/s);
  assert.match(css, /@media \(max-width: 1050px\) \{[\s\S]*?\.queue-pane \{ position: static; top: auto; \}/);
  assert.match(css, /:host\(\[narrow\]\) \.queue-pane \{ position: static; top: auto; \}/);
});

test("playlist-first tabs keep keyboard endpoints aligned with visual order", () => {
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  let selected = "";
  panel.libraryTab = "tracks";
  panel._selectLibraryTab = (tab) => { selected = tab; };
  const event = { key: "Home", preventDefault: () => undefined };

  panel._handleLibraryTabKey(event);
  assert.equal(selected, "playlists");
  event.key = "End";
  panel._handleLibraryTabKey(event);
  assert.equal(selected, "tracks");
});

test("player uses a rotating disc, icon controls, ranges, and one mode button", async () => {
  const source = await readFile(moduleUrl, "utf8");
  const css = await readFile(
    new URL("../custom_components/xiaoai_navidrome/frontend/panel.css", import.meta.url),
    "utf8",
  );
  assert.equal(source.includes('className: `disc ${active ? "disc-spinning" : ""}`'), true);
  assert.equal(source.includes('className: "mode-button icon-button"'), true);
  assert.equal(source.includes('className: "progress-range"'), true);
  assert.equal(source.includes('className: "volume-range"'), true);
  assert.equal(source.includes('this._queueCommand("player_control"'), true);
  assert.equal(source.includes('className: "now-playing"'), false);
  assert.equal(source.includes("Material Design Icons 7.4.47"), true);
  assert.equal(source.includes("M17,3L22.25,7.5L17,12"), true);
  assert.equal(source.includes("M6,19A2,2 0 0,0 8,21H16"), true);
  assert.match(css, /@keyframes disc-spin/);
  assert.doesNotMatch(css, /\.mode-button\[data-mode="one"\]::after/);
  assert.match(css, /::-webkit-slider-runnable-track/);
  assert.match(css, /--range-progress/);
  assert.match(css, /\.transport-main:hover[^}]+background: var\(--x-primary\)/);
  assert.match(css, /prefers-reduced-motion:[^}]+animation: none/s);
});

test("queue state updates preserve pending volume and use a local pane refresh", () => {
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  let queueRenders = 0;
  let timerSyncs = 0;
  Object.assign(panel, {
    queue: {
      items: [],
      current_index: -1,
      revision: 4,
      media_player: "media_player.synthetic",
      player: { volume_level: 0.7 },
    },
    _pendingVolume: { value: 0.3, expiresAt: Date.now() + 10000 },
    _volumeConfirmTimer: null,
    _queueEpoch: 0,
    _renderQueueOnly: () => { queueRenders += 1; },
    _syncProgressTimer: () => { timerSyncs += 1; },
  });
  panel._applyQueue({
    items: [],
    current_index: -1,
    revision: 4,
    media_player: "media_player.synthetic",
    player: { volume_level: 0.7 },
  });
  assert.equal(panel._pendingVolume.value, 0.3);
  assert.equal(queueRenders, 1);
  assert.equal(timerSyncs, 1);

  panel._applyQueue({
    items: [],
    current_index: -1,
    revision: 4,
    media_player: "media_player.synthetic",
    player: { volume_level: 0.3 },
  });
  assert.equal(panel._pendingVolume, null);
  assert.equal(queueRenders, 2);
});

test("responsive narrow assignments never request a full panel render", () => {
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  const toggles = [];
  Object.assign(panel, {
    _narrow: false,
    toggleAttribute: (name, value) => { toggles.push([name, value]); },
    _render: () => { throw new Error("narrow must not rebuild the Shadow DOM"); },
  });

  panel.narrow = false;
  panel.narrow = true;
  panel.narrow = true;
  panel.narrow = false;
  assert.deepEqual(toggles, [["narrow", true], ["narrow", false]]);
});

test("playlist navigation restores stable focus keys without retaining DOM nodes", async () => {
  const panel = Object.create(XiaoAINavidromePanel.prototype);
  let focused = "";
  let targets = [{ dataset: { focusKey: "playlist-back" }, focus: () => { focused = "playlist-back"; } }];
  let cancelled = false;
  Object.assign(panel, {
    _connected: true,
    isConnected: true,
    libraryTab: "playlists",
    selectedPlaylist: null,
    playlistTrackOffset: 0,
    playlistTracks: [],
    _playlistReturnFocusKey: "",
    _playlistTracksGate: { cancel: () => { cancelled = true; } },
    shadowRoot: { querySelectorAll: () => targets },
    _render: () => undefined,
    _loadPlaylistTracks: async () => undefined,
  });

  await panel._openPlaylist({ id: "playlist-one", name: "Synthetic Playlist" });
  await Promise.resolve();
  assert.equal(focused, "playlist-back");
  assert.equal(panel._playlistReturnFocusKey, "playlist-card:playlist-one");

  targets = [{ dataset: { focusKey: "playlist-card:playlist-one" }, focus: () => { focused = "playlist-card:playlist-one"; } }];
  panel._closePlaylist();
  await Promise.resolve();
  assert.equal(cancelled, true);
  assert.equal(focused, "playlist-card:playlist-one");
  assert.equal(panel.selectedPlaylist, null);
});

test("playlist navigation preserves keyboard focus across Shadow DOM rerenders", async (context) => {
  if (process.env.CI && !process.env.CHROME_PATH) {
    context.skip("Set CHROME_PATH to enable the optional browser regression in CI");
    return;
  }
  const browserCandidates = [
    process.env.CHROME_PATH,
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
  ].filter(Boolean);
  let browser = "";
  for (const candidate of browserCandidates) {
    try {
      await access(candidate);
      browser = candidate;
      break;
    } catch (_) {
      // Try the next known browser path.
    }
  }
  if (!browser) {
    context.skip("Chromium is not installed");
    return;
  }

  const source = await readFile(moduleUrl, "utf8");
  const stylesheet = await readFile(
    new URL("../custom_components/xiaoai_navidrome/frontend/panel.css", import.meta.url),
    "utf8",
  );
  assert.equal(source.includes("</script>"), false);
  const directory = await mkdtemp(join(tmpdir(), "xiaoai-panel-focus-"));
  const fixture = join(directory, "focus.html");
  const html = `<!doctype html>
<html><body><script type="module">
${source}
const panel = document.createElement("xiaoai-navidrome-panel");
document.body.append(panel);
panel.libraryTab = "playlists";
panel.playlists = [{ id: "playlist-one", name: "Synthetic Playlist", song_count: 1, cover_art: "playlist-cover-one" }];
const coverSizes = [];
panel._covers.peek = (_id, pixelSize) => {
  coverSizes.push(pixelSize);
  return "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E";
};
panel.queue = {
  ...panel.queue,
  state: "playing",
  current_index: 0,
  current: { id: "track-one", title: "Synthetic Track", cover_art: "cover-one", duration: 180 },
  items: [{ id: "track-one", title: "Synthetic Track", cover_art: "cover-one", duration: 180 }],
  player: { volume_level: 0.4, supports_seek: true, duration: 180 },
};
panel._render();
const fixtureSheet = new CSSStyleSheet();
fixtureSheet.replaceSync(${JSON.stringify(stylesheet)});
panel.shadowRoot.adoptedStyleSheets = [...panel.shadowRoot.adoptedStyleSheets, fixtureSheet];
const densityAwareCovers = [64, 96, 256].every((size) => coverSizes.includes(size));
const mainBefore = panel.shadowRoot.querySelector("main.panel");
const libraryBefore = panel.shadowRoot.querySelector(".library-pane");
const queueBefore = panel.shadowRoot.querySelector(".queue-pane");
const desktopPlaylistCoverBefore = panel.shadowRoot.querySelector(".playlist-cover");
const desktopSticky = getComputedStyle(queueBefore).position === "sticky"
  && getComputedStyle(queueBefore).top === "12px";
const discCoverBefore = panel.shadowRoot.querySelector(".disc-cover");
const queueCoverBefore = panel.shadowRoot.querySelector(".queue-cover");
const discImageBefore = discCoverBefore.querySelector("img");
const queueImageBefore = queueCoverBefore.querySelector("img");
const previousBefore = panel.shadowRoot.querySelector('[data-focus-key="player-previous"]');
const toggleBefore = panel.shadowRoot.querySelector('[data-focus-key="player-toggle"]');
const progressBefore = panel.shadowRoot.querySelector(".progress-range");
progressBefore.value = "70";
progressBefore.focus();
progressBefore.dispatchEvent(new Event("input", { bubbles: true }));
panel._applyQueue({ ...panel.queue, position: 6 });
await new Promise((resolve) => setTimeout(resolve, 1200));
const activeRangeStable = progressBefore.value === "70"
  && Math.abs(Number.parseFloat(progressBefore.style.getPropertyValue("--range-progress")) - (70 / 180 * 100)) < 0.001
  && panel._seekPreview === 70
  && progressBefore.dataset.localEditing === "true";
panel._applyQueue({ ...panel.queue, state: "stopped", position: 7 });
const localQueueRefresh = panel.shadowRoot.querySelector(".library-pane") === libraryBefore && panel.shadowRoot.querySelector(".queue-pane") === queueBefore;
const coversStable = panel.shadowRoot.querySelector(".disc-cover") === discCoverBefore
  && panel.shadowRoot.querySelector(".queue-cover") === queueCoverBefore
  && panel.shadowRoot.querySelector(".disc-cover img") === discImageBefore
  && panel.shadowRoot.querySelector(".queue-cover img") === queueImageBefore;
const controlsStable = panel.shadowRoot.querySelector('[data-focus-key="player-previous"]') === previousBefore
  && panel.shadowRoot.querySelector('[data-focus-key="player-toggle"]') === toggleBefore
  && panel.shadowRoot.querySelector(".progress-range") === progressBefore;
const statePatched = panel.shadowRoot.querySelector(".player-state")?.textContent === "Ready"
  && !panel.shadowRoot.querySelector(".disc")?.classList.contains("disc-spinning");
panel.themeMode = "dark";
panel.notice = { key: "syncComplete", values: {}, error: false };
panel._render();
const noticeBefore = panel.shadowRoot.querySelector(".notice");
const fullTreeStable = panel.shadowRoot.querySelector("main.panel") === mainBefore
  && panel.shadowRoot.querySelector(".library-pane") === libraryBefore
  && panel.shadowRoot.querySelector(".queue-pane") === queueBefore
  && panel.shadowRoot.querySelector(".disc-cover img") === discImageBefore
  && panel.shadowRoot.querySelector(".notice")?.textContent.includes("Library sync completed.")
  && mainBefore.dataset.theme === "dark";
progressBefore.blur();
panel._applyQueue({ ...panel.queue, position: 20 });
const settledRangePatched = progressBefore.value === "20"
  && panel._seekPreview === null
  && progressBefore.dataset.localEditing === undefined;
panel.entryId = "synthetic-entry";
panel._initializedEntry = "synthetic-entry";
let menuToggled = false;
document.addEventListener("hass-toggle-menu", () => { menuToggled = true; }, { once: true });
panel.narrow = true;
panel.narrow = true;
panel.shadowRoot.querySelector(".menu-button").click();
const mobileMenuWorks = menuToggled && panel.hasAttribute("narrow");
const narrowNotSticky = getComputedStyle(queueBefore).position === "static";
const mobilePlaylistCompact = desktopPlaylistCoverBefore !== null
  && panel.shadowRoot.querySelector(".playlist-cover") === null;
panel.hass = { connection: {} };
panel.panel = { config: { entry_id: "synthetic-entry", title: "Synthetic Music", language: "zh-Hans" } };
const haPropertiesStable = panel.shadowRoot.querySelector(".library-pane") === libraryBefore;
const panelTitleWorks = panel.shadowRoot.querySelector("h1")?.textContent === "Synthetic Music";
const panelLanguageWorks = panel.shadowRoot.querySelector(".tab")?.textContent === "歌单"
  && panel.shadowRoot.querySelector(".notice") === noticeBefore
  && panel.shadowRoot.querySelector(".notice")?.textContent.includes("曲库同步已完成。");
let playlistCommand = null;
let transportAction = null;
panel._call = async (command, fields = {}) => {
  if (command === "playlist_tracks") return {
    items: [
      { id: "track-duplicate", title: "Synthetic First" },
      { id: "track-duplicate", title: "Synthetic Selected" },
    ],
    total: 2,
  };
  if (command === "queue_playlist") playlistCommand = fields;
  if (command === "queue_control") transportAction = fields.action;
  return { ...panel.queue, revision: Number(panel.queue.revision || 0) + 1 };
};
toggleBefore.click();
await new Promise((resolve) => setTimeout(resolve, 30));
const listenerPatched = transportAction === "play";
const mode = panel.shadowRoot.querySelector(".mode-button");
mode.focus();
mode.click();
await new Promise((resolve) => setTimeout(resolve, 30));
const playerControlPreserved = panel.shadowRoot.activeElement?.dataset.focusKey === "player-mode";
const controlClickStable = panel.shadowRoot.querySelector(".library-pane") === libraryBefore;
const cover = panel.shadowRoot.querySelector(".playlist-card");
cover.focus();
cover.click();
await new Promise((resolve) => setTimeout(resolve, 30));
const entered = panel.shadowRoot.activeElement?.dataset.focusKey === "playlist-back";
panel.shadowRoot.querySelectorAll(".track-primary")[1].click();
await new Promise((resolve) => setTimeout(resolve, 30));
const exactOccurrence = playlistCommand?.start_track_id === "track-duplicate" && playlistCommand?.start_index === 1;
panel.shadowRoot.querySelector(".back").click();
await new Promise((resolve) => setTimeout(resolve, 30));
const returned = panel.shadowRoot.activeElement?.dataset.focusKey === "playlist-card:playlist-one";
document.body.dataset.focusResult = densityAwareCovers && desktopSticky && narrowNotSticky && mobileMenuWorks && mobilePlaylistCompact && localQueueRefresh && coversStable && controlsStable && activeRangeStable && settledRangePatched && statePatched && fullTreeStable && listenerPatched && haPropertiesStable && panelTitleWorks && panelLanguageWorks && controlClickStable && playerControlPreserved && entered && exactOccurrence && returned ? "pass" : \`sizes=\${densityAwareCovers}:\${coverSizes.join("-")};sticky=\${desktopSticky};narrow-sticky=\${narrowNotSticky};menu=\${mobileMenuWorks};compact=\${mobilePlaylistCompact};local=\${localQueueRefresh};covers=\${coversStable};controls=\${controlsStable};range=\${activeRangeStable};settled=\${settledRangePatched};state=\${statePatched};tree=\${fullTreeStable};listener=\${listenerPatched};props=\${haPropertiesStable};title=\${panelTitleWorks};language=\${panelLanguageWorks};click=\${controlClickStable};control=\${playerControlPreserved};entered=\${entered};occurrence=\${exactOccurrence};returned=\${returned}\`;
</script></body></html>`;

  try {
    await writeFile(fixture, html, "utf8");
    const { stdout } = await execFileAsync(browser, [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--window-size=1280,900",
      "--dump-dom",
      "--virtual-time-budget=2500",
      new URL(`file://${fixture}`).href,
    ], { maxBuffer: 4 * 1024 * 1024, timeout: 15000 });
    assert.match(stdout, /data-focus-result="pass"/, stdout);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
