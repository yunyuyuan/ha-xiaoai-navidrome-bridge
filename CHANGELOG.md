# Changelog

All significant changes are documented in this file. Version tags follow Semantic Versioning.

## [1.0.13] - 2026-09-06

### Changed

- Public documentation is now English-first, including the README, architecture, Panel guide, local-model guide, release process, and changelog.
- Home Assistant remains fully localized through English and Simplified Chinese translation files. The quick-play playlist prompt now uses a translated SelectEntity state instead of a hard-coded display language.
- HACS validation now runs without disabled checks in both mainline CI and the release workflow; the HACS manifest declares the integration's `CN` country scope.

## [1.0.12] - 2026-09-05

### Added

- The Panel now provides English and Simplified Chinese interfaces; installation and configuration default to English. The language can be selected only on the integration configuration page; no switch is added to the Home page or within the Panel.

### Fixed

- The cover-art Blob cache now lasts for the current Home Assistant frontend module lifecycle. Leaving and returning to the Panel reuses the same bounded cache instead of redownloading cache-hit covers at the same size; object URLs are released together when the page is actually unloaded.

## [1.0.11] - 2026-09-02

### Changed

- The first option and the post-playback idle option of the quick-play playlist selector entity now use a clear **Play playlist** prompt rather than a dash. Playlists with identical names remain independently selectable through automatic numbering.

## [1.0.10] - 2026-09-02

### Added

- Added the native `xiaoai_navidrome.pause` action and a quick-play playlist selector entity that can be added directly to the Home Assistant dashboard. Selecting a playlist replaces the shared queue with that exact playlist and starts playback immediately; concurrent playlist refreshes are coalesced into a single request.

### Changed

- The sidebar library now opens on the playlists page by default, and the **Playlists** tab precedes the **Tracks** tab.
- On mobile, playlists use a compact single-column list without cover elements; the full row opens playlist details. Existing playlist covers are removed in place when switching from a wide to a narrow screen.

## [1.0.9] - 2026-09-01

### Added

- Integration configuration now includes a sidebar Panel visibility toggle and name. The name is used for both the Home Assistant sidebar and the Panel page title; hiding the entry does not affect voice control or the background queue.

### Changed

- The queue panel in the desktop two-column layout uses `position: sticky` with a `12px` top offset. Single-column and narrow-screen layouts retain normal document flow.

## [1.0.8] - 2026-09-01

### Fixed

- Leaving the Panel now releases the current initialization generation in sync. Returning to the page immediately establishes a new queue subscription and local state snapshot rather than waiting for the next Home Assistant state update.
- On disconnect, pending frontend command waits are cancelled and the serialized command chain is released. Operations during reconnection wait until the current connection is ready instead of first being shown as failures.
- Library and playlist data now refresh in the background and no longer delay queue and player-control readiness.

## [1.0.7] - 2026-08-31

### Fixed

- Track, queue, player, detail, and playlist covers select 64–384 px Navidrome thumbnails according to context and device pixel density. Density is capped at 1.5×, rather than always downloading 600 px images.
- Mobile titles now include a Home Assistant sidebar menu button and follow Home Assistant narrow-screen and kiosk display rules.
- Repeated refreshes of the latest recognition record from the conversation sensor no longer replay the request. When no stable event field exists, the Home Assistant state-change timestamp is used as the event identity.
- Voice-match results for a track or playlist are bound to the queue revision that triggered the match. If a pause, clear, queue change, or other control occurs during matching, a late result cannot overwrite newer user operations.

## [1.0.6] - 2026-08-31

### Fixed

- All Panel rendering paths now reconcile the DOM in place. Queue and player events, notifications, themes, and data refreshes no longer replace the root tree, queue container, CD, buttons, sliders, or matching cover nodes, eliminating page and image flicker during continuous updates.
- The cover-object cache count limit now covers the full default queue while a total-byte limit continues to constrain memory. A progress-drag preview is not overwritten by status events or timers for the same track.

## [1.0.5] - 2026-08-31

### Fixed

- When a playlist track is clicked in shuffle mode, the selected track is fixed as the first queue item and only subsequent tracks are shuffled.
- When Home Assistant repeatedly sends narrow-screen layout attributes, only host styles are updated. Partial updates on the right reuse the existing CD and queue-cover nodes, so control operations no longer rebuild the full Shadow DOM or flicker covers.
- Removed the Play All, Play Next, and Add to Queue actions from the top of playlist details; per-track playback remains available.

