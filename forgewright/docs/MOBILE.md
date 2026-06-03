# Installing forgewright on a phone (PWA)

The forgewright web chat is a Progressive Web App. It installs to your
phone's home screen and runs fullscreen, no browser chrome. With a
real LLM behind it, the phone becomes a portable agent in your pocket.

## What this is

- A single FastAPI process on the Pi (`forgewright web`).
- A service worker on the phone that caches the app shell and the
  most recent session so the app opens even with no Wi-Fi.
- Tailscale HTTPS so the install prompt works on iOS (iOS requires
  HTTPS for any PWA install except localhost).

## One-time setup on the Pi

1. Install Tailscale on the Pi (if not already):

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

2. Make sure your phone is on the same Tailscale tailnet. Install
   the Tailscale app from the App Store / Play Store and sign in
   with the same account.

3. From your phone, note the tailnet DNS name. Tailscale defaults
   to `<hostname>.<tailnet>.ts.net`. For this Pi the hostname is
   `aiserver`, so the URL is `https://aiserver.<tailnet>.ts.net`.
   (You can confirm with `tailscale status` on the Pi.)

## Starting the server

The `--bind tailscale --tailscale-serve` flags wire the Pi's
Tailscale IP and a HTTPS listener in one step:

```bash
# Pick a port — 8787 is the default.
uv run --extra web forgewright web --bind tailscale --tailscale-serve
```

What that does:

- `--bind tailscale` → binds the aiserver Tailscale IP
  (`100.124.255.77`) so other tailnet devices can reach the
  server directly.
- `--tailscale-serve` → shells out to
  `tailscale serve --bg --https=443 http://localhost:8787` so the
  chat is reachable at `https://aiserver.<tailnet>.ts.net` with
  Tailscale-managed TLS. **This is the part iOS requires for PWA
  install.**

The plain `--host 0.0.0.0` and `--host <pi-lan-ip>` flags still
work for everything else (Tailscale Funnel, custom reverse
proxies, direct LAN access on Android).

## Installing on the phone

### Android (Chrome / Edge / Samsung Internet)

1. Open `https://aiserver.<tailnet>.ts.net` in Chrome.
2. Chrome will show an install banner automatically (the
   `beforeinstallprompt` event). If it doesn't, open the
   three-dot menu and choose "Install app" / "Add to Home
   screen".
3. Confirm. The forgewright icon now appears on your home
   screen. Tapping it opens the app fullscreen.

### iOS (Safari)

1. Open `https://aiserver.<tailnet>.ts.net` in Safari.
2. Tap the **Share** button (the square with the up arrow).
3. Choose **Add to Home Screen**.
4. Confirm. The icon appears on your home screen. Opening it
   launches forgewright in standalone mode with no Safari
   chrome.

iOS does not fire `beforeinstallprompt`, so the app shows a
small in-page hint the first time you load it. Dismiss it with
the close button — the dismissal persists in `localStorage`.

## What works offline

The service worker caches:

- The HTML, CSS, JS, and PWA manifest.
- The icon set.
- The most recent `GET /api/sessions` and `GET /api/sessions/{id}`
  responses (network-first, last-good fallback).

What this means in practice: if you lose Wi-Fi, the app still
opens and you can still scroll through your most recent
conversation. **Sending new messages requires connectivity** —
SSE is not cached and there's no offline message-send queue
(yet; that's a follow-up).

## Reproducing the install

After a fresh deploy, browsers cache the old service worker.
If the install prompt or icon doesn't appear right away:

1. On the phone, open the app and pull-to-refresh, or
2. Go to `⋮ → Settings → Site settings → Clear & reset` in
   Chrome / iOS Settings → Safari → Advanced → Website Data →
   remove the entry for `aiserver.<tailnet>.ts.net`.
3. Reload.

The SW's cache name is `forgewright-shell-v1`; bumping it (in
`src/forgewright/web/static/sw.js`) invalidates the old shell
on next activate without any user action.

## Troubleshooting

**`--tailscale-serve` says "tailscale binary not found".**
Install Tailscale (see one-time setup) or drop the flag and
expose the port through your own reverse proxy with your own
certificate.

**iOS won't show the install option.** Three checks:
1. You're on HTTPS, not HTTP. iOS requires HTTPS for PWA install
   except for `localhost`. Tailscale serve provides this.
2. You're in Safari, not Chrome/Firefox/Edge. iOS only allows
   PWA install from Safari.
3. The `apple-touch-icon` link in `<head>` resolves. Open the
   page source and check for
   `<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">`.

**The app opens but stays on the loading screen.** The SW is
probably serving a stale cached shell. Force a reload (Chrome:
`⋮ → Reload`; iOS Safari: hold the reload button → "Request
Desktop Site" off, then reload).

**Messages don't stream.** Check that the server log shows
`tool_call.dispatched` events when you send a message. If it
shows the request arriving but no events, the LLM backend
isn't configured — see
[`docs/INSTALL.md`](./INSTALL.md) for setting `FORGEWRIGHT_LLM__*`
environment variables.
