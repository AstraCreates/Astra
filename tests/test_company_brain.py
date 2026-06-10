from backend.tools.company_brain import (
    add_company_brain_record,
    ask_company_brain,
    company_brain_agent_context,
    company_brain_context,
    configure_company_brain_sync,
    get_company_brain,
    ingest_company_brain_records,
    maintain_company_brain,
    revise_company_brain_record,
    resolve_company_brain_proposal,
    run_due_company_brain_syncs,
    run_company_brain_sync,
    search_company_brain,
    sync_company_brain,
)
from backend.tools.company_brain_connectors import import_company_brain_sources
from backend.tools.graph_rag_ingest import run_graph_rag_sync
from backend.tools.graph_rag_v2 import export_graph_visualization


def test_company_brain_sync_add_and_search(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_test"

    added = add_company_brain_record(
        founder_id=founder_id,
        source="manual",
        title="Pricing decision",
        content="Use team pricing with a founder plan and enterprise tier.",
        canonical=True,
        stale_risk="low",
    )
    assert added["ok"] is True

    synced = sync_company_brain(founder_id, ["github", "notion"])
    assert synced["ok"] is True
    assert synced["record_count"] >= 3

    results = search_company_brain(founder_id, "enterprise pricing", 5)
    assert results["count"] >= 1
    assert results["results"][0]["title"] == "Pricing decision"

    brain = get_company_brain(founder_id)
    assert brain["sources"]["github"]["record_count"] >= 1
    assert any(record["canonical"] for record in brain["records"])
    assert brain["sources"]["github"]["credential_fields"] == ["token"]
    assert brain["sources"]["slack"]["credential_fields"] == ["bot_token"]
    assert brain["sources"]["granola"]["importer"] is False


def test_graph_rag_v2_sync_search_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_graph_v2"

    add_company_brain_record(
        founder_id=founder_id,
        source="manual",
        title="Enterprise pricing source",
        content="Astra should package enterprise pricing with SSO, audit logs, and founder onboarding.",
        canonical=True,
        stale_risk="low",
    )
    before = search_company_brain(founder_id, "enterprise pricing", 5)
    assert before["retrieval"] == "keyword"

    synced = run_graph_rag_sync(founder_id)
    assert synced["ok"] is True
    assert synced["inserted_chunks"] >= 1

    after = search_company_brain(founder_id, "enterprise pricing", 5)
    assert after["retrieval"] == "graph_rag_v2"
    assert after["count"] >= 1
    assert "Enterprise pricing source" in after["formatted"]

    context = company_brain_agent_context(founder_id, "enterprise pricing", 5)
    assert context["retrieval"] == "graph_rag_v2"
    assert context["relationships"] is not None

    snapshot = company_brain_context(founder_id, "anything", 5)
    assert "Company graph snapshot:" in snapshot

    graph = export_graph_visualization(founder_id)
    assert graph["ok"] is True
    assert graph["nodes"]


def test_company_brain_ingest_detects_conflicts_and_resolves_proposals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_maintenance"

    ingest = ingest_company_brain_records(
        founder_id,
        "notion",
        [
            {
                "title": "Architecture source of truth",
                "content": "The backend uses FastAPI, Postgres, Supabase, Clerk auth, and Vercel deployment.",
                "canonical": True,
                "domain": "architecture",
            },
        ],
    )
    assert ingest["ok"] is True

    ingest_company_brain_records(
        founder_id,
        "slack",
        [
            {
                "title": "Old launch thread",
                "text": "Decision: use Django, MySQL, custom JWT auth, and AWS for the architecture.",
                "channel": "eng",
                "domain": "architecture",
            },
        ],
    )

    maintained = maintain_company_brain(founder_id)
    assert maintained["maintenance"]["contradiction_count"] >= 1
    assert maintained["proposals"]
    proposal = maintained["proposals"][0]
    assert proposal["kind"] == "contradiction"

    resolved = resolve_company_brain_proposal(founder_id, proposal["id"], "resolved")
    assert resolved["ok"] is True
    assert resolved["proposal"]["status"] == "resolved"


def test_company_brain_maintenance_dismisses_obsolete_proposals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_obsolete_maintenance"

    ingest_company_brain_records(
        founder_id,
        "notion",
        [{
            "title": "Architecture source of truth",
            "content": "The backend uses FastAPI, Postgres, Supabase, Clerk auth, and Vercel deployment.",
            "canonical": True,
            "domain": "architecture",
        }],
    )
    ingest_company_brain_records(
        founder_id,
        "slack",
        [{
            "title": "Old launch thread",
            "text": "Decision: use Django, MySQL, custom JWT auth, and AWS for the architecture.",
            "channel": "eng",
            "domain": "architecture",
        }],
    )
    first = maintain_company_brain(founder_id)
    proposal = next(p for p in first["proposals"] if p["kind"] == "contradiction")

    brain = get_company_brain(founder_id)
    old_record = next(r for r in brain["records"] if r["id"] in proposal["record_ids"] and r["source"] == "slack")
    revised = revise_company_brain_record(
        founder_id,
        old_record["id"],
        content="Decision: use FastAPI, Postgres, Supabase, Clerk auth, and Vercel for the architecture.",
    )
    assert revised["ok"] is True

    maintained = maintain_company_brain(founder_id)
    assert maintained["maintenance"]["contradiction_count"] == 0
    assert [p for p in maintained["proposals"] if p["id"] == proposal["id"]] == []

    brain = get_company_brain(founder_id)
    dismissed = next(p for p in brain["proposals"] if p["id"] == proposal["id"])
    assert dismissed["status"] == "dismissed"
    assert dismissed["dismissed_reason"] == "maintenance_scan_obsolete"


def test_company_brain_maintenance_ignores_generated_run_artifact_conflicts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_generated_artifacts"

    add_company_brain_record(
        founder_id,
        "astra",
        "Agent Department Manifest - Venture",
        "Venture product choices: FastAPI, Postgres, subscription pricing, and Vercel deployment.",
        kind="department_manifest",
        canonical=True,
        metadata={"domain": "product"},
    )
    add_company_brain_record(
        founder_id,
        "astra",
        "Run Digest - Venture - abc123",
        "This generated run digest mentions Django, MySQL, free pricing, and AWS deployment.",
        kind="run_digest",
        canonical=False,
        metadata={"domain": "product"},
    )
    add_company_brain_record(
        founder_id,
        "astra_vault",
        "abc123 / market_research",
        "Agent notes mention Django, MySQL, free pricing, and AWS while researching Venture.",
        kind="agent_memory",
        canonical=False,
        metadata={"domain": "product", "session_id": "abc123"},
    )

    maintained = maintain_company_brain(founder_id)

    assert maintained["maintenance"]["contradiction_count"] == 0
    assert [p for p in maintained["proposals"] if p["kind"] == "contradiction"] == []


def test_company_brain_github_import_normalizes_provider_payload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_github"

    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"token": "ghp_test"} if fid == founder_id and service == "github" else None,
    )

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/user/repos"):
            return Resp([{
                "full_name": "acme/app",
                "name": "app",
                "description": "Company operating system",
                "language": "TypeScript",
                "default_branch": "main",
                "html_url": "https://github.com/acme/app",
                "updated_at": "2026-05-01T00:00:00Z",
            }])
        if url.endswith("/readme"):
            import base64
            return Resp({
                "content": base64.b64encode(b"# Acme App\nFastAPI and Supabase architecture").decode(),
                "html_url": "https://github.com/acme/app/blob/main/README.md",
            })
        if url.endswith("/issues"):
            return Resp([{
                "number": 7,
                "title": "Add Slack importer",
                "body": "Import Slack decisions into the company brain",
                "state": "open",
                "html_url": "https://github.com/acme/app/issues/7",
                "updated_at": "2026-05-02T00:00:00Z",
            }])
        if url.endswith("/pulls"):
            return Resp([{
                "number": 8,
                "title": "Company brain graph",
                "body": "Adds graph relationships",
                "state": "closed",
                "html_url": "https://github.com/acme/app/pull/8",
                "updated_at": "2026-05-03T00:00:00Z",
            }])
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    imported = import_company_brain_sources(founder_id, ["github"], limit=1)
    assert imported["ok"] is True
    assert imported["imported_sources"] == ["github"]

    brain = get_company_brain(founder_id)
    titles = {record["title"] for record in brain["records"]}
    assert "Repository: acme/app" in titles
    assert "README: acme/app" in titles
    assert any("Slack importer" in title for title in titles)


