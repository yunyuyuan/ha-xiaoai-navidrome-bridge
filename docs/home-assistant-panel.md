# Home Assistant Native Playback Panel

The sidebar playback page is registered directly with Home Assistant by the custom integration. It is not an iframe and does not depend on an external page, a separate token, or a Home Assistant long-lived access token.

## Operating Model

Home Assistant serves the Panel JavaScript and CSS from a static path. Browsing, search, playlists, the queue, and control commands are sent through the Home Assistant WebSocket API to the same Config Entry. A Home Assistant custom Panel receives the standard `hass` frontend object, and integration WebSocket commands inherit the identity of the currently signed-in user. [1] [2]

All Panel WebSocket commands and the cover-art HTTP proxy require administrator privileges. The sidebar entry is also registered with `require_admin=true`, so non-administrators cannot see or invoke this control interface.

## Sidebar Management

This page is a native `panel_custom` registered by the integration, not a Lovelace dashboard; therefore, it does not appear on Home Assistant’s **Dashboards** management page. Administrators can open **Settings → Devices & services → XiaoAI Navidrome → Configure** to change the **sidebar and panel name**, choose the **panel language**, or disable **Show sidebar panel**. The name is used for both the sidebar entry and the page title. The panel language supports only English and Simplified Chinese, defaults to English, and can be changed only on this configuration page; neither the home page nor the Panel provides a language control. Disabling the switch unregisters only the sidebar entry. The integration runtime, voice commands, service actions, persistent queue, and automatic track advancement continue to run. Re-enabling the switch restores the entry after the configuration is reloaded.

## Page Components

| Area | Function |
|---|---|
| Header status | Home Assistant sidebar menu on mobile, integration name, index synchronization status, and day/night/follow-system theme selection |
| Player | Rotating CD, current track, progress, previous, play/pause, next, three-state playback mode, volume, and mute |
| Playback queue | Output player, selectable track queue, and an icon-only clear action |
| Library | Playlist and track tabs, with playlists open by default; tracks support local-index pagination and search, and clicking the cover, title, or metadata area plays the track immediately |
| Playlists | Navidrome playlist search; on desktop, click the entire cover card, and on mobile, click a compact list row without cover art to open the track list; click a playlist track’s main area to play the entire playlist beginning with that track |
| Details | Cover art, title, artist, album, duration, format, bitrate, year, and other available metadata |

In the wide-screen two-column layout, the library is on the left and the queue is on the right. The right-side queue panel uses `position: sticky` with `top: 12px`, keeping player controls available while the page scrolls. A one-column layout at widths of `1050px` or less, and a layout marked narrow by Home Assistant, explicitly restore `position: static` and place the queue above the library. Mobile playlists use single-column text rows. The initial narrow-screen render does not create playlist-cover nodes. When switching from wide to narrow, the library is redrawn in place and existing cover nodes are removed. On narrow screens, the left side of the header displays a menu button that dispatches the native `hass-toggle-menu` event; the button remains hidden in kiosk mode. [8] [9]

## Home Dashboard Controls

The integration does not register additional Lovelace frontend resources. Pause, resume, previous, and next actions on the home page can use native Home Assistant button cards to call `xiaoai_navidrome.pause`, `xiaoai_navidrome.resume`, `xiaoai_navidrome.previous`, and `xiaoai_navidrome.next` directly.

The dynamic playlist entry uses a standard `SelectEntity`. Its `options` come from a short-lived runtime playlist cache, and ordinary attribute reads access memory only. The runtime refreshes the cache only when the entity is first added or explicitly updated, in accordance with Home Assistant entity requirements. [10] A single-flight lock coalesces concurrent refreshes, and an older request cannot overwrite a newer name mapping. Each display name maps to an exact playlist ID. Duplicate names receive stable sequence numbers, and IDs are not exposed as entity options. A selection calls the same `async_add_playlist(..., "replace")` used by the Panel, so it shares the persistent queue, revision, and player. After success, the entity returns to a fixed prompt localized by Home Assistant, so the same playlist can be selected again. Playlist names matching a supported localized prompt receive a sequence number. Calls with a user identity require administrator privileges, while Home Assistant internal automations without a user identity can still run.

