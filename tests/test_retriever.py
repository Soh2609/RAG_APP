import unittest
from unittest.mock import MagicMock, patch

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.services.retrival.retriever import (
    RetrievalResult,
    RetrievedChunk,
    SemanticRetriever,
    build_qdrant_filter,
)


class TestRetriever(unittest.TestCase):

    def test_query_validation_rejects_empty(self):
        retriever = SemanticRetriever(collection_name="test_col")
        with self.assertRaises(ValueError):
            retriever.retrieve("")

        with self.assertRaises(ValueError):
            retriever.retrieve("   \n\t  ")

    def test_build_qdrant_filter_none(self):
        self.assertIsNone(build_qdrant_filter())
        self.assertIsNone(build_qdrant_filter(source_type=None, source_file=None))

    def test_build_qdrant_filter_single_values(self):
        q_filter = build_qdrant_filter(source_type="web_docs", source_file="guide.html")
        self.assertIsNotNone(q_filter)
        self.assertEqual(len(q_filter.must), 2)
        self.assertEqual(q_filter.must[0].key, "source_type")
        self.assertEqual(q_filter.must[0].match.value, "web_docs")
        self.assertEqual(q_filter.must[1].key, "source_file")
        self.assertEqual(q_filter.must[1].match.value, "guide.html")

    def test_build_qdrant_filter_list_values(self):
        q_filter = build_qdrant_filter(source_type=["web", "pdf"])
        self.assertIsNotNone(q_filter)
        self.assertEqual(len(q_filter.must), 1)
        self.assertEqual(q_filter.must[0].key, "source_type")
        self.assertEqual(q_filter.must[0].match.any, ["web", "pdf"])

    def test_retrieved_chunk_and_result_dto(self):
        chunk = RetrievedChunk(
            chunk_id="chunk_1",
            text="Architecture guide",
            score=0.92,
            source_file="arch.md",
            source_path="/data/arch.md",
            source_type="markdown",
            chunk_index=0,
            total_chunks=3,
            file_hash="abc123hash",
            metadata={"extra_key": "val"},
        )
        c_dict = chunk.to_dict()
        self.assertEqual(c_dict["chunk_id"], "chunk_1")
        self.assertEqual(c_dict["score"], 0.92)
        self.assertEqual(c_dict["metadata"]["extra_key"], "val")

        result = RetrievalResult(
            query="how does architecture work?",
            chunks=[chunk],
            total_found=1,
            latency_ms=12.5,
            applied_filters={"source_type": "markdown"},
            embedding_dim=768,
        )
        r_dict = result.to_dict()
        self.assertEqual(r_dict["total_found"], 1)
        self.assertEqual(r_dict["latency_ms"], 12.5)
        self.assertEqual(len(r_dict["chunks"]), 1)

    @patch("app.services.retrival.retriever.embed_query")
    def test_retrieve_with_mocked_qdrant(self, mock_embed_query):
        mock_embed_query.return_value = [0.1, 0.2, 0.3, 0.4]

        mock_point = MagicMock()
        mock_point.id = "p-123"
        mock_point.score = 0.885
        mock_point.payload = {
            "text": "This is chunk content.",
            "source_file": "intro.html",
            "source_path": "/data/intro.html",
            "source_type": "web_docs",
            "chunk_index": 0,
            "total_chunks": 1,
            "file_hash": "hash789",
            "custom_tag": "v1",
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.points = [mock_point]
        mock_client.query_points.return_value = mock_response

        retriever = SemanticRetriever(collection_name="test_col", client=mock_client)
        res = retriever.retrieve("What is the intro?", top_k=3, score_threshold=0.7)

        mock_embed_query.assert_called_once_with("What is the intro?")
        mock_client.query_points.assert_called_once()
        call_kwargs = mock_client.query_points.call_args.kwargs
        self.assertEqual(call_kwargs["collection_name"], "test_col")
        self.assertEqual(call_kwargs["limit"], 3)
        self.assertEqual(call_kwargs["score_threshold"], 0.7)

        self.assertEqual(res.total_found, 1)
        self.assertEqual(res.chunks[0].chunk_id, "p-123")
        self.assertEqual(res.chunks[0].text, "This is chunk content.")
        self.assertEqual(res.chunks[0].score, 0.885)
        self.assertEqual(res.chunks[0].metadata["custom_tag"], "v1")

    @patch("app.services.retrival.retriever.embed_query")
    def test_retrieve_in_memory_integration(self, mock_embed_query):
        # Deterministic mock query embedding
        mock_embed_query.return_value = [1.0, 0.0, 0.0, 0.0]

        # Create real in-memory Qdrant client
        mem_client = QdrantClient(":memory:")
        col_name = "integration_test_col"
        mem_client.create_collection(
            collection_name=col_name,
            vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
        )

        # Upsert 3 points
        # Point 1: very similar ([1, 0, 0, 0])
        # Point 2: moderately similar ([0.7, 0.7, 0, 0])
        # Point 3: orthogonal ([0, 1, 0, 0])
        mem_client.upsert(
            col_name,
            points=[
                models.PointStruct(
                    id=1,
                    vector=[1.0, 0.0, 0.0, 0.0],
                    payload={"text": "Target Document Alpha", "source_type": "docs", "source_file": "alpha.html"},
                ),
                models.PointStruct(
                    id=2,
                    vector=[0.7071, 0.7071, 0.0, 0.0],
                    payload={"text": "Target Document Beta", "source_type": "docs", "source_file": "beta.html"},
                ),
                models.PointStruct(
                    id=3,
                    vector=[0.0, 1.0, 0.0, 0.0],
                    payload={"text": "Unrelated Gamma", "source_type": "other", "source_file": "gamma.html"},
                ),
            ],
        )

        retriever = SemanticRetriever(collection_name=col_name, client=mem_client)

        # 1. Unfiltered query: should return Alpha and Beta first
        res = retriever.retrieve("query Alpha", top_k=2)
        self.assertEqual(res.total_found, 2)
        self.assertEqual(res.chunks[0].text, "Target Document Alpha")
        self.assertAlmostEqual(res.chunks[0].score, 1.0, places=4)

        # 2. Filtered query: filter by source_file="beta.html"
        res_filtered = retriever.retrieve("query Alpha", top_k=2, source_file="beta.html")
        self.assertEqual(res_filtered.total_found, 1)
        self.assertEqual(res_filtered.chunks[0].text, "Target Document Beta")

        # 3. Score threshold: cutoff at 0.9 (should only return Alpha)
        res_threshold = retriever.retrieve("query Alpha", top_k=3, score_threshold=0.9)
        self.assertEqual(res_threshold.total_found, 1)
        self.assertEqual(res_threshold.chunks[0].text, "Target Document Alpha")


if __name__ == "__main__":
    unittest.main()
