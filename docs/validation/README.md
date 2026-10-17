# Session-state validation

Run `.venv/Scripts/python.exe -m unittest -v test_stream test_app test_token_retriever`.
All 38 backend, callback and Qt widget tests passed on 2026-10-17; Python compilation
also passed. Tests use fake HTTP responses and never publish a live stream.

Coverage includes accepted preparation versus unconfirmed video receipt,
asynchronous start, duplicate-start prevention, retained session on failed end,
confirmed end, account-change guards, pending-operation persistence, restart
recovery, manual-close confirmation, safe error messages, category debounce and
stale responses, and masked keys. No new dependencies or animations.

Web login opens the default browser through Qt on the GUI thread. Cancel
immediately restores retry and invalidates late responses; the worker releases
the loopback callback server and never logs tokens, remote response bodies or
credential-bearing network exceptions. Tests cover cancellation while waiting,
timeout, failed browser launch, callback exchange and closed server/thread.
An in-flight HTTP token exchange has a 30-second timeout; cancellation suppresses
its result rather than starting another request with the same identity.

The screenshots use synthetic credentials and the real Qt widgets, rendered
offscreen with the installed Segoe UI font. No account settings were loaded.
Reviewed at 1000×760 (prepared) and 800×600 (uncertain): status text wraps,
the recovery action has reserved space, and credentials remain masked.

- [Prepared session](generator-prepared.png)
- [Uncertain session](generator-uncertain.png)
- [Cancellable web login](generator-login.png)

These checks do **not** prove TikTok video ingestion. The existing integration
returns session credentials without verified video-ingest telemetry. The UI
therefore explicitly leaves video receipt unconfirmed and provides Live Monitor.
Authenticated start/end and video receipt still require a real active session.
