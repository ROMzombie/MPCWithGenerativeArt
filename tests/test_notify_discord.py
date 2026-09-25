"""Unit tests for the Discord PR notification script."""

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

# Ensure .github/scripts is importable
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, ".github", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import notify_discord  # noqa: E402


class TestNotifyDiscord(unittest.TestCase):
    """Test suite for Discord PR notification generation and transmission."""

    def test_truncate_text(self):
        """Test string truncation helper."""
        self.assertEqual(notify_discord.truncate_text("short", 10), "short")
        self.assertEqual(notify_discord.truncate_text("exactlen10", 10), "exactlen10")
        self.assertEqual(
            notify_discord.truncate_text("toolongstringhere", 10), "toolong..."
        )

    def test_build_discord_payload_full(self):
        """Test payload construction with all fields provided."""
        payload = notify_discord.build_discord_payload(
            pr_title="Add Discord CI notifications",
            pr_body="This pull request integrates Discord notifications into the CI pipeline.",
            pr_url="https://github.com/ROMzombie/MPCWithGenerativeArt/pull/42",
            pr_number="42",
            pr_author="testuser",
        )

        self.assertIn("content", payload)
        self.assertIn("PR #42: Add Discord CI notifications", payload["content"])
        self.assertIn(
            "https://github.com/ROMzombie/MPCWithGenerativeArt/pull/42",
            payload["content"],
        )

        self.assertEqual(len(payload["embeds"]), 1)
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "PR #42: Add Discord CI notifications")
        self.assertEqual(
            embed["url"], "https://github.com/ROMzombie/MPCWithGenerativeArt/pull/42"
        )
        self.assertEqual(
            embed["description"],
            "This pull request integrates Discord notifications into the CI pipeline.",
        )
        self.assertEqual(embed["color"], notify_discord.EMBED_COLOR_SUCCESS)
        self.assertEqual(embed["author"]["name"], "testuser")
        self.assertEqual(embed["fields"][0]["name"], "PR Link")
        self.assertEqual(
            embed["fields"][0]["value"],
            "https://github.com/ROMzombie/MPCWithGenerativeArt/pull/42",
        )

    def test_build_discord_payload_empty_body(self):
        """Test payload construction with empty or whitespace description."""
        payload = notify_discord.build_discord_payload(
            pr_title="Quick Fix",
            pr_body="   ",
            pr_url="https://github.com/ROMzombie/MPCWithGenerativeArt/pull/1",
        )
        embed = payload["embeds"][0]
        self.assertEqual(embed["description"], "No description provided.")

    def test_build_discord_payload_truncation(self):
        """Test payload construction with oversized title and body."""
        huge_title = "A" * 300
        huge_body = "B" * 5000
        payload = notify_discord.build_discord_payload(
            pr_title=huge_title,
            pr_body=huge_body,
            pr_url="https://github.com/ROMzombie/MPCWithGenerativeArt/pull/99",
        )
        embed = payload["embeds"][0]
        self.assertLessEqual(len(embed["title"]), notify_discord.MAX_TITLE_LENGTH)
        self.assertTrue(embed["title"].endswith("..."))
        self.assertLessEqual(
            len(embed["description"]), notify_discord.MAX_DESCRIPTION_LENGTH
        )
        self.assertTrue(embed["description"].endswith("..."))

    def test_build_discord_payload_invalid_url(self):
        """Test payload construction with missing or invalid URL."""
        payload = notify_discord.build_discord_payload(
            pr_title="Local Branch",
            pr_body="Description",
            pr_url="",
        )
        embed = payload["embeds"][0]
        self.assertNotIn("url", embed)
        self.assertNotIn("fields", embed)

    @patch("urllib.request.urlopen")
    def test_send_discord_notification_success(self, mock_urlopen):
        """Test successful notification dispatch."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        payload = {"content": "hello"}
        result = notify_discord.send_discord_notification(
            webhook_url="https://discord.com/api/webhooks/test/123",
            payload=payload,
        )

        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertEqual(req.headers["User-agent"], "GitHub-Actions-CI/1.0")
        self.assertEqual(json.loads(req.data.decode("utf-8")), payload)

    @patch("urllib.request.urlopen")
    def test_send_discord_notification_http_error(self, mock_urlopen):
        """Test handling of HTTP errors from Discord."""
        mock_error = urllib.error.HTTPError(
            url="https://discord.com/api/webhooks/test/123",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"message": "Invalid Form Body"}'),
        )
        mock_urlopen.side_effect = mock_error

        result = notify_discord.send_discord_notification(
            webhook_url="https://discord.com/api/webhooks/test/123",
            payload={"content": "bad"},
        )
        self.assertFalse(result)

    @patch("urllib.request.urlopen")
    def test_send_discord_notification_exception(self, mock_urlopen):
        """Test handling of general network exceptions."""
        mock_urlopen.side_effect = TimeoutError("Timed out")

        result = notify_discord.send_discord_notification(
            webhook_url="https://discord.com/api/webhooks/test/123",
            payload={"content": "bad"},
        )
        self.assertFalse(result)

    def test_main_dry_run(self):
        """Test main entrypoint in dry-run mode."""
        test_args = [
            "notify_discord.py",
            "--title",
            "Test PR",
            "--body",
            "Test Body",
            "--url",
            "https://github.com/ROMzombie/MPCWithGenerativeArt/pull/5",
            "--dry-run",
        ]
        with patch.object(sys, "argv", test_args):
            exit_code = notify_discord.main()
            self.assertEqual(exit_code, 0)

    @patch.dict(os.environ, {
        "PR_TITLE": "Env PR Title",
        "PR_BODY": "Env PR Body",
        "PR_URL": "https://github.com/ROMzombie/MPCWithGenerativeArt/pull/10",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/env",
    })
    @patch("notify_discord.send_discord_notification")
    def test_main_with_env_vars(self, mock_send):
        """Test main entrypoint using environment variables."""
        mock_send.return_value = True
        test_args = ["notify_discord.py"]
        with patch.object(sys, "argv", test_args):
            exit_code = notify_discord.main()
            self.assertEqual(exit_code, 0)
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            self.assertEqual(
                call_kwargs["webhook_url"],
                "https://discord.com/api/webhooks/test/env",
            )
            payload = call_kwargs["payload"]
            self.assertIn("Env PR Title", payload["embeds"][0]["title"])
            self.assertEqual(payload["embeds"][0]["description"], "Env PR Body")

    @patch.dict(os.environ, {}, clear=True)
    @patch("notify_discord.send_discord_notification")
    def test_main_missing_webhook_skips(self, mock_send):
        """Test main entrypoint writes to log and skips when secret is not set."""
        test_args = ["notify_discord.py"]
        with patch.object(sys, "argv", test_args):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                exit_code = notify_discord.main()
                self.assertEqual(exit_code, 0)
                mock_send.assert_not_called()
                output = mock_stdout.getvalue()
                self.assertIn("DISCORD_WEBHOOK_URL secret is not present. Skipping step.", output)


if __name__ == "__main__":
    unittest.main()

