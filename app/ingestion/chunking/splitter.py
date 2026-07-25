from typing import List
import logfire

def chunk_text(text:str, chunk_size: int = 1500) -> List[str]:
    """
    simple semantic-ish chunker that splits by paragraph"""
