import logfire
from pypdf import PdfReader

def parse_pdf(file_path:str):
    """
    Extract text from a pdf locally using pdf
    falls back to pdfplumber for pages that yeild no text"""
    with logfire.span("Pdf parsing local", filename=file_path):
        try:
            reader=PdfReader(file_path)
            total_pages = len(reader.pages)
            logfire.info(f"Pdf has (total_pages) pages")

            text_parts: list[str]= []
            blank_pages: list[int] = []

            for i, page in enumerate[page_num](reader.pages):
                text = page.extract_text()
                if text and len(text.strip()) > 0:
                    text_parts.append(text.strip())
                else:
                    blank_pages.append(i)

            #fallback if pdfreader doesnt work
            if blank_pages:
                logfire.info(f"pypdf returned blank on pages {blank_pages} - retrying with pdfplumber")
                try:
                    import pdfplumber
                    with pdfplumber.open(file_path) as pdf:
                        for page_num in blank_pages:
                            page = pdf.pages[page_num - 1]
                            fallback_text = page.extract_text() or ""
                            if fallback_text.strip():
                                text_parts.append(fallback_text.strip())
                except Exception as plumber_err:
                    logfire.warning("pdfplumber fallback also failed")
                    
            full_text="\n".join(text_parts)

            if not full_text.strip():
                logfire.warning(f"No text extracted from {file_path}")
            else:
                logfire.info(f"text extracted")

            return full_text
        except Exception as e:
            logfire.error("failed to parse pdf", error=str(e), filename=file_path)
            raise e