import logfire


def parse_text(file_path: str) -> str:
    """Parses plain text and markdown documents.

    Handles UTF-8 and falls back gracefully to Latin-1 encoding if necessary.
    """
    with logfire.span("Text parsing", filename=file_path):
        try:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(file_path, "r", encoding="latin-1", errors="replace") as f:
                    content = f.read()

            content = content.strip()
            if not content:
                logfire.warning(f"Text file {file_path} is empty")
            else:
                logfire.info(
                    f"Successfully loaded {len(content)} characters from {file_path}"
                )
            return content
        except Exception as e:
            logfire.error("Text parse failed", error=str(e), filename=file_path)
            raise e
