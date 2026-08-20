"""Desktop launcher: FastAPI + PyWebView window."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

import uvicorn

from dropship_desk import config

PORT_SEARCH_RANGE = 30


def _is_port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _find_free_port(host: str, start_port: int) -> int:
    for offset in range(PORT_SEARCH_RANGE + 1):
        candidate = start_port + offset
        if _is_port_free(host, candidate):
            return candidate
    raise RuntimeError(
        f"No free port in range {start_port}..{start_port + PORT_SEARCH_RANGE}"
    )


def _start_backend(host: str, port: int) -> threading.Thread:
    from dropship_desk.api import create_app

    app = create_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", access_log=True)
    )
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return thread
        except OSError:
            time.sleep(0.1)
    sys.stderr.write(f"[launcher] Backend failed to start ({host}:{port}).\n")
    raise SystemExit(2)


def _open_window(url: str) -> None:
    import webview

    webview.create_window(
        title="Dropship Desk",
        url=url,
        width=1280,
        height=860,
        min_size=(900, 600),
        text_select=True,  # allow mark / copy / paste (pywebview default is False)
    )
    webview.start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Dropship Desk desktop launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=config.DEFAULT_API_PORT)
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Load UI from Vite at http://localhost:5173",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Backend only (use a browser)",
    )
    args = parser.parse_args()

    try:
        port = _find_free_port(args.host, args.port)
    except RuntimeError as e:
        sys.stderr.write(f"[launcher] {e}\n")
        return 2

    if port != args.port:
        print(f"[launcher] Port {args.port} busy, using {port}.", flush=True)

    config.ensure_data_dir()
    _start_backend(args.host, port)
    print(f"[launcher] API http://{args.host}:{port}/api/health", flush=True)

    if args.headless:
        print("[launcher] Headless — Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    if args.dev:
        url = "http://localhost:5173/"
    else:
        index = config.RUNTIME_ROOT / "ui" / "dist" / "index.html"
        if not index.is_file():
            sys.stderr.write(
                "[launcher] ui/dist missing. Run: cd ui && npm install && npm run build\n"
                "[launcher] Or use: python launcher.py --dev  (with Vite running)\n"
            )
            return 1
        url = f"http://{args.host}:{port}/"

    _open_window(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
