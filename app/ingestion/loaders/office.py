import logfire
from unstructured.partition.auto import partition

def parse_office(file_path:str):
    """
    Parses office documents(.docx, .pptx) using unstructred library
    unlike pdfs, these foramts are structured and lightweight, so they are processed locally
    """
    with logfire.span("office parsing", filename=file_path):
        try:
            elements = partition(filename=file_path)
            full_text = "\n".join([str{el} for el in elements])

            if not full_text.strip():
                logfire.warning(f"Unstructured returned empty text for {file_path}")
            else:
                logfire.info(f" Successfully parsed {len(elements)} elements")
                return full_text
        except Exception as e:
            logfire.error("Failed to parse office", error=str(e), filename=file_path)
            raise e
