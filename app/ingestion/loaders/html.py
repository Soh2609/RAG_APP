import re
from bs4 import BeautifulSoup
import logfire


def parse_html(file_path: str) -> str:
    """Parses local HTML files using BeautifulSoup.

    Removes scripts, styles, metadata, and extraneous navigation elements,
    extracts clean readable text, and normalizes whitespace while preserving
    paragraph structure for semantic chunking.
    """
    with logfire.span("HTML Parsing", filename=file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            soup = BeautifulSoup(content, "html.parser")

            # 1. Remove non-content and noisy elements
            unwanted_tags = [
                "script", "style", "noscript", "meta", "link",
                "svg", "form"
            ]
            for tag in soup(unwanted_tags):
                tag.decompose()

            # 2. Extract text with newline delimiters between blocks
            raw_text = soup.get_text(separator="\n")

            # 3. Clean and normalize whitespace while preserving paragraphs
            lines = []
            for line in raw_text.splitlines():
                cleaned_line = re.sub(r"[ \t]+", " ", line).strip()
                if cleaned_line:
                    lines.append(cleaned_line)

            # Reconstruct text with paragraph separation
            normalized_text = "\n".join(lines)
            # Collapse more than two consecutive newlines into two
            clean_text = re.sub(r"\n{3,}", "\n\n", normalized_text).strip()

            if not clean_text:
                logfire.warning(f"No readable text extracted from HTML: {file_path}")
            else:
                logfire.info(
                    f"Successfully parsed HTML, extracted {len(clean_text)} characters",
                    filename=file_path,
                )

            return clean_text
        except Exception as e:
            logfire.error("Failed to parse HTML", error=str(e), filename=file_path)
            raise e
