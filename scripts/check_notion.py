#!/usr/bin/env python3
"""Read-only connection/schema check; never adds columns or pages."""
import os
from notion_client import Client
from sync_applications_to_notion import load_dotenv, normalize_db_id, get_ds_id_and_schema, validate_schema


def main():
    load_dotenv()
    token = os.environ.get('NOTION_TOKEN', '').strip()
    if not token:
        print('Missing NOTION_TOKEN. See docs/NOTION_SETUP.md.')
        return 2
    try:
        database = normalize_db_id(os.environ.get('NOTION_DB_ID', ''))
        client = Client(auth=token, notion_version='2025-09-03')
        _, schema, _, _ = get_ds_id_and_schema(client, database)
        validate_schema(schema)
    except Exception as exc:
        print(f'Connection/schema check failed ({type(exc).__name__}). See docs/NOTION_SETUP.md; no values logged.')
        return 1
    print('Connection and schema verified (read-only).')
    if 'Application ID' not in schema:
        print('First live sync will add the Application ID text property.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
