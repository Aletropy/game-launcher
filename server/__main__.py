"""Run the friends server: ``python -m server [--host] [--port] [--db]``.

Admin: ``python -m server admin users list|search|show ...`` (read-only
except reset-token / recovery rotate, which mint new secrets).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from server.api import make_server
from server.db import Store


def _when(stamp: object) -> str:
    try:
        value = int(stamp or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return "-"
    if value <= 0:
        return "-"
    # Local wall-clock time, like every other date the launcher shows.
    return datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")  # noqa: DTZ006


def _print_users(rows: list[dict]) -> None:
    print(f"{'id':>5}  {'name':<24} {'code':<10} {'platform':<8} {'created':<16} {'seen':<16}")
    for row in rows:
        print(
            f"{int(row['id']):>5}  {str(row['display_name'])[:24]:<24}"
            f" {row['friend_code']:<10} {row.get('platform', 'linux'):<8}"
            f" {_when(row.get('created')):<16} {_when(row.get('last_seen')):<16}"
        )


def _cmd_users_list(store: Store, args: argparse.Namespace) -> int:
    rows = store.list_users(limit=args.limit, order=args.order)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_users(rows)
    return 0


def _cmd_users_search(store: Store, args: argparse.Namespace) -> int:
    rows = store.search_users(args.text, limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_users(rows)
    return 0


def _cmd_users_show(store: Store, args: argparse.Namespace) -> int:
    found = store.get_user(args.ref)
    if found is None:
        print(f"no user {args.ref!r}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(found, indent=2))
        return 0
    print(f"id:           {found['id']}")
    print(f"name:         {found['display_name']}")
    print(f"friend_code:  {found['friend_code']}")
    print(f"platform:     {found.get('platform', 'linux')}")
    print(f"created:      {_when(found.get('created'))}")
    print(f"last_seen:    {_when(found.get('last_seen'))}")
    print(f"devices:      {found.get('devices')}")
    print(f"sessions:     {found.get('sessions')}")
    print(f"friends:      {found.get('friends')}")
    for device in store.list_devices(int(found["id"])):
        print(
            f"  device {device['id']}: {device.get('device_name')}"
            f"  seen {_when(device.get('last_seen'))}"
        )
    return 0


def _cmd_users_export(store: Store, args: argparse.Namespace) -> int:
    rows = store.list_users(limit=args.limit, order=args.order)
    # Never includes token hashes or recovery hashes.
    payload = [
        {
            "user_id": r["id"],
            "display_name": r["display_name"],
            "friend_code": r["friend_code"],
            "platform": r.get("platform", "linux"),
            "created": r.get("created"),
            "last_seen": r.get("last_seen"),
        }
        for r in rows
    ]
    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {len(payload)} users to {args.out}")
    else:
        print(text)
    return 0


def _write_profile(path: Path, payload: dict) -> None:
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def _cmd_reset_token(store: Store, args: argparse.Namespace) -> int:
    result = store.reset_token(args.ref, device_name=args.device or "recovery")
    if result is None:
        print(f"no user {args.ref!r}", file=sys.stderr)
        return 1
    user, token = result
    payload = {
        "version": 1,
        "server": args.server or "",
        "user_id": user.id,
        "display_name": user.display_name,
        "friend_code": user.friend_code,
        "token": token,
    }
    if args.out:
        _write_profile(args.out, payload)
        print(f"new token for {user.display_name} ({user.friend_code}) -> {args.out} (0600)")
        print("Import it: milso-launcher --import-profile", args.out)
    else:
        print(json.dumps(payload, indent=2))
        print("Save the token now; it is shown only once.", file=sys.stderr)
    return 0


def _cmd_recovery_rotate(store: Store, args: argparse.Namespace) -> int:
    found = store.get_user(args.ref)
    if found is None:
        print(f"no user {args.ref!r}", file=sys.stderr)
        return 1
    key = store.issue_recovery(int(found["id"]))
    if args.out:
        payload = {
            "version": 1,
            "server": args.server or "",
            "user_id": found["id"],
            "display_name": found["display_name"],
            "friend_code": found["friend_code"],
            "recovery_key": key,
        }
        _write_profile(args.out, payload)
        print(f"new recovery key for {found['display_name']} -> {args.out} (0600)")
    else:
        print(f"recovery_key for {found['display_name']} ({found['friend_code']}):")
        print(key)
        print("Save it now; only the hash is kept.", file=sys.stderr)
    return 0


def _cmd_devices(store: Store, args: argparse.Namespace) -> int:
    found = store.get_user(args.ref)
    if found is None:
        print(f"no user {args.ref!r}", file=sys.stderr)
        return 1
    for device in store.list_devices(int(found["id"])):
        print(
            f"{device['id']}: {device.get('device_name')}"
            f"  seen {_when(device.get('last_seen'))}"
        )
    return 0


def _cmd_revoke(store: Store, args: argparse.Namespace) -> int:
    found = store.get_user(args.ref)
    if found is None:
        print(f"no user {args.ref!r}", file=sys.stderr)
        return 1
    if store.revoke_device(int(found["id"]), args.device_id):
        print(f"revoked device {args.device_id} for {found['display_name']}")
        return 0
    print("no such device", file=sys.stderr)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m server", description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=Path("friends-server.db"), help="(default: %(default)s)"
    )
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the HTTP server (default)")
    serve.add_argument("--db", dest="serve_db", type=Path, default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--quiet", action="store_true")

    admin = sub.add_parser("admin", help="inspect and recover users")
    admin_sub = admin.add_subparsers(dest="admin_cmd", required=True)

    # `users list` stays as the friendly alias; bare verbs work too.
    u = admin_sub.add_parser("users", help="user admin")
    u_sub = u.add_subparsers(dest="users_cmd", required=True)
    for name, help_text, func in (
        ("list", "list users", _cmd_users_list),
        ("search", "search by name or code", _cmd_users_search),
        ("show", "show one user", _cmd_users_show),
        ("export", "export users (no secrets)", _cmd_users_export),
        ("reset-token", "mint a new device token (same user)", _cmd_reset_token),
        ("rotate-recovery", "mint a new recovery key", _cmd_recovery_rotate),
        ("devices", "list devices", _cmd_devices),
        ("revoke", "revoke a device", _cmd_revoke),
    ):
        q = u_sub.add_parser(name, help=help_text)
        q.set_defaults(func=func)
        if name in ("list", "export"):
            q.add_argument("--limit", type=int, default=1000 if name == "export" else 100)
            q.add_argument("--order", default="last_seen")
            q.add_argument("--json", action="store_true")
            if name == "export":
                q.add_argument("--out", type=Path, default=None)
        elif name == "search":
            q.add_argument("text")
            q.add_argument("--limit", type=int, default=50)
            q.add_argument("--json", action="store_true")
        elif name in ("show", "devices"):
            q.add_argument("ref", help="user id or friend code")
            if name == "show":
                q.add_argument("--json", action="store_true")
        elif name == "reset-token":
            q.add_argument("ref", help="user id or friend code")
            q.add_argument("--device", default="recovery")
            q.add_argument("--server", default="")
            q.add_argument("--out", type=Path, default=None)
        elif name == "rotate-recovery":
            q.add_argument("ref", help="user id or friend code")
            q.add_argument("--server", default="")
            q.add_argument("--out", type=Path, default=None)
        elif name == "revoke":
            q.add_argument("ref", help="user id or friend code")
            q.add_argument("device_id", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    # `python -m server` with no subcommand still serves, as before.
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        raw = ["serve"]
    elif raw[0] in ("-h", "--help"):
        pass
    elif "admin" not in raw and "serve" not in raw:
        # Old style: `python -m server --port 9000` -> serve.
        raw = ["serve", *raw]
    parser = _build_parser()
    args = parser.parse_args(raw)

    if getattr(args, "command", None) == "admin":
        func = getattr(args, "func", None)
        if func is None:
            parser.error("admin needs a subcommand")
        db_path: Path = args.db
        store = Store(db_path)
        try:
            return int(func(store, args))
        finally:
            store.close()

    # Backwards compatible: `python -m server --host ..` still works.
    host: str = getattr(args, "host", "127.0.0.1")
    port: int = getattr(args, "port", 8765)
    quiet: bool = getattr(args, "quiet", False)
    db: Path = getattr(args, "serve_db", None) or args.db
    store = Store(db)
    server = make_server(store, host, port, quiet=quiet)
    actual_host, actual_port = server.server_address[:2]
    print(f"Friends server on http://{actual_host!s}:{actual_port}  (database: {db.resolve()})")
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
