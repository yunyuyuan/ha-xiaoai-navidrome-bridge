# XiaoAI Navidrome for Home Assistant

[![Open your Home Assistant instance and add this repository to HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yunyuyuan&repository=ha-xiaoai-navidrome-bridge&category=integration)
[![Home Assistant 2026.8+](https://img.shields.io/badge/Home%20Assistant-2026.8%2B-18BCF2.svg)](https://www.home-assistant.io/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**XiaoAI Navidrome** is a custom Home Assistant integration installed through HACS. It enables XiaoAI speakers to play individual Navidrome tracks and playlists, while providing a complete library, queue, and output-device interface in the Home Assistant sidebar.

Home Assistant directly manages configuration, indexing, the queue, voice events, and player-state synchronization. **No standalone service container, long-lived Home Assistant access token, REST YAML, or additional reverse-proxy route is required.** The integration uses Navidrome's native time-limited shared streams to send public audio URLs without query parameters or Subsonic credentials to the speaker. Navidrome v0.63.2 provides the public `/share/s/<signed-id>` stream and Range handling.[1] [2]

## Features

| Capability | Implementation |
|---|---|
| HACS and UI configuration | Config Flow, reauthentication, and Options Flow; no handwritten secrets or YAML |
| Tracks and playlists | Home Assistant native service actions, voice phrases, and the sidebar Panel use the same queue |
| Audio URLs | Navidrome native time-limited MP3 shared streams; URLs contain no `?`, `&`, username, salt, or Subsonic token |
| Persistent queue | Persisted in Home Assistant `.storage`; contents are restored after restart, while playback remains stopped |
| Queue controls | Previous, next, stop, clear, jump, play next, append, shuffle, repeat one, and repeat queue |
| State synchronization | Listens directly to HA `state_changed`; an external pause or stop immediately cancels automatic track advancement, with no polling, long connection, or webhook |
| Multilingual matching | NFKC, case normalization, Simplified/Traditional Chinese conversion, full Chinese pinyin, Japanese readings, kana, romanization, and character distance |
| Misplay prevention | Refuses automatic playback when confidence is low or the candidate-score gap is insufficient |
| Optional semantic matching | Supports Ollama and OpenAI-compatible embeddings; automatically falls back to lexical matching when a model fails |
| Native Panel | Light and dark themes, responsive layout, artwork, details, playlists, queue, and dynamic player selection |
| Permission boundary | The Panel, WebSocket commands, native service actions, and artwork proxy are restricted to Home Assistant administrators |

## Architecture

```text
XiaoAI conversation sensor ──state_changed──┐
Home Assistant native service actions ──────┼──> HACS integration
HA sidebar Panel ──authenticated WebSocket──┘       │
                                                   ├── Local multilingual index
                                                   ├── HA .storage persistent queue
                                                   ├── Optional Ollama / OpenAI embeddings
                                                   └── Navidrome API creates time-limited MP3 shares
                                                              │
HA media_player.play_media <── query-free share URL ─────────┘
             │
             └──> XiaoAI speaker fetches audio directly from Navidrome `/share/s/...`
```

The Panel calls integration WebSocket commands through the existing Home Assistant login session and never accesses the Navidrome password. The speaker receives only the time-limited share capability URL for the active queue. See [`docs/architecture.md`](docs/architecture.md) for the complete design.

## Prerequisites

| Component | Requirement |
|---|---|
| Home Assistant | **2026.8.0 or later** |
| Installation method | HACS installed; alternatively, copy `custom_components/xiaoai_navidrome` manually |
| Navidrome | **v0.63.2 or later**, reachable from Home Assistant |
| Navidrome sharing | `EnableSharing=true`; enabled by default upstream. The reverse proxy must permit `/share/`.[3] |
| Public share address | The speaker must be able to reach a public `/share/` route. If internal and external addresses differ, enter the HTTPS endpoint used by the speaker as the external share address. The integration rewrites strictly validated `/share/s/` paths from Navidrome M3U output to that endpoint.[4] |
| Playback entity | Supports `media_player.play_media` and either `media_pause` or `media_stop` |
| Voice entity | Optional; a conversation `sensor` supplied by the Mi Home integration whose state contains XiaoAI-recognized text |

Create a dedicated ordinary Navidrome user for this integration and grant access only to the media libraries that it must play. Navidrome shares inherit the creator's media-library access scope.[3]

## Installation

### 1. Install through HACS

In HACS, open **Integrations → menu in the upper-right corner → Custom repositories**, then enter:

```text
https://github.com/yunyuyuan/ha-xiaoai-navidrome-bridge
```

Select the **Integration** category, download the latest release, and restart Home Assistant. HACS custom integration repositories require runtime files in a single `custom_components/<domain>/` directory; this repository follows that layout.[5]

For a manual installation, copy the complete `custom_components/xiaoai_navidrome` directory to:

```text
/config/custom_components/xiaoai_navidrome
```

Then restart Home Assistant.

### 2. Add the integration in Home Assistant

Open **Settings → Devices & services → Add integration → XiaoAI Navidrome**. The setup wizard completes configuration in two steps:

| Step | Contents |
|---|---|
| Navidrome connection | API server address, optional external share address, username, password, and TLS certificate validation |
| Playback and matching | Sidebar title, visibility setting, Panel language, default XiaoAI player, optional conversation sensor, voice prefixes, queue parameters, and optional embeddings |

Connection validation checks Subsonic authentication, the native Navidrome login, and creation and deletion of a five-minute test share from a non-empty library. If any step fails, the Home Assistant log identifies `Subsonic ping`, `native login`, `library probe`, or `share probe`. Protocol errors also include a fixed `reason` code, but passwords, share IDs, and complete URLs are not logged. After setup, the integration synchronizes the library in the background; the current index remains available during refresh.

When Navidrome is published through a reverse proxy, enter the HTTPS address that the speaker can also reach, for example:

```text
https://<public-share-host>
```

When the internal Navidrome address used by Home Assistant differs from the address used by the speaker, you can also set the following in Navidrome:

```text
ND_SHAREURL=https://<public-share-host>
```

The **Navidrome address** on the first Config Flow page is the address Home Assistant uses for API requests. It can be `127.0.0.1`, a LAN IP address, or a hostname resolving to an internal IP address. The **external Navidrome share address** is the endpoint from which the speaker downloads audio. When provided, the integration obtains a query-free `/share/s/` signed path from Navidrome M3U output, validates it strictly, and rewrites that path to the public endpoint. M3U output may contain an internal hostname, a different reverse-proxy hostname, or a relative path. When this field is blank, the integration uses the only consistent origin returned in the M3U output. In all cases, authentication, library access, share creation, and M3U retrieval always use the internal API address. Ensure that the public reverse proxy permits `/share/`.

### 3. Initial check

After restarting, open the configured sidebar page (the default title is **XiaoAI Music**). Confirm the connection status at the top of the Panel, select an output speaker in the queue card, and click **Sync library**. If a player was selected during configuration, the Panel displays that selection immediately.

## Usage

### Native sidebar Panel

The Panel uses English by default, opens the playlists page, and places the **Playlists** tab before **Tracks**. The page supports paginated libraries and playlists, search, artwork and details, and a complete player with a rotating CD. Previous, play/pause, next, playback mode, and clear-queue controls use Material Design Icons. Volume, mute, and seek controls are dynamically enabled according to the capabilities reported by the current Home Assistant `media_player`; when native `SEEK` is unavailable, the progress control remains read-only. On desktop, playlists are displayed as artwork cards. On mobile, a compact single-column list is used without playlist-artwork elements; tapping a row opens its details, and existing playlist artwork is removed in place when the viewport changes from wide to narrow. For other artwork, Navidrome thumbnails from 64 to 384 px are requested according to display use and device pixel density, capped at 1.5×, to avoid transferring images far larger than their display size. Artwork Blobs are cached and reused across Panel navigation within the same Home Assistant browser page, so returning to a page does not download an already-cached artwork size again; object URLs are released together when the page is actually unloaded. All state, notifications, theme changes, and data refreshes update the existing DOM in place rather than replacing the root tree, queue container, CD, buttons, sliders, or identical artwork nodes; repeated layout properties delivered by Home Assistant also do not rebuild the page. When leaving and returning to the Panel, it immediately resubscribes to the queue and reads a local snapshot; unfinished commands from the old page do not block new operations, while library and playlist data refresh in the background. In the desktop two-column layout, the queue panel on the right is sticky with a `12px` top offset. Single-column and mobile layouts remain in normal flow. On mobile, a Home Assistant sidebar menu is available in the upper left, and the player and queue appear above the library. The theme may follow Home Assistant or be fixed to light or dark.

The page is registered by the integration rather than being a Lovelace dashboard, so it does not appear in Home Assistant dashboard management. Open **Settings → Devices & services → XiaoAI Navidrome → Configure** to change the sidebar and page titles, switch between English and Simplified Chinese, or disable **Show sidebar panel**. Language can be changed only on this configuration page; there is no second language entry point on the dashboard or in the Panel. Disabling the option removes only the sidebar entry. Voice playback, service actions, the persistent queue, and automatic track advancement continue to operate; re-enabling the same option restores the entry.

| Panel action | Behavior |
|---|---|
| Play a track now | Replaces the queue with that track and starts playback |
| Play next | Inserts the track after the current track |
| Add to queue | Appends the track to the end of the queue |
| Click a track's artwork, title, or metadata | Immediately plays that track in the library; in a playlist, plays the complete playlist beginning with that track, while shuffle randomizes only following tracks |
| Click a playlist card or mobile playlist row | Opens the track list for that playlist |
| Click a queue track | Leaves queue order unchanged, moves the current pointer, and starts playback |
| Playback mode button | Cycles among sequential queue repeat, shuffle, and repeat one; sequential mode returns to the first track after the last track |
| Progress / volume / mute | Availability depends on `SEEK`, `VOLUME_SET`, and `VOLUME_MUTE` capabilities of the selected player |
| Pause | Pauses or stops the speaker while retaining the queue; resumes from the paused position when native resume is available |
| Clear | Stops the speaker and removes the entire queue |

The Home Assistant backend owns the queue and index, so closing the browser does not interrupt automatic track advancement. Queue operations use revision-based optimistic concurrency control. Track and playlist voice matching is also bound to the revision at trigger time; therefore, a late result cannot overwrite a newer action if a pause, clear, queue replacement, or other control occurs while matching. Periodic refreshes of the same recent conversation-sensor record also do not trigger duplicate playback.

### Voice phrases

After selecting a conversation sensor in Config Flow, no automation YAML is required. The default recognized phrases are shown below. These Chinese literals are the default user-configurable voice prefixes and command examples; they are intentionally retained because the conversation sensor recognizes XiaoAI speech text.

```text
小爱同学，播放家庭音乐<曲目名称><歌手名称>
小爱同学，播放家庭歌单<歌单名称>
小爱同学，上一首家庭音乐
小爱同学，家庭音乐上一首
小爱同学，下一首家庭音乐
小爱同学，家庭音乐下一首
小爱同学，停止家庭音乐
小爱同学，家庭音乐停止
```

Tracks, playlists, the Panel, and service actions use one shared Home Assistant queue. A voice-started playlist is therefore synchronized to the Panel immediately, and previous, next, and stop control the same state. The integration deduplicates events using the conversation timestamp, conversation ID, or sequence where available; otherwise it uses Home Assistant's state-change time. Stale records are rejected, and attribute refreshes for an already processed event do not trigger duplicate playback.

If an entity state contains extra punctuation or polite wording, the integration extracts the query after the last configured voice prefix. The two prefixes can be changed in **Devices & services → XiaoAI Navidrome → Configure**.

### Home Assistant service actions

The integration registers the following native actions for automations, scripts, and Developer Tools:

| Action | Parameters | Returns |
|---|---|---|
| `xiaoai_navidrome.play` | `query`, optional `media_player` | Match details and queue state |
| `xiaoai_navidrome.play_playlist` | `query`, optional `media_player` | Playlist match and queue state |
| `xiaoai_navidrome.previous` | None | Queue state |
| `xiaoai_navidrome.next` | None | Queue state |
| `xiaoai_navidrome.pause` | None | Pauses and retains the queue and pointer |
| `xiaoai_navidrome.resume` | None | Resumes from the retained position and returns queue state |
| `xiaoai_navidrome.stop` | None | Queue state |
| `xiaoai_navidrome.clear_queue` | None | Queue state |
| `xiaoai_navidrome.sync_library` | None | Index state |

These global actions are registered as Home Assistant administrator services. Internal Home Assistant automations without a user context can still call them; ordinary non-administrator accounts cannot bypass Panel permissions through the generic WebSocket.

### Compact dashboard controls

No additional frontend card is required. On the home dashboard, use Home Assistant native **button cards** to call `xiaoai_navidrome.previous`, `xiaoai_navidrome.pause`, `xiaoai_navidrome.resume`, and `xiaoai_navidrome.next` separately. The integration also provides a `select` entity named **Quick play playlist**. Add it to an entity card, and selecting any Navidrome playlist replaces the shared queue by its exact playlist ID and starts playback immediately. After success, the selector returns to the **Play playlist** prompt, so the same playlist can be selected again. When playlist names are duplicated, an ordinal is added so that each option remains individually selectable; backend IDs are not displayed on the dashboard.

The select entity reads playlists when the integration loads and updates its options when the sidebar refreshes its playlist list; it does not poll the player. Dashboard-initiated playback continues to observe the integration's administrator permission boundary, while internal Home Assistant automations can call it normally.

Example:

```yaml
action: xiaoai_navidrome.play
data:
  query: "<track title> <artist>"
```

## Multilingual matching

Each track receives search keys for original metadata, Unicode NFKC, Simplified/Traditional Chinese conversion, full pinyin, Japanese readings, hiragana, katakana, and romanization. **Pinyin initials are not generated.** Transliteration keys participate only in identity-exact and character-distance matching, not high-score substring containment, reducing collisions among short strings.

Optional embeddings independently handle cross-language relationships with no character overlap. Semantic similarity cannot override a strong exact lexical match; the integration refuses automatic playback when the top score or the gap between candidates is insufficient. If a model is unavailable, a query continues through the lexical index. When the model name and track document are unchanged, synchronization reuses existing vectors and encodes only added or changed tracks.

See [`docs/local-model-research.md`](docs/local-model-research.md) for Ollama, Qwen3 Embedding, and low-power NAS configuration. Embeddings are not required; first verify the complete playback path with the default lexical index.

## State synchronization and automatic track advancement

Automatic track advancement uses the Navidrome track duration plus the configured inter-track buffer. The integration listens directly to Home Assistant `state_changed` events. While its internal queue is playing, it immediately stops the queue timer when the target player enters `paused`, `off`, `standby`, or `unavailable`, even if it briefly passes through `buffering`. The `idle` state, which is more likely at a natural track end, receives a five-second confirmation and is ignored near the expected track end to avoid disrupting normal advancement.

This mechanism uses no polling, Bridge webhook, or additional long-lived connection. It processes only the player selected for the active queue and uses the current track start time to discard stale state events.

## Security model

| Data or interface | Boundary |
|---|---|
| Navidrome password | Stored only in the Home Assistant Config Entry; diagnostics redact it |
| Subsonic token and salt | Used only for requests from HA to Navidrome; never sent to the Panel or speaker |
| Panel WebSocket | Uses the HA login session and requires administrator privileges |
| Artwork | Served through an HA-authenticated proxy with a response-size limit; the browser receives no Navidrome credentials |
| Audio share URL | A time-limited public capability URL without query parameters; anyone holding it can access it until expiry |
| Queue and index | Stored in HA `.storage`; contain neither the Navidrome password nor voice records |

The integration records active and pending-revocation share IDs in a private HA Store. It deletes unused Navidrome shares when replacing or clearing a queue, or when unloading. Temporary deletion failures are retried with exponential backoff during runtime, and revocation resumes on the next load after an unexpected shutdown. Any share that cannot be revoked still expires after the default six-hour lifetime. Do not publish an active share URL in an untrusted location.

## Troubleshooting

| Symptom | First checks |
|---|---|
| Config Flow reports that it cannot connect | Navidrome address, container networking, TLS certificate, and ordinary-user credentials |
| Invalid response message | Search HA logs for `Navidrome setup validation failed`, then use its validation stage to check the native Navidrome API, sharing feature, or `/share/` route |
| The Panel has a queue but the speaker is silent | Whether the speaker can reach the address generated by `ND_SHAREURL`; whether the player supports URL `play_media` |
| It advances after a pause | Whether the entity actually changes from `playing` to `paused/off/standby` in HA; download integration diagnostics and verify the entity ID |
| Newly added library content does not appear | Wait for the refresh interval, or call `xiaoai_navidrome.sync_library` / **Sync library** in the Panel |
| Embedding count does not increase | Whether the Ollama model is pulled and its URL is reachable from HA; model failure does not affect lexical synchronization |
| No voice response | The current conversation-sensor state, configured phrase prefixes, and integration warnings in HA logs |

Obtain redacted status from **Settings → Devices & services → XiaoAI Navidrome → Download diagnostics**. Diagnostics do not include passwords, API keys, track metadata, query text, or voice records.

During initialization, search **Settings → System → Logs** for `xiaoai_navidrome`. If the Home Assistant container is named `homeassistant`, you can also run:

```bash
docker logs --since 10m homeassistant 2>&1 | grep -iE 'xiaoai_navidrome|Navidrome setup validation'
```

`127.0.0.1` always refers to the network namespace containing the Home Assistant process. It can reach host ports when Home Assistant uses host networking. With a standard Docker bridge, HA OS, or remote Navidrome, enter the LAN address or service name that is actually reachable from that environment.

## Development and release

This repository contains one HACS integration. Run `make setup` to create the test environment, then run `make check` to execute Ruff, Mypy, Home Assistant 2026.8.3 tests, frontend syntax checks, and Node unit tests. HACS and Hassfest are additionally validated in GitHub Actions. See [`docs/releasing.md`](docs/releasing.md) for release rules.

## References

[1]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/public.go "Navidrome v0.63.2 public share routes"
[2]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/handle_streams.go "Navidrome v0.63.2 public shared stream handler"
[3]: https://www.navidrome.org/docs/usage/features/sharing/ "Navidrome sharing feature documentation"
[4]: https://www.navidrome.org/docs/usage/configuration/options/ "Navidrome configuration options"
[5]: https://www.hacs.xyz/docs/publish/integration/ "HACS integration repository requirements"
[6]: https://developers.home-assistant.io/docs/config_entries_config_flow_handler/ "Home Assistant Config Flow documentation"
[7]: https://developers.home-assistant.io/docs/integration_listen_events/ "Home Assistant event subscription documentation"
