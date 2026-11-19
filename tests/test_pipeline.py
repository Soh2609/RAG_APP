import unittest
from unittest.mock import MagicMock, patch

from app.scraper.crawler import CrawlSummary
from app.scraper.pipeline import scrape_and_ingest


class TestPipeline(unittest.TestCase):

    @patch("app.scraper.pipeline.DocumentationCrawler")
    @patch("app.scraper.pipeline.process_directory")
    @patch("app.scraper.pipeline.ensure_collection")
    @patch("app.scraper.pipeline.get_qdrant_client")
    def test_scrape_and_ingest_auto_ingest_true(
        self, mock_client, mock_ensure_col, mock_proc_dir, mock_crawler_cls
    ):
        mock_crawler_instance = MagicMock()
        mock_crawler_instance.crawl.return_value = CrawlSummary(
            start_url="https://docs.example.com",
            domain="docs.example.com",
            total_pages_scraped=5,
            total_failed=0,
            output_dir="/fake/scraped/docs.example.com",
            manifest_path="/fake/scraped/docs.example.com/manifest.json",
            elapsed_seconds=1.2,
        )
        mock_crawler_cls.return_value = mock_crawler_instance

        mock_proc_dir.return_value = {
            "directory": "/fake/scraped/docs.example.com",
            "successful": 5,
            "errors": 0,
        }

        report = scrape_and_ingest(
            start_url="https://docs.example.com",
            max_pages=5,
            auto_ingest=True,
        )

        # Verify crawler was called
        mock_crawler_instance.crawl.assert_called_once()
        # Verify vector ingestion was triggered
        mock_proc_dir.assert_called_once_with(
            dir_path="/fake/scraped/docs.example.com",
            source_type="web_docs.example.com",
        )
        self.assertIsNotNone(report["ingestion_summary"])
        self.assertEqual(report["crawl_summary"]["total_pages_scraped"], 5)

    @patch("app.scraper.pipeline.DocumentationCrawler")
    @patch("app.scraper.pipeline.process_directory")
    def test_scrape_and_ingest_no_ingest(self, mock_proc_dir, mock_crawler_cls):
        mock_crawler_instance = MagicMock()
        mock_crawler_instance.crawl.return_value = CrawlSummary(
            start_url="https://docs.example.com",
            domain="docs.example.com",
            total_pages_scraped=3,
            total_failed=0,
            output_dir="/fake/scraped/docs.example.com",
            manifest_path="/fake/scraped/docs.example.com/manifest.json",
            elapsed_seconds=0.8,
        )
        mock_crawler_cls.return_value = mock_crawler_instance

        report = scrape_and_ingest(
            start_url="https://docs.example.com",
            auto_ingest=False,
        )

        mock_crawler_instance.crawl.assert_called_once()
        # Ingestion must NOT be called
        mock_proc_dir.assert_not_called()
        self.assertIsNone(report["ingestion_summary"])


if __name__ == "__main__":
    unittest.main()
