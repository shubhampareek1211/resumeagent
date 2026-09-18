#!/usr/bin/env python3
"""One-way sync: applications.md (Active table) -> Notion Job Applications DB.

Usage:
  .venv/bin/python scripts/sync_applications_to_notion.py --dry-run   # default, no writes
  .venv/bin/python scripts/sync_applications_to_notion.py --live       # write to Notion
  .venv/bin/python scripts/sync_applications_to_notion.py --live --single sample_resume

Identity: persistent Application ID; exact Company+Role+Date migration for legacy pages.
Lookup failures and ambiguous matches stop writes. Filename is never an identity.

Secrets: read from .env (NOTION_TOKEN, NOTION_DB_ID) — never printed, never committed.
NOTION_DB_ID accepts raw hex, dashed UUID, or full Notion URL (auto-extracted).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from applications import application_id, read_manifest, mark_sync, sync_state, locked, migrate_manifest

ROOT = Path(__file__).resolve().parent.parent
APPS_MD = ROOT / "applications.md"

ALLOWED_STATUSES = {"Draft", "Applied", "Interview", "Offer", "Rejected", "Archived", "Lost", "Base"}
PLACEHOLDER_TOKENS = {"—", "-", "--", "–", ""}


def load_dotenv() -> None:
    """Minimal .env loader (avoids hard dep on python-dotenv)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        # strip inline comments only when value is unquoted
        if v and v[0] not in ("'", '"') and " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k and k not in os.environ:
            os.environ[k] = v


def norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def normalize_db_id(raw: str) -> str:
    raw = raw.strip().strip('"').strip("'")
    m = re.search(
        r"([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})",
        raw,
    )
    if not m:
        raise ValueError("NOTION_DB_ID has no 32-hex-char ID (paste DB URL or hex ID)")
    hex32 = m.group(1).replace("-", "").lower()
    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


def is_real_filename(value: str) -> bool:
    v = value.strip()
    if v in PLACEHOLDER_TOKENS:
        return False
    if "MISSING" in v.upper():
        return False
    if " " in v:  # e.g. "(uses general DE resume)"
        return False
    return True


def parse_active_table() -> list[dict]:
    """Read legacy or ID-bearing tables, rejecting malformed or duplicate rows."""
    return [row for _, row in read_manifest(APPS_MD)[3]]


def build_notion_props(row: dict, schema: dict) -> dict:
    """Build Notion properties dict, adapting to actual DB schema types.

    schema: {prop_name: prop_type} from live DB retrieve.
    Title prop is required — we use Company for it (or first title prop found).
    """
    props: dict = {}
    # find title prop (should be Company)
    title_prop = next((k for k, t in schema.items() if t == "title"), "Company")

    def set_prop(name: str, value):
        if name not in schema:
            return  # skip silently if user renamed/removed column
        t = schema[name]
        if t == "title":
            props[name] = {"title": [{"text": {"content": value[:100]}}]}
        elif t == "rich_text":
            props[name] = {"rich_text": [{"text": {"content": value[:2000]}}] if value not in PLACEHOLDER_TOKENS else []}
        elif t == "select":
            if value in ALLOWED_STATUSES:
                props[name] = {"select": {"name": value}}
        elif t == "date":
            if re.match(r"\d{4}-\d{2}-\d{2}", value):
                props[name] = {"date": {"start": value}}
        elif t == "status" and value in ALLOWED_STATUSES:
            props[name] = {"status": {"name": value}}

    # Company goes to title prop (usually Company itself)
    if title_prop == "Company":
        set_prop("Company", row["Company"])
    else:
        # fallback: put company into whatever the title prop is
        if title_prop in schema:
            t = schema[title_prop]
            if t == "title":
                props[title_prop] = {"title": [{"text": {"content": row["Company"][:100]}}]}

    for key in ("Role", "Resume file", "Cover letter", "Status", "Date", "Application ID"):
        # Company already handled if it is the title
        if key == "Company":
            continue
        set_prop(key, application_id(row) if key == "Application ID" else row[key])
    # ensure Company set even when schema has Company as rich_text (non-title edge)
    if "Company" in schema and "Company" not in props:
        set_prop("Company", row["Company"])
    return props


def query_ds(client, ds_id: str, **kwargs):
    """Query a data source — works on notion-client v3 (data_sources) and v2 (databases)."""
    if hasattr(client, "data_sources"):
        return client.data_sources.query(data_source_id=ds_id, **kwargs)
    return client.databases.query(database_id=ds_id, **kwargs)  # type: ignore


