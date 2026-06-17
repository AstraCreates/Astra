"""Supabase tools — provision DB tables, RLS, auth, storage for user projects."""
import logging
import requests
from backend.config import settings
from backend.provisioning.supabase_provisioner import provision_supabase_project

logger = logging.getLogger(__name__)
_API = "https://api.supabase.com/v1"


def _headers():
    tok = getattr(settings, "supabase_management_token", "")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"} if tok else {}


def supabase_create_project(
    project_name: str,
    region: str = "us-east-1",
    org_id: str = "",
) -> dict:
    """
    Create a new Supabase project via Management API. Returns project_ref, anon_key,
    service_role_key, db_connection_string, and dashboard_url.
    Falls back to manual setup instructions if SUPABASE_MANAGEMENT_TOKEN is not set.

    Args:
        project_name: short name for the project (kebab-case recommended)
        region: AWS region (us-east-1, eu-west-1, ap-southeast-1, etc.)
        org_id: Supabase org ID — auto-detected from account if omitted
    """
    return provision_supabase_project(
        founder_id="agent",
        project_name=project_name,
        org_id=org_id,
        region=region,
    )


def supabase_create_table(project_ref: str, table_name: str, columns: list[dict]) -> dict:
    """
    Create table in Supabase project via SQL.
    columns: [{"name": "id", "type": "uuid", "primary": true}, ...]
    Falls back to returning SQL if no management token.
    """
    col_defs = []
    for c in columns:
        defn = f"{c['name']} {c['type']}"
        if c.get("primary"):
            defn += " PRIMARY KEY DEFAULT gen_random_uuid()"
        if c.get("not_null"):
            defn += " NOT NULL"
        if c.get("default"):
            defn += f" DEFAULT {c['default']}"
        col_defs.append(defn)
    col_defs.append("created_at timestamptz DEFAULT now()")

    sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n  " + ",\n  ".join(col_defs) + "\n);"

    if not _headers():
        return {"sql": sql, "note": "SUPABASE_MANAGEMENT_TOKEN not set — run this SQL in Supabase dashboard"}

    try:
        resp = requests.post(
            f"{_API}/projects/{project_ref}/database/query",
            headers=_headers(), json={"query": sql}, timeout=15,
        )
        return {"created": resp.ok, "table": table_name, "sql": sql, "status": resp.status_code}
    except Exception as e:
        return {"error": str(e), "sql": sql}


def supabase_enable_rls(project_ref: str, table_name: str, policies: list[dict] = None) -> dict:
    """
    Enable Row Level Security on table and create policies.
    policies: [{"name": "Users own rows", "using": "auth.uid() = user_id"}]
    """
    sqls = [f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;"]
    for p in (policies or []):
        sqls.append(
            f"CREATE POLICY \"{p['name']}\" ON {table_name} "
            f"FOR ALL USING ({p['using']});"
        )
    sql = "\n".join(sqls)
    if not _headers():
        return {"sql": sql, "note": "Run in Supabase SQL Editor"}
    try:
        resp = requests.post(
            f"{_API}/projects/{project_ref}/database/query",
            headers=_headers(), json={"query": sql}, timeout=15,
        )
        return {"enabled": resp.ok, "table": table_name, "sql": sql}
    except Exception as e:
        return {"error": str(e), "sql": sql}


def supabase_setup_auth(project_ref: str, providers: list[str] = None) -> dict:
    """
    Return auth setup instructions and code snippets for Supabase Auth.
    providers: ['google', 'github', 'magic_link', 'email']
    """
    providers = providers or ["email", "magic_link"]
    snippets = {
        "install": "npm install @supabase/supabase-js @supabase/auth-helpers-nextjs",
        "client": (
            "import { createClient } from '@supabase/supabase-js'\n"
            "export const supabase = createClient(\n"
            "  process.env.NEXT_PUBLIC_SUPABASE_URL!,\n"
            "  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!\n)"
        ),
        "signin_magic": (
            "await supabase.auth.signInWithOtp({ email })"
        ) if "magic_link" in providers else None,
        "signin_google": (
            "await supabase.auth.signInWithOAuth({ provider: 'google' })"
        ) if "google" in providers else None,
        "get_user": "const { data: { user } } = await supabase.auth.getUser()",
        "signout": "await supabase.auth.signOut()",
        "env_vars": ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    }
    return {
        "project_ref": project_ref,
        "providers": providers,
        "snippets": {k: v for k, v in snippets.items() if v},
        "dashboard_url": f"https://app.supabase.com/project/{project_ref}/auth/providers",
    }


def supabase_create_storage_bucket(project_ref: str, bucket_name: str, public: bool = False) -> dict:
    """Create a Supabase Storage bucket for file uploads."""
    if not _headers():
        return {
            "sql": f"-- Create bucket '{bucket_name}' in Supabase Dashboard > Storage",
            "code": (
                f"await supabase.storage.createBucket('{bucket_name}', {{ public: {str(public).lower()} }})"
            ),
        }
    try:
        resp = requests.post(
            f"{_API}/projects/{project_ref}/storage/buckets",
            headers=_headers(),
            json={"name": bucket_name, "public": public},
            timeout=15,
        )
        return {"created": resp.ok, "bucket": bucket_name, "public": public}
    except Exception as e:
        return {"error": str(e)}


def supabase_generate_schema(app_name: str = "", entities: list[str] | None = None) -> dict:
    """
    Generate a complete Supabase schema (SQL + RLS) for an app's entities.
    entities: ['users', 'posts', 'comments']
    """
    from backend.tools._arg_utils import parse_list_arg
    if not app_name:
        return {"error": "app_name is required"}
    entities = parse_list_arg(entities, "entities")
    if not entities:
        return {"error": "entities is required — pass a list of table names, e.g. [\"users\", \"posts\", \"comments\"]"}
    tables = []
    for entity in entities:
        if isinstance(entity, dict):
            entity = entity.get("name") or entity.get("table") or str(entity)
        singular = entity.rstrip("s")
        tables.append({
            "table": entity,
            "sql": (
                f"CREATE TABLE IF NOT EXISTS {entity} (\n"
                f"  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n"
                f"  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,\n"
                f"  created_at timestamptz DEFAULT now(),\n"
                f"  updated_at timestamptz DEFAULT now()\n);\n"
                f"ALTER TABLE {entity} ENABLE ROW LEVEL SECURITY;\n"
                f"CREATE POLICY \"Users own {entity}\" ON {entity} FOR ALL USING (auth.uid() = user_id);"
            ),
        })
    return {
        "app": app_name,
        "entities": entities,
        "tables": tables,
        "full_sql": "\n\n".join(t["sql"] for t in tables),
        "note": "Run full_sql in Supabase SQL Editor to create all tables with RLS",
    }
