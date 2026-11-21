import argparse
import json
import time
from typing import Any, Dict, List, Optional, Union

import logfire

from app.config import settings
from app.core.exceptions import RAGError
from app.services.generation.models import Citation, GeneratedAnswer
from app.services.generation.prompts import SYSTEM_PROMPT, build_user_prompt, format_context
from app.services.retrieval.retriever import RetrievedChunk, SemanticRetriever

try:
    logfire.configure(service_name="generation-service", send_to_logfire="if-token-present")
except Exception:
    pass


class GroqGenerator:
    """Production LLM Generation service powered by Groq and Llama 3.3.

    Enforces anti-injection context boundaries, strict grounding, low-temperature
    determinism, and structured provenance citations.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        model_name: Optional[str] = None,
    ):
        self._client = client
        self.model_name = model_name or settings.groq_model

    def get_client(self) -> Any:
        """Lazily initializes and returns the Groq client."""
        if self._client is not None:
            return self._client

        if not settings.groq_api_key:
            raise RAGError(
                "GROQ_API_KEY is not configured in .env. "
                "Please configure a valid Groq API key to enable answer generation."
            )

        try:
            from groq import Groq
            self._client = Groq(api_key=settings.groq_api_key)
            return self._client
        except Exception as e:
            raise RAGError(f"Failed to initialize Groq client: {e}") from e

    def generate(
        self,
        question: str,
        retrieved_chunks: List[RetrievedChunk],
        temperature: float = 0.1,
    ) -> GeneratedAnswer:
        """Generates a grounded, citation-backed answer from retrieved chunks."""
        if not question or not isinstance(question, str) or not question.strip():
            raise ValueError("Question string cannot be empty")

        cleaned_question = question.strip()
        t0 = time.time()

        # If no chunks provided, short-circuit immediately without LLM call
        if not retrieved_chunks:
            return GeneratedAnswer(
                question=cleaned_question,
                answer="I don't have enough information in the provided documentation to answer this question.",
                citations=[],
                model=self.model_name,
                latency_ms=0.0,
                grounded=False,
                retrieved_chunks_count=0,
            )

        with logfire.span("LLM Answer Generation", model=self.model_name, chunks=len(retrieved_chunks)):
            # 1. Format context with token budgeting and build citations
            context_str, citations = format_context(retrieved_chunks)

            # 2. Build delimited user prompt
            user_prompt = build_user_prompt(cleaned_question, context_str)

            # 3. Call Groq API
            client = self.get_client()
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )

            elapsed_ms = round((time.time() - t0) * 1000, 2)

            # 4. Extract completion text & token usage
            choice = response.choices[0]
            answer_text = choice.message.content.strip()

            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

            # 5. Check groundedness heuristic
            not_enough_info_indicators = [
                "don't have enough information",
                "do not have enough information",
                "context does not contain",
                "not mentioned in the provided",
            ]
            is_grounded = not any(ind in answer_text.lower() for ind in not_enough_info_indicators)

            result = GeneratedAnswer(
                question=cleaned_question,
                answer=answer_text,
                citations=citations,
                model=self.model_name,
                latency_ms=elapsed_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                grounded=is_grounded,
                retrieved_chunks_count=len(retrieved_chunks),
            )

            logfire.info(
                f"Generated answer in {elapsed_ms}ms (tokens: {total_tokens}, grounded: {is_grounded})"
            )
            return result


class QuestionAnswerEngine:
    """End-to-End Enterprise RAG Engine linking Semantic Retrieval to LLM Generation."""

    def __init__(
        self,
        retriever: Optional[SemanticRetriever] = None,
        generator: Optional[GroqGenerator] = None,
    ):
        self.retriever = retriever or SemanticRetriever()
        self.generator = generator or GroqGenerator()

    def ask(
        self,
        query: str,
        top_k: int = 5,
        min_score: Optional[float] = None,
        source_type: Optional[Union[str, List[str]]] = None,
        source_file: Optional[Union[str, List[str]]] = None,
        temperature: float = 0.1,
    ) -> GeneratedAnswer:
        """Executes full RAG workflow:

        1. Semantic retrieval from Qdrant with pre-filters and score threshold.
        2. Short-circuit guard: if no chunks found, returns immediately.
        3. Factual generation via Groq Llama 3.3 with citation mapping.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty")

        cleaned_query = query.strip()
        t0 = time.time()

        with logfire.span("RAG Question Answering", query=cleaned_query, top_k=top_k):
            # 1. Retrieve relevant chunks
            retrieval_result = self.retriever.retrieve(
                query=cleaned_query,
                top_k=top_k,
                score_threshold=min_score,
                source_type=source_type,
                source_file=source_file,
            )

            # 2. Short-circuit if retrieval is empty
            if not retrieval_result.chunks or retrieval_result.total_found == 0:
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                logfire.info(f"No relevant chunks found for '{cleaned_query}'. Short-circuiting generation.")
                return GeneratedAnswer(
                    question=cleaned_query,
                    answer="I don't have enough information in the provided documentation to answer this question.",
                    citations=[],
                    model=self.generator.model_name,
                    latency_ms=elapsed_ms,
                    grounded=False,
                    retrieved_chunks_count=0,
                )

            # 3. Generate answer
            answer = self.generator.generate(
                question=cleaned_query,
                retrieved_chunks=retrieval_result.chunks,
                temperature=temperature,
            )

            # Total pipeline latency
            answer.latency_ms = round((time.time() - t0) * 1000, 2)
            return answer


