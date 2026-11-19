import logfire
from pypdf import PdfReader


def parse_pdf(file_path: str) -> str:
    """Extract text from a PDF document locally using pypdf,

    with fallback to pdfplumber for any pages where pypdf returns blank.
    """
    with logfire.span("PDF parsing local", filename=file_path):
        try:
            reader = PdfReader(file_path)
            total_pages = len(reader.pages)
            logfire.info(f"PDF has {total_pages} pages", filename=file_path)

            text_parts: list[str] = []
            blank_pages: list[int] = []

            for page_num, page in enumerate(reader.pages):
                text = page.extract_text()
                if text and len(text.strip()) > 0:
                    text_parts.append(text.strip())
                else:
                    blank_pages.append(page_num)

            # Fallback for pages that yielded no text with pypdf
            if blank_pages:
                logfire.info(
                    f"pypdf returned blank on pages {blank_pages} - attempting fallback with pdfplumber",
                    filename=file_path,
                )
                try:
                    import pdfplumber

                    with pdfplumber.open(file_path) as pdf:
                        for page_num in blank_pages:
                            if 0 <= page_num < len(pdf.pages):
                                page = pdf.pages[page_num]
                                fallback_text = page.extract_text() or ""
                                if fallback_text.strip():
                                    text_parts.append(fallback_text.strip())
                except Exception as plumber_err:
                    logfire.warning(
                        "pdfplumber fallback failed",
                        error=str(plumber_err),
                        filename=file_path,
                    )

            full_text = "\n\n".join(text_parts).strip()

            if not full_text:
                logfire.warning(f"No text extracted from {file_path}")
            else:
                logfire.info(
                    f"Successfully extracted {len(full_text)} characters from {file_path}"
                )

            return full_text
        except Exception as e:
            logfire.error("Failed to parse PDF", error=str(e), filename=file_path)
            raise e