def test_company_brain_github_import_uses_delta_cursor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_github_delta"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"token": "ghp_test"} if fid == founder_id and service == "github" else None,
    )

    phase = {"value": 1}

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/user/repos"):
            return Resp([{
                "full_name": "acme/app",
                "name": "app",
                "description": "Company operating system",
                "language": "TypeScript",
                "default_branch": "main",
                "html_url": "https://github.com/acme/app",
                "updated_at": "2026-05-03T00:00:00Z" if phase["value"] == 1 else "2026-05-04T00:00:00Z",
            }])
        if url.endswith("/readme"):
            import base64
            return Resp({"content": base64.b64encode(b"# Acme App").decode(), "html_url": "https://github.com/acme/app/blob/main/README.md"})
        if url.endswith("/issues"):
            if phase["value"] == 1:
                return Resp([{
                    "number": 1,
                    "title": "Old issue",
                    "body": "Initial import",
                    "state": "open",
                    "html_url": "https://github.com/acme/app/issues/1",
                    "updated_at": "2026-05-02T00:00:00Z",
                }])
            return Resp([
                {
                    "number": 2,
                    "title": "New issue",
                    "body": "Delta import",
                    "state": "open",
                    "html_url": "https://github.com/acme/app/issues/2",
                    "updated_at": "2026-05-05T00:00:00Z",
                },
                {
                    "number": 1,
                    "title": "Old issue",
                    "body": "Should be skipped",
                    "state": "open",
                    "html_url": "https://github.com/acme/app/issues/1",
                    "updated_at": "2026-05-02T00:00:00Z",
                },
            ])
        if url.endswith("/pulls"):
            return Resp([])
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    first = import_company_brain_sources(founder_id, ["github"], limit=1)
    assert first["ok"] is True
    phase["value"] = 2
    second = import_company_brain_sources(founder_id, ["github"], limit=1)
    assert second["ok"] is True

    from backend.connector_sync_ledger import get_connector_sync_status
    cursor = get_connector_sync_status(founder_id)["sources"]["github"]["cursor"]
    assert cursor == "2026-05-05T00:00:00Z"

    brain = get_company_brain(founder_id)
    titles = {record["title"] for record in brain["records"]}
    assert "Issue #2: New issue" in titles
    assert not any("Should be skipped" in record["content"] for record in brain["records"])