# Singleton default engine instance
qa_engine = QuestionAnswerEngine()


def ask(
    query: str,
    top_k: int = 5,
    min_score: Optional[float] = None,
    source_type: Optional[Union[str, List[str]]] = None,
    source_file: Optional[Union[str, List[str]]] = None,
) -> GeneratedAnswer:
    """Convenience function for global end-to-end question answering."""
    return qa_engine.ask(
        query=query,
        top_k=top_k,
        min_score=min_score,
        source_type=source_type,
        source_file=source_file,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-End Enterprise RAG Question Answering")
    parser.add_argument("--query", type=str, required=True, help="Natural language question to ask")
    parser.add_argument("--top-k", type=int, default=5, help="Number of context chunks to retrieve")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum similarity score cutoff")
    parser.add_argument("--source-type", type=str, default=None, help="Filter by document source_type")
    parser.add_argument("--source-file", type=str, default=None, help="Filter by document source_file")
    parser.add_argument("--model", type=str, default=None, help="Custom Groq model name")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")

    args = parser.parse_args()

    custom_generator = GroqGenerator(model_name=args.model)
    engine = QuestionAnswerEngine(generator=custom_generator)

    answer_res = engine.ask(
        query=args.query,
        top_k=args.top_k,
        min_score=args.min_score,
        source_type=args.source_type,
        source_file=args.source_file,
    )

    if args.json:
        print(json.dumps(answer_res.to_dict(), indent=2))
    else:
        print("\n" + "=" * 60)
        print(f"QUESTION: {answer_res.question}")
        print("=" * 60)
        print(f"\n{answer_res.answer}\n")
        print("-" * 60)
        print(f"Model: {answer_res.model} | Latency: {answer_res.latency_ms}ms | Grounded: {answer_res.grounded}")
        print(f"Tokens: prompt={answer_res.prompt_tokens}, completion={answer_res.completion_tokens}, total={answer_res.total_tokens}")
        print("\nCITATIONS:")
        if answer_res.citations:
            for c in answer_res.citations:
                print(f"  {c.marker} {c.source_file} (Chunk {c.chunk_index}, Score: {c.score:.3f})")
                print(f"      Path: {c.source_path}")
        else:
            print("  (No citations)")
        print("=" * 60 + "\n")
