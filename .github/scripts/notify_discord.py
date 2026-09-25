#!/usr/bin/env python3
"""Send a notification to Discord on successful PR CI test completion.

This script constructs a formatted Discord embed and payload containing
the pull request title, description, and link, then posts it to the configured
webhook URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

EMBED_COLOR_SUCCESS = 3066993  # 0x2ecc71 (Green)
MAX_TITLE_LENGTH = 256
MAX_DESCRIPTION_LENGTH = 4000


def truncate_text(text: str, max_length: int) -> str:
    """Truncate text to max_length with an ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def build_discord_payload(
    pr_title: str,
    pr_body: Optional[str],
    pr_url: Optional[str],
    pr_number: Optional[str] = None,
    pr_author: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a Discord message payload with a rich embed."""
    raw_title = pr_title.strip() if pr_title else "Pull Request"
    if pr_number and str(pr_number).strip():
        display_title = f"PR #{str(pr_number).strip()}: {raw_title}"
    else:
        display_title = raw_title
    display_title = truncate_text(display_title, MAX_TITLE_LENGTH)

    clean_body = (pr_body or "").strip()
    if not clean_body:
        clean_body = "No description provided."
    clean_body = truncate_text(clean_body, MAX_DESCRIPTION_LENGTH)

    content_line = f"CI tests passed for PR: **{display_title}**"
    clean_url = (pr_url or "").strip()
    if clean_url and clean_url.startswith(("http://", "https://")):
        content_line += f"\n<{clean_url}>"

    embed: Dict[str, Any] = {
        "title": display_title,
        "description": clean_body,
        "color": EMBED_COLOR_SUCCESS,
        "footer": {
            "text": "MPCWithGenerativeArt CI"
        },
    }

    if clean_url and clean_url.startswith(("http://", "https://")):
        embed["url"] = clean_url
        embed["fields"] = [
            {
                "name": "PR Link",
                "value": clean_url,
                "inline": False,
            }
        ]

    if pr_author and pr_author.strip():
        embed["author"] = {
            "name": pr_author.strip()
        }

    return {
        "content": content_line,
        "embeds": [embed],
    }


def send_discord_notification(
    webhook_url: str,
    payload: Dict[str, Any],
    timeout: float = 15.0,
) -> bool:
    """Send payload to Discord webhook URL via HTTP POST."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "GitHub-Actions-CI/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = getattr(response, "status", 200)
            print(f"[Discord CI] Notification sent successfully (HTTP {status_code}).")
            return True
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        print(f"[Discord CI] HTTP Error {exc.code}: {err_msg}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[Discord CI] Error sending webhook: {exc}", file=sys.stderr)
        return False


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Send Discord PR CI notification")
    parser.add_argument("--webhook-url", default=None, help="Discord Webhook URL")
    parser.add_argument("--title", default=None, help="PR Title")
    parser.add_argument("--body", default=None, help="PR Description")
    parser.add_argument("--url", default=None, help="PR URL")
    parser.add_argument("--number", default=None, help="PR Number")
    parser.add_argument("--author", default=None, help="PR Author")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload without sending HTTP request",
    )
    return parser.parse_args()


def main() -> int:
    """Main execution entrypoint."""
    args = parse_args()

    webhook_url = (
        args.webhook_url
        or os.environ.get("DISCORD_WEBHOOK_URL")
        or ""
    ).strip()

    if not webhook_url and not args.dry_run:
        print(
            "[Discord CI] DISCORD_WEBHOOK_URL secret is not present. Skipping step."
        )
        return 0

    pr_title = args.title or os.environ.get("PR_TITLE", "Pull Request")
    pr_body = args.body if args.body is not None else os.environ.get("PR_BODY")
    pr_url = args.url or os.environ.get("PR_URL", "")
    pr_number = args.number or os.environ.get("PR_NUMBER", "")
    pr_author = args.author or os.environ.get("PR_AUTHOR", "")

    payload = build_discord_payload(
        pr_title=pr_title,
        pr_body=pr_body,
        pr_url=pr_url,
        pr_number=pr_number,
        pr_author=pr_author,
    )

    if args.dry_run:
        print("[Discord CI] Dry run enabled. Payload:")
        print(json.dumps(payload, indent=2))
        return 0

    success = send_discord_notification(webhook_url=webhook_url, payload=payload)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
