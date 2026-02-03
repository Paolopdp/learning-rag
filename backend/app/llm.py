from __future__ import annotations

import os
from functools import lru_cache

from app.models import Chunk


def llm_enabled() -> bool:
    return os.getenv("RAG_USE_LLM", "0").lower() in {"1", "true", "yes"}


def llm_model_path() -> str | None:
    return os.getenv("RAG_LLM_MODEL_PATH")


def llm_chat_format() -> str | None:
    return os.getenv("RAG_LLM_CHAT_FORMAT")


def llm_ctx() -> int:
    return int(os.getenv("RAG_LLM_CTX", "2048"))


def llm_threads() -> int:
    return int(os.getenv("RAG_LLM_THREADS", "4"))


def llm_gpu_layers() -> int:
    return int(os.getenv("RAG_LLM_GPU_LAYERS", "0"))


@lru_cache(maxsize=1)
def get_llm():
    try:
        from llama_cpp import Llama
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "llama-cpp-python is not installed. Install with '.[llm]'."
        ) from exc

    model_path = llm_model_path()
    if not model_path:
        raise RuntimeError("RAG_LLM_MODEL_PATH is not set.")

    return Llama(
        model_path=model_path,
        n_ctx=llm_ctx(),
        n_threads=llm_threads(),
        n_gpu_layers=llm_gpu_layers(),
        chat_format=llm_chat_format(),
    )


def build_context(chunks: list[Chunk]) -> str:
    lines: list[str] = []
    for chunk in chunks:
        source = chunk.source_title
        lines.append(f"[Fonte: {source}] {chunk.content}")
    return "\n\n".join(lines)


def generate_answer(question: str, chunks: list[Chunk]) -> str:
    context = build_context(chunks)
    system_prompt = (
        "Sei un assistente. Rispondi in italiano usando solo il contesto fornito. "
        "Se l'informazione non e' nel contesto, di' che non lo sai."
    )
    user_prompt = (
        "Domanda: " + question + "\n\n" + "Contesto:\n" + context
    )

    llm = get_llm()
    try:
        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception:
        prompt = system_prompt + "\n\n" + user_prompt + "\n\nRisposta:"
        response = llm.create_completion(prompt=prompt, max_tokens=256)
        return response["choices"][0]["text"].strip()
