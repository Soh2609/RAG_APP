from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Citation:
    """Represents a citation referencing a specific retrieved document chunk."""
    marker: str
    source_file: str
    source_path: str
    source_type: str
    chunk_index: int
    score: float
    snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeneratedAnswer:
    """Encapsulates the complete LLM generated answer with citations and metrics."""
    question: str
    answer: str
    citations: List[Citation] = field(default_factory=list)
    model: str = "llama-3.3-70b-versatile"
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    grounded: bool = True
    retrieved_chunks_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "grounded": self.grounded,
            "retrieved_chunks_count": self.retrieved_chunks_count,
            "token_usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
            "citations": [c.to_dict() for c in self.citations],
        }
