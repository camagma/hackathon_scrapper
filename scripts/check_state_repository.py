"""Reject inaccessible or public state repositories before runner delivery."""

import os
import re
import sys

import requests


def verify_private_repository(repository: str, token: str) -> None:
    """Check GitHub metadata without logging credentials or response bodies."""
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository)
            or repository.rsplit("/", 1)[-1] in (".", "..")):
        raise ValueError("STATE_REPOSITORY must use OWNER/REPOSITORY format")
    if not token.strip():
        raise ValueError("Set the STATE_REPOSITORY_TOKEN secret")
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repository}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "User-Agent": "DevpostReminder-StateCheck"},
            timeout=(10, 30), allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError("Cannot verify state repository access")
        body = response.json()
        if not isinstance(body, dict) or body.get("private") is not True:
            raise ValueError("State repository must be private")
    except requests.RequestException:
        raise ValueError("State repository verification request failed") from None


def main() -> int:
    """Read runner configuration and fail closed before checkout or delivery."""
    try:
        verify_private_repository(os.environ.get("STATE_REPOSITORY", ""), os.environ.get("GH_TOKEN", ""))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Private state repository verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
