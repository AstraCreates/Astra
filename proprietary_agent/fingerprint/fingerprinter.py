"""
Execution Fingerprinting — System F.

Every completed Astra run is compressed into a fingerprint.
New runs are matched against historical fingerprints using
TF-IDF cosine similarity (goal text) + Jaccard (tool outcomes).
"""

import json
import logging
import math
import os
import sqlite3
import uuid
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get("ASTRA_FINGERPRINT_DB", os.path.expanduser("~/agent-workspace/fingerprints.db"))
_SIMILARITY_THRESHOLD = 0.65
_TOP_K = 3


class Fingerprinter:
    def __init__(self):
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        self._db = sqlite3.connect(_DB_PATH, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS fingerprints (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                founder_id TEXT,
                goal TEXT,
                goal_vector TEXT,      -- JSON: {term: tfidf}
                agents_used TEXT,      -- JSON list
                tool_outcomes TEXT,    -- JSON: {tool: success|fail}
                timing TEXT,           -- JSON: {agent: seconds}
                success_score REAL,
                timestamp TEXT
            )
        """)
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_founder ON fingerprints(founder_id)")
        self._db.commit()

    # ------------------------------------------------------------------ #
    # TF-IDF helpers (no sklearn dep)
    # ------------------------------------------------------------------ #

    def _tokenize(self, text: str) -> list[str]:
        return [w.lower() for w in text.replace(",", " ").replace(".", " ").split() if len(w) > 2]

    def _tfidf_vector(self, text: str, corpus_docs: list[str]) -> dict[str, float]:
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        total = max(len(tokens), 1)
        N = max(len(corpus_docs), 1)

        vec: dict[str, float] = {}
        for term, count in tf.items():
            # TF
            tf_score = count / total
            # IDF: log((N+1) / (df+1)) + 1
            df = sum(1 for doc in corpus_docs if term in self._tokenize(doc))
            idf = math.log((N + 1) / (df + 1)) + 1
            vec[term] = tf_score * idf
        return vec

    def _cosine(self, v1: dict[str, float], v2: dict[str, float]) -> float:
        shared = set(v1) & set(v2)
        dot = sum(v1[t] * v2[t] for t in shared)
        mag1 = math.sqrt(sum(x * x for x in v1.values()))
        mag2 = math.sqrt(sum(x * x for x in v2.values()))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    def _jaccard(self, set1: set, set2: set) -> float:
        if not set1 and not set2:
            return 1.0
        return len(set1 & set2) / len(set1 | set2)

    # ------------------------------------------------------------------ #
    # Store
    # ------------------------------------------------------------------ #

    def store(
        self,
        *,
        session_id: str,
        founder_id: str,
        goal: str,
        agents_used: list[str],
        tool_outcomes: dict[str, str],
        timing: dict[str, float],
        success_score: float,
    ) -> str:
        # Build vector from current corpus
        corpus = [row[0] for row in self._db.execute("SELECT goal FROM fingerprints").fetchall()]
        vec = self._tfidf_vector(goal, corpus)

        fp_id = str(uuid.uuid4())
        self._db.execute(
            "INSERT INTO fingerprints VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                fp_id,
                session_id,
                founder_id,
                goal,
                json.dumps(vec),
                json.dumps(agents_used),
                json.dumps(tool_outcomes),
                json.dumps(timing),
                success_score,
                datetime.utcnow().isoformat(),
            ),
        )
        self._db.commit()
        logger.info("Fingerprint stored: %s (session=%s)", fp_id, session_id)
        return fp_id

    # ------------------------------------------------------------------ #
    # Match
    # ------------------------------------------------------------------ #

    def match(self, goal: str, founder_id: str | None = None) -> list[dict]:
        """Return top-K similar historical runs above threshold."""
        rows = self._db.execute("SELECT goal FROM fingerprints").fetchall()
        corpus = [r[0] for r in rows]
        query_vec = self._tfidf_vector(goal, corpus)

        query = "SELECT * FROM fingerprints"
        params: list = []
        if founder_id:
            query += " WHERE founder_id = ?"
            params.append(founder_id)

        results = []
        for row in self._db.execute(query, params).fetchall():
            fp_id, session_id, f_id, fp_goal, goal_vec_json, agents_json, tools_json, timing_json, score, ts = row
            fp_vec = json.loads(goal_vec_json)
            tool_outcomes = json.loads(tools_json)

            goal_sim = self._cosine(query_vec, fp_vec)
            tool_sim = self._jaccard(
                {t for t, s in tool_outcomes.items() if s == "success"},
                set(),  # query has no tool history yet
            )
            # Weighted: 80% goal similarity + 20% tool Jaccard
            combined = 0.8 * goal_sim + 0.2 * tool_sim

            if combined >= _SIMILARITY_THRESHOLD:
                results.append(
                    {
                        "fingerprint_id": fp_id,
                        "session_id": session_id,
                        "goal": fp_goal,
                        "similarity": round(combined, 3),
                        "success_score": score,
                        "tool_outcomes": tool_outcomes,
                        "timing": json.loads(timing_json),
                        "agents_used": json.loads(agents_json),
                        "timestamp": ts,
                    }
                )

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:_TOP_K]

    def format_match_block(self, goal: str, founder_id: str | None = None) -> str:
        """Human-readable fingerprint context for orchestrator prompt injection."""
        matches = self.match(goal, founder_id=founder_id)
        if not matches:
            return ""

        lines = ["[Execution Fingerprinting — Similar Past Runs]"]
        for m in matches:
            failed = [t for t, s in m["tool_outcomes"].items() if s != "success"]
            succeeded = [t for t, s in m["tool_outcomes"].items() if s == "success"]
            lines.append(
                f"• {int(m['similarity'] * 100)}% match — \"{m['goal'][:80]}\" ({m['timestamp'][:10]})\n"
                f"  Worked: {', '.join(succeeded) or 'none'}\n"
                + (f"  Failed: {', '.join(failed)}\n" if failed else "")
                + f"  Success score: {m['success_score']:.2f}"
            )
        return "\n".join(lines)

    def stats(self) -> dict:
        total = self._db.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
        avg_score = self._db.execute("SELECT AVG(success_score) FROM fingerprints").fetchone()[0] or 0
        return {"total_fingerprints": total, "avg_success_score": round(avg_score, 3)}
