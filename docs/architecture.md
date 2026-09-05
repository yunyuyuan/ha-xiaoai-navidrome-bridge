# Architecture

## Design Goals

The entire control plane runs within Home Assistant. The custom integration manages configuration, Navidrome access, multilingual indexing, the queue, voice events, player-state synchronization, and the Panel API. The audio data plane does not pass through Home Assistant or an additional proxy. Instead, the XiaoAI speaker reads the time-limited public share stream directly from Navidrome.

```text
conversation sensor ──┐
HA service actions ───┼──> XiaoAI Navidrome integration
HA native Panel ──────┘          │
                                 ├── Config Entry secrets
                                 ├── .storage index and queue
                                 ├── state_changed listeners
                                 ├── optional HTTP embeddings
                                 └── Navidrome Subsonic + native API
                                               │
                                               └── temporary MP3 share
                                                        │
HA media_player.play_media <── /share/s/<signed-id> ─────┘
             │
             └──> XiaoAI speaker downloads from Navidrome
```

## Home Assistant Runtime

Each Config Entry creates a runtime object containing a Navidrome client, a matching index, and a persistent playback queue. The integration manifest limits the integration to one Config Entry. This gives the sidebar Panel and service actions without an explicit `entry_id` a deterministic target.

| Lifecycle stage | Behavior |
|---|---|
| `async_setup_entry` | Validates Navidrome, restores the index, restores the queue in its stopped state, registers event listeners, and starts background synchronization. |
| Options update | Home Assistant reloads the Config Entry; it unloads the old runtime and rebuilds it with the new parameters. |
| Home Assistant shutdown or unload | Cancels synchronization and timer tasks, stops active output, and makes a best-effort attempt to delete temporary shares. |
| Home Assistant restart | Restores the track, queue position, shuffle mode, and repeat mode, but does not automatically resume audio. |

The only long-running work is cancellable background library synchronization and a single timer task for the current track. The integration does not establish its own persistent WebSocket, poll the player, or require a separate webhook.

## Navidrome API Responsibilities

The Subsonic/OpenSubsonic API authenticates with a token and salt. It handles ping, full-library pagination, search, playlists, track details, and artwork. The Navidrome native API uses a short-lived bearer token. It creates and deletes shares that can specify MP3 format, maximum bitrate, and expiration time.

Navidrome v0.63.2 public routes provide `/share/s/{id}` audio handling and the `/{id}/m3u` playlist. [1] Shared media files load tracks in the `ResourceIDs` request order and generate a signed public stream ID for each track. [2] [3]

When a queue first plays or its order changes, the integration creates one share for the complete track set and parses its M3U. M3U entries must be under `/share/s/` and must not contain query parameters, userinfo, fragments, control characters, or encoded path traversal. When no external share address is supplied in the Config Flow, all entries in the same M3U must use one unique, consistent origin. When an external share address is supplied, the integration retains only the signed paths that pass the preceding validation and rewrites them to the user-trusted public scheme, host, port, and base path. Home Assistant can therefore call the API through an internal address while the speaker consistently uses a separate public endpoint. Previous, next, and seek operations reuse the same URL set while the track ID order is unchanged and the share has more than five minutes remaining. Active shares and IDs pending revocation are written to the private Store. The integration deletes old shares when replacing or clearing a queue or shutting down the runtime. If deletion temporarily fails, it retries with exponential backoff from one to sixty minutes and continues revocation after restart.

## Library Synchronization

Library synchronization uses Navidrome's supported empty-query `search3` pagination extension. The existing index remains in use during synchronization. The integration replaces the in-memory snapshot and persists it only after every page has been fetched successfully. It rejects an overwrite when results are empty or when the new track count falls below the old index's safety ratio. This reduces the risk that partial results during a Navidrome scan corrupt the existing index.

The index is stored in the Home Assistant `Store`. It contains only track display metadata, normalized search keys, optional embeddings, and content fingerprints. It does not contain the Navidrome password, Subsonic token, user queries, or voice history. Existing vectors are reused when both the model identifier and content fingerprint are unchanged. Only new or changed tracks are re-encoded.

## Multilingual Retrieval

Queries and tracks each generate Unicode NFKC, case-folded, simplified/traditional Chinese conversion, full Pinyin, Japanese readings, Hiragana, Katakana, and romanization keys. Pinyin, kana, and romanization are identity transliterations. They participate only in exact and character-distance comparisons. High-scoring substring matches are permitted only for the original text and simplified/traditional surface variants. The index explicitly does not generate Pinyin initials.

