import pytest
from unittest.mock import MagicMock
from backend.db.client import (
    get_ready_tasks,
    persist_task_graph,
    update_task_status,
    store_memory_document,
)


@pytest.fixture
def mock_supabase(mocker):
    mock = MagicMock()
    mocker.patch("backend.db.client.get_supabase", return_value=mock)
    return mock


@pytest.mark.asyncio
async def test_get_ready_tasks_returns_tasks_with_deps_done(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "t1", "status": "done",    "depends_on": []},
        {"id": "t2", "status": "pending", "depends_on": ["t1"]},
        {"id": "t3", "status": "pending", "depends_on": ["t2"]},
    ]
    ready = await get_ready_tasks("g1")
    assert len(ready) == 1
    assert ready[0]["id"] == "t2"


@pytest.mark.asyncio
async def test_persist_task_graph_inserts_rows(mock_supabase):
    tasks = [
        {"task_id": "t1", "agent": "legal", "depends_on": [], "instruction": "draft NDA"},
    ]
    await persist_task_graph("g1", "f1", tasks)
    mock_supabase.table.return_value.insert.assert_called_once()


@pytest.mark.asyncio
async def test_update_task_status_calls_update(mock_supabase):
    await update_task_status("t1", "done", result={"doc": "content"})
    mock_supabase.table.return_value.update.assert_called_once()
