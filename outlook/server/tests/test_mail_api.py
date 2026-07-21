from __future__ import annotations

import unittest
from typing import Any

from outlook.mailbox_graph import GraphMailboxClient, message_recipient_addresses
from outlook.server import __version__
from outlook.server.main import latest_subject_api_url


class FakeRecipientClient(GraphMailboxClient):
    def __init__(self, messages_by_folder: dict[str, list[dict[str, Any]]]) -> None:
        self.messages_by_folder = messages_by_folder

    def list_message_titles(
        self,
        access_token: str,
        folder_id: str,
        top: int = 50,
    ) -> list[dict[str, Any]]:
        return self.messages_by_folder.get(folder_id, [])[:top]


class FakeLatestClient(GraphMailboxClient):
    def __init__(self, pages: dict[str, dict[str, Any]]) -> None:
        self.pages = pages

    def _graph_get(
        self,
        access_token: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self.pages[url]


def graph_message(address: str, received_at: str, subject: str = "Test") -> dict[str, Any]:
    return {
        "subject": subject,
        "receivedDateTime": received_at,
        "toRecipients": [
            {"emailAddress": {"name": address, "address": address}},
        ],
    }


class MailApiTests(unittest.TestCase):
    def test_service_version(self) -> None:
        self.assertEqual(__version__, "26.7.12A")

    def test_message_recipient_addresses_normalizes_duplicates(self) -> None:
        message = {
            "toRecipients": [
                {"emailAddress": {"name": "Alias", "address": "User+1@outlook.com"}},
                {"emailAddress": {"name": "Duplicate", "address": "user+1@outlook.com"}},
                {"emailAddress": {"name": "Missing"}},
            ]
        }

        self.assertEqual(
            message_recipient_addresses(message),
            [{"name": "Alias", "address": "User+1@outlook.com"}],
        )

    def test_recipient_list_includes_primary_and_observed_aliases(self) -> None:
        client = FakeRecipientClient(
            {
                "inbox": [
                    graph_message("user+2@outlook.com", "2026-07-12T10:00:00Z"),
                    graph_message("user@outlook.com", "2026-07-12T09:00:00Z"),
                ],
                "junkemail": [
                    graph_message("user+2@outlook.com", "2026-07-11T10:00:00Z"),
                ],
            }
        )

        recipients = client.list_recipient_addresses("token", "user@outlook.com")

        self.assertEqual([item["address"] for item in recipients], [
            "user@outlook.com",
            "user+2@outlook.com",
        ])
        self.assertTrue(recipients[0]["is_primary"])
        self.assertEqual(recipients[1]["message_count"], 2)
        self.assertEqual(recipients[1]["folders"], ["inbox", "junkemail"])

    def test_latest_message_title_filters_by_recipient(self) -> None:
        first_url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
        second_url = "page-2"
        client = FakeLatestClient(
            {
                first_url: {
                    "value": [graph_message("user@outlook.com", "2026-07-12T10:00:00Z", "Primary")],
                    "@odata.nextLink": second_url,
                },
                second_url: {
                    "value": [graph_message("user+2@outlook.com", "2026-07-12T09:00:00Z", "Alias")],
                },
            }
        )

        message = client.latest_message_title("token", recipient="USER+2@OUTLOOK.COM")

        self.assertIsNotNone(message)
        self.assertEqual(message["subject"], "Alias")

    def test_latest_subject_url_is_readable_and_encodes_alias_query(self) -> None:
        self.assertEqual(
            latest_subject_api_url("user@outlook.com", "user+2@outlook.com"),
            "/api/mailboxes/user@outlook.com/messages/latest?recipient=user%2B2%40outlook.com",
        )


if __name__ == "__main__":
    unittest.main()
