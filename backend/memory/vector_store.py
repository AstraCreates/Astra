import asyncio
import uuid
from typing import Optional

from vertexai.language_models import TextEmbeddingModel

from backend.config import settings
from backend.db.client import store_memory_document


class VectorStore:
    def __init__(self):
        self._model: Optional[TextEmbeddingModel] = None

    def _get_model(self) -> TextEmbeddingModel:
        if self._model is None:
            import vertexai
            vertexai.init(project=settings.vertex_project, location=settings.vertex_location)
            self._model = TextEmbeddingModel.from_pretrained("text-embedding-004")
        return self._model

    async def embed(self, text: str) -> list[float]:
        def _embed():
            model = self._get_model()
            embeddings = model.get_embeddings([text])
            return embeddings[0].values

        return await asyncio.to_thread(_embed)

    async def write(
        self,
        doc_id: str,
        founder_id: str,
        namespace: str,
        agent: str,
        doc_type: str,
        content: str,
        summary: str,
        task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        embedding = await self.embed(summary)
        doc = {
            "id": doc_id or str(uuid.uuid4()),
            "founder_id": founder_id,
            "namespace": namespace,
            "agent": agent,
            "task_id": task_id,
            "doc_type": doc_type,
            "content": content,
            "summary": summary,
            "metadata": {**(metadata or {}), "embedding": embedding},
        }
        await store_memory_document(doc)

    async def retrieve(
        self,
        founder_id: str,
        namespaces: list[str],
        query: str,
        k: int = 5,
    ) -> list[dict]:
        """
        Retrieve top-k relevant memory documents.
        In Stage 1, returns empty list if no Vertex AI configured.
        Full semantic search added in Stage 2.
        """
        if not settings.vertex_project:
            return []

        query_embedding = await self.embed(query)

        def _query():
            from backend.db.client import get_supabase
            rows = (
                get_supabase()
                .table("memory_documents")
                .select("*")
                .eq("founder_id", founder_id)
                .in_("namespace", namespaces)
                .limit(k * 3)
                .execute()
                .data
            )
            # cosine similarity against stored embeddings
            def cosine(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                na = sum(x ** 2 for x in a) ** 0.5
                nb = sum(x ** 2 for x in b) ** 0.5
                return dot / (na * nb + 1e-9)

            scored = [
                (row, cosine(query_embedding, row["metadata"].get("embedding", [])))
                for row in rows
                if row["metadata"].get("embedding")
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [row for row, _ in scored[:k]]

        return await asyncio.to_thread(_query)


vector_store = VectorStore()
