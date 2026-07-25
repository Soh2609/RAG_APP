import logfire
def parse_text(file_path:str):
    """
    parses text file"""
    with logfire.span("text parsing", filename=file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                return content 
        except Exception as e:
            logfire.error(f"text parse failed {e}")
            raise e
            