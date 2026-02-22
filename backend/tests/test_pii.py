from __future__ import annotations

import pytest

from app import pii as pii_module
from app.pii import RedactionResult, merge_redaction_counts, redact_text


def test_redact_text_masks_multiple_identifiers(monkeypatch) -> None:
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    source = (
        "Email mario.rossi@example.com, "
        "IBAN IT60X0542811101000000123456, "
        "CF RSSMRA85T10A562S."
    )

    result = redact_text(source)

    assert result.applied is True
    assert "mario.rossi@example.com" not in result.text
    assert "IT60X0542811101000000123456" not in result.text
    assert "RSSMRA85T10A562S" not in result.text
    assert result.counts["email"] == 1
    assert result.counts["iban"] == 1
    assert result.counts["tax_id_it"] == 1
    assert result.backend == "regex"


def test_redact_text_disabled_returns_original(monkeypatch) -> None:
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "0")
    source = "Email mario.rossi@example.com"

    result = redact_text(source)

    assert result.applied is False
    assert result.text == source
    assert result.counts == {}
    assert result.backend == "regex"


def test_merge_redaction_counts_combines_entities() -> None:
    merged = merge_redaction_counts(
        {"email": 1, "iban": 1},
        {"email": 2},
        {},
    )

    assert merged == {"email": 3, "iban": 1}


def test_redact_text_falls_back_to_regex_if_presidio_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    monkeypatch.setenv("RAG_PII_BACKEND", "presidio")
    monkeypatch.setattr("app.pii._redact_with_presidio", lambda _value: None)

    result = redact_text("Email mario.rossi@example.com")

    assert result.backend == "regex"
    assert result.applied is True
    assert result.counts == {"email": 1}


def test_redact_text_uses_presidio_when_available(monkeypatch) -> None:
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    monkeypatch.setenv("RAG_PII_BACKEND", "presidio")
    monkeypatch.setattr(
        "app.pii._redact_with_presidio",
        lambda _value: RedactionResult(
            text="[REDACTED_EMAIL]",
            counts={"email": 1},
            applied=True,
            backend="presidio",
        ),
    )

    result = redact_text("Email mario.rossi@example.com")

    assert result.backend == "presidio"
    assert result.applied is True
    assert result.counts == {"email": 1}


def test_redact_text_with_presidio_runtime_when_installed(monkeypatch) -> None:
    pytest.importorskip("presidio_analyzer")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    monkeypatch.setenv("RAG_PII_BACKEND", "presidio")

    result = redact_text("Email mario.rossi@example.com")

    assert result.backend == "presidio"
    assert result.applied is True
    assert result.counts.get("email") == 1
    assert "[REDACTED_EMAIL]" in result.text


def test_unknown_backend_warning_is_logged_once_per_value(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    monkeypatch.setenv("RAG_PII_BACKEND", "unexpected_backend")
    monkeypatch.setenv("RAG_PII_REDACTION_ENABLED", "1")
    monkeypatch.setattr(pii_module, "logger", _FakeLogger())
    pii_module._resolve_pii_backend.cache_clear()

    redact_text("first")
    redact_text("second")
    redact_text("third", enabled=False)

    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "pii_unknown_backend"
    assert payload["extra"]["configured_backend"] == "unexpected_backend"
    assert payload["extra"]["fallback_backend"] == "regex"


def test_presidio_unavailable_warning_contains_error_message_and_debug_flag(monkeypatch) -> None:
    warnings = []

    class _FakeLogger:
        def warning(self, message: str, **kwargs) -> None:
            warnings.append((message, kwargs))

    monkeypatch.setenv("RAG_PII_DEBUG", "1")
    monkeypatch.setattr(pii_module, "logger", _FakeLogger())
    monkeypatch.setattr(pii_module, "_PRESIDIO_UNAVAILABLE_WARNING_EMITTED", False)

    pii_module._log_presidio_unavailable(RuntimeError("missing runtime deps"))

    assert len(warnings) == 1
    message, payload = warnings[0]
    assert message == "pii_presidio_backend_unavailable"
    assert payload["exc_info"] is True
    assert payload["extra"]["error_type"] == "RuntimeError"
    assert payload["extra"]["error_message"] == "missing runtime deps"
    assert payload["extra"]["fallback_backend"] == "regex"
