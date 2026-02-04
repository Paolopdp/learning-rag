"use client";

import type { FormEvent } from "react";
import { useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type IngestResponse = {
  documents: number;
  chunks: number;
};

type Workspace = {
  id: string;
  name: string;
  role: string;
};

type Citation = {
  chunk_id: string;
  source_title: string;
  source_url: string | null;
  score: number;
  excerpt: string;
};

type QueryResponse = {
  answer: string;
  citations: Citation[];
};

type AuthResponse = {
  access_token: string;
  token_type: string;
  user: { id: string; email: string };
  default_workspace: Workspace | null;
};

const SAMPLE_QUESTIONS = [
  {
    label: "SPID",
    text: "Che cos’è SPID e a cosa serve?",
  },
  {
    label: "PagoPA",
    text: "Qual è il ruolo di PagoPA?",
  },
  {
    label: "ANPR + CAD",
    text: "Cos’è l’ANPR e come si collega al Codice dell’Amministrazione Digitale?",
  },
];

export default function Home() {
  const [email, setEmail] = useState("demo@local");
  const [password, setPassword] = useState("change-me-now");
  const [token, setToken] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [question, setQuestion] = useState(SAMPLE_QUESTIONS[0].text);
  const [topK, setTopK] = useState(3);
  const [ingestInfo, setIngestInfo] = useState<IngestResponse | null>(null);
  const [answer, setAnswer] = useState<string>("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busyIngest, setBusyIngest] = useState(false);
  const [busyQuery, setBusyQuery] = useState(false);
  const [busyAuth, setBusyAuth] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReady = useMemo(
    () => Boolean(ingestInfo && ingestInfo.chunks > 0),
    [ingestInfo]
  );

  const canUseApi = Boolean(token && workspace);

  const fetchWorkspaces = async (accessToken: string) => {
    const response = await fetch(`${API_BASE}/workspaces`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!response.ok) {
      throw new Error("Failed to load workspaces.");
    }
    const payload = (await response.json()) as Workspace[];
    setWorkspaces(payload);
    setWorkspace(payload[0] ?? null);
  };

  const handleRegister = async () => {
    setBusyAuth(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Registration failed.");
      }
      const payload = (await response.json()) as AuthResponse;
      setToken(payload.access_token);
      setWorkspace(payload.default_workspace);
      setWorkspaces(payload.default_workspace ? [payload.default_workspace] : []);
      setIngestInfo(null);
      setAnswer("");
      setCitations([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setBusyAuth(false);
    }
  };

  const handleLogin = async () => {
    setBusyAuth(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Login failed.");
      }
      const payload = (await response.json()) as AuthResponse;
      setToken(payload.access_token);
      if (payload.default_workspace) {
        setWorkspace(payload.default_workspace);
        setWorkspaces([payload.default_workspace]);
      } else {
        await fetchWorkspaces(payload.access_token);
      }
      setIngestInfo(null);
      setAnswer("");
      setCitations([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setBusyAuth(false);
    }
  };

  const handleIngest = async () => {
    if (!token || !workspace) {
      setError("Login first to ingest data.");
      return;
    }
    setBusyIngest(true);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspace.id}/ingest/demo`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Ingest failed.");
      }
      const payload = (await response.json()) as IngestResponse;
      setIngestInfo(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed.");
    } finally {
      setBusyIngest(false);
    }
  };

  const handleQuery = async (event: FormEvent) => {
    event.preventDefault();
    if (!token || !workspace) {
      setError("Login first to run a query.");
      return;
    }
    setBusyQuery(true);
    setError(null);
    setAnswer("");
    setCitations([]);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspace.id}/query`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ question, top_k: topK }),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Query failed.");
      }
      const payload = (await response.json()) as QueryResponse;
      setAnswer(payload.answer);
      setCitations(payload.citations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed.");
    } finally {
      setBusyQuery(false);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_#ffffff,_#f6f2ed_45%,_#efe6db_100%)] text-[15px]">
      <div className="mx-auto max-w-6xl px-6 pb-16 pt-10">
        <header className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm uppercase tracking-[0.25em] text-[color:var(--muted)]">
                Governance-First RAG Demo
              </p>
              <h1 className="mt-3 text-4xl font-semibold text-[color:var(--foreground)] md:text-5xl">
                <span className="font-[var(--font-serif)]">
                  RAG Assistant
                </span>{" "}
                <span className="text-[color:var(--accent)]">
                  with citations
                </span>
              </h1>
              <p className="mt-4 max-w-2xl text-base text-[color:var(--muted)]">
                A minimal end-to-end slice: ingest a demo dataset, ask a
                question, and get a grounded answer with cited sources.
              </p>
            </div>
            <div className="rounded-full border border-[color:var(--border)] bg-white px-4 py-2 text-xs text-[color:var(--muted)] shadow-sm">
              API: {API_BASE}
            </div>
          </div>
          {error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}
        </header>

        <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <section className="rounded-3xl border border-[color:var(--border)] bg-white/80 p-6 shadow-sm backdrop-blur">
            <h2 className="text-lg font-semibold text-[color:var(--foreground)]">
              1. Authenticate
            </h2>
            <p className="mt-2 text-sm text-[color:var(--muted)]">
              Create an account or log in to a workspace.
            </p>
            <div className="mt-4 space-y-3">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="mt-2 w-full rounded-2xl border border-[color:var(--border)] px-4 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="mt-2 w-full rounded-2xl border border-[color:var(--border)] px-4 py-2 text-sm"
                />
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handleRegister}
                  disabled={busyAuth}
                  className="rounded-full bg-[color:var(--accent)] px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[color:var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busyAuth ? "Working..." : "Register"}
                </button>
                <button
                  type="button"
                  onClick={handleLogin}
                  disabled={busyAuth}
                  className="rounded-full border border-[color:var(--border)] px-4 py-2 text-sm font-semibold text-[color:var(--foreground)]"
                >
                  Login
                </button>
              </div>
              <div className="rounded-2xl bg-[#f9f4ee] px-4 py-3 text-sm text-[color:var(--muted)]">
                <div className="flex items-center justify-between">
                  <span>Status</span>
                  <span className="font-semibold text-[color:var(--foreground)]">
                    {token ? "Authenticated" : "Not authenticated"}
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span>Workspace</span>
                  <span className="font-semibold text-[color:var(--foreground)]">
                    {workspace?.name ?? "—"}
                  </span>
                </div>
              </div>
              {workspaces.length > 1 ? (
                <div className="text-xs text-[color:var(--muted)]">
                  {workspaces.length} workspaces available.
                </div>
              ) : null}
            </div>
          </section>

          <section className="rounded-3xl border border-[color:var(--border)] bg-white/90 p-6 shadow-sm backdrop-blur">
            <h2 className="text-lg font-semibold text-[color:var(--foreground)]">
              2. Ingest + Query
            </h2>
            <p className="mt-2 text-sm text-[color:var(--muted)]">
              Italian Wikipedia excerpts (SPID, PagoPA, ANPR, CAD).
            </p>
            <button
              type="button"
              onClick={handleIngest}
              disabled={busyIngest || !canUseApi}
              className="mt-4 inline-flex items-center gap-2 rounded-full bg-[color:var(--accent)] px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[color:var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busyIngest ? "Ingesting..." : "Ingest Demo"}
            </button>
            <div className="mt-4 grid gap-3 rounded-2xl bg-[#f9f4ee] px-4 py-4 text-sm text-[color:var(--muted)]">
              <div className="flex items-center justify-between">
                <span>Documents</span>
                <span className="font-semibold text-[color:var(--foreground)]">
                  {ingestInfo?.documents ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Chunks</span>
                <span className="font-semibold text-[color:var(--foreground)]">
                  {ingestInfo?.chunks ?? "—"}
                </span>
              </div>
              <div className="text-xs">
                Status:{" "}
                <span className="font-semibold text-[color:var(--foreground)]">
                  {isReady ? "Ready" : "Not ingested"}
                </span>
              </div>
            </div>
            <form onSubmit={handleQuery} className="mt-4 space-y-4">
              <label className="block text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                Question
              </label>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                rows={3}
                className="w-full rounded-2xl border border-[color:var(--border)] bg-white px-4 py-3 text-sm text-[color:var(--foreground)] shadow-sm focus:border-[color:var(--accent)] focus:outline-none"
              />
              <div className="flex flex-wrap items-center gap-3">
                {SAMPLE_QUESTIONS.map((sample) => (
                  <button
                    key={sample.label}
                    type="button"
                    onClick={() => setQuestion(sample.text)}
                    className="rounded-full border border-[color:var(--border)] px-3 py-1 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--foreground)]"
                  >
                    {sample.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <label className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  Top K
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                  className="w-20 rounded-full border border-[color:var(--border)] px-3 py-1 text-sm"
                />
                <button
                  type="submit"
                  disabled={busyQuery || !canUseApi}
                  className="ml-auto inline-flex items-center gap-2 rounded-full bg-[color:var(--foreground)] px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-black/90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busyQuery ? "Querying..." : "Run Query"}
                </button>
              </div>
            </form>

            <div className="mt-8 space-y-6">
              <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  Answer
                </p>
                <p className="mt-2 text-sm text-[color:var(--foreground)]">
                  {answer || "Run a query to see a response."}
                </p>
              </div>

              <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  Citations
                </p>
                {citations.length === 0 ? (
                  <p className="mt-2 text-sm text-[color:var(--muted)]">
                    Citations will appear here after a query.
                  </p>
                ) : (
                  <div className="mt-3 grid gap-3">
                    {citations.map((citation) => (
                      <div
                        key={citation.chunk_id}
                        className="rounded-2xl border border-[color:var(--border)] bg-[#fcfaf7] p-3 text-sm"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold text-[color:var(--foreground)]">
                            {citation.source_title}
                          </span>
                          <span className="rounded-full bg-white px-2 py-1 text-xs text-[color:var(--muted)]">
                            score {citation.score.toFixed(3)}
                          </span>
                        </div>
                        <p className="mt-2 text-[13px] text-[color:var(--muted)]">
                          {citation.excerpt}
                        </p>
                        {citation.source_url ? (
                          <a
                            className="mt-2 inline-flex text-xs text-[color:var(--accent)] hover:underline"
                            href={citation.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Source
                          </a>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
