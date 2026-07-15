"""Runtime Graphiti adapter for Wave 6 Company Brain projection/retrieval.

This module keeps Graphiti optional at import time but real when installed.
It uses one shared Graphiti graph backend and scopes company data with
`group_id=company_id`, matching the Wave 6 plan's "one namespace per company"
without forcing every company into a separate database.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config import settings


def graphiti_available() -> bool:
    try:
        import graphiti_core  # noqa: F401

        return True
    except Exception:
        return False


_LOCAL_EMBEDDER_MODEL_NAME = "BAAI/bge-large-en-v1.5"  # 1024-dim -- matches
# graphiti_core.embedder.client.EMBEDDING_DIM exactly, no padding/projection needed.
_local_embedder_model_lock = threading.Lock()
_local_embedder_model: Any | None = None


def _get_local_embedder_model() -> Any:
    """Lazily load the local sentence-transformers model, once per process,
    shared across every GraphitiBrainClient instance (loading it is the slow/
    heavy part -- keep it out of the hot path)."""
    global _local_embedder_model
    with _local_embedder_model_lock:
        if _local_embedder_model is None:
            from sentence_transformers import SentenceTransformer

            _local_embedder_model = SentenceTransformer(_LOCAL_EMBEDDER_MODEL_NAME)
        return _local_embedder_model


class LocalSentenceTransformerEmbedder:
    """Zero-external-cost EmbedderClient backed by a local sentence-transformers
    model, for when no dedicated OpenAI-compatible embeddings credential exists
    (OpenRouter has no /embeddings endpoint -- see _build_graphiti's fallback
    branch). Runs CPU inference in a worker thread since sentence-transformers
    itself is synchronous and graphiti_core's EmbedderClient interface is
    async."""

    def __init__(self) -> None:
        pass

    async def create(self, input_data: Any) -> list[float]:
        if isinstance(input_data, str):
            text = input_data
        elif isinstance(input_data, (list, tuple)) and input_data and isinstance(input_data[0], str):
            text = " ".join(str(item) for item in input_data)
        else:
            text = str(input_data)
        vectors = await self.create_batch([text])
        return vectors[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            model = _get_local_embedder_model()
            embeddings = model.encode(list(input_data_list), normalize_embeddings=True)
            return [list(float(x) for x in vec) for vec in embeddings]

        return await asyncio.to_thread(_encode)


@dataclass
class GraphitiSearchResult:
    record_ids: list[str]


class GraphitiBrainClient:
    def __init__(self) -> None:
        if not graphiti_available():
            raise RuntimeError("graphiti_core is not installed")
        self._lock = threading.Lock()
        self._graphiti: Any | None = None
        self._initialized = False
        # A dedicated ASTRA_BRAIN_GRAPH_API_KEY is preferred (real OpenAI-compatible
        # embeddings work), but falls back to the existing OpenRouter credential --
        # see _build_graphiti's driver selection for what that fallback can and
        # can't do (no embeddings; OpenRouter has no /embeddings endpoint).
        self._has_model_credentials = bool(
            str(settings.astra_brain_graph_api_key or "").strip()
            or str(settings.openrouter_api_key or "").strip()
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    def search(self, query: str, top_k: int = 10, company_id: Optional[str] = None) -> dict[str, Any]:
        self._ensure_model_credentials("search")
        normalized_company = self._normalize_group_id(company_id or "default")
        group_ids = [normalized_company] if company_id else None
        graphiti = self._graphiti_instance()
        edges = self._run_async(
            graphiti.search(
                query=query,
                group_ids=group_ids,
                num_results=max(1, top_k),
            )
        )
        candidate_episode_ids: list[str] = []
        for edge in edges or []:
            for episode_id in list(getattr(edge, "episodes", []) or []):
                normalized = str(episode_id or "").strip()
                if normalized and normalized not in candidate_episode_ids:
                    candidate_episode_ids.append(normalized)
        record_ids: list[str] = []
        episode_name_by_uuid = {
            str(getattr(episode, "uuid", "") or "").strip(): str(getattr(episode, "name", "") or "").strip()
            for episode in self._list_episodes(normalized_company)
        }
        for episode_uuid in candidate_episode_ids:
            record_id = episode_name_by_uuid.get(episode_uuid)
            if record_id and record_id not in record_ids:
                record_ids.append(record_id)
        if not record_ids:
            record_ids = self._fallback_rank_episode_names(normalized_company, query, top_k=top_k)
        return GraphitiSearchResult(record_ids=record_ids[:top_k]).__dict__

    def upsert_episode(self, company_id: str, episode_id: str, text: str, metadata: dict) -> None:
        self._ensure_model_credentials("upsert")
        graphiti = self._graphiti_instance()
        normalized_group = self._normalize_group_id(company_id)
        self._delete_by_name(graphiti, normalized_group, episode_id)
        from graphiti_core.nodes import EpisodeType

        reference_time = _coerce_datetime(metadata.get("retrieved_at")) or datetime.now(timezone.utc)
        self._run_async(
            graphiti.add_episode(
                name=str(episode_id),
                episode_body=text,
                source_description=str(metadata.get("source") or "astra_brain_record"),
                reference_time=reference_time,
                source=EpisodeType.json,
                group_id=normalized_group,
                update_communities=False,
            )
        )

    def delete_episode(self, company_id: str, episode_id: str) -> None:
        graphiti = self._graphiti_instance()
        self._delete_by_name(graphiti, self._normalize_group_id(company_id), episode_id)

    def clear_namespace(self, company_id: str) -> None:
        group_id = self._normalize_group_id(company_id)
        graphiti = self._graphiti_instance()
        episodes = self._list_episodes(group_id)
        for episode in episodes or []:
            episode_id = str(getattr(episode, "uuid", "") or "").strip()
            if episode_id:
                try:
                    self._run_async(graphiti.remove_episode(episode_id))
                except Exception:
                    pass

    def mark_superseded(self, company_id: str, old_episode_id: str, new_episode_id: str) -> None:
        # Graphiti's episode API is append/remove oriented; supersession remains
        # canonical in Supabase. Removing the old episode from the derived index
        # prevents stale retrieval while the new canonical episode is projected.
        self.delete_episode(company_id, old_episode_id)

    def _list_episodes(self, normalized_group_id: str) -> list[Any]:
        graphiti = self._graphiti_instance()
        return list(
            self._run_async(
                graphiti.retrieve_episodes(
                    reference_time=datetime.now(timezone.utc),
                    last_n=10_000,
                    group_ids=[normalized_group_id],
                )
            )
            or []
        )

    def _delete_by_name(self, graphiti: Any, normalized_group: str, episode_name: str) -> None:
        for episode in self._list_episodes(normalized_group):
            uuid = str(getattr(episode, "uuid", "") or "").strip()
            name = str(getattr(episode, "name", "") or "").strip()
            if uuid and (uuid == episode_name or name == episode_name):
                try:
                    self._run_async(graphiti.remove_episode(uuid))
                except Exception:
                    pass

    def _fallback_rank_episode_names(self, normalized_group_id: str, query: str, *, top_k: int) -> list[str]:
        query_terms = {
            token
            for token in str(query or "").lower().split()
            if token
        }
        scored: list[tuple[int, str]] = []
        for episode in self._list_episodes(normalized_group_id):
            name = str(getattr(episode, "name", "") or "").strip()
            haystack = " ".join(
                part
                for part in [
                    name.lower(),
                    str(getattr(episode, "content", "") or "").lower(),
                    str(getattr(episode, "source_description", "") or "").lower(),
                ]
                if part
            )
            score = sum(1 for term in query_terms if term in haystack)
            if score > 0 and name:
                scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [name for _, name in scored[: max(1, top_k)]]

    def _graphiti_instance(self) -> Any:
        graphiti: Any
        needs_init = False
        with self._lock:
            if self._graphiti is None:
                self._graphiti = self._build_graphiti()
            graphiti = self._graphiti
            if not self._initialized:
                needs_init = True
        if needs_init:
            self._run_async(graphiti.build_indices_and_constraints())
            with self._lock:
                self._initialized = True
        return graphiti

    @staticmethod
    def _normalize_group_id(company_id: str) -> str:
        raw = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(company_id or "default"))
        return raw[:120] or "default"

    def _build_graphiti(self) -> Any:
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver

        graph_driver_mode = str(settings.astra_brain_graph_driver or "falkordblite").strip().lower()
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_client import OpenAIClient

        api_key = str(settings.astra_brain_graph_api_key or "").strip()
        base_url = str(settings.astra_brain_graph_base_url or "").strip() or None
        embedder = None

        if api_key:
            # Dedicated, real OpenAI-compatible credentials -- full embeddings
            # support (text-embedding-3-small is an OpenAI-native model, only
            # correct against a genuine OpenAI-compatible /embeddings endpoint).
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

            llm_config = LLMConfig(
                api_key=api_key,
                base_url=base_url,
                model=str(settings.astra_brain_graph_model or "openai/gpt-4.1-mini"),
                small_model=str(settings.astra_brain_graph_small_model or settings.astra_brain_graph_model or "openai/gpt-4.1-mini"),
            )
            embedder = OpenAIEmbedder(
                config=OpenAIEmbedderConfig(
                    api_key=api_key,
                    base_url=base_url,
                    embedding_model=str(settings.astra_brain_graph_embedding_model or "text-embedding-3-small"),
                )
            )
        else:
            # Fall back to the existing OpenRouter credential (via Headroom, same
            # routing this codebase already uses everywhere else) so entity/
            # relationship extraction and reranking still work with zero new
            # paid credentials. Graphiti's own Graphiti(embedder=...) always
            # constructs a *default* OpenAIEmbedder() internally if embedder is
            # None (verified: not truly optional, needs OPENAI_API_KEY) -- since
            # OpenRouter has no /embeddings endpoint, use a local
            # sentence-transformers model instead so embeddings still work with
            # zero external cost/credentials.
            openrouter_key = str(settings.openrouter_api_key or "").strip()
            # deepseek-v4-flash: cheap/fast, already a known-good gateway alias
            # (see backend/control_plane/gateway.py's _KNOWN_GATEWAY_ALIASES) --
            # entity extraction is a background task, not a latency-sensitive one.
            llm_config = LLMConfig(
                api_key=openrouter_key or "sk-astra-placeholder",
                base_url=str(settings.openrouter_base_url or "").strip() or None,
                model="deepseek/deepseek-v4-flash",
                small_model="deepseek/deepseek-v4-flash",
            )
            embedder = LocalSentenceTransformerEmbedder()

        llm_client = OpenAIClient(config=llm_config)
        cross_encoder = OpenAIRerankerClient(config=llm_config)

        if graph_driver_mode == "falkordb":
            driver = FalkorDriver(
                host=str(settings.astra_brain_graph_host or "localhost"),
                port=int(settings.astra_brain_graph_port or 6379),
                username=str(settings.astra_brain_graph_username or "") or None,
                password=str(settings.astra_brain_graph_password or "") or None,
                database=str(settings.astra_brain_graph_database or "astra_company_brain"),
            )
        else:
            from redislite.async_falkordb_client import AsyncFalkorDB

            db_path = Path(str(settings.astra_brain_graph_path or ".astra/graphiti/company_brain.db")).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            driver = FalkorDriver(
                falkor_db=AsyncFalkorDB(dbfilename=str(db_path)),
                database=str(settings.astra_brain_graph_database or "astra_company_brain"),
            )

        return Graphiti(graph_driver=driver, llm_client=llm_client, embedder=embedder, cross_encoder=cross_encoder)

    def _run_async(self, coro: Any) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            ready = threading.Event()
            loop_box: dict[str, asyncio.AbstractEventLoop] = {}

            def runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop_box["loop"] = loop
                ready.set()
                loop.run_forever()

            thread = threading.Thread(target=runner, name="graphiti-brain-loop", daemon=True)
            thread.start()
            ready.wait()
            self._loop = loop_box["loop"]
            self._loop_thread = thread
            return self._loop

    def _ensure_model_credentials(self, operation: str) -> None:
        if not self._has_model_credentials:
            raise RuntimeError(
                f"Graphiti {operation} requires ASTRA_BRAIN_GRAPH_API_KEY (or astra_brain_graph_api_key) to be configured"
            )


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