def test_company_brain_slack_import_includes_thread_replies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_slack"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"bot_token": "xoxb-test"} if fid == founder_id and service == "slack" else None,
    )

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/conversations.list"):
            return Resp({"ok": True, "channels": [{"id": "C1", "name": "eng"}]})
        if url.endswith("/conversations.history"):
            return Resp({"ok": True, "messages": [{"ts": "1.0", "thread_ts": "1.0", "user": "U1", "text": "Decision: ship the company brain"}]})
        if url.endswith("/conversations.replies"):
            return Resp({"ok": True, "messages": [
                {"ts": "1.0", "user": "U1", "text": "Decision: ship the company brain"},
                {"ts": "1.1", "user": "U2", "text": "Also import Slack threads"},
            ]})
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)
    imported = import_company_brain_sources(founder_id, ["slack"], limit=1)
    assert imported["ok"] is True
    brain = get_company_brain(founder_id)
    assert any("Also import Slack threads" in record["content"] for record in brain["records"])


def test_company_brain_slack_import_uses_delta_cursor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_slack_delta"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"bot_token": "xoxb-test"} if fid == founder_id and service == "slack" else None,
    )
    phase = {"value": 1}
    history_params = []

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/conversations.list"):
            return Resp({"ok": True, "channels": [{"id": "C1", "name": "eng"}]})
        if url.endswith("/conversations.history"):
            history_params.append(params or {})
            if phase["value"] == 1:
                return Resp({"ok": True, "messages": [{"ts": "1.0", "thread_ts": "1.0", "user": "U1", "text": "Old launch decision"}]})
            return Resp({"ok": True, "messages": [
                {"ts": "2.0", "thread_ts": "2.0", "user": "U2", "text": "New launch decision"},
                {"ts": "1.0", "thread_ts": "1.0", "user": "U1", "text": "Should be skipped"},
            ]})
        if url.endswith("/conversations.replies"):
            if phase["value"] == 1:
                return Resp({"ok": True, "messages": [
                    {"ts": "1.0", "user": "U1", "text": "Old launch decision"},
                    {"ts": "1.1", "user": "U2", "text": "Old reply"},
                ]})
            return Resp({"ok": True, "messages": [
                {"ts": "2.0", "user": "U2", "text": "New launch decision"},
                {"ts": "2.1", "user": "U3", "text": "New reply"},
            ]})
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    first = import_company_brain_sources(founder_id, ["slack"], limit=1)
    assert first["ok"] is True
    phase["value"] = 2
    second = import_company_brain_sources(founder_id, ["slack"], limit=1)
    assert second["ok"] is True

    from backend.connector_sync_ledger import get_connector_sync_status
    cursor = get_connector_sync_status(founder_id)["sources"]["slack"]["cursor"]
    assert cursor == "2.1"
    assert history_params[1]["oldest"] == "1.1"
    assert history_params[1]["inclusive"] is False

    brain = get_company_brain(founder_id)
    assert any("New reply" in record["content"] for record in brain["records"])
    assert not any("Should be skipped" in record["content"] for record in brain["records"])


