# TikTok Live Stream Key Generator for OBS Studio Using Streamlabs

This is a small PySide6 desktop application that prepares a TikTok RTMP
session through Streamlabs and displays the server URL and stream key for OBS
Studio or another streaming client.

The application does not transmit video and does not configure OBS
automatically. It asks Streamlabs to prepare the session; the actual broadcast
starts when OBS sends the stream.

## Requirements

- A TikTok account with the required Streamlabs TikTok LIVE/RTMP access.
- Windows, macOS, or Linux for the graphical application.
- Python 3.11 or newer when running from source.
- A browser for the web-login flow.

Streamlabs may change access rules or its desktop integration. In particular,
not every TikTok account receives RTMP stream-key access, and the official
Streamlabs Desktop flow may not require a manually copied key.

## Run from source

Install runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the application:

```bash
python StreamLabsTikTokStreamKeyGenerator.py
```

For development and tests:

```bash
python -m pip install -r requirements-dev.txt
ruff check .
pytest
```

The source checkout does not require a generated `_version.py`; it uses a
development version until a release build supplies one.

## Authentication and token storage

The application supports two token-loading paths:

1. **Load from PC** reads the known Streamlabs Desktop local-storage directory
   on Windows or macOS.
2. **Load from Web** opens the Streamlabs login page and receives the OAuth
   callback on a loopback-only local server using PKCE.

Tokens are not stored in `config.json`. After successful account validation,
the **Save Token Securely** button stores the token in the operating system's
credential store through `keyring`:

- Windows Credential Manager
- macOS Keychain
- Linux Secret Service/libsecret

If no secure backend is available, the token is used for the current session
only and must be loaded again after restarting the application.

Older versions stored a token in a working-directory `config.json`. On first
launch, the application offers to migrate that token to the OS credential
store and removes the token field from the old configuration only after the
user accepts and the secure save succeeds.

## Usage

1. Obtain the required TikTok LIVE/RTMP access through Streamlabs.
2. Use **Load from PC**, **Load from Web**, or paste a token.
3. Click **Refresh Account Info** and wait for account validation.
4. Enter a title and choose a game category.
5. Optionally click **Save Token Securely**.
6. Click **Go Live** to prepare the Streamlabs session.
7. Copy the displayed URL and stream key into OBS.
8. Click **End Live** when the Streamlabs session should be closed.

The stream key is copied to the clipboard only on request and is cleared after
60 seconds if it has not been replaced by another application.

## Compatibility limitation

The TikTok operations use Streamlabs Desktop endpoints under
`/api/v5/slobs/tiktok`. These endpoints are internal implementation details,
not a stable public API contract. If Streamlabs changes its desktop
application, the adapter may need an update. The application reports an
endpoint or response-format change without printing tokens or response bodies.

## Releases and security

Release archives are built by GitHub Actions for Windows, macOS, and Linux.
Before running a downloaded binary, verify that it came from the expected
release and compare its published checksum when one is provided. Do not
disable macOS Gatekeeper quarantine blindly; an unsigned or unnotarized binary
should be inspected or built from source instead.

The project does not automatically download or execute updates. The update
check only opens the GitHub release page after confirmation.

## Development notes

- `streamlabs_client.py` contains the typed, timeout-bound Streamlabs adapter.
- `TokenRetriever.py` contains the browser OAuth/PKCE callback flow.
- `secure_store.py` contains OS credential-store access.
- `config_store.py` contains non-secret, versioned preferences.
- `Stream.py` remains as a compatibility facade for older imports.

The project is licensed under GPL-3.0. See `LICENSE.txt`.
