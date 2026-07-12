# Outlook Module

Current module version: `26.7.12A`

This directory is the target home for Outlook-specific code and documentation.

The Graph metadata client and local mailbox server now live under `outlook/`.
Registration, unlock, broker, and platform-facing mailbox helpers still live at
the project root or under `common/` so existing CLI commands and WebUI entries
keep working. Move the remaining modules here in small, compatible steps.

## Current Scope

Outlook-specific responsibilities include:

- Outlook account registration and account-pool production.
- Outlook account unlock workflows.
- Microsoft Graph refresh-token extraction.
- Outlook mailbox code/link retrieval.
- Shared mailbox broker service for parallel platform registration.
- Runtime files such as account pools, screenshots, unlock results, and Graph
  token exports.

## Current Files To Split Later

| Current path | Role |
|---|---|
| `outlook_reg_loop.py` | Loops Outlook self-registration and writes usable accounts to the pool. |
| `register_outlook_standalone.py` | Standalone Outlook registration flow. |
| `unlock_outlook.py` | Unlocks locked Outlook accounts. |
| `extract_graph_tokens.py` | Extracts Microsoft Graph refresh tokens from Outlook accounts. |
| `mailbox_broker.py` | Local shared Outlook mailbox code/link broker. |
| `common/mailbox.py` | Outlook mailbox reading via Graph API or browser fallback. |
| `common/emails.py` | Shared email-pool reservation and state files. |
| `_outlook_pool/` | Runtime Outlook account pool. |
| `screenshots_outlook/` | Outlook-specific screenshots. |

## Current Local Files

| Path | Role |
|---|---|
| `mailbox_graph.py` | Reads Graph mailbox folder lists and message title metadata from RT account files. |
| `server/` | Runs the local aiohttp mailbox UI and authenticated mailbox metadata API. |
| `db/` | Runtime folder-list CSV output. Account CSV files are Git-ignored. |
| `out/` | Runtime message-title CSV output. Account CSV files are Git-ignored. |

## Local Mailbox Server

The server reads account records from `graph_refresh_token/out/*.txt` and serves
an authenticated mailbox UI plus JSON metadata endpoints. It never requests
message body fields.

### Start

Use the project Python environment:

```powershell
D:\0Code2\py312\python.exe outlook/server/main.py --host 127.0.0.1 --port 8780
```

Open `http://127.0.0.1:8780`. The default account directory can be replaced with
`--accounts-dir <path>`; Graph proxy use is opt-in through
`--use-system-proxy`.

### Authentication And Local Whitelist

- Normal login validates the mailbox address and password stored in the matching
  Graph account file.
- Local passwordless login is enabled only when the original `Host` name and
  `request.remote` are both exactly `127.0.0.1`.
- `localhost`, proxy identity headers, and forwarded IP headers do not satisfy
  the whitelist.
- A local-whitelist session can access all account files. The server rechecks
  host and IP on every request and invalidates that session if either changes.
- A normal session can access only its own mailbox.

### Mailbox UI

The mailbox page provides:

- an account list, with all accounts visible to a local-whitelist session;
- a recipient-address list containing the primary address and observed aliases;
- Graph mail folders and unread counts;
- message title metadata with `Subject`, `From`, `To`, and received time columns;
- a per-recipient link to the latest-message subject API.

Recipient addresses are discovered from recent `toRecipients` metadata in the
inbox and junk-mail folders. The primary mailbox address is always included,
even when no recent message targets it. This is an observed-recipient list, not
an authoritative Microsoft account alias inventory.

### HTTP API

All mailbox data endpoints require the current session cookie; the auth
endpoints establish, inspect, or delete that session. `/health` is public.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service name, version, time, and account-directory readiness. |
| `POST` | `/api/auth/query` | Validate credentials or report local-whitelist availability. |
| `POST` | `/api/auth/login` | Create the in-memory mailbox session. |
| `GET` | `/api/auth/me` | Return the current session and a renewed mailbox entry token. |
| `POST` | `/api/auth/logout` | Delete the current session cookie and server-side session. |
| `GET` | `/api/accounts` | Return all authorized mailbox accounts. |
| `GET` | `/api/folders?email=<address>` | Return Graph folder metadata. |
| `GET` | `/api/messages?email=<address>&folder=inbox&top=20` | Return message title metadata, including `toRecipients`. |
| `GET` | `/api/mailboxes/<address>/recipients` | Return the primary and observed recipient addresses. |
| `GET` | `/api/mailboxes/<address>/messages/latest` | Return the latest inbox subject. |
| `GET` | `/api/mailboxes/<address>/messages/latest?recipient=<address>` | Return the latest subject addressed to one alias. |

Examples:

```text
GET /api/mailboxes/user@outlook.com/recipients
GET /api/mailboxes/user@outlook.com/messages/latest
GET /api/mailboxes/user@outlook.com/messages/latest?recipient=user%2B2%40outlook.com
```

The latest-message response deliberately exposes only the subject:

```json
{
  "ok": true,
  "mailbox": "user@outlook.com",
  "recipient": "user+2@outlook.com",
  "folder": "inbox",
  "found": true,
  "subject": "Example subject"
}
```

### Logs And Verification

