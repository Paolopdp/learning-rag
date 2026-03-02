# Operations Playbook

This document provides concrete observability queries and alert examples for abuse-control events emitted by:
- `POST /workspaces/{workspace_id}/query`
- `POST /auth/register`
- `POST /auth/login`
- `POST /workspaces/{workspace_id}/ingest`

## Logging Backend Assumption
- Examples use Grafana Loki + LogQL.
- The backend must emit structured JSON logs (default Python logger with `extra` fields captured by your log pipeline).

## Events To Monitor
- `query_rate_limit_near_exhaustion`
- `query_rate_limit_denied`
- `query_rate_limit_redis_init_failed_fallback_memory`
- `query_rate_limit_redis_unavailable_fallback_memory`
- `query_rate_limit_redis_recovered`
- `auth_login_rate_limit_near_exhaustion`
- `auth_login_rate_limit_denied`
- `auth_login_rate_limit_redis_init_failed_fallback_memory`
- `auth_login_rate_limit_redis_unavailable_fallback_memory`
- `auth_login_rate_limit_redis_recovered`
- `auth_register_rate_limit_near_exhaustion`
- `auth_register_rate_limit_denied`
- `auth_register_rate_limit_redis_init_failed_fallback_memory`
- `auth_register_rate_limit_redis_unavailable_fallback_memory`
- `auth_register_rate_limit_redis_recovered`
- `ingest_rate_limit_near_exhaustion`
- `ingest_rate_limit_denied`
- `ingest_rate_limit_redis_init_failed_fallback_memory`
- `ingest_rate_limit_redis_unavailable_fallback_memory`
- `ingest_rate_limit_redis_recovered`

## LogQL Queries

Count denied requests by workspace in the last 5 minutes:
```logql
sum by (workspace_id) (
  count_over_time(
    {service="rag-backend"} |= "query_rate_limit_denied" [5m]
  )
)
```

Count near-exhaustion events by role in the last 5 minutes:
```logql
sum by (access_role) (
  count_over_time(
    {service="rag-backend"} |= "query_rate_limit_near_exhaustion" [5m]
  )
)
```

Detect fallback activation (Redis unavailable/init failure):
```logql
sum(
  count_over_time(
    {service="rag-backend"} |= "query_rate_limit_redis_unavailable_fallback_memory" [10m]
  )
) + sum(
  count_over_time(
    {service="rag-backend"} |= "query_rate_limit_redis_init_failed_fallback_memory" [10m]
  )
)
```

Track fallback recovery:
```logql
sum(
  count_over_time(
    {service="rag-backend"} |= "query_rate_limit_redis_recovered" [10m]
  )
)
```

Count denied login attempts by source IP in the last 5 minutes:
```logql
sum by (client_ip) (
  count_over_time(
    {service="rag-backend"} |= "auth_login_rate_limit_denied" [5m]
  )
)
```

Count denied registration attempts by source IP in the last 5 minutes:
```logql
sum by (client_ip) (
  count_over_time(
    {service="rag-backend"} |= "auth_register_rate_limit_denied" [5m]
  )
)
```

Count denied login attempts by scope (`ip` vs `subject`) in the last 5 minutes:
```logql
sum by (rate_limit_scope) (
  count_over_time(
    {service="rag-backend"} |= "auth_login_rate_limit_denied" [5m]
  )
)
```

Count denied upload-ingest requests by workspace in the last 5 minutes:
```logql
sum by (workspace_id) (
  count_over_time(
    {service="rag-backend"} |= "ingest_rate_limit_denied" [5m]
  )
)
```

Count denied upload-ingest requests by user in the last 5 minutes:
```logql
sum by (user_id) (
  count_over_time(
    {service="rag-backend"} |= "ingest_rate_limit_denied" [5m]
  )
)
```

## Suggested Dashboard Panels
- `Rate-limit denied / 5m` (stack by `workspace_id`).
- `Rate-limit near-exhaustion / 5m` (stack by `access_role`).
- `Fallback mode active` (single stat from fallback-activation query).
- `Fallback recoveries / 10m` (single stat).
- `Top workspaces by deny volume` (table with `workspace_id`, count).
- `Top client IPs by login deny volume` (table with `client_ip`, count).
- `Top client IPs by register deny volume` (table with `client_ip`, count).
- `Top users by ingest deny volume` (table with `user_id`, count).

## Suggested Alerts
- `ThrottleDeniedSpike`: trigger if denied count for one workspace exceeds a threshold in 5m.
- `ThrottleBudgetPressure`: trigger if near-exhaustion volume grows for consecutive windows.
- `ThrottleBackendFallback`: trigger immediately on fallback activation.
- `ThrottleBackendRecovered`: resolve incident when recovery events appear and fallback events stop.
- `AuthLoginDeniedSpike`: trigger if login deny count from one IP exceeds threshold in 5m.
- `AuthLoginBudgetPressure`: trigger when `auth_login_rate_limit_near_exhaustion` grows quickly.
- `AuthRegisterDeniedSpike`: trigger if register deny count from one IP exceeds threshold in 5m.
- `AuthRegisterBudgetPressure`: trigger when `auth_register_rate_limit_near_exhaustion` grows quickly.
- `IngestDeniedSpike`: trigger if ingest deny count for one workspace or user exceeds threshold in 5m.
- `IngestBudgetPressure`: trigger when `ingest_rate_limit_near_exhaustion` grows quickly.

## Tuning Workflow
- Confirm affected scope (`workspace_id`, `access_role`) from logs.
- Confirm backend mode (`redis` vs fallback memory).
- If fallback is active, restore Redis first.
- If Redis is healthy, tune member limit first:
  - `RAG_QUERY_RATE_LIMIT_REQUESTS_MEMBER`
  - then `RAG_QUERY_RATE_LIMIT_REQUESTS_ADMIN`
  - then global `RAG_QUERY_RATE_LIMIT_REQUESTS`
- Tune login protection separately:
  - `RAG_AUTH_LOGIN_RATE_LIMIT_REQUESTS`
  - `RAG_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- Tune register protection separately:
  - `RAG_AUTH_REGISTER_RATE_LIMIT_REQUESTS`
  - `RAG_AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS`
- Tune upload-ingest protection separately:
  - `RAG_INGEST_RATE_LIMIT_REQUESTS_WORKSPACE`
  - `RAG_INGEST_RATE_LIMIT_REQUESTS_USER`
  - `RAG_INGEST_RATE_LIMIT_WINDOW_SECONDS`
- Keep `RAG_QUERY_RATE_LIMIT_WINDOW_SECONDS` stable unless traffic profile requires a larger window.

Related references:
- `docs/governance.md` (policy + runbook baseline)
- `README.md` (environment variables)
