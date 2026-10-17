---
version: alpha
name: Streamlabs TikTok Session Generator
description: Native desktop tool for preparing and closing TikTok sessions with truthful signal status.
colors:
  muted: '#595959'
  warning: '#8a5200'
  danger: '#b00020'
omitted:
  - section: typography
    reason: Native QApplication font and platform fallback; no custom fonts introduced.
  - section: rounded
    reason: Native Qt QStyle owns control shapes.
  - section: spacing
    reason: Existing QLayout geometry is retained; this change is behavioral.
components:
  button: {}
  input: {}
  dialog: {}
  sessionStatus: {}
---

# Desktop generator design context

## Product context

Single-window PySide6 utility used beside an Android broadcaster. Preserve its
native desktop forms and two-column layout. The job is to prepare credentials and
manage the remote session; the PC does not forward camera frames or host a server.
Source: README.md and the user's explicit mobile-independent workflow.
Existing controls remain English; corrected operational feedback follows the
existing Spanish status messages. No new animation, font or dependency.

## Canonical owners

| Capability | Owner | Verification |
|---|---|---|
| Session/API state | Stream.py, start/end/getInfo | test_stream.py |
| Pending actions and feedback | StreamApp._run_api / _finish_api / _sync_controls | test_app.py |
| Credentials form | Existing QLineEdit and copy buttons | Masking and clear-state GUI tests |
| Dialog | Native QMessageBox, default Cancel for uncertain-state recovery | GUI cancellation test |
| Search | QTimer debounce, generation check, one in-flight request | Stale-result GUI test |
| Scroll/control chrome | Platform QStyle | Qt offscreen screenshots |

## Status and visual language

Runtime status colors are owned by StreamApp._set_live_state: muted for no
locally prepared session, warning for preparing/closing/prepared/unknown and danger
for a rejected operation. Labels carry meaning independently of color. Status text
wraps and uses plain text; network messages never become rich text. Muted and
warning text use darker shades than the original UI for legibility on native
light-gray surfaces. Status/help areas reserve space and manual-recovery actions
retain their layout slot while hidden, keeping credential controls stable.

Receiving credentials proves only that a session was prepared. It must never
produce an EN VIVO badge or a claim that TikTok received media. The distinct signal
label says reception is unconfirmed and points to Live Monitor. The API methods
currently integrated do not provide verified video-ingest telemetry.

## Lifecycle and recovery

Refresh on the same account preserves the session client and ID. Start/end execute
on a worker and deliver results through a Qt signal; no worker touches widgets.
Busy state disables duplicate mutations and account switching. An uncertain start
cannot be repeated automatically. A failed End retains the session ID and offers
retry. Neither HTTP 404 nor an unconfirmed response counts as confirmed closure.

Persist pending state and the session ID before dispatching a lifecycle request,
bound to the account fingerprint, so restart cannot silently forget a pending
session. No RTMP URL/key is persisted by this change. The pre-existing account
token storage policy in config.json is retained.

Manual recovery only clears local state after the user explicitly confirms in
Live Monitor that the remote session ended. It does not issue an API request and
does not stop or prove anything remotely. Closing the generator does not end LIVE;
the UI warns and preserves pending state.

## Verification

Run `.venv/Scripts/python.exe -m unittest -v test_stream test_app test_token_retriever` and Python
byte-compilation. GUI tests use real Qt widgets offscreen with synthetic API
responses, including delayed requests, unknown results, preserved IDs, masking,
and manual recovery. They never create real TikTok sessions.

## Web-login recovery

`TokenRetriever` owns one cancellable OAuth attempt and callback server.
`fetch_online_token` and `_finish_online_token` own the GUI lifecycle; Qt opens
the default browser on the GUI thread. The visible Cancel action restores retry
immediately, and attempt identity prevents an old completion replacing a new
account. Cancellation never changes the current token. Pending login disables
account edits and Go Live. Browser failure and timeout leave an actionable status.
No new libraries, animations or credential logging.
