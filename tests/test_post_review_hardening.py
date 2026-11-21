import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import Settings
from app.core.exceptions import DimensionMismatchError, EmbeddingError
from app.ingestion.processor import process_file
from app.scraper.crawler import DocumentationCrawler
from app.scraper.fetcher import PageFetcher
from app.scraper.url_utils import is_safe_url
from app.services.retrieval.qdrant import ensure_collection


class TestPostReviewHardening(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # 1. SSRF Security Protection Tests
    # -------------------------------------------------------------
    def test_ssrf_blocks_private_and_metadata_ips(self):
        # Localhost & Loopback
        self.assertFalse(is_safe_url("http://127.0.0.1/admin"))
        self.assertFalse(is_safe_url("http://localhost:8000/"))

        # AWS / GCP Instance Metadata Service (IMDS)
        self.assertFalse(is_safe_url("http://169.254.169.254/latest/meta-data/"))

        # Private RFC-1918 addresses
        self.assertFalse(is_safe_url("http://10.0.0.1/internal-api"))
        self.assertFalse(is_safe_url("http://192.168.1.1/router"))
        self.assertFalse(is_safe_url("http://172.16.0.50/"))

        # Invalid schemes
        self.assertFalse(is_safe_url("file:///etc/passwd"))
        self.assertFalse(is_safe_url("ftp://ftp.example.com"))

    def test_fetcher_rejects_ssrf_with_403(self):
        fetcher = PageFetcher()
        res = fetcher.fetch("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(res.is_success)
        self.assertEqual(res.status_code, 403)
        self.assertIn("SSRF", res.error)

    # -------------------------------------------------------------
    # 2. Robots.txt Compliance Tests
    # -------------------------------------------------------------
    def test_crawler_respects_disallow_rules(self):
        crawler = DocumentationCrawler(
            start_url="https://docs.example.com/",
            output_dir=self.temp_dir,
            respect_robots_txt=True,
        )
        mock_rp = MagicMock()
        # Disallow /private/ paths
        mock_rp.can_fetch.side_effect = lambda ua, url: "/private/" not in url
        crawler.robot_parser = mock_rp

        self.assertTrue(crawler._is_allowed_by_robots("https://docs.example.com/guide"))
        self.assertFalse(crawler._is_allowed_by_robots("https://docs.example.com/private/secret"))

    # -------------------------------------------------------------
    # 3. Vector Dimension Mismatch Hard Invariant Tests
    # -------------------------------------------------------------
    @patch("app.services.retrieval.qdrant.get_embedding_dim", return_value=768)
    def test_ensure_collection_detects_dimension_mismatch(self, mock_dim):
        # Create in-memory Qdrant collection with 3072d vectors
        client = QdrantClient(":memory:")
        col_name = "test_col_3072"
        client.create_collection(
            collection_name=col_name,
            vectors_config=models.VectorParams(size=3072, distance=models.Distance.COSINE),
        )

        # Attempt to connect when active model produces 768d vectors
        with self.assertRaises(DimensionMismatchError) as ctx:
            ensure_collection(client, collection_name=col_name, recreate=False)

        self.assertIn("DIMENSION MISMATCH", str(ctx.exception))

    # -------------------------------------------------------------
    # 4. Fail-Fast Safety Flags Tests
    # -------------------------------------------------------------
    @patch("app.services.retrieval.embeddings._probe_gemini", return_value=None)
    @patch("app.services.retrieval.embeddings.settings")
    def test_embedding_fallback_raises_when_disabled(self, mock_settings, mock_probe):
        from app.services.retrieval import embeddings
        # Set fallback to false (production mode)
        mock_settings.allow_embedding_fallback = False
        mock_settings.gemini_api_key = "dummy_key"
        embeddings._active_model = None
        embeddings._model_type = None

        with self.assertRaises(EmbeddingError) as ctx:
            embeddings._init()

        self.assertIn("ALLOW_EMBEDDING_FALLBACK is disabled", str(ctx.exception))

    # -------------------------------------------------------------
    # 5. Stale Vector Purge on Re-ingest Tests
    # -------------------------------------------------------------
    @patch("app.ingestion.processor.get_qdrant_client")
    @patch("app.ingestion.processor.ensure_collection", return_value="test_collection")
    @patch("app.ingestion.processor.embed_texts", return_value=[[0.1] * 768])
    def test_process_file_purges_stale_vectors_before_upsert(
        self, mock_embed, mock_ensure_col, mock_get_client
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        test_file = Path(self.temp_dir) / "test_doc.txt"
        test_file.write_text("This is test document text for indexing.", encoding="utf-8")

        res = process_file(
            file_path=str(test_file),
            source_type="test_docs",
            collection_name="test_collection",
        )

        self.assertEqual(res["status"], "success")
        # Verify client.delete was called to purge existing points for this source_file
        mock_client.delete.assert_called_once()
        delete_kwargs = mock_client.delete.call_args.kwargs
        self.assertEqual(delete_kwargs["collection_name"], "test_collection")
        self.assertTrue(delete_kwargs["wait"])

        # Verify client.upsert was called with wait=True
        mock_client.upsert.assert_called_once()
        upsert_kwargs = mock_client.upsert.call_args.kwargs
        self.assertTrue(upsert_kwargs["wait"])

    # -------------------------------------------------------------
    # 6. File Size Limit Protection Tests
    # -------------------------------------------------------------
    @patch("app.ingestion.processor.settings")
    def test_process_file_skips_oversized_file(self, mock_settings):
        # Set max limit to 10 bytes
        mock_settings.max_file_size_bytes = 10

        large_file = Path(self.temp_dir) / "huge.txt"
        large_file.write_text("This content exceeds 10 bytes limit easily.", encoding="utf-8")

        res = process_file(file_path=str(large_file))
        self.assertEqual(res["status"], "skipped_too_large")
        self.assertIn("exceeds limit", res["reason"])

    # -------------------------------------------------------------
    # 7. Pydantic Settings Validation Tests
    # -------------------------------------------------------------
    def test_settings_defaults_and_validation(self):
        s = Settings(
            gemini_api_key="test_key",
            qdrant_cluster_endpoint="https://test.qdrant.io",
            allow_embedding_fallback=False,
        )
        self.assertEqual(s.gemini_api_key, "test_key")
        self.assertEqual(s.qdrant_url, "https://test.qdrant.io")
        self.assertFalse(s.allow_embedding_fallback)
        self.assertEqual(s.qdrant_collection, "enterprise_rag")


if __name__ == "__main__":
    unittest.main()
