"""``forgewright web`` — launch the FastAPI chat UI.

The ``uvicorn`` and ``fastapi`` imports are deferred to the call
site so the ``[web]`` extra stays opt-in: the core package does not
depend on either.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Literal

__all__ = ["web_command"]


# ``--bind`` is a convenience over the raw ``--host`` flag. The values
# correspond to where the user actually wants the phone to reach the
# server: loopback (default), the LAN, the Tailscale tailnet IP, or
# every interface.
Bind = Literal["loopback", "lan", "tailscale", "all"]
_BIND_HOST: dict[str, str] = {
    "loopback": "127.0.0.1",
    "lan": "0.0.0.0",
    "tailscale": "<your-tailnet-ip>",  # set FORGEWRIGHT_TS_BIND to your tailnet IP
    "all": "0.0.0.0",
}


def web_command(
    host: str = "127.0.0.1",
    port: int = 8787,
    reload: bool = False,
    bind: Bind | None = None,
    tailscale_serve: bool = False,
) -> None:
    """Launch the web chat UI.

    Parameters
    ----------
    host
        Bind address. Use ``0.0.0.0`` to expose on the LAN/Tailscale
        tailnet; default is loopback only. Ignored when ``--bind`` is
        set (the convenience flag wins).
    port
        TCP port. Default ``8787`` keeps it well above the standard
        MCP range (8000) and below the dashboard range (9000+).
    reload
        Auto-reload on source changes (dev only). Requires the
        ``[web]`` extra to include ``watchfiles`` transitively.
    bind
        Convenience over ``--host``:

        * ``loopback`` (default) — only reachable from this machine.
        * ``lan`` — bind 0.0.0.0 so phones on the same Wi-Fi can
          reach the Pi at ``http://<pi-lan-ip>:8787``. PWA install
          on iOS will *not* work without HTTPS.
        * ``tailscale`` — bind the aiserver Tailscale IP
          (``<your-tailnet-ip>``) so other tailnet devices can reach
          the server. Pair with ``--tailscale-serve`` for HTTPS.
        * ``all`` — same as ``lan``.
    tailscale_serve
        If set, also run ``tailscale serve --bg --https=443
        http://localhost:{port}`` so the chat is reachable on the
        tailnet as ``https://aiserver.<tailnet>.ts.net`` with
        Tailscale-managed TLS. iOS PWA install requires HTTPS,
        so this is the recommended path for a phone install.
        Requires the ``tailscale`` binary on ``$PATH``.
    """
    if bind is not None:
        host = _BIND_HOST[bind]

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover — install path
        raise SystemExit(
            "The web UI requires the [web] extra.\n"
            "Install it with:  uv pip install 'forgewright[web]'\n"
            f"(underlying error: {exc})"
        ) from None

    # Validate the import is wired up correctly; gives a clear error
    # if the user installed fastapi but forgewright itself isn't
    # importable from the venv.
    from forgewright.web.server import app  # noqa: F401  (validates wiring)

    if tailscale_serve:
        _enable_tailscale_serve(port)

    print(f"forgewright web — listening on http://{host}:{port}  (Ctrl-C to stop)")
    if tailscale_serve:
        print("                — reachable at https://aiserver.<tailnet>.ts.net via Tailscale")
    uvicorn.run(
        "forgewright.web.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def _enable_tailscale_serve(port: int) -> None:
    """Shell out to ``tailscale serve`` to expose the local port over
    Tailscale's automatic HTTPS.

    Exits with a clear error if the binary is missing. Uses
    ``--https=443`` so the phone reaches the chat at
    ``https://aiserver.<tailnet>.ts.net`` (or whatever the tailnet
    name is) without needing any cert config.
    """
    ts = shutil.which("tailscale")
    if ts is None:
        raise SystemExit(
            "--tailscale-serve requested but the `tailscale` binary "
            "was not found on $PATH. Install Tailscale or drop the flag."
        )
    # Reset any prior serve config for this host so re-running the
    # command does not stack duplicate listeners.
    subprocess.run(
        [ts, "serve", "reset"],
        check=False,
        capture_output=True,
    )
    cmd = [
        ts, "serve",
        "--bg",                # background the listener
        "--https=443",         # Tailscale-managed HTTPS on the standard port
        f"http://localhost:{port}",
    ]
    print(f"forgewright web — enabling Tailscale HTTPS via: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"tailscale serve failed (exit {result.returncode}):\n"
            f"  stdout: {result.stdout.strip()}\n"
            f"  stderr: {result.stderr.strip()}"
        )
