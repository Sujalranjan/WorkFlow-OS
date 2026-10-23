"""Administrative commands.

    python backend/app/cli.py create-user --email you@example.com --name "Your Name" --role admin
    docker compose exec api python -m app.cli create-user --email you@example.com --name "You" --role admin

The password is asked for interactively (or read from WORKFLOWOS_NEW_PASSWORD for scripted setups).
There is no sign-up page: the first admin is created here, and admins add everyone else in Settings.
"""

import argparse
import getpass
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from app.models.auth import CreateUserRequest, Role, UpdateUserRequest  # noqa: E402
from app.services.auth_service import AuthError, AuthService  # noqa: E402


def _password() -> str:
    env = os.getenv("WORKFLOWOS_NEW_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Password (at least 12 characters): ")
    if getpass.getpass("Repeat password: ") != first:
        raise SystemExit("Passwords do not match.")
    return first


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="WorkFlowOS administration")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="create a user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=[r.value for r in Role], default=Role.VIEWER.value)

    reset = sub.add_parser("set-password", help="set a user's password (ends their sessions)")
    reset.add_argument("--email", required=True)

    sub.add_parser("list-users", help="list users")

    args = parser.parse_args(argv)
    service = AuthService()

    try:
        if args.command == "create-user":
            user = service.create_user(
                CreateUserRequest(email=args.email, name=args.name, role=Role(args.role), password=_password())
            )
            print(f"Created {user.role.value} {user.email} ({user.user_id}).")
        elif args.command == "set-password":
            found = service.repo.get_user_with_hash(args.email)
            if not found:
                raise SystemExit(f"No user with email {args.email}.")
            service.update_user(found[0].user_id, UpdateUserRequest(password=_password()), acting_user_id="cli")
            print(f"Password updated for {args.email}; existing sessions were signed out.")
        elif args.command == "list-users":
            for u in service.repo.list_users():
                print(f"{u.email:40} {u.role.value:9} {'active' if u.active else 'disabled'}")
    except ValidationError as e:
        raise SystemExit("; ".join(err["msg"] for err in e.errors()))
    except AuthError as e:
        raise SystemExit(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
