"""Sign in to Gmail (read-only) and save the token WorkFlowOS uses.

Opens Google's consent page in your browser, stores the authorized token at GMAIL_TOKEN_PATH
(default: token.json), then confirms access with one read-only search.

    python scripts/gmail_login.py            # sign in only if needed
    python scripts/gmail_login.py --force    # discard the saved token and sign in again
"""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)  # relative paths in .env (credentials.json, token.json) resolve from the repo root

from app.services.gmail_client import GmailApiClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="delete the saved token and sign in again")
    args = parser.parse_args()

    client = GmailApiClient()
    if not os.path.exists(client.credentials_path):
        print(
            f"OAuth client file not found: {client.credentials_path}\n"
            "Create an OAuth client ID of type 'Desktop app' in Google Cloud Console "
            "(APIs & Services > Credentials), download it and save it there."
        )
        return 1

    if args.force and os.path.exists(client.token_path):
        os.remove(client.token_path)

    ok, detail = client.check_access()
    if not ok:
        print("Opening Google sign-in in your browser (read-only Gmail access)...")
        client.authenticate_interactive(open_browser=True)
        ok, detail = client.check_access()
    if not ok:
        print(f"Sign-in failed: {detail}")
        return 1

    found = client.search_messages(query="in:inbox", max_results=1)
    print(f"Gmail access confirmed. Token saved to {client.token_path}.")
    print(f"Read-only test search returned {found.total_found} message(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
