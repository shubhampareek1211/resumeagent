# Connect your own Notion database

Notion is optional. `--local-only` builds need neither a token nor a database.
Do this setup on your machine, never by putting tokens in GitHub Actions secrets.

## 1. Create a private connection

Create an **internal connection/integration** for your workspace in Notion's developer
settings. Give it read, insert and update content access; this workflow does not need
user-directory or comment access. Copy its token into the ignored `.env` as
`NOTION_TOKEN`. Use a dedicated application-tracking database and grant the connection
access to that database through its Connections menu. Access is separate from the
connection's capabilities. See [Notion's connection guide](https://www.notion.com/help/create-integrations-with-the-notion-api)
and [connection access management](https://www.notion.com/help/add-and-manage-connections-with-the-api).

No public database sharing, OAuth application, callback URL or hosted server is needed.
The repository never ships a shared token or database ID.

## 2. Create the schema

Create a full-page database with one data source. Rename its default title property
(e.g. Name) to **Company**. Add these properties with exact names:

| Property | Notion type | Example (fictional) |
| --- | --- | --- |
| Company | Title | Example Company |
| Role | Text | Software Developer |
| Date | Date | Application creation date |
| Resume file | Text | example_role |
| Cover letter | Text | example_letter |
| Status | Select | Draft |
| Application ID | Text | Generated locally; do not enter manually |

For Status, add `Draft`, `Applied`, `Interview`, `Offer`, `Rejected`, `Archived`,
`Lost`, and `Base`. Status or Text properties also work; for a Status property, configure
all needed options. Company can alternatively be Text if another title property exists.
All other property types must match the table.

Application ID may be omitted initially; the first live sync adds it. Its creation uses
Notion's [data source update API](https://developers.notion.com/reference/update-a-data-source).
The client explicitly uses API version `2025-09-03` with the pinned Python SDK.
Databases with multiple data sources are rejected to avoid choosing the wrong target.

## 3. Configure and check

Setup already creates a blank, ignored `.env`. Fill it locally:

```dotenv
NOTION_TOKEN=your_private_connection_token
NOTION_DB_ID=your_database_url_or_id
```

Use the database's own URL, not a row/page URL or a linked-view-only URL. Raw UUIDs
and dashed IDs also work. Environment variables override `.env` values.

```sh
.venv/bin/python scripts/check_notion.py
```

This only reads the database and validates its schema. It never adds properties/pages
or prints credential values. It works even when the local application table is empty.

## 4. Sync a real application

First prepare your own source/keywords and build locally:

```sh
./build.sh --type resume example_role "Example Company" "Software Developer" --local-only
```

The output prints the application UUID. Preview exactly that row:

```sh
.venv/bin/python scripts/sync_applications_to_notion.py --dry-run --application-id UUID
.venv/bin/python scripts/sync_applications_to_notion.py --live --application-id UUID
```

Normal builds without `--local-only` perform the scoped live sync automatically.
A failed sync returns nonzero; retry using `--live --pending`. Unfiltered `--live`
syncs all Active rows. Existing legacy records are migrated by exact company/role/date.
Keep those fields unchanged until the first successful ID migration.

## What is transmitted

Company, role, date, status, resume/cover-letter **filenames** and Application ID.
No PDF bytes, source resume, job-description file, contact profile or truth ledger is
uploaded by the scripts. The Notion token is used only for API authentication.
This tracker does not submit job applications. Local status wins over Notion status.

## Troubleshooting

| Symptom | Resolution |
| --- | --- |
| Missing token | Set NOTION_TOKEN in local .env; run with project .venv |
| Unauthorized | Check/rotate the token and confirm the intended workspace |
| Database not found | Verify the database ID and grant the connection access |
| Schema preflight failed | Check exact property names/types and single data source |
| Forbidden write | Enable insert/update content and database access |
| Duplicate match | Resolve duplicate Notion rows; do not blindly retry creation |
| Network failure/rate limit | Wait and retry pending records; lookup errors never authorize creation |
| Notion status reverted | Update applications.md; this is one-way synchronization |

Keep .env backed up securely outside Git. If exposed, revoke the token immediately;
removing it from the latest commit does not remove it from Git history.