def _plain(prop: dict | None) -> str:
    if not prop:
        return ""
    if prop.get("type") == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if prop.get("type") == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    return ""


def validate_schema(schema):
    expected = {"Company": {"title", "rich_text"}, "Role": {"rich_text"},
                "Date": {"date"}, "Resume file": {"rich_text"},
                "Cover letter": {"rich_text"}, "Status": {"status", "select", "rich_text"}}
    for name, types in expected.items():
        if schema.get(name) not in types:
            raise ValueError(f"Missing or incompatible Notion property: {name}")
    if not any(t == "title" for t in schema.values()):
        raise ValueError("Notion schema has no title")
    if "Application ID" in schema and schema["Application ID"] != "rich_text":
        raise ValueError("Application ID must be rich_text")


def composite_filter(row, schema):
    return {"and": [
        {"property": "Company", schema["Company"]: {"equals": row["Company"]}},
        {"property": "Role", "rich_text": {"equals": row["Role"]}},
        {"property": "Date", "date": {"equals": row["Date"]}},
    ]}


def unique_match(client, ds_id, filter):
    # Two results suffice to reject ambiguity. Never turn a failed request into a miss.
    response = query_ds(client, ds_id, filter=filter, page_size=2)
    results = response["results"]
    if len(results) > 1 or response.get("has_more"):
        raise ValueError("Multiple Notion pages match this application; resolve duplicates first")
    return results[0] if results else None


def find_existing(client, ds_id, row, schema):
    identity = application_id(row)
    if "Application ID" in schema:
        page = unique_match(client, ds_id, {"property": "Application ID", "rich_text": {"equals": identity}})
        if page:
            return page
    # Migrate existing six-column records without creating duplicates.
    page = unique_match(client, ds_id, composite_filter(row, schema))
    if page:
        old_id = _plain(page.get("properties", {}).get("Application ID"))
        if old_id and old_id != identity:
            raise ValueError("Legacy match belongs to a different Application ID")
    return page


def ensure_identity_property(client, ds_id, schema, is_ds):
    if "Application ID" not in schema:
        properties = {"Application ID": {"rich_text": {}}}
        if is_ds:
            client.data_sources.update(data_source_id=ds_id, properties=properties)
        else:
            client.databases.update(database_id=ds_id, properties=properties)
        schema["Application ID"] = "rich_text"


def get_ds_id_and_schema(client, db_id: str) -> tuple[str, dict, str, bool]:
    """Resolve database -> data source (Notion API 2025+).

    Returns (write_id, schema, title, is_data_source). write_id is the data
    source ID when the DB exposes one, else the DB ID for the legacy API.
    """
    db = client.databases.retrieve(database_id=db_id)
    title_parts = db.get("title") or []
    title = title_parts[0].get("plain_text", "?") if title_parts else "?"
    sources = db.get("data_sources") or []
    if len(sources) > 1:
        raise ValueError("Database has multiple data sources; use a dedicated applications database")
    if sources:
        ds_id = sources[0]["id"]
        ds = client.data_sources.retrieve(data_source_id=ds_id)
        schema = {k: v.get("type", "") for k, v in ds.get("properties", {}).items()}
        return ds_id, schema, title, True
    # old API fallback: properties live directly on the database
    schema = {k: v.get("type", "") for k, v in db.get("properties", {}).items()}
    return db_id, schema, title, False


