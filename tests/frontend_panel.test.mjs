import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const moduleUrl = new URL("../custom_components/xiaoai_navidrome/frontend/panel.js", import.meta.url);
const {
  RequestGate,
  coverApiPath,
  coverClassNames,
  cycleRepeat,
  formatDuration,
  queueStatus,
  responseItems,
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
