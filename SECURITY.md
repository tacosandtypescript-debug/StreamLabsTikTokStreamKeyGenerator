# Security policy

## What this application handles

It stores and uses a **Streamlabs OAuth token** that can start and end live
sessions on your TikTok account, and it can read the token the Streamlabs
Desktop client keeps in its own local storage. Treat that token as a password.

The token is kept in the operating system credential store (Windows Credential
Manager, macOS Keychain, Linux Secret Service). It is never written to
`config.json`, and the application never prints it or writes it to the log.

## Never post these in an issue, discussion or screenshot

- Your Streamlabs token (`oauth_token`, `apiToken`): it can open and close live
  streams on your account.
- Your TikTok stream key or the RTMP URL.
- A screenshot with the token field revealed with the eye button.
- Your `config.json` — it holds no token, but check it before sharing anyway.

**If you already posted a token, revoke it first** (in Streamlabs Desktop,
signing out invalidates the stored token) and only then edit or delete the
message. Rotating the credential matters far more than hiding the message.

## What to include in a report

- The application version (shown in the update dialog, or `version.py`).
- Your operating system.
- The log file: click **Logs** in the application and attach the `app.log` it
  opens. It contains no tokens, authorization codes or stream keys by design,
  but read it before attaching it.

## Reporting a vulnerability

Use GitHub's **Security → Report a vulnerability** tab for anything sensitive,
or open a regular issue otherwise. A redacted example is always enough: never
send a working token or stream key.