## Queue Semantics

| Action | Queue change | Plays immediately? |
|---|---|---|
| Track: “Play now” | Clears the queue and replaces it with the selected track | Yes |
| Track: “Play next” | Inserts the track after the current pointer | No |
| Track: “Add to queue” | Appends the track to the end of the queue | No |
| Play a playlist track | Replaces the queue with the complete playlist and places the selected track first; shuffle mode randomizes only subsequent tracks | Yes |
| Click a queued track | Leaves order unchanged and moves only the current pointer | Yes |
| Previous / next | Moves the pointer according to the current order | Yes |
| Pause | Retains the track and pointer | No; automatic advancement stops |
| Resume | Retains the track and pointer | Yes; resumes from the paused position when the player supports `PLAY`, otherwise sends the current track again |
| Clear | Removes all items and stops output | No |
| Sequential loop | Plays in queue order and returns to the first track after the final track | Yes |
| Shuffle | Shuffles unplayed items and randomizes the next cycle | Keeps the current track playing |
| Repeat one | Plays the current item again after automatic track completion | Yes |

Voice commands, Home Assistant service actions, and the Panel use the same backend queue. After a playlist is started by voice, the Panel receives queue state in real time through its WebSocket subscription; it does not need to poll the page or refresh the browser. The conversation sensor may periodically refresh the latest recognition record. The integration deduplicates records using the record timestamp, conversation ID, or sequence in that order; if none is present, it uses Home Assistant’s state-change time. An attribute refresh cannot run the same music-request command again.

## Player Selection

The Panel lists only `media_player` entities that support both of the following capabilities:

1. `MediaPlayerEntityFeature.PLAY_MEDIA`;
2. At least one of `PAUSE` or `STOP`.

The selection is saved in persistent queue state. When the output device is changed during active playback, the integration stops the previous device before saving the new selection. To prevent unintended playback continuation across devices, the current queue enters a stopped state and playback must be started manually.

When stopping output, the integration calls `media_pause` first and calls `media_stop` only when the player does not provide pause capability.

The player card reads `supported_features` from the entity in memory. It enables the corresponding progress, volume, or mute controls only when the entity declares `SEEK`, `VOLUME_SET`, or `VOLUME_MUTE`, respectively. The commands call the Home Assistant `media_seek`, `volume_set`, and `volume_mute` actions. Unsupported controls remain disabled and explain why; the Panel does not attempt to bypass entity capabilities. [3]

## State and Concurrency

When the Panel first loads or returns from another page, it reads configuration, player capabilities, and a queue snapshot in parallel, then subscribes to real-time queue events. All of this data comes from Home Assistant memory and does not wait for Navidrome library or playlist requests. The library and playlists continue to refresh in the background after player controls are ready. Home Assistant `state_changed` events push the selected player’s state, volume, and progress properties through the same subscription; the Panel does not poll the player. During playback, the Panel smooths the displayed seconds in the browser using the most recent Home Assistant position timestamp. Home Assistant still performs the actual seek after the progress bar is dragged. A drag session’s progress preview persists until `change`, loss of focus, or a current-track change; state events for the same track and the per-second display timer cannot overwrite it. Volume commands retain their target value while awaiting confirmation from an entity state event, preventing an old attribute from making the slider jump back. [3] [4]

For ordinary state changes, the outer Home Assistant Panel forwards only changed properties to the existing custom element and does not recreate the element. [1] [5] Every Panel rendering path synchronizes properties, text, event handlers, and control states item by item on the existing DOM. Queue events, notifications, theme changes, and data refreshes do not replace the root tree, queue container, CD, buttons, sliders, or image nodes with matching cover identifiers. Repeatedly setting the same `narrow`, `hass`, or Panel configuration in Home Assistant likewise preserves existing Shadow DOM nodes.

Each mutating command includes the current `expected_revision`. Single-track and playlist voice tasks record the revision before matching begins and validate it when they finally replace the queue. If pausing, clearing, switching the queue, automatic advancement, or another page changes the queue during matching, the server rejects the late result. Stale Panel commands likewise obtain current state rather than overwriting a newer action.