def test_company_brain_discord_import_normalizes_messages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_discord"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"bot_token": "discord-test"} if fid == founder_id and service == "discord" else None,
    )

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        assert headers["Authorization"] == "Bot discord-test"
        if url.endswith("/users/@me/guilds"):
            return Resp([{"id": "G1", "name": "Astra HQ"}])
        if url.endswith("/guilds/G1/channels"):
            return Resp([
                {"id": "C1", "name": "engineering", "type": 0},
                {"id": "V1", "name": "voice", "type": 2},
            ])
        if url.endswith("/channels/C1/messages"):
            return Resp([{
                "id": "M1",
                "content": "Engineering shipped connector auth and needs review.",
                "author": {"username": "isabel"},
                "timestamp": "2026-05-01T00:00:00Z",
                "attachments": [{"url": "https://example.com/spec.pdf"}],
                "embeds": [],
            }])
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    imported = import_company_brain_sources(founder_id, ["discord"], limit=1)
    assert imported["ok"] is True
    assert imported["imported_sources"] == ["discord"]

    brain = get_company_brain(founder_id)
    assert brain["sources"]["discord"]["record_count"] == 1
    record = next(record for record in brain["records"] if record["source"] == "discord")
    assert record["title"].startswith("Discord #engineering")
    assert "connector auth" in record["content"]
    assert record["metadata"]["server"] == "Astra HQ"


