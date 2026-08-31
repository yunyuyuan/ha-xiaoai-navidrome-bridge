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
  RequestGate,
  coverApiPath,
  coverClassNames,
  cycleRepeat,
  formatDuration,
  queueStatus,
  responseItems,
  trackPrimaryCommand,
  voiceSafeText,
} = await import(moduleUrl);

test("voiceSafeText removes control and directional characters while preserving readable synthetic metadata", () => {
  assert.equal(voiceSafeText("  Demo\u0000 Artist\u202e  \n"), "Demo Artist");
  assert.equal(voiceSafeText(null, "Untitled"), "Untitled");
  assert.equal(voiceSafeText("\t", "Untitled"), "Untitled");
});

test("cycleRepeat uses the exact off, all, one sequence and recovers from invalid values", () => {
  assert.equal(cycleRepeat("off"), "all");
  assert.equal(cycleRepeat("all"), "one");
  assert.equal(cycleRepeat("one"), "off");
  assert.equal(cycleRepeat("unexpected"), "off");
});

test("formatDuration produces stable compact timestamps", () => {
  assert.equal(formatDuration(0), "0:00");
  assert.equal(formatDuration(65.9), "1:05");
  assert.equal(formatDuration(-1), "0:00");
});

test("cover requests use one relative authenticated Home Assistant path", async () => {
  assert.equal(
    coverApiPath("entry / one", "cover / two"),
    "/api/xiaoai_navidrome/cover/entry%20%2F%20one/cover%20%2F%20two",
  );
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

test("track primary targets select context-appropriate playback mutations", () => {
  assert.deepEqual(trackPrimaryCommand("library", "track-one"), {
    command: "queue_add",
    fields: { track_ids: ["track-one"], position: "replace" },
  });
  assert.deepEqual(trackPrimaryCommand("playlist", "track-two", "playlist-one"), {
    command: "queue_playlist",
    fields: {
      playlist_id: "playlist-one",
      position: "replace",
      start_track_id: "track-two",
    },
  });
  assert.equal(trackPrimaryCommand("playlist", "track-two"), null);
  assert.equal(trackPrimaryCommand("library", ""), null);
});

test("panel exposes direct track and playlist-cover targets with segmented tabs", async () => {
  const source = await readFile(moduleUrl, "utf8");
  const css = await readFile(
    new URL("../custom_components/xiaoai_navidrome/frontend/panel.css", import.meta.url),
    "utf8",
  );
  assert.equal(source.includes('className: "track-primary"'), true);
  assert.equal(source.includes('className: "playlist-cover-button"'), true);
  assert.equal(source.includes('role: "tab"'), true);
  assert.match(css, /\.tab\[aria-selected="true"\]/);
  assert.match(css, /\.track-primary:hover/);
  assert.match(css, /\.playlist-cover-button:hover/);
});

test("playlist navigation preserves keyboard focus across Shadow DOM rerenders", async (context) => {
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
  assert.equal(source.includes("</script>"), false);
  const directory = await mkdtemp(join(tmpdir(), "xiaoai-panel-focus-"));
  const fixture = join(directory, "focus.html");
  const html = `<!doctype html>
<html><body><script type="module">
${source}
const panel = document.createElement("xiaoai-navidrome-panel");
document.body.append(panel);
panel.libraryTab = "playlists";
panel.playlists = [{ id: "playlist-one", name: "Synthetic Playlist", song_count: 1 }];
panel._render();
const cover = panel.shadowRoot.querySelector(".playlist-cover-button");
cover.focus();
cover.click();
await new Promise((resolve) => setTimeout(resolve, 30));
const entered = panel.shadowRoot.activeElement?.dataset.focusKey === "playlist-back";
panel.shadowRoot.querySelector(".back").click();
await new Promise((resolve) => setTimeout(resolve, 30));
const returned = panel.shadowRoot.activeElement?.dataset.focusKey === "playlist-cover:playlist-one";
document.body.dataset.focusResult = entered && returned ? "pass" : \`entered=\${entered};returned=\${returned}\`;
</script></body></html>`;

  try {
    await writeFile(fixture, html, "utf8");
    const { stdout } = await execFileAsync(browser, [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--dump-dom",
      "--virtual-time-budget=1000",
      new URL(`file://${fixture}`).href,
    ], { maxBuffer: 4 * 1024 * 1024, timeout: 15000 });
    assert.match(stdout, /data-focus-result="pass"/, stdout);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
