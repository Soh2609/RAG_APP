import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from app.scraper.crawler import DocumentationCrawler
from app.scraper.fetcher import FetchResult, PageFetcher


class TestDocumentationCrawler(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_fetcher = MagicMock(spec=PageFetcher)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_bfs_crawl_with_depth_and_page_limits(self):
        start_url = "https://docs.example.com/home"

        # Mock page responses
        page_home = """
        <html><head><title>Home</title></head>
        <body>
            <a href="/docs/guide-a">Guide A</a>
            <a href="/docs/guide-b">Guide B</a>
            <a href="https://external.com/promo">External</a>
        </body></html>
        """
        page_a = """
        <html><head><title>Guide A</title></head>
        <body>
            <p>Content A</p>
            <a href="/docs/deep-c">Deep C</a>
        </body></html>
        """
        page_b = """
        <html><head><title>Guide B</title></head>
        <body><p>Content B</p></body></html>
        """
        page_c = """
        <html><head><title>Deep C</title></head>
        <body><p>Content C</p></body></html>
        """

        def mock_fetch(url):
            mapping = {
                "https://docs.example.com/home": page_home,
                "https://docs.example.com/docs/guide-a": page_a,
                "https://docs.example.com/docs/guide-b": page_b,
                "https://docs.example.com/docs/deep-c": page_c,
            }
            if url in mapping:
                return FetchResult(
                    url=url,
                    status_code=200,
                    html=mapping[url],
                    content_type="text/html",
                )
            return FetchResult(url=url, status_code=404, error="Not found")

        self.mock_fetcher.fetch.side_effect = mock_fetch

        # 1. Test crawling with max_depth=1 (should crawl home, guide-a, guide-b, but NOT deep-c)
        crawler = DocumentationCrawler(
            start_url=start_url,
            output_dir=self.test_dir,
            max_pages=10,
            max_depth=1,
            delay=0,  # No sleep during unit tests
            fetcher=self.mock_fetcher,
        )

        summary = crawler.crawl()

        self.assertEqual(summary.total_pages_scraped, 3)
        scraped_urls = [p["url"] for p in summary.pages]
        self.assertIn("https://docs.example.com/home", scraped_urls)
        self.assertIn("https://docs.example.com/docs/guide-a", scraped_urls)
        self.assertIn("https://docs.example.com/docs/guide-b", scraped_urls)
        # Deep C is depth 2, so it must not be scraped
        self.assertNotIn("https://docs.example.com/docs/deep-c", scraped_urls)
        # External URL must not be scraped
        self.assertNotIn("https://external.com/promo", scraped_urls)

        # Check manifest file
        manifest_file = Path(summary.manifest_path)
        self.assertTrue(manifest_file.exists())
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_json = json.load(f)
            self.assertEqual(manifest_json["total_pages"], 3)
            self.assertIn("https://docs.example.com/home", manifest_json["pages"])

    def test_crawl_respects_max_pages(self):
        start_url = "https://docs.example.com/home"

        def mock_infinite_links(url):
            page_id = url.split("/")[-1]
            next_id = int(page_id) + 1 if page_id.isdigit() else 1
            html = f"""
            <html><head><title>Page {page_id}</title></head>
            <body><a href="/page/{next_id}">Next</a></body></html>
            """
            return FetchResult(url=url, status_code=200, html=html, content_type="text/html")

        self.mock_fetcher.fetch.side_effect = mock_infinite_links

        crawler = DocumentationCrawler(
            start_url=start_url,
            output_dir=self.test_dir,
            max_pages=2,
            max_depth=10,
            delay=0,
            fetcher=self.mock_fetcher,
        )

        summary = crawler.crawl()
        self.assertEqual(summary.total_pages_scraped, 2)


if __name__ == "__main__":
    unittest.main()