def test_company_brain_discord_import_uses_delta_cursor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_discord_delta"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"bot_token": "discord-test"} if fid == founder_id and service == "discord" else None,
    )
    phase = {"value": 1}
    message_params = []

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/users/@me/guilds"):
            return Resp([{"id": "G1", "name": "Astra HQ"}])
        if url.endswith("/guilds/G1/channels"):
            return Resp([{"id": "C1", "name": "engineering", "type": 0}])
        if url.endswith("/channels/C1/messages"):
            message_params.append(params or {})
            if phase["value"] == 1:
                return Resp([{
                    "id": "100",
                    "content": "Old Discord decision",
                    "author": {"username": "isabel"},
                    "timestamp": "2026-05-01T00:00:00Z",
                }])
            return Resp([
                {
                    "id": "200",
                    "content": "New Discord decision",
                    "author": {"username": "isabel"},
                    "timestamp": "2026-05-02T00:00:00Z",
                },
                {
                    "id": "100",
                    "content": "Should be skipped",
                    "author": {"username": "isabel"},
                    "timestamp": "2026-05-01T00:00:00Z",
                },
            ])
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    first = import_company_brain_sources(founder_id, ["discord"], limit=1)
    assert first["ok"] is True
    phase["value"] = 2
    second = import_company_brain_sources(founder_id, ["discord"], limit=1)
    assert second["ok"] is True

    from backend.connector_sync_ledger import get_connector_sync_status
    cursor = get_connector_sync_status(founder_id)["sources"]["discord"]["cursor"]
    assert cursor == "200"
    assert message_params[1]["after"] == "100"

    brain = get_company_brain(founder_id)
    assert any("New Discord decision" in record["content"] for record in brain["records"])
    assert not any("Should be skipped" in record["content"] for record in brain["records"])


def test_company_brain_google_drive_import_exports_doc_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_drive"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"access_token": "ya29.test"} if fid == founder_id and service == "google_drive" else None,
    )

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            text = "Launch plan\nUse the company brain as source of truth."

            def __init__(self, payload=None):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/drive/v3/files"):
            return Resp({"files": [{
                "id": "doc1",
                "name": "Launch plan",
                "mimeType": "application/vnd.google-apps.document",
                "webViewLink": "https://docs.google.com/document/d/doc1",
                "modifiedTime": "2026-05-01T00:00:00Z",
            }]})
        if url.endswith("/export"):
            return Resp()
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)
    imported = import_company_brain_sources(founder_id, ["google_drive"], limit=1)
    assert imported["ok"] is True
    brain = get_company_brain(founder_id)
    assert any("source of truth" in record["content"] for record in brain["records"])


def test_company_brain_google_drive_import_uses_delta_cursor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_drive_delta"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"access_token": "ya29.test"} if fid == founder_id and service == "google_drive" else None,
    )
    phase = {"value": 1}
    listing_params = []

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            text = "Updated plan"

            def __init__(self, payload=None):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if url.endswith("/drive/v3/files"):
            listing_params.append(params or {})
            if phase["value"] == 1:
                return Resp({"files": [{
                    "id": "doc1",
                    "name": "Old plan",
                    "mimeType": "application/vnd.google-apps.document",
                    "webViewLink": "https://docs.google.com/document/d/doc1",
                    "modifiedTime": "2026-05-01T00:00:00Z",
                }]})
            return Resp({"files": [
                {
                    "id": "doc2",
                    "name": "New plan",
                    "mimeType": "application/vnd.google-apps.document",
                    "webViewLink": "https://docs.google.com/document/d/doc2",
                    "modifiedTime": "2026-05-02T00:00:00Z",
                },
                {
                    "id": "doc1",
                    "name": "Should be skipped",
                    "mimeType": "application/vnd.google-apps.document",
                    "webViewLink": "https://docs.google.com/document/d/doc1",
                    "modifiedTime": "2026-05-01T00:00:00Z",
                },
            ]})
        if url.endswith("/export"):
            return Resp()
        raise AssertionError(url)

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    first = import_company_brain_sources(founder_id, ["google_drive"], limit=2)
    assert first["ok"] is True
    phase["value"] = 2
    second = import_company_brain_sources(founder_id, ["google_drive"], limit=2)
    assert second["ok"] is True

    from backend.connector_sync_ledger import get_connector_sync_status
    cursor = get_connector_sync_status(founder_id)["sources"]["google_drive"]["cursor"]
    assert cursor == "2026-05-02T00:00:00Z"
    assert listing_params[1]["q"] == "modifiedTime > '2026-05-01T00:00:00Z'"

    brain = get_company_brain(founder_id)
    assert any(record["title"] == "New plan" for record in brain["records"])
    assert not any(record["title"] == "Should be skipped" for record in brain["records"])