Runtime logs and Playwright screenshots are written under
`outlook/server/log/`. Its local `.gitignore` keeps every generated artifact out
of Git while preserving the directory itself.

```powershell
D:\0Code2\py312\python.exe -m unittest discover -s outlook/server/tests -p "test_*.py"
D:\0Code2\py312\python.exe -m py_compile outlook/mailbox_graph.py outlook/server/main.py
node --check outlook/server/static/mailbox.js
```

## Graph Mailbox Metadata Export

`mailbox_graph.py` belongs here because it reads Outlook mailbox metadata. It uses
RT files produced by `graph_refresh_token/oauth_graph.py` as input, but does not
belong to the RT extraction subproject.

Default input:

```text
graph_refresh_token/out/*.txt
```

Default outputs:

```text
outlook/db/<email>.csv
outlook/out/<email>+<folder>.csv
```

Access-token persistence output:

```text
outlook/db/at.csv
```

Run all token files:

```powershell
graph_refresh_token/.venv/Scripts/python.exe outlook/mailbox_graph.py
```

Run one account:

```powershell
graph_refresh_token/.venv/Scripts/python.exe outlook/mailbox_graph.py --email "user@hotmail.com"
```

Only export one folder, for example junk mail:

```powershell
graph_refresh_token/.venv/Scripts/python.exe outlook/mailbox_graph.py --folder "垃圾邮件"
```

The message-title export intentionally does not request message body fields:

```text
body
bodyPreview
uniqueBody
attachments/contentBytes
$value
```

### Persist Graph Access Tokens

Access tokens are short-lived. Use RT files from `graph_refresh_token/out/` to
refresh current access tokens and decode their JWT header/payload into
`outlook/db/at.csv`:

```powershell
graph_refresh_token/.venv/Scripts/python.exe outlook/mailbox_graph.py --export-at
```

Only one account:

```powershell
graph_refresh_token/.venv/Scripts/python.exe outlook/mailbox_graph.py --export-at --email "user@hotmail.com"
```

The CSV includes the raw access token plus decoded JWT fields. Important
columns:

```text
email
client_id
token_type
scope
access_token
is_jwt
jwt_part_count
jwt_parse_status
refreshed_at_utc
expires_in
ext_expires_in
response_expires_at_utc
issued_at_utc
not_before_utc
expires_at_utc
expires_in_seconds
jwt_header_*
jwt_claim_*
```

Some Microsoft Graph access tokens, especially for consumer Outlook accounts,
may be opaque tokens rather than `header.payload.signature` JWTs. In that case
`is_jwt=false`, `jwt_parse_status=not_jwt_or_opaque`, and the JWT claim columns
will be absent. Use `expires_in` and `response_expires_at_utc` from the token
endpoint response as the effective lifetime.

`outlook/db/*.csv` is Git-ignored because these files contain account data and
short-lived access tokens.

## Future: Push-Like Mail Updates

Microsoft Graph has two approaches that can replace or improve simple polling.

### Change Notifications / Webhook

This is the closest Graph equivalent to IMAP `IDLE`.

Flow:

```text
Create a Graph subscription
  -> Microsoft posts change notifications to our HTTPS webhook
  -> webhook validates clientState
  -> worker uses Graph API to fetch the changed message metadata/content
```

Typical resources:

```text
me/mailFolders('inbox')/messages
me/mailFolders('junkemail')/messages
```

Tradeoffs:

- Near real-time.
- Requires a public HTTPS webhook endpoint.
- Subscriptions expire and must be renewed.
- Notifications can be duplicated or delayed, so the receiver still needs
  idempotency and fallback sync.
- More suitable after the local mailbox flow is stable.

### Delta Query

Delta Query is not push, but it is the better first step for this local project.

Flow:

```text
First call /messages/delta for a folder
  -> save @odata.deltaLink
Next call with deltaLink
  -> Graph returns only created/updated/deleted changes
  -> update saved deltaLink
```

Typical endpoint:

```text
GET https://graph.microsoft.com/v1.0/me/mailFolders/{folder_id}/messages/delta
```

Suggested local state file:

```text
outlook/db/delta_state.csv
```

Suggested columns:

```text
email,folder_id,folder_name,delta_link,last_sync_at
```

Recommended future CLI:

```powershell
graph_refresh_token/.venv/Scripts/python.exe outlook/mailbox_graph.py --watch-delta --folder "收件箱" --folder "垃圾邮件" --interval 3
```

Why Delta Query first:

- Works from a local script.
- Does not need a public webhook.
- Reuses current RT/AT and folder-id logic.
- Avoids repeatedly scanning full folders.
- Good fit for verification-code polling.

References:

- `https://learn.microsoft.com/en-us/graph/change-notifications-overview`
- `https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks`
- `https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions`
- `https://learn.microsoft.com/en-us/graph/api/message-delta`
- `https://learn.microsoft.com/en-us/graph/delta-query-messages`

## Suggested Migration Order

1. Move pure Outlook helpers first, starting with mailbox and Graph utilities.
2. Move standalone CLI scripts one at a time and leave root compatibility
   wrappers if needed.
3. Update `webui/scripts.py` command paths after each script move.
4. Update README and project overview docs.
5. Move runtime output paths only after scripts support configurable paths.
