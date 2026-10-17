---
version: alpha
name: FPV Stream TikTok Session Generator
description: Herramienta de escritorio nativa para preparar y cerrar sesiones de TikTok con la identidad visual de FPV Stream.
colors:
  brand: '#DF2531'
  brandLight: '#FF4A54'
  brandDark: '#A50E1A'
  background: '#0D0D0F'
  surface: '#1C1C20'
  text: '#FFFFFF'
  muted: '#C5C5CB'
  warning: '#F4C95D'
  danger: '#FF4A54'
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
The desktop chrome follows the local FPV Stream identity: a dark charcoal surface,
white controls, and a red recording/play accent. All owned interface copy is Spanish.
The logo is the committed vector asset at branding/fpv-stream-logo.svg. No new
animation, font or dependency.

## Canonical owners

| Capability | Owner | Verification |
|---|---|---|
| Session/API state | Stream.py, start/end/getInfo | test_stream.py |
| Pending actions and feedback | StreamApp._run_api / _finish_api / _sync_controls | test_app.py |
| Account switching | StreamApp.change_account, guarded token callbacks, fixed config_path | Clear/restart/cancel/stale-result GUI tests |
| Credentials form | Existing QLineEdit and copy buttons | Masking and clear-state GUI tests |
| Dialog | Native QMessageBox, default Cancel for uncertain-state recovery | GUI cancellation test |
| Search | QTimer debounce, generation check, one in-flight request, keyboard selection | Stale-result and keyboard GUI tests |
| Brand chrome | branding/fpv-stream-logo.svg, StreamApp._apply_brand_theme | UI smoke test and Qt icon load |
| Scroll/control chrome | QScrollArea + platform QStyle | 800×600 scroll test and Qt offscreen screenshots |

## Status and visual language

Runtime status colors are owned by StreamApp._set_live_state: muted for no
locally prepared session, warning for preparing/closing/prepared/unknown and danger
for a rejected operation. Labels carry meaning independently of color. Status text
wraps and uses plain text; network messages never become rich text. The dark
surface uses #C5C5CB for muted text, #F4C95D for warnings and #FF4A54 for errors.
Status/help areas reserve space and manual-recovery actions retain their layout slot
while hidden, keeping credential controls stable.

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
Only one generator may run per config file; a second launch asks the existing
window to come forward instead of allowing two writers.

Persist pending state and the session ID before dispatching a lifecycle request,
bound to the account fingerprint, so restart cannot silently forget a pending
session. No RTMP URL/key is persisted by this change. The token is protected with
Windows DPAPI before it is written to config.json; platforms without a keyring keep
the historical plain-text value. Clipboard copies are cleared after 30 seconds when
they still hold the copied value.

Manual recovery only clears local state after the user explicitly confirms in
Live Monitor that the remote session ended. It does not issue an API request and
does not stop or prove anything remotely. Closing the generator does not end LIVE;
the UI warns and preserves pending state. A request in progress or a failed journal
write asks before the window closes, so the user can cancel instead of losing the
pending session.

## Verification

Run `.venv/Scripts/python.exe -m unittest -v` and Python byte-compilation. GUI tests use real Qt widgets offscreen with synthetic API
responses, including delayed requests, unknown results, preserved IDs, masking,
manual recovery, Spanish copy, emoji-free controls and the FPV Stream icon/theme.
They never create real TikTok sessions.

## Web-login recovery

`TokenRetriever` owns one cancellable OAuth attempt and callback server.
`fetch_online_token` and `_finish_online_token` own the GUI lifecycle. Browser
launch runs on the worker through `BrowserLauncher`. The system URL handler runs
first, as upstream did; only when it reports failure does a registered Chrome, Edge
or Firefox executable receive an explicit visible new-window request. Qt's
GUI-thread URL handler is the final fallback. The OAuth URL is passed as one
argument, without a command shell.
The visible Cancel action restores retry immediately, and attempt identity prevents
an old completion replacing a new account. Cancellation never changes the current
token. Pending login disables account edits and preparing a transmission. Browser
failure and timeout leave an actionable status.
No new libraries, animations or credential logging.

## Explicit account switching

The native `Cambiar cuenta` button clears the generator's token, username, access
status, stream URL/key and cached account results before opening a new web login.
Persist the empty account atomically first; a write failure blocks login and offers
retry rather than claiming that the stored account was removed. `config_path`
defaults to config.json beside the application when that folder is writable,
otherwise to the per-user configuration directory, independent of the launch folder.
A legacy file is copied to the new location on first use.
Title, category and audience settings remain drafts for the next account.

Cancel or failed login leaves the generator signed out. Only the new attempt can
apply credentials. Old account-info, category and local-token callbacks cannot
restore a cleared account. A read-only refresh may be detached; prepared,
unconfirmed or mutating LIVE sessions must be resolved first and remain recoverable.

This clears the generator's identity, not TikTok's browser cookies or Streamlabs
Desktop's separate account. The inline message directs the user to TikTok's
`Cambiar de cuenta` action; account information is loaded for the chosen identity.