def test_company_brain_notion_import_uses_delta_cursor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_notion_delta"
    monkeypatch.setattr(
        "backend.tools.company_brain_connectors.load_credentials",
        lambda fid, service: {"token": "secret_test"} if fid == founder_id and service == "notion" else None,
    )
    phase = {"value": 1}
    search_payloads = []

    def fake_post(url, headers=None, json=None, timeout=20):
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                search_payloads.append(json or {})
                if phase["value"] == 1:
                    return {"results": [{
                        "id": "page1",
                        "object": "page",
                        "url": "https://notion.so/page1",
                        "last_edited_time": "2026-05-01T00:00:00Z",
                        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Old page"}]}},
                    }]}
                return {"results": [
                    {
                        "id": "page2",
                        "object": "page",
                        "url": "https://notion.so/page2",
                        "last_edited_time": "2026-05-02T00:00:00Z",
                        "properties": {"Name": {"type": "title", "title": [{"plain_text": "New page"}]}},
                    },
                    {
                        "id": "page1",
                        "object": "page",
                        "url": "https://notion.so/page1",
                        "last_edited_time": "2026-05-01T00:00:00Z",
                        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Should be skipped"}]}},
                    },
                ]}

        assert url.endswith("/v1/search")
        return Resp()

    def fake_get(url, headers, params=None, timeout=20):
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Planning content"}]}}]}

        return Resp()

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.post", fake_post)
    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)

    first = import_company_brain_sources(founder_id, ["notion"], limit=2)
    assert first["ok"] is True
    phase["value"] = 2
    second = import_company_brain_sources(founder_id, ["notion"], limit=2)
    assert second["ok"] is True

    from backend.connector_sync_ledger import get_connector_sync_status
    cursor = get_connector_sync_status(founder_id)["sources"]["notion"]["cursor"]
    assert cursor == "2026-05-02T00:00:00Z"
    assert search_payloads[0]["sort"] == {"direction": "descending", "timestamp": "last_edited_time"}

    brain = get_company_brain(founder_id)
    assert any(record["title"] == "New page" for record in brain["records"])
    assert not any(record["title"] == "Should be skipped" for record in brain["records"])


