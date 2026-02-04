from __future__ import annotations

import os


def otel_enabled() -> bool:
    return os.getenv("RAG_OTEL_ENABLED", "0").lower() in {"1", "true", "yes"}


def otel_service_name() -> str:
    return os.getenv("OTEL_SERVICE_NAME", "rag-backend")


def otel_otlp_endpoint() -> str | None:
    return os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")


def configure_otel(app) -> None:
    if not otel_enabled():
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "OpenTelemetry is not installed. Install with '.[observability]'."
        ) from exc

    resource = Resource.create({SERVICE_NAME: otel_service_name()})
    provider = TracerProvider(resource=resource)

    endpoint = otel_otlp_endpoint()
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint)
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