## [1.0.4] - 2026-08-31

### Fixed

- Playback mode and clear-queue controls now use official Material Design Icons SVG paths, correcting icon outlines.
- Fixed the primary play/pause button becoming solid white on hover in light themes and the volume slider using the browser’s black default track.
- Volume commands use target-value feedback and bounded confirmation state, preventing the slider from immediately snapping back before Home Assistant refreshes entity attributes.
- Queue and player events update only the right-side area and reuse cached covers, preventing full-page and image flicker while operating controls.

## [1.0.3] - 2026-08-31

### Changed

- The track cover, title, artist, album, and duration area now form a complete playback target. In the library, a track plays immediately; in playlist details, the full playlist plays beginning with the selected track.
- A playlist cover directly opens its track list and provides hover, pressed, and keyboard-focus feedback.
- Track/playlist switching now uses a compact segmented control with a clear selected state, light- and dark-theme support, and arrow-key switching.
- Entering playlist details with the keyboard moves focus to the back control; returning to the list restores focus to the original playlist cover.
- Removed the duplicate current-track item at the top and changed the right-side control area to a rotating CD player with icon buttons for previous, play/pause, next, mode, clear, and related controls.
- Progress, volume, and mute controls are enabled according to the selected Home Assistant player’s capabilities. Player status continues to synchronize in real time through `state_changed` without polling.
- Shuffle and repeat are combined into one three-state mode button: sequential repeat, shuffle, and single-track repeat. In sequential mode, playback returns to the first item after the final item by default.

## [1.0.2] - 2026-08-31

### Fixed

- Separated the Navidrome API address from the speaker’s public playback endpoint. When an external sharing address is explicitly configured, the strictly validated `/share/s/` signed path is safely rewritten to that endpoint; the M3U no longer needs to return the same domain.
- Config Flow protocol-failure logs now include fixed `reason` codes that distinguish share API, M3U HTTP, encoding, count, URL, origin, and path errors, without logging URLs or temporary share identifiers.
- OpenCC and pykakasi dictionaries now load lazily in the first normalization task in a thread pool, preventing integration initialization from blocking the Home Assistant event loop.

## [1.0.1] - 2026-08-31

### Added

- Added the native `xiaoai_navidrome.resume` service, which resumes playback from the current position of a stopped queue.
- When Config Flow connection validation fails, Home Assistant logs the specific validation stage without credentials.
- Playback error states and voice-failure logs retain only fixed error categories and do not write temporary share identifiers or upstream response text.

### Fixed

- When the Navidrome API uses a private address and no public sharing address is explicitly provided, a consistent public share origin is safely identified from the test M3U.
- Dedicated cover containers, including playlist cover containers, always retain a base square size and the `object-fit: cover` cropping rule.

## [1.0.0] - 2026-08-31

### Added

- Native Home Assistant HACS integration, with all configuration completed through Config Flow, reauthentication, and Options Flow.
- Navidrome Subsonic/OpenSubsonic library, playlist, detail, and cover access, plus native time-limited MP3 share playback.
- Home Assistant sidebar playback Panel with search, playlists, covers, details, light and dark themes, a dynamic player, and responsive mobile layout.
- A Home Assistant `.storage` persistent queue supporting previous, next, stop, clear, seek, insert, append, shuffle, single-track repeat, and list repeat.
- Direct `state_changed` listening to synchronize player paused, stopped, and unavailable states, without player polling or additional persistent connections.
- Conversation-sensor voice control and native Home Assistant service actions available to administrators.
- Simplified/traditional Chinese conversion, complete Chinese Pinyin, Japanese readings, kana, rōmaji, and character-distance matching; Pinyin initials are not generated.
- Optional Ollama and OpenAI-compatible embeddings, with incremental vector reuse and lexical fallback on failure.
- Administrator WebSocket API, administrator cover proxy, bounded response bodies, strict share-origin validation, and redacted diagnostics.
- Ruff, Mypy, Home Assistant tests, Node frontend tests, Hassfest, and HACS GitHub Actions validation.

### Fixed

- Native Navidrome share creation and deletion use official trailing-slash routes, preventing redirects and invalid-response classification when directly accessing a private-network address.
- The Panel passes relative cover paths directly to Home Assistant `fetchWithAuth`, preventing the public Home Assistant address from being concatenated twice.