def test_company_brain_linear_zendesk_confluence_importers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_more_sources"

    def fake_creds(fid, service):
        if fid != founder_id:
            return None
        return {
            "linear": {"api_key": "lin_test"},
            "zendesk": {"subdomain": "acme", "email": "ops@example.com", "token": "zd_test"},
            "confluence": {"base_url": "https://acme.atlassian.net", "email": "ops@example.com", "token": "conf_test"},
        }.get(service)

    monkeypatch.setattr("backend.tools.company_brain_connectors.load_credentials", fake_creds)

    def fake_get(url, headers=None, params=None, timeout=20, auth=None):
        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        if "zendesk.com" in url:
            return Resp({"tickets": [{"id": 42, "subject": "Importer bug", "description": "Customer cannot sync Zendesk", "status": "open", "priority": "high", "updated_at": "2026-05-02"}]})
        if "confluence" in url or "atlassian.net" in url:
            return Resp({"results": [{"id": "p1", "title": "Runbook", "body": {"storage": {"value": "<p>Restart the sync worker</p>"}}, "version": {"when": "2026-05-03"}, "_links": {"webui": "/wiki/spaces/ENG/pages/p1"}}]})
        raise AssertionError(url)

    def fake_post(url, headers=None, json=None, timeout=20):
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": {"issues": {"nodes": [{
                    "id": "lin1",
                    "identifier": "ENG-1",
                    "title": "Build importer",
                    "description": "Add Linear to company brain",
                    "url": "https://linear.app/acme/issue/ENG-1",
                    "priority": 2,
                    "updatedAt": "2026-05-04",
                    "state": {"name": "In Progress", "type": "started"},
                    "assignee": {"name": "Ishaan", "email": "i@example.com"},
                    "team": {"name": "Engineering", "key": "ENG"},
                }]}}}

        assert "linear.app" in url
        return Resp()

    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.get", fake_get)
    monkeypatch.setattr("backend.tools.company_brain_connectors.requests.post", fake_post)

    imported = import_company_brain_sources(founder_id, ["linear", "zendesk", "confluence"], limit=1)
    assert imported["ok"] is True
    assert set(imported["imported_sources"]) == {"linear", "zendesk", "confluence"}
    brain = get_company_brain(founder_id)
    content = "\n".join(record["content"] for record in brain["records"])
    assert "Add Linear to company brain" in content
    assert "Customer cannot sync Zendesk" in content
    assert "Restart the sync worker" in content


def test_company_brain_sync_runner_and_agent_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_sync"

    add_company_brain_record(
        founder_id,
        "manual",
        "Canonical architecture",
        "Use FastAPI, Supabase, Clerk, and Vercel for the production architecture.",
        canonical=True,
        stale_risk="low",
    )
    configured = configure_company_brain_sync(
        founder_id,
        enabled=True,
        sources=["github"],
        interval_minutes=15,
    )
    assert configured["sync"]["enabled"] is True
    assert configured["sync"]["interval_minutes"] == 15

    def fake_import(founder_id_arg, sources, limit=20):
        assert founder_id_arg == founder_id
        assert sources == ["github"]
        return {"ok": True, "imported_sources": ["github"], "failed_sources": [], "results": []}

    monkeypatch.setattr("backend.tools.company_brain_connectors.import_company_brain_sources", fake_import)

    run = run_company_brain_sync(founder_id, force=True)
    assert run["ok"] is True
    assert run["sync"]["last_status"] == "ok"
    assert run["sync"]["history"][0]["imported_sources"] == ["github"]

    ctx = company_brain_agent_context(founder_id, "production architecture", 5)
    assert ctx["ok"] is True
    assert "Canonical architecture" in ctx["context"]
    assert ctx["canonical_sources"]


def test_company_brain_due_sync_discovers_enabled_founders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_due"
    configure_company_brain_sync(founder_id, enabled=True, sources=["github"], interval_minutes=15)

    called = []

    def fake_import(founder_id_arg, sources, limit=20):
        called.append((founder_id_arg, sources))
        return {"ok": True, "imported_sources": ["github"], "failed_sources": [], "results": []}

    monkeypatch.setattr("backend.tools.company_brain_connectors.import_company_brain_sources", fake_import)
    brain = get_company_brain(founder_id)
    brain["sync"]["next_run_at"] = "2000-01-01T00:00:00Z"
    path = tmp_path / ".astra" / "company_brain" / f"{founder_id}.json"
    import json
    path.write_text(json.dumps(brain))

    result = run_due_company_brain_syncs()
    assert result["ok"] is True
    assert result["ran"] == 1
    assert called == [(founder_id, ["github"])]