Lexical and semantic channels are scored independently. Optional embeddings support cross-language recall when no characters overlap, but do not override strong exact lexical results. Automatic playback is constrained by both a first-candidate threshold and the score difference between the first and second candidates. If either condition is not met, service actions return an error. The voice path logs a redacted warning and does not play audio.

## Queue Consistency

An asynchronous operation lock serializes queue changes. Panel commands carry `expected_revision`, and stale revisions are rejected. Voice commands and native Home Assistant services do not rely on a browser revision, but still pass through the same lock. Share creation, the `media_player.play_media` call, state persistence, and timer updates are performed within the same serialized operation. This prevents a stop operation from interleaving with a slow share request and restarting playback.

| State | Meaning |
|---|---|
| `stopped` | No automatic-advance task runs; the queue and current position may be retained. |
| `loading` | A share is being created or parsed, and a URL is being sent to the Home Assistant player. |
| `playing` | The current URL has been issued, and automatic advance is scheduled using the metadata duration. |
| `error` | A share, Navidrome, or Home Assistant service call failed; an error summary is written to the queue state. |

Shuffle mode shuffles only the unplayed portion. Single-track repeat keeps the current item during automatic advance. List repeat returns from the last item to the first. Non-transport queue changes still rebuild the timer using the current `ends_at` and the new revision. This prevents automatic advance from being lost after enabling repeat or adding tracks.

## Player-State Synchronization

The runtime subscribes directly to Home Assistant's global `state_changed` event, but processes only the `media_player` selected by the current queue. During internal queue playback, if the entity enters `paused`, `off`, `standby`, or `unavailable`, the integration stops immediately and cancels the timer. It does not require the event's previous state to be exactly `playing`, so `playing → buffering → paused` also terminates correctly. Because `idle` may indicate a natural track end, the integration first excludes a thirty-second window before and after the expected end, then requires the state to remain continuous for five seconds.

An event timestamp must not precede the current track's `started_at`. After entering the queue lock, state handling validates the current player, current state, and event timestamp again. This prevents a delayed pause event for a previous track from stopping a newly started track.

## Panel and Permissions

The integration registers an administrator-visible Home Assistant sidebar Panel. The Home Assistant HTTP component serves static JavaScript and CSS. Data and commands use a custom WebSocket API and therefore inherit the Home Assistant login session. Every WebSocket command uses `require_admin`, and the artwork proxy also requires administrator access.

The Panel does not store the Navidrome password, a Home Assistant token, or a separate Panel token. Track text is written through DOM `textContent`. Artwork is retrieved as a Blob through an authenticated Home Assistant request and displayed using a bounded object-URL cache.

## Security Boundaries

| Boundary | Control |
|---|---|
| Home Assistant to Navidrome | TLS verification is enabled by default. Config Flow can explicitly disable it, which is suitable only for a trusted network. |
| Panel to Home Assistant | The existing Home Assistant login session, administrator WebSocket permissions, and administrator HTTP view. |
| Speaker to Navidrome | Time-limited share URLs that contain neither query parameters nor account credentials. |
| Persistent data | Home Assistant private `Store` with atomic writes; diagnostics exclude sensitive configuration and library contents. |
| HTTP responses | JSON, M3U, artwork, and embeddings each have response-body limits and request timeouts. |
| Background tasks | Config Entry unload cancels and awaits tasks; exceptions do not prevent Home Assistant from shutting down. |

A share URL is a temporary bearer capability: even without query parameters, any client that obtains the complete URL while it is valid can access the corresponding media. Use HTTPS, and do not expose logs or URLs in untrusted locations.

## References

[1]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/public.go "Navidrome v0.63.2 public share routes"
[2]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/handle_streams.go "Navidrome v0.63.2 shared stream handler"
[3]: https://github.com/navidrome/navidrome/blob/v0.63.2/persistence/share_repository.go "Navidrome v0.63.2 share media ordering"
[4]: https://developers.home-assistant.io/docs/config_entries_index/ "Home Assistant Config Entry lifecycle"
[5]: https://developers.home-assistant.io/docs/integration_listen_events/ "Home Assistant event subscriptions"
[6]: https://developers.home-assistant.io/docs/frontend/custom-ui/creating-custom-panels/ "Home Assistant custom panel development"
