import pytest

from backend.skills.proposals import (
    activate_proposal,
    create_proposal,
    list_proposals,
    resolve_proposal,
    rollback_skill,
)


def test_proposal_requires_review_before_activation(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    proposal = create_proposal(
        founder_id="f1", specialist="research", source_session="s1",
        evidence="Repeated query planning improved coverage.",
        proposed_change="Always build a query plan before broad research.",
    )
    assert activate_proposal("f1", proposal["id"], "admin") is None
    approved = resolve_proposal("f1", proposal["id"], "approved", "admin")
    assert approved["status"] == "approved"
    activated = activate_proposal("f1", proposal["id"], "admin")
    assert activated["proposal"]["status"] == "active"
    assert activated["skill"]["founder_id"] == "f1"
    assert list_proposals("f1", "active")[0]["id"] == proposal["id"]


def test_skill_activation_preserves_rollback_history(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    from backend.skills.store import create_skill
    skill = create_skill("f1", "Research", content="old", agent_keys=["research"])
    proposal = create_proposal(
        founder_id="f1", specialist="research", source_session="s1",
        evidence="New repeatable workflow.", proposed_change="new", skill_id=skill["id"],
    )
    resolve_proposal("f1", proposal["id"], "approved", "admin")
    activated = activate_proposal("f1", proposal["id"], "admin")
    assert activated["skill"]["content"] == "new"
    rolled_back = rollback_skill("f1", skill["id"])
    assert rolled_back["content"] == "old"


def test_proposal_rejects_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    with pytest.raises(ValueError):
        create_proposal(
            founder_id="f1", specialist="research", source_session="s1",
            evidence="Use api_key=abc", proposed_change="Store it",
        )
