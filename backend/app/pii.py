from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_ENABLED_VALUES = {"1", "true", "yes"}
_PII_BACKENDS = {"regex", "presidio"}
_DEFAULT_BACKEND = "regex"
logger = logging.getLogger(__name__)
_PRESIDIO_UNAVAILABLE_WARNING_EMITTED = False

_EMAIL_REGEX = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
_IBAN_REGEX = r"\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b"
_IT_TAX_CODE_REGEX = r"\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b"
_CREDIT_CARD_REGEX = r"\b(?:\d[ -]?){13,19}\b"

_REPLACEMENTS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "email",
        re.compile(_EMAIL_REGEX),
        "[REDACTED_EMAIL]",
    ),
    (
        "iban",
        re.compile(_IBAN_REGEX),
        "[REDACTED_IBAN]",
    ),
    (
        "tax_id_it",
        re.compile(_IT_TAX_CODE_REGEX),
        "[REDACTED_TAX_ID]",
    ),
    (
        "credit_card",
        re.compile(_CREDIT_CARD_REGEX),
        "[REDACTED_CREDIT_CARD]",
    ),
)

_PRESIDIO_ENTITY_CONFIG: dict[str, tuple[str, str, str]] = {
    "EMAIL_ADDRESS": ("email", "[REDACTED_EMAIL]", _EMAIL_REGEX),
    "IBAN_CODE": ("iban", "[REDACTED_IBAN]", _IBAN_REGEX),
    "IT_FISCAL_CODE": ("tax_id_it", "[REDACTED_TAX_ID]", _IT_TAX_CODE_REGEX),
    "CREDIT_CARD": ("credit_card", "[REDACTED_CREDIT_CARD]", _CREDIT_CARD_REGEX),
}


def pii_redaction_enabled() -> bool:
    return os.getenv("RAG_PII_REDACTION_ENABLED", "1").lower() in _ENABLED_VALUES


def pii_ingest_redaction_enabled() -> bool:
    return os.getenv("RAG_PII_INGEST_REDACTION_ENABLED", "1").lower() in _ENABLED_VALUES


def pii_debug_enabled() -> bool:
    return os.getenv("RAG_PII_DEBUG", "0").lower() in _ENABLED_VALUES


def pii_backend() -> str:
    configured = os.getenv("RAG_PII_BACKEND", _DEFAULT_BACKEND).strip().lower()
    return _resolve_pii_backend(configured)


@lru_cache(maxsize=16)
def _resolve_pii_backend(configured: str) -> str:
    if configured in _PII_BACKENDS:
        return configured
    logger.warning(
        "pii_unknown_backend",
        extra={
            "configured_backend": configured,
            "fallback_backend": _DEFAULT_BACKEND,
        },
    )
    return _DEFAULT_BACKEND


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]
    applied: bool
    backend: str


def redact_text(
    value: str,
    *,
    enabled: bool | None = None,
    backend: str | None = None,
) -> RedactionResult:
    enabled_value = pii_redaction_enabled() if enabled is None else enabled
    resolved_backend = backend if backend in _PII_BACKENDS else pii_backend()
    if not value:
        return RedactionResult(text=value, counts={}, applied=False, backend=resolved_backend)
    if not enabled_value:
        return RedactionResult(text=value, counts={}, applied=False, backend=resolved_backend)

    if resolved_backend == "presidio":
        presidio_result = _redact_with_presidio(value)
        if presidio_result is not None:
            return presidio_result

    return _redact_with_regex(value)


def merge_redaction_counts(*counts: dict[str, int]) -> dict[str, int]:
    merged: Counter[str] = Counter()
    for count_map in counts:
        merged.update(count_map)
    return dict(merged)


def _redact_with_regex(value: str) -> RedactionResult:
    redacted = value
    counts: Counter[str] = Counter()
    for key, pattern, replacement in _REPLACEMENTS:
        redacted, replaced = pattern.subn(replacement, redacted)
        if replaced:
            counts[key] += replaced
    return RedactionResult(
        text=redacted,
        counts=dict(counts),
        applied=bool(counts),
        backend="regex",
    )


@lru_cache(maxsize=1)
def _load_presidio_analyzer() -> Any:
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry

    registry = RecognizerRegistry()
    for entity_type, (_key, _replacement, regex) in _PRESIDIO_ENTITY_CONFIG.items():
        registry.add_recognizer(
            PatternRecognizer(
                supported_entity=entity_type,
                patterns=[Pattern(name=f"{entity_type.lower()}_pattern", regex=regex, score=0.7)],
                supported_language="en",
            )
        )

    return AnalyzerEngine(
        registry=registry,
        nlp_engine=None,
        supported_languages=["en"],
    )


def _redact_with_presidio(value: str) -> RedactionResult | None:
    try:
        analyzer = _load_presidio_analyzer()
    except Exception as exc:  # pragma: no cover - depends on optional runtime setup
        _log_presidio_unavailable(exc)
        return None

    try:
        raw_results = analyzer.analyze(
            text=value,
            entities=list(_PRESIDIO_ENTITY_CONFIG.keys()),
            language="en",
        )
    except Exception as exc:  # pragma: no cover - depends on optional runtime setup
        _log_presidio_unavailable(exc)
        return None

    if not raw_results:
        return RedactionResult(text=value, counts={}, applied=False, backend="presidio")

    filtered = [
        result
        for result in raw_results
        if result.entity_type in _PRESIDIO_ENTITY_CONFIG
    ]
    selected = _select_non_overlapping_results(filtered)
    if not selected:
        return RedactionResult(text=value, counts={}, applied=False, backend="presidio")

    redacted_parts: list[str] = []
    counts: Counter[str] = Counter()
    cursor = 0
    for result in selected:
        start = int(result.start)
        end = int(result.end)
        if start < cursor:
            continue
        redacted_parts.append(value[cursor:start])
        key, replacement, _regex = _PRESIDIO_ENTITY_CONFIG[result.entity_type]
        redacted_parts.append(replacement)
        counts[key] += 1
        cursor = end

    redacted_parts.append(value[cursor:])
    return RedactionResult(
        text="".join(redacted_parts),
        counts=dict(counts),
        applied=bool(counts),
        backend="presidio",
    )


def _select_non_overlapping_results(results: list[Any]) -> list[Any]:
    ordered = sorted(
        results,
        key=lambda item: (int(item.start), -(int(item.end) - int(item.start))),
    )
    selected: list[Any] = []
    last_end = -1
    for item in ordered:
        start = int(item.start)
        end = int(item.end)
        if start < last_end:
            continue
        selected.append(item)
        last_end = end
    return selected


def _log_presidio_unavailable(exc: Exception) -> None:
    global _PRESIDIO_UNAVAILABLE_WARNING_EMITTED
    if _PRESIDIO_UNAVAILABLE_WARNING_EMITTED:
        return
    _PRESIDIO_UNAVAILABLE_WARNING_EMITTED = True
    logger.warning(
        "pii_presidio_backend_unavailable",
        exc_info=pii_debug_enabled(),
        extra={
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "fallback_backend": "regex",
        },
    )
