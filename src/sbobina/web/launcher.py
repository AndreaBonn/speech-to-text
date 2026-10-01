import logging
import socket
import threading
import time
import webbrowser

import httpx
import uvicorn

from sbobina.settings import Settings
from sbobina.web.app import create_app

logger = logging.getLogger(__name__)

BROWSER_POLL_ATTEMPTS = 100
BROWSER_POLL_INTERVAL_S = 0.1
READINESS_TIMEOUT_S = 0.5
READINESS_PATH = "/api/v1/system"


def base_url(host: str, port: int) -> str:
    """Return the URL the browser opens; IPv6 hosts need square brackets."""
    netloc = f"[{host}]" if ":" in host else host
    return f"http://{netloc}:{port}"


def is_port_available(host: str, port: int) -> bool:
    """Probe ``host:port`` with a throwaway bind; ``False`` if already taken."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def open_browser_when_ready(url: str) -> None:
    """Open ``url`` once the server answers, so the page never loads half-started."""
    for _ in range(BROWSER_POLL_ATTEMPTS):
        try:
            response = httpx.get(f"{url}{READINESS_PATH}", timeout=READINESS_TIMEOUT_S)
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code == httpx.codes.OK:
            webbrowser.open(url)
            return
        time.sleep(BROWSER_POLL_INTERVAL_S)
    logger.warning("Il server non risponde: apri a mano %s", url)


def run_server(config: Settings, open_browser: bool) -> int:
    """Serve the web UI on ``config.web_host:web_port``; return the exit code.

    The same ``config`` builds the Origin check, so the port the server binds
    and the origin it accepts cannot drift apart.
    """
    host, port = config.web_host, config.web_port
    if not is_port_available(host=host, port=port):
        logger.error(
            "Porta %d già occupata su %s: scegli un'altra porta con --port", port, host
        )
        return 1
    url = base_url(host=host, port=port)
    logger.info("Interfaccia su %s", url)
    if open_browser:
        threading.Thread(
            target=open_browser_when_ready, args=(url,), daemon=True
        ).start()
    uvicorn.run(create_app(settings=config), host=host, port=port, log_level="info")
    return 0
