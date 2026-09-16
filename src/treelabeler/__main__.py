"""Vstupni bod: python -m treelabeler <slozka_s_daty>"""

from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .server import create_app


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    # nepovinny arg: cesta ke slozce s daty — bez nej startuj s prazdnym GUI
    data_dir = None
    port = 8000

    # positional = prvni arg, ktery neni --flag a neni hodnota po --flag
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            i += 2  # preskoc flag i jeho hodnotu
        else:
            positional.append(a)
            i += 1
    if positional:
        data_dir = Path(positional[0]).resolve()
        if not data_dir.is_dir():
            print(f"Chyba: slozka neexistuje: {data_dir}")
            return 1

    if "--port" in args:
        i = args.index("--port")
        port = int(args[i + 1])

    app = create_app(data_dir)

    # otevri prohlizec az po startu serveru
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)), daemon=True).start()

    print(f"TreeLabeler: {url}  (data: {data_dir})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
