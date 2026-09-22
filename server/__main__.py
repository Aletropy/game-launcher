"""Run the friends server: ``python -m server [--host] [--port] [--db]``."""

from __future__ import annotations

import argparse
from pathlib import Path

from server.api import make_server
from server.db import Store


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m server", description=__doc__)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to listen on; 0.0.0.0 to accept other machines (default: %(default)s)",
    )
    parser.add_argument("--port", type=int, default=8765, help="(default: %(default)s)")
    parser.add_argument(
        "--db", type=Path, default=Path("friends-server.db"), help="(default: %(default)s)"
    )
    parser.add_argument("--quiet", action="store_true", help="don't log each request")
    args = parser.parse_args()

    store = Store(args.db)
    server = make_server(store, args.host, args.port, quiet=args.quiet)
    host, port = server.server_address[:2]
    print(f"Friends server on http://{host!s}:{port}  (database: {args.db.resolve()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
