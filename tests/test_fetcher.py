import unittest
from unittest.mock import MagicMock, patch
import requests

from app.scraper.fetcher import (
    FetchResult,
    PageFetcher,
    extract_page_data,
)


class TestFetcher(unittest.TestCase):

    def test_extract_page_data_title_and_links(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Documentation Overview - System</title>
            <script>console.log("drop me");</script>
            <style>body { color: red; }</style>
        </head>
        <body>
            <h1>Main Title</h1>
            <p>Welcome to our documentation.</p>
            <a href="/guides/quickstart">Quickstart</a>
            <a href="https://example.com/api/reference#section">API Reference</a>
            <a href="#ignore-me">Anchor</a>
            <a href="mailto:test@example.com">Email</a>
            <a href="javascript:void(0)">JS</a>
        </body>
        </html>
        """
        base_url = "https://example.com/docs/index.html"
        extracted = extract_page_data(sample_html, base_url)

        self.assertEqual(extracted.title, "Documentation Overview - System")
        self.assertIn("Welcome to our documentation.", extracted.text)
        self.assertNotIn("console.log", extracted.text)

        # Verify link extraction and resolution
        expected_links = [
            "https://example.com/guides/quickstart",
            "https://example.com/api/reference",  # stripped fragment
        ]
        for link in expected_links:
            self.assertIn(link, extracted.links)

        # Ignored links should not be present
        self.assertNotIn("mailto:test@example.com", extracted.links)
        self.assertNotIn("javascript:void(0)", extracted.links)

    @patch("requests.Session.get")
    def test_fetch_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://example.com/docs/"
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.text = "<html><head><title>Test</title></head><body>Hello</body></html>"
        mock_get.return_value = mock_resp

        fetcher = PageFetcher(timeout=5.0)
        res = fetcher.fetch("https://example.com/docs/")

        self.assertTrue(res.is_success)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.url, "https://example.com/docs")
        self.assertIn("Hello", res.html)

    @patch("requests.Session.get")
    def test_fetch_rejects_non_html(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://example.com/api/data.json"
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"status": "ok"}'
        mock_get.return_value = mock_resp

        fetcher = PageFetcher()
        res = fetcher.fetch("https://example.com/api/data.json")

        self.assertFalse(res.is_success)
        self.assertIn("Non-HTML", res.error)

    @patch("requests.Session.get")
    def test_fetch_handles_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        fetcher = PageFetcher()
        res = fetcher.fetch("https://example.com/slow")

        self.assertFalse(res.is_success)
        self.assertEqual(res.status_code, 408)
        self.assertIn("timed out", res.error)


if __name__ == "__main__":
    unittest.main()
