# Outlook Module

This directory is the target home for Outlook-specific code and documentation.

Current Outlook-related files still live at the project root or under `common/`
so existing CLI commands and WebUI entries keep working. Move them here in small
steps and update imports, subprocess paths, WebUI schema, and documentation in
the same change.

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

## Suggested Migration Order

1. Move pure Outlook helpers first, starting with mailbox and Graph utilities.
2. Move standalone CLI scripts one at a time and leave root compatibility
   wrappers if needed.
3. Update `webui/scripts.py` command paths after each script move.
4. Update README and project overview docs.
5. Move runtime output paths only after scripts support configurable paths.