The client also sends commands serially and ignores stale responses whose revision moves backward, preventing rapid clicks from causing response reordering. When Home Assistant removes the Panel from the page, the Panel synchronously invalidates its current initialization generation, cancels pending frontend request waits, and releases the command chain. Remounting immediately begins a new initialization. Operations during reconnection wait until the current configuration, player capabilities, and queue snapshot are ready before being sent. Closing the Panel does not terminate the backend queue or automatic track advancement. [5]

## Cover Art and Details

The browser does not access a Navidrome URL containing Subsonic credentials directly. The Panel uses an authenticated Home Assistant cover-art proxy. The proxy accepts only bounded-length cover IDs and the eight sizes `64`, `96`, `128`, `160`, `192`, `256`, `320`, and `384` px, limits response-body size, and uses OpenSubsonic’s `size` parameter for `getCoverArt` so Navidrome generates the thumbnail. [6] Based on the CSS size and `devicePixelRatio` for a track, queue item, rotating CD, detail view, or playlist, the client selects the smallest size tier that is not smaller than the target. Pixel density is capped at 1.5× to balance clarity and transfer speed. Navidrome caches resized cover art. [7] The browser caches Blob object URLs by Config Entry, size, and cover ID, preventing images from being incorrectly shared across configurations or uses. The cache belongs to the current frontend module rather than to a temporary Panel element. A new Panel instance that returns from another Home Assistant page reuses the same bounded cache, so cache hits do not request the cover-art proxy again. The count limit accommodates the default full queue, while memory remains constrained by a total-byte limit. The browser revokes all object URLs when the page is truly unloaded; it does not release them early when entering the back-forward cache.

All track, artist, album, and error text is written through DOM `textContent`; Navidrome metadata is not parsed as HTML.

## Theme

The theme mode is stored in the browser’s local settings. The available modes are:

| Mode | Behavior |
|---|---|
| Follow Home Assistant | Uses the current Home Assistant light or dark theme |
| Day | Uses a fixed light Panel |
| Night | Uses a fixed dark Panel |

The theme affects only the current browser. It is not written to the queue or the Home Assistant Config Entry.

## Troubleshooting

If the configured page name does not appear in the sidebar, first confirm that the Config Entry loaded successfully and that you are signed in with an administrator account. A browser hard refresh can clear the static-resource cache. Static-resource URLs contain the integration version, so normal updates automatically use new resources.

If the player list is empty, inspect the target entity’s `supported_features` in Developer Tools. If a queue can be created but the speaker does not play, the issue is usually the Navidrome public share URL or reverse-proxy `/share/` path, not the Panel WebSocket.

If multi-page operations produce a revision conflict, it is a safe rejection rather than data corruption; the Panel refreshes automatically. If conflicts persist, close other pages or automations that are controlling the queue.

## References

[1]: https://developers.home-assistant.io/docs/frontend/custom-ui/creating-custom-panels/ "Home Assistant custom panel development"
[2]: https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/ "Home Assistant frontend hass object and WebSocket API"
[3]: https://developers.home-assistant.io/docs/core/entity/media-player/ "Home Assistant media player entity features"
[4]: https://developers.home-assistant.io/docs/integration_listen_events/ "Home Assistant event subscriptions"
[5]: https://github.com/home-assistant/frontend/blob/350fae410719663c18f72180d83cfeea542288f3/src/panels/custom/ha-panel-custom.ts "Home Assistant custom panel container source"
[6]: https://opensubsonic.netlify.app/docs/endpoints/getcoverart/ "OpenSubsonic getCoverArt endpoint"
[7]: https://www.navidrome.org/docs/usage/library/artwork/ "Navidrome artwork resolution and image encoding"
[8]: https://github.com/home-assistant/frontend/blob/350fae410719663c18f72180d83cfeea542288f3/src/layouts/home-assistant-main.ts "Home Assistant main layout sidebar event handling"
[9]: https://github.com/home-assistant/frontend/blob/350fae410719663c18f72180d83cfeea542288f3/src/components/ha-menu-button.ts "Home Assistant menu button implementation"
[10]: https://developers.home-assistant.io/docs/core/entity/select/ "Home Assistant Select entity"