def create_page(client, ds_id: str, props: dict, is_ds: bool):
    if is_ds and hasattr(client, "data_sources"):
        return client.pages.create(parent={"data_source_id": ds_id}, properties=props)
    return client.pages.create(parent={"database_id": ds_id}, properties=props)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync applications.md -> Notion (default dry-run)")
    ap.add_argument("--live", action="store_true", help="actually write to Notion")
    ap.add_argument("--dry-run", action="store_true", help="preview only (default)")
    ap.add_argument("--single", default=None, help="only sync one Resume file substring")
    ap.add_argument("--application-id", help="sync exactly this application ID")
    ap.add_argument("--pending", action="store_true", help="retry only pending or failed syncs")
    ap.add_argument("--sleep", type=float, default=0.2, help="seconds between writes")
    args = ap.parse_args()

    live = args.live and not args.dry_run  # --dry-run wins if both passed
    if not args.live and not args.dry_run:
        live = False  # default safe: dry-run

    load_dotenv()
    token = os.environ.get("NOTION_TOKEN", "").strip()
    raw_db = os.environ.get("NOTION_DB_ID", "").strip()
    if not token:
        print("❌ NOTION_TOKEN missing in .env")
        return 2
    try:
        db_id = normalize_db_id(raw_db)
    except ValueError as e:
        print(f"❌ {e}")
        return 2

    try:
        from notion_client import Client
    except ImportError:
        print("❌ notion-client not installed. Run ./scripts/setup.sh and use .venv/bin/python")
        return 2

    try:
        if live:
            migrate_manifest(APPS_MD)
        rows = parse_active_table()
    except FileNotFoundError:
        print(f"❌ {APPS_MD} not found")
        return 2
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    total_parsed = len(rows)
    if args.application_id:
        rows = [r for r in rows if r["Application ID"] == args.application_id]
        if not rows:
            print("Application ID not found")
            return 2
    if args.pending:
        state = sync_state(ROOT)
        rows = [r for r in rows if state.get(r["Application ID"], {}).get("status") in {"pending", "failed"}]
    if args.single:
        needle = args.single.lower()
        rows = [r for r in rows if needle in r["Resume file"].lower()
                or needle in r["Company"].lower() or needle in r["Role"].lower()]
        if not rows:
            print(f"ℹ️ no rows match --single={args.single!r} (searched Resume file, Company, Role)")
            return 0

    print(f"📋 Parsed {total_parsed} Active rows from applications.md"
          + (f" (filtered to {len(rows)} by --single)" if args.single else ""))
    if args.sleep < 0:
        print("❌ --sleep must be >= 0")
        return 2

    if not rows:
        print("No applications selected; nothing to sync.")
        return 0

    if live:
        for row in rows:
            mark_sync(ROOT, row["Application ID"], "pending")
    client = Client(auth=token, notion_version="2025-09-03")
    try:
        ds_id, schema, db_title, is_ds = get_ds_id_and_schema(client, db_id)
        validate_schema(schema)
        if live:
            ensure_identity_property(client, ds_id, schema, is_ds)
    except Exception as e:
        msg = str(e)
        if "Could not find database" in msg or "404" in msg:
            print("❌ DB not found. Fix: Share the DB with the configured integration (Share → Add connections).")
        elif "Unauthorized" in msg or "401" in msg:
            print("❌ Unauthorized. Regenerate NOTION_TOKEN in notion.so/my-integrations and update .env.")
        else:
            print(f"❌ DB access/schema preflight failed ({type(e).__name__}); verify property names and types.")
        return 1

    print(f"🗄️  DB: {db_title} | props: {schema}")
    created = updated = skipped = warned = 0
    failed: list[str] = []
    for row in rows:
        label = f"{row['Date']} | {row['Company']} | {row['Role']} | {row['Resume file']} | {row['Status']}"
        if row["Status"] not in ALLOWED_STATUSES:
            print(f"  ⚠️  unknown Status {row['Status']!r} — will sync without Status ({label})")
            warned += 1
        if not re.match(r"\d{4}-\d{2}-\d{2}", row["Date"]):
            print(f"  ⚠️  non-date {row['Date']!r} — will sync without Date ({label})")
            warned += 1
        try:
            existing = find_existing(client, ds_id, row, schema)
        except Exception as e:
            msg = f"lookup failed ({type(e).__name__})"
            print(f"❌ FAILED {label}: {msg}")
            failed.append(label)
            if live:
                mark_sync(ROOT, row["Application ID"], "failed", type(e).__name__)
            continue
        props = build_notion_props(row, schema)
        if not live:
            action = "UPDATE" if existing else "CREATE"
            print(f"[{action}] {label}")
            skipped += 1
            continue
        try:
            if existing:
                client.pages.update(page_id=existing["id"], properties=props)
                updated += 1
                print(f"[UPDATED] {label}")
            else:
                create_page(client, ds_id, props, is_ds)
                created += 1
                print(f"[CREATED] {label}")
        except Exception as e:
            print(f"❌ FAILED {label}: {type(e).__name__}")
            failed.append(label)
            if live:
                mark_sync(ROOT, row["Application ID"], "failed", type(e).__name__)
            continue
        mark_sync(ROOT, row["Application ID"], "synced")
        time.sleep(args.sleep)

    mode = "LIVE" if live else "DRY-RUN (no writes)"
    print(f"\n{'❌' if failed else '✅'} {mode} done — parsed={total_parsed} filtered={len(rows)} "
          f"created={created} updated={updated} previewed={skipped} warnings={warned} failed={len(failed)}")
    for f in failed:
        print(f"❌ failed: {f}")
    if not live:
        print("Run with --live to write. Example: .venv/bin/python scripts/sync_applications_to_notion.py --live")
    return 1 if failed else 0


if __name__ == "__main__":
    with locked(ROOT / ".state/notion.lock"):
        sys.exit(main())
