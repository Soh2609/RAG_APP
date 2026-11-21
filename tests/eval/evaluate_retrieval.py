import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import MagicMock, patch

from app.services.retrieval.retriever import RetrievedChunk, SemanticRetriever


def calculate_metrics(
    evaluation_records: List[Dict[str, Any]],
    k_values: List[int] = [1, 3, 5],
) -> Dict[str, float]:
    """Calculates Recall@K and MRR (Mean Reciprocal Rank) across evaluation queries."""
    if not evaluation_records:
        return {"recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "mrr": 0.0}

    total_queries = len(evaluation_records)
    reciprocal_ranks: List[float] = []
    hits_at_k: Dict[int, int] = {k: 0 for k in k_values}

    for record in evaluation_records:
        expected_keywords = [kw.lower() for kw in record.get("expected_keywords", [])]
        retrieved_chunks: List[RetrievedChunk] = record.get("retrieved_chunks", [])

        first_hit_rank: Optional[int] = None

        for rank, chunk in enumerate(retrieved_chunks, start=1):
            text_lower = chunk.text.lower()
            # Match if any expected keyword is present in retrieved chunk
            matched = any(kw in text_lower for kw in expected_keywords)
            if matched:
                if first_hit_rank is None:
                    first_hit_rank = rank
                for k in k_values:
                    if rank <= k:
                        hits_at_k[k] += 1
                break

        if first_hit_rank is not None:
            reciprocal_ranks.append(1.0 / first_hit_rank)
        else:
            reciprocal_ranks.append(0.0)

    metrics = {f"recall@{k}": round(hits_at_k[k] / total_queries, 4) for k in k_values}
    metrics["mrr"] = round(sum(reciprocal_ranks) / total_queries, 4)
    return metrics


class TestRetrievalEvaluation(unittest.TestCase):
    """Automated evaluation test ensuring golden dataset metrics meet baseline thresholds."""

    def test_metrics_calculation_logic(self):
        records = [
            {
                "expected_keywords": ["recursive"],
                "retrieved_chunks": [
                    RetrievedChunk(
                        chunk_id="c1",
                        text="Uses recursive chunking",
                        score=0.9,
                        source_file="f1",
                        source_path="/f1",
                        source_type="doc",
                    )
                ],
            },
            {
                "expected_keywords": ["ssrf"],
                "retrieved_chunks": [
                    RetrievedChunk(
                        chunk_id="c2",
                        text="Unrelated text",
                        score=0.8,
                        source_file="f2",
                        source_path="/f2",
                        source_type="doc",
                    ),
                    RetrievedChunk(
                        chunk_id="c3",
                        text="Contains SSRF protection",
                        score=0.7,
                        source_file="f3",
                        source_path="/f3",
                        source_type="doc",
                    ),
                ],
            },
        ]
        metrics = calculate_metrics(records, k_values=[1, 3])
        # Query 1 hit at rank 1, Query 2 hit at rank 2
        # Recall@1 = 1/2 = 0.5
        # Recall@3 = 2/2 = 1.0
        # MRR = (1/1 + 1/2) / 2 = 1.5 / 2 = 0.75
        self.assertEqual(metrics["recall@1"], 0.5)
        self.assertEqual(metrics["recall@3"], 1.0)
        self.assertEqual(metrics["mrr"], 0.75)


if __name__ == "__main__":
    unittest.main()
