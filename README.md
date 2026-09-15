# TikTok Live Stream Key Generator for OBS Studio Using Streamlabs

This is a small PySide6 desktop application that prepares a TikTok RTMP
session through Streamlabs and displays the server URL and stream key for OBS
Studio or another streaming client.

The application does not transmit video and does not configure OBS
automatically. It asks Streamlabs to prepare the session; the actual broadcast
starts when OBS sends the stream.

This repository is a hardened derivative of
[Loukious/StreamLabsTikTokStreamKeyGenerator](https://github.com/Loukious/StreamLabsTikTokStreamKeyGenerator).
See [Attribution and license](#attribution-and-license).

## Requirements

- A TikTok account with the required Streamlabs TikTok LIVE/RTMP access.
- Windows, macOS, or Linux for the graphical application.
- Python 3.11 or newer when running from source. CI runs the tests on 3.12 and
  builds the binaries with 3.13.
- A browser for the web-login flow.
- On Linux, `libsecret` (Secret Service) if the token should be stored
  securely. Without it the token is kept in memory for the current session
  only.

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
development version until a release build supplies one. Development versions
never trigger the update prompt.

Set `STREAMLABS_KEYGEN_LOG_LEVEL=DEBUG` for verbose diagnostics on stderr.

## Authentication and token storage

The application supports three token-loading paths:

1. Paste a token into the **Token Loader** field.
2. **Load from PC** reads the Streamlabs Desktop local-storage directory on
   Windows or macOS.
3. **Load from Web** opens the Streamlabs login page and receives the OAuth
   callback on a loopback-only local server using PKCE and a `state` value.

Tokens are never written to `config.json`. After successful account
validation, the **Save Token Securely** button stores the token in the
operating system's credential store through `keyring`:

- Windows Credential Manager
- macOS Keychain
- Linux Secret Service/libsecret

If no secure backend is available, the token is used for the current session
only and must be loaded again after restarting the application. There is
intentionally no plaintext-file fallback.

Older versions stored a token in a working-directory `config.json`. When such a
file is found, the application asks what to do and offers three options:
import the token into the OS credential store, delete the old file, or decide
later. A token from a file you chose not to import is never loaded into the UI,
and the decision is remembered.

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

## Risk and compatibility notes

- The TikTok operations use Streamlabs Desktop endpoints under
  `/api/v5/slobs/tiktok`, and the login exchange impersonates the Streamlabs
  Desktop user agent. These endpoints are internal implementation details, not
  a stable public API contract. If Streamlabs changes its desktop application,
  the adapter may need an update. The application reports an endpoint or
  response-format change without printing tokens or response bodies.
- Using these endpoints may fall outside the Streamlabs terms of service, and
  any consequence is borne by the account that authorises the session. Make
  sure you are comfortable with that before using the application.
- **Load from PC** reads another application's local storage and extracts its
  API token. It is intended for the owner of the machine, but it is the same
  technique credential stealers use, so antivirus and EDR products may flag the
  binary. Prefer **Load from Web** when possible.
- Release binaries are unsigned and unnotarized. Do not disable macOS
  Gatekeeper quarantine blindly; inspect the artifact or build from source
  instead.

## Releases and security

Release archives are built by GitHub Actions for Windows, macOS, and Linux.
Every release also publishes `SHA256SUMS.txt`:

```bash
# Linux
sha256sum -c SHA256SUMS.txt

# macOS
shasum -a 256 -c SHA256SUMS.txt
```

```powershell
# Windows
Get-FileHash .\StreamLabsTikTokStreamKeyGenerator-win-<version>.zip -Algorithm SHA256
```

Compare the value with the matching line before running a downloaded binary,
and make sure the release came from this repository.

The project does not automatically download or execute updates. The update
check only opens the GitHub release page after confirmation.

## Development notes

- `streamlabs_client.py` contains the typed, timeout-bound Streamlabs adapter.
- `TokenRetriever.py` contains the browser OAuth/PKCE callback flow.
- `secure_store.py` contains OS credential-store access.
- `config_store.py` contains non-secret, versioned preferences.
- `workers.py` contains the `QThreadPool` helpers. Callbacks connected to a
  worker must use `Qt.ConnectionType.QueuedConnection` so that they run on the
  GUI thread.
- `Stream.py` remains as a compatibility facade for older imports.

CI runs `python -m compileall`, `ruff check`, `pytest` and `pip-audit` on
Ubuntu, Windows and macOS. The dependency audit is reported but does not fail
the build, so a newly published CVE cannot freeze releases unexpectedly.

Packaged builds must bundle the platform keyring backend explicitly
(`win32ctypes` on Windows, `secretstorage`/`jeepney` on Linux); otherwise the
token store is unavailable in the frozen binary even though it works from
source.

## Attribution and license

The original application was written by
[Loukious](https://github.com/Loukious) and is licensed under GPL-3.0. This
repository is a derivative work and keeps that licence; see `LICENSE.txt`.

For continuity, the configuration directory and the keyring service name still
use the upstream author identifier. Changing them would orphan the
configuration and the stored token of existing installations.
