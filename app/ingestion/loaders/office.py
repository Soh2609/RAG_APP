import logfire


def parse_office(file_path: str) -> str:
    """Parses office documents (.docx, .pptx) using the unstructured library.

    Extracts text elements locally and formats them cleanly for chunking.
    Uses lazy import for unstructured to avoid slow application startup.
    """
    with logfire.span("Office parsing", filename=file_path):
        try:
            from unstructured.partition.auto import partition

            elements = partition(filename=file_path)
            element_texts = [str(el).strip() for el in elements if str(el).strip()]
            full_text = "\n\n".join(element_texts).strip()

            if not full_text:
                logfire.warning(f"Unstructured returned empty text for {file_path}")
            else:
                logfire.info(
                    f"Successfully parsed {len(elements)} elements from {file_path}"
                )

            return full_text
        except Exception as e:
            logfire.error("Failed to parse office document", error=str(e), filename=file_path)
            raise e
