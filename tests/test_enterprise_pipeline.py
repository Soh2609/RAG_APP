import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.pipeline import PipelineResult, Stage1Result, Stage2Result, TwoStagePipeline
from app.scraper.crawler import CrawlSummary


class TestEnterprisePipeline(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.pipeline = TwoStagePipeline(collection_name="test_collection")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.pipeline.DocumentationCrawler")
    def test_run_web_pipeline_stage1_only(self, mock_crawler_cls):
        mock_crawler = MagicMock()
        mock_crawler.crawl.return_value = CrawlSummary(
            start_url="https://docs.example.com",
            domain="docs.example.com",
            total_pages_scraped=5,
            total_failed=0,
            output_dir=self.test_dir,
            manifest_path=f"{self.test_dir}/manifest.json",
            elapsed_seconds=1.0,
        )
        mock_crawler_cls.return_value = mock_crawler

        result: PipelineResult = self.pipeline.run_web_pipeline(
            url="https://docs.example.com",
            auto_index=False,
        )

        self.assertEqual(result.status, "stage_1_only")
        self.assertIsNotNone(result.stage_1)
        self.assertEqual(result.stage_1.total_files, 5)
        self.assertIsNone(result.stage_2)

    @patch("app.pipeline.DocumentationCrawler")
    @patch.object(TwoStagePipeline, "index_staged_directory")
    def test_run_web_pipeline_linked(self, mock_index_staged, mock_crawler_cls):
        mock_crawler = MagicMock()
        mock_crawler.crawl.return_value = CrawlSummary(
            start_url="https://docs.example.com",
            domain="docs.example.com",
            total_pages_scraped=3,
            total_failed=0,
            output_dir=self.test_dir,
            manifest_path=f"{self.test_dir}/manifest.json",
            elapsed_seconds=0.8,
        )
        mock_crawler_cls.return_value = mock_crawler

        mock_index_staged.return_value = Stage2Result(
            collection_name="test_collection",
            source_type="web_docs.example.com",
            total_documents=3,
            successful=3,
            skipped=0,
            errors=0,
            elapsed_seconds=0.5,
        )

        result: PipelineResult = self.pipeline.run_web_pipeline(
            url="https://docs.example.com",
            auto_index=True,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.stage_1.total_files, 3)
        self.assertIsNotNone(result.stage_2)
        self.assertEqual(result.stage_2.successful, 3)

    @patch("app.pipeline.get_qdrant_client")
    @patch("app.pipeline.ensure_collection")
    @patch("app.pipeline.process_file")
    def test_index_staged_directory_incremental_skipping(
        self, mock_process_file, mock_ensure_col, mock_client
    ):
        # Create a sample staged document
        sample_file = Path(self.test_dir) / "guide.html"
        sample_file.write_text("<html><body>Hello World</body></html>", encoding="utf-8")

        # Mock cached hash matching guide.html
        file_hash = self.pipeline._compute_quick_hash(sample_file)
        with patch.object(self.pipeline, "_load_existing_hashes", return_value={"guide": file_hash}):
            res: Stage2Result = self.pipeline.index_staged_directory(
                staged_dir=self.test_dir,
                source_type="test_source",
                incremental=True,
            )

            # process_file should NOT be called because hash matched
            mock_process_file.assert_not_called()
            self.assertEqual(res.skipped, 1)
            self.assertEqual(res.successful, 0)
            self.assertEqual(res.details[0]["status"], "skipped_unchanged")

    @patch("app.pipeline.get_qdrant_client")
    @patch("app.pipeline.ensure_collection")
    @patch("app.pipeline.process_file")
    def test_index_staged_directory_processes_new_files(
        self, mock_process_file, mock_ensure_col, mock_client
    ):
        sample_file = Path(self.test_dir) / "new_guide.html"
        sample_file.write_text("<html><body>Brand New Page</body></html>", encoding="utf-8")

        mock_process_file.return_value = {
            "status": "success",
            "file": "new_guide.html",
            "chunks": 2,
        }

        # Cache is empty (no previous hashes)
        with patch.object(self.pipeline, "_load_existing_hashes", return_value={}):
            res: Stage2Result = self.pipeline.index_staged_directory(
                staged_dir=self.test_dir,
                source_type="test_source",
                incremental=True,
            )

            mock_process_file.assert_called_once()
            self.assertEqual(res.successful, 1)
            self.assertEqual(res.skipped, 0)


if __name__ == "__main__":
    unittest.main()