def test_company_brain_ask_returns_citations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_ask"
    add_company_brain_record(
        founder_id=founder_id,
        source="manual",
        title="Onboarding strategy",
        content="Use founder-led onboarding first, then self-serve checklists for expansion.",
        canonical=True,
        stale_risk="low",
    )
    add_company_brain_record(
        founder_id=founder_id,
        source="notion",
        title="Onboarding notes",
        content="Track activation milestones and first-week retention.",
        canonical=False,
        stale_risk="medium",
    )
    asked = ask_company_brain(founder_id, "What is our onboarding strategy?", limit=5)
    assert asked["ok"] is True
    assert asked["citations"]
    assert "onboarding" in asked["answer"].lower()
    assert "[1]" in asked["answer"]
    assert asked["citations"][0]["title"] == "Onboarding strategy"


def test_company_brain_ask_answers_subteam_activity_from_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_subteam_question"
    add_company_brain_record(
        founder_id=founder_id,
        source="github",
        title="Engineering shipped connector validation",
        content="Technical agent completed live validation for Supabase, Clerk, Discord, and Figma connectors.",
        kind="run_digest",
        canonical=True,
        stale_risk="low",
        metadata={
            "agent": "technical",
            "session_id": "run_1",
            "status": "done",
            "task_title": "Connector validation",
            "next_action": "Wire connector validation into the production launch gate.",
        },
    )
    add_company_brain_record(
        founder_id=founder_id,
        source="notion",
        title="Landing page implementation notes",
        content="Web agent finished the single-page dashboard launch surface and route cleanup.",
        kind="implementation_note",
        canonical=False,
        stale_risk="low",
        metadata={
            "agent": "web",
            "session_id": "run_1",
            "status": "in_progress",
            "task_title": "Dashboard route cleanup",
            "next_action": "Verify the one-page app in production.",
        },
    )

    asked = ask_company_brain(founder_id, "What did the engineering subteam do last week?", limit=5)

    assert asked["ok"] is True
    assert asked["report"]["team"] == "engineering"
    assert asked["report"]["record_count"] == 2
    assert asked["report"]["status_counts"]["done"] == 1
    assert asked["report"]["status_counts"]["in_progress"] == 1
    assert asked["report"]["completed_work"][0]["title"] == "Connector validation"
    assert asked["report"]["active_work"][0]["title"] == "Dashboard route cleanup"
    assert asked["report"]["expected_next_work"]
    assert asked["citations"]
    assert "1 completed, 1 active" in asked["answer"]
    assert "Wire connector validation into the production launch gate" in asked["answer"]
    assert "connector validation" in asked["context"]

    brain = get_company_brain(founder_id)
    assert any(record["kind"] == "subteam_report" for record in brain["records"])


def test_company_brain_ask_reports_connector_coverage_against_stack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    founder_id = "founder_connector_question"

    def fake_readiness(founder_id_arg, stack_id):
        assert founder_id_arg == founder_id
        assert stack_id == "idea_to_revenue"
        return {
            "connectors": [
                {
                    "key": "github",
                    "label": "GitHub",
                    "category": "code",
                    "purpose": "Repository handoff",
                    "required": True,
                    "connected": True,
                    "status": "connected",
                    "credential_service": "github",
                },
                {
                    "key": "vercel",
                    "label": "Vercel",
                    "category": "deployment",
                    "purpose": "Preview deployment",
                    "required": True,
                    "connected": False,
                    "status": "missing_required",
                    "credential_service": None,
                },
            ]
        }

    monkeypatch.setattr("backend.connector_coverage.stack_readiness", fake_readiness)
    add_company_brain_record(
        founder_id=founder_id,
        source="github",
        title="Repository synced",
        content="The product repository and README are available to the company brain.",
        kind="repository",
        canonical=True,
        stale_risk="low",
    )

    asked = ask_company_brain(founder_id, "What connector coverage do we have for the idea to revenue stack?", limit=5)

    assert asked["ok"] is True
    assert asked["connector_coverage"]["required_total"] == 2
    assert asked["connector_coverage"]["ready_required"] == 1
    assert "1/2 required connectors" in asked["answer"]
    assert any("GitHub: ready" in line for line in asked["evidence"])
    assert any("Vercel: missing_required" in line for line in asked["evidence"])
