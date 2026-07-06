import json
from pathlib import Path

from backend.custom_agents import store as custom_agents_store
from backend.deployments import store as deployments_store
from backend.library import store as library_store
from backend.model_settings import store as model_settings_store
from backend.outreach.local_store import get_local_store
from backend.skills import store as skills_store


def test_model_settings_corrupt_file_is_quarantined_before_rewrite(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    path = tmp_path / "model_settings" / "founder_1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad", encoding="utf-8")

    assert model_settings_store.get_all_overrides("founder_1") == {}
    quarantined = list(path.parent.glob("founder_1.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{bad"

    model_settings_store.set_model_override("founder_1", "research", "highoutput")

    assert model_settings_store.get_model_override("founder_1", "research") == "highoutput"
    assert json.loads(path.read_text(encoding="utf-8")) == {"research": "highoutput"}


def test_deployments_corrupt_record_is_quarantined_and_index_fallback_survives(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    record = deployments_store.record_deployment("session_1", "founder_1", "https://staging.example")
    record_path = tmp_path / "deployments" / "session_1.json"
    record_path.write_text("{bad", encoding="utf-8")

    loaded = deployments_store.get_deployment("session_1")

    assert loaded == record
    quarantined = list(record_path.parent.glob("session_1.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{bad"


def test_skills_corrupt_index_is_quarantined_before_rewrite(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    path = tmp_path / "skills" / "founder_1" / "index.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad", encoding="utf-8")

    assert skills_store.list_skills("founder_1") == []
    quarantined = list(path.parent.glob("index.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{bad"

    skill = skills_store.create_skill("founder_1", "Research")

    assert skills_store.get_skill("founder_1", skill["id"]) == skill
    assert json.loads(path.read_text(encoding="utf-8")) == {skill["id"]: skill}


def test_library_corrupt_record_is_quarantined_and_index_survives(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))

    record = library_store.create_file("founder_1", "ops", "notes.md", "hello")
    record_path = tmp_path / "library" / "founder_1" / f"{record['id']}.json"
    record_path.write_text("{bad", encoding="utf-8")

    assert library_store.get_file("founder_1", record["id"]) is None
    quarantined = list(record_path.parent.glob(f"{record['id']}.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{bad"
    assert library_store.list_files("founder_1") == [{k: v for k, v in record.items() if k != "content"}]


def test_custom_agents_corrupt_index_is_quarantined_before_rewrite(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    path = tmp_path / "custom_agents" / "founder_1" / "index.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad", encoding="utf-8")

    assert custom_agents_store.list_agents("founder_1") == []
    quarantined = list(path.parent.glob("index.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{bad"

    spec = custom_agents_store.create_agent("founder_1", name="SEO Watcher", role="Track rankings")

    assert custom_agents_store.get_agent("founder_1", spec["id"]) == spec
    assert json.loads(path.read_text(encoding="utf-8")) == {spec["id"]: spec}


def test_outreach_corrupt_store_is_quarantined_before_insert(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    path = tmp_path / "outreach" / "store.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad", encoding="utf-8")

    store = get_local_store()

    assert store.table("outreach_contacts").select("*").execute().data == []
    quarantined = list(path.parent.glob("store.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{bad"

    inserted = store.table("outreach_contacts").insert({"founder_id": "founder_1", "email": "a@example.com"}).execute()

    assert inserted.data[0]["email"] == "a@example.com"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["outreach_contacts"][0]["email"] == "a@example.com"
