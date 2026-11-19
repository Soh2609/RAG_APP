import unittest
from app.scraper.url_utils import (
    clean_url,
    get_domain,
    is_same_domain,
    is_valid_crawl_target,
    url_to_filename,
)


class TestUrlUtils(unittest.TestCase):

    def test_clean_url_removes_fragment(self):
        url = "https://docs.example.com/guide/intro#getting-started"
        expected = "https://docs.example.com/guide/intro"
        self.assertEqual(clean_url(url), expected)

    def test_clean_url_strips_tracking_params(self):
        url = "https://example.com/page?utm_source=twitter&utm_medium=social&page=2&ref=banner"
        expected = "https://example.com/page?page=2"
        self.assertEqual(clean_url(url), expected)

    def test_clean_url_normalizes_trailing_slash(self):
        url = "https://example.com/docs/api/"
        expected = "https://example.com/docs/api"
        self.assertEqual(clean_url(url), expected)

        # Root slash should be preserved
        self.assertEqual(clean_url("https://example.com/"), "https://example.com/")

    def test_clean_url_lowercases_host(self):
        url = "HTTPS://DOCS.Example.COM/Path"
        expected = "https://docs.example.com/Path"
        self.assertEqual(clean_url(url), expected)

    def test_is_same_domain(self):
        base = "https://docs.example.com"
        self.assertTrue(is_same_domain("https://docs.example.com/page", base))
        self.assertTrue(is_same_domain("https://sub.docs.example.com/page", base))
        self.assertFalse(is_same_domain("https://google.com", base))
        self.assertFalse(is_same_domain("https://example2.com", base))

    def test_is_valid_crawl_target_scheme(self):
        base = "https://docs.example.com"
        self.assertFalse(is_valid_crawl_target("mailto:info@example.com", base))
        self.assertFalse(is_valid_crawl_target("javascript:void(0)", base))
        self.assertFalse(is_valid_crawl_target("ftp://docs.example.com/file", base))

    def test_is_valid_crawl_target_excluded_extensions(self):
        base = "https://docs.example.com"
        self.assertFalse(is_valid_crawl_target("https://docs.example.com/img/logo.png", base))
        self.assertFalse(is_valid_crawl_target("https://docs.example.com/assets/app.js", base))
        self.assertFalse(is_valid_crawl_target("https://docs.example.com/styles.css", base))
        self.assertFalse(is_valid_crawl_target("https://docs.example.com/archive.zip", base))
        self.assertTrue(is_valid_crawl_target("https://docs.example.com/docs/overview", base))
        self.assertTrue(is_valid_crawl_target("https://docs.example.com/docs/overview.html", base))

    def test_is_valid_crawl_target_prefix(self):
        base = "https://example.com"
        prefix = "/docs/"
        self.assertTrue(is_valid_crawl_target("https://example.com/docs/intro", base, allowed_prefix=prefix))
        self.assertFalse(is_valid_crawl_target("https://example.com/blog/post-1", base, allowed_prefix=prefix))

    def test_url_to_filename(self):
        self.assertEqual(url_to_filename("https://example.com/"), "index.html")
        self.assertEqual(url_to_filename("https://example.com/docs/api/"), "docs_api.html")
        self.assertEqual(url_to_filename("https://example.com/docs/api/search.html"), "docs_api_search.html")

        # Test Windows illegal characters
        dirty_url = "https://example.com/docs/?query=foo:bar*baz"
        filename = url_to_filename(dirty_url)
        for char in ':*?"<>|':
            self.assertNotIn(char, filename)


if __name__ == "__main__":
    unittest.main()
