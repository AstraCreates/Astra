import pytest
from unittest.mock import patch, MagicMock
from backend.memory.vector_store import VectorStore


@pytest.fixture
def store(mocker):
    mocker.patch("backend.memory.vector_store.TextEmbeddingModel")
    return VectorStore()


@pytest.mark.asyncio
async def test_embed_returns_list_of_floats(store, mocker):
    store._model = MagicMock()
    store._model.get_embeddings.return_value = [MagicMock(values=[0.1, 0.2, 0.3])]
    result = await store.embed("test text")
    assert isinstance(result, list)
    assert result == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_write_calls_store_memory_document(store, mocker):
    mock_store = mocker.patch("backend.memory.vector_store.store_memory_document")
    mock_store.return_value = None
    store._model = MagicMock()
    store._model.get_embeddings.return_value = [MagicMock(values=[0.1] * 768)]

    await store.write(
        doc_id="d1",
        founder_id="f1",
        namespace="legal",
        agent="legal",
        task_id="t1",
        doc_type="document",
        content="full agreement text",
        summary="founder agreement summary",
    )
    mock_store.assert_called_once()
