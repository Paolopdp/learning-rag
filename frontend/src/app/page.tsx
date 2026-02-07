"use client";

import type { FormEvent } from "react";
import { useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const DOCUMENT_PAGE_SIZE = 50;

type IngestResponse = {
  documents: number;
  chunks: number;
};

type Workspace = {
  id: string;
  name: string;
  role: string;
};

type WorkspaceRole = "admin" | "member";

type WorkspaceMember = {
  user_id: string;
  email: string;
  role: WorkspaceRole;
  created_at: string;
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

type AuditEvent = {
  id: string;
  workspace_id: string;
  user_id: string | null;
  action: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type ClassificationLabel =
  | "public"
  | "internal"
  | "confidential"
  | "restricted";

type DocumentInventoryItem = {
  id: string;
  title: string;
  source_url: string | null;
  license: string | null;
  accessed_at: string | null;
  classification_label: ClassificationLabel;
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

const CLASSIFICATION_OPTIONS: { value: ClassificationLabel; label: string }[] = [
  { value: "internal", label: "Internal" },
  { value: "public", label: "Public" },
  { value: "confidential", label: "Confidential" },
  { value: "restricted", label: "Restricted" },
];

export default function Home() {
  const [email, setEmail] = useState("demo@local");
  const [password, setPassword] = useState("change-me-now");
  const [currentUser, setCurrentUser] = useState<{ id: string; email: string } | null>(
    null
  );
  const [token, setToken] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<WorkspaceRole>("member");
  const [question, setQuestion] = useState(SAMPLE_QUESTIONS[0].text);
  const [topK, setTopK] = useState(3);
  const [ingestInfo, setIngestInfo] = useState<IngestResponse | null>(null);
  const [answer, setAnswer] = useState<string>("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [documents, setDocuments] = useState<DocumentInventoryItem[]>([]);
  const [documentOffset, setDocumentOffset] = useState(0);
  const [hasMoreDocuments, setHasMoreDocuments] = useState(false);
  const [busyIngest, setBusyIngest] = useState(false);
  const [busyQuery, setBusyQuery] = useState(false);
  const [busyAuth, setBusyAuth] = useState(false);
  const [busyAudit, setBusyAudit] = useState(false);
  const [busyDocuments, setBusyDocuments] = useState(false);
  const [busyMembers, setBusyMembers] = useState(false);
  const [busyMemberAction, setBusyMemberAction] = useState<"add" | "update" | "remove" | null>(
    null
  );
  const [busyDocumentUpdateId, setBusyDocumentUpdateId] = useState<string | null>(
    null
  );
  const [busyMemberMutationId, setBusyMemberMutationId] = useState<string | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  const formatAuditTimestamp = (value: string) =>
    new Date(value).toLocaleString();
  const formatAccessDate = (value: string | null) =>
    value ? new Date(`${value}T00:00:00`).toLocaleDateString() : "—";
  const formatMemberTimestamp = (value: string) =>
    new Date(value).toLocaleString();
  const safeExternalUrl = (value: string | null): URL | null => {
    if (!value) {
      return null;
    }
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  };

  const isReady = useMemo(
    () => Boolean(ingestInfo && ingestInfo.chunks > 0),
    [ingestInfo]
  );

  const canUseApi = Boolean(token && workspace);

  const fetchWorkspaces = async (
    accessToken: string,
    preferredWorkspaceId: string | null = null
  ) => {
    const response = await fetch(`${API_BASE}/workspaces`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!response.ok) {
      throw new Error("Failed to load workspaces.");
    }
    const payload = (await response.json()) as Workspace[];
    setWorkspaces(payload);
    const selected =
      payload.find((candidate) => candidate.id === preferredWorkspaceId) ??
      payload[0] ??
      null;
    setWorkspace(selected);
    return selected;
  };

  const loadAudit = async (
    accessToken: string | null = token,
    workspaceId: string | null = workspace?.id ?? null
  ) => {
    if (!accessToken || !workspaceId) {
      setAuditEvents([]);
      return;
    }
    setBusyAudit(true);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspaceId}/audit?limit=20`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Audit log request failed.");
      }
      const payload = (await response.json()) as AuditEvent[];
      setAuditEvents(payload);
    } catch (err) {
      setAuditEvents([]);
      setError(err instanceof Error ? err.message : "Audit log request failed.");
    } finally {
      setBusyAudit(false);
    }
  };

  const loadDocuments = async (
    accessToken: string | null = token,
    workspaceId: string | null = workspace?.id ?? null,
    options: { offset?: number; append?: boolean } = {}
  ) => {
    const nextOffset = options.offset ?? 0;
    const append = options.append ?? false;
    if (!accessToken || !workspaceId) {
      setDocuments([]);
      setDocumentOffset(0);
      setHasMoreDocuments(false);
      return;
    }
    setBusyDocuments(true);
    try {
      const params = new URLSearchParams({
        limit: String(DOCUMENT_PAGE_SIZE),
        offset: String(nextOffset),
      });
      const response = await fetch(
        `${API_BASE}/workspaces/${workspaceId}/documents?${params.toString()}`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Document inventory request failed.");
      }
      const payload = (await response.json()) as DocumentInventoryItem[];
      if (append) {
        setDocuments((current) => {
          const merged = [...current];
          for (const item of payload) {
            if (!merged.some((existing) => existing.id === item.id)) {
              merged.push(item);
            }
          }
          return merged;
        });
      } else {
        setDocuments(payload);
      }
      setDocumentOffset(nextOffset);
      setHasMoreDocuments(payload.length === DOCUMENT_PAGE_SIZE);
    } catch (err) {
      if (!append) {
        setDocuments([]);
      }
      setError(
        err instanceof Error ? err.message : "Document inventory request failed."
      );
    } finally {
      setBusyDocuments(false);
    }
  };

  const loadMembers = async (
    accessToken: string | null = token,
    workspaceId: string | null = workspace?.id ?? null
  ) => {
    if (!accessToken || !workspaceId) {
      setMembers([]);
      return;
    }
    setBusyMembers(true);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspaceId}/members`,
        {
          headers: { Authorization: `Bearer ${accessToken}` },
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Workspace members request failed.");
      }
      const payload = (await response.json()) as WorkspaceMember[];
      setMembers(payload);
    } catch (err) {
      setMembers([]);
      setError(
        err instanceof Error ? err.message : "Workspace members request failed."
      );
    } finally {
      setBusyMembers(false);
    }
  };

  const addWorkspaceMember = async () => {
    if (!token || !workspace) {
      setError("Login first to manage workspace members.");
      return;
    }
    if (!memberEmail.trim()) {
      setError("Member email is required.");
      return;
    }
    setBusyMemberAction("add");
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspace.id}/members`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            email: memberEmail.trim(),
            role: memberRole,
          }),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Adding workspace member failed.");
      }
      setMemberEmail("");
      setMemberRole("member");
      await loadMembers(token, workspace.id);
      await loadAudit(token, workspace.id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Adding workspace member failed."
      );
    } finally {
      setBusyMemberAction(null);
    }
  };

  const updateWorkspaceMemberRole = async (
    userId: string,
    role: WorkspaceRole
  ) => {
    if (!token || !workspace) {
      setError("Login first to manage workspace members.");
      return;
    }
    setBusyMemberAction("update");
    setBusyMemberMutationId(userId);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspace.id}/members/${userId}/role`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ role }),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Updating member role failed.");
      }
      await loadMembers(token, workspace.id);
      await loadAudit(token, workspace.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Updating member role failed.");
    } finally {
      setBusyMemberAction(null);
      setBusyMemberMutationId(null);
    }
  };

  const removeWorkspaceMember = async (userId: string) => {
    if (!token || !workspace) {
      setError("Login first to manage workspace members.");
      return;
    }
    setBusyMemberAction("remove");
    setBusyMemberMutationId(userId);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspace.id}/members/${userId}`,
        {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Removing workspace member failed.");
      }
      await loadMembers(token, workspace.id);
      await loadAudit(token, workspace.id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Removing workspace member failed."
      );
    } finally {
      setBusyMemberAction(null);
      setBusyMemberMutationId(null);
    }
  };

  const updateDocumentClassification = async (
    documentId: string,
    classificationLabel: ClassificationLabel
  ) => {
    if (!token || !workspace) {
      setError("Login first to update document classification.");
      return;
    }
    setBusyDocumentUpdateId(documentId);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/workspaces/${workspace.id}/documents/${documentId}/classification`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            classification_label: classificationLabel,
          }),
        }
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.detail ?? "Classification update failed.");
      }
      const payload = (await response.json()) as DocumentInventoryItem;
      setDocuments((current) =>
        current.map((document) =>
          document.id === payload.id ? payload : document
        )
      );
      await loadAudit(token, workspace.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Classification update failed.");
    } finally {
      setBusyDocumentUpdateId(null);
    }
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
      setCurrentUser(payload.user);
      setIngestInfo(null);
      setAnswer("");
      setCitations([]);
      setAuditEvents([]);
      setDocuments([]);
      setDocumentOffset(0);
      setHasMoreDocuments(false);
      setMembers([]);
      const selected = await fetchWorkspaces(
        payload.access_token,
        payload.default_workspace?.id ?? null
      );
      if (selected) {
        await loadAudit(payload.access_token, selected.id);
        await loadDocuments(payload.access_token, selected.id, {
          offset: 0,
        });
        await loadMembers(payload.access_token, selected.id);
      }
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
      setCurrentUser(payload.user);
      setAuditEvents([]);
      setDocuments([]);
      setDocumentOffset(0);
      setHasMoreDocuments(false);
      setMembers([]);
      const selected = await fetchWorkspaces(
        payload.access_token,
        payload.default_workspace?.id ?? null
      );
      if (selected) {
        await loadAudit(payload.access_token, selected.id);
        await loadDocuments(payload.access_token, selected.id, {
          offset: 0,
        });
        await loadMembers(payload.access_token, selected.id);
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
      await loadAudit(token, workspace.id);
      await loadDocuments(token, workspace.id, { offset: 0 });
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
      await loadAudit(token, workspace.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed.");
    } finally {
      setBusyQuery(false);
    }
  };

  const handleWorkspaceSelect = async (workspaceId: string) => {
    if (!token) {
      return;
    }
    const selected = workspaces.find((candidate) => candidate.id === workspaceId);
    if (!selected) {
      return;
    }
    setWorkspace(selected);
    setError(null);
    setIngestInfo(null);
    setAnswer("");
    setCitations([]);
    await loadAudit(token, selected.id);
    await loadDocuments(token, selected.id, { offset: 0 });
    await loadMembers(token, selected.id);
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
              {token && workspaces.length > 0 ? (
                <div>
                  <label className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    Active Workspace
                  </label>
                  <select
                    value={workspace?.id ?? ""}
                    onChange={(event) => handleWorkspaceSelect(event.target.value)}
                    className="mt-2 w-full rounded-2xl border border-[color:var(--border)] bg-white px-4 py-2 text-sm"
                  >
                    {workspaces.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.name} ({candidate.role})
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
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
                    {citations.map((citation) => {
                      const safeSourceUrl = safeExternalUrl(citation.source_url);
                      return (
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
                          {safeSourceUrl ? (
                            <a
                              className="mt-2 inline-flex text-xs text-[color:var(--accent)] hover:underline"
                              href={safeSourceUrl.href}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              Source ({safeSourceUrl.host})
                            </a>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    Document Inventory
                  </p>
                  <button
                    type="button"
                    onClick={() => loadDocuments(token, workspace?.id ?? null, { offset: 0 })}
                    disabled={!canUseApi || busyDocuments}
                    className="rounded-full border border-[color:var(--border)] px-3 py-1 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busyDocuments ? "Loading..." : "Refresh"}
                  </button>
                </div>
                {documents.length === 0 ? (
                  <p className="mt-3 text-sm text-[color:var(--muted)]">
                    No documents yet. Run ingest to populate inventory.
                  </p>
                ) : (
                  <div className="mt-3 grid gap-3">
                    {documents.map((document) => {
                      const safeSourceUrl = safeExternalUrl(document.source_url);
                      return (
                        <div
                          key={document.id}
                          className="rounded-2xl border border-[color:var(--border)] bg-[#fcfaf7] p-3 text-sm"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-semibold text-[color:var(--foreground)]">
                              {document.title}
                            </span>
                            <select
                              value={document.classification_label}
                              onChange={(event) =>
                                updateDocumentClassification(
                                  document.id,
                                  event.target.value as ClassificationLabel
                                )
                              }
                              disabled={busyDocumentUpdateId === document.id}
                              className="rounded-full border border-[color:var(--border)] bg-white px-3 py-1 text-xs text-[color:var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {CLASSIFICATION_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="mt-2 text-xs text-[color:var(--muted)]">
                            Accessed: {formatAccessDate(document.accessed_at)}
                          </div>
                          <div className="mt-1 text-xs text-[color:var(--muted)]">
                            License: {document.license ?? "—"}
                          </div>
                          {safeSourceUrl ? (
                            <a
                              className="mt-2 inline-flex text-xs text-[color:var(--accent)] hover:underline"
                              href={safeSourceUrl.href}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              Source ({safeSourceUrl.host})
                            </a>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
                {hasMoreDocuments ? (
                  <button
                    type="button"
                    onClick={() =>
                      loadDocuments(token, workspace?.id ?? null, {
                        offset: documentOffset + DOCUMENT_PAGE_SIZE,
                        append: true,
                      })
                    }
                    disabled={!canUseApi || busyDocuments}
                    className="mt-3 rounded-full border border-[color:var(--border)] bg-white px-4 py-1 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busyDocuments ? "Loading..." : "Load more"}
                  </button>
                ) : null}
              </div>

              <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    Workspace Members
                  </p>
                  <button
                    type="button"
                    onClick={() => loadMembers()}
                    disabled={!canUseApi || busyMembers}
                    className="rounded-full border border-[color:var(--border)] px-3 py-1 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busyMembers ? "Loading..." : "Refresh"}
                  </button>
                </div>
                <div className="mt-3 grid gap-2 rounded-2xl border border-[color:var(--border)] bg-[#fcfaf7] p-3">
                  <label className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    Add Member
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="email"
                      value={memberEmail}
                      onChange={(event) => setMemberEmail(event.target.value)}
                      placeholder="member@domain"
                      className="min-w-[220px] flex-1 rounded-full border border-[color:var(--border)] bg-white px-3 py-1 text-sm"
                    />
                    <select
                      value={memberRole}
                      onChange={(event) =>
                        setMemberRole(event.target.value as WorkspaceRole)
                      }
                      className="rounded-full border border-[color:var(--border)] bg-white px-3 py-1 text-sm"
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button
                      type="button"
                      onClick={addWorkspaceMember}
                      disabled={!canUseApi || busyMemberAction === "add"}
                      className="rounded-full bg-[color:var(--foreground)] px-4 py-1 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {busyMemberAction === "add" ? "Adding..." : "Add"}
                    </button>
                  </div>
                </div>
                {members.length === 0 ? (
                  <p className="mt-3 text-sm text-[color:var(--muted)]">
                    No members found for this workspace.
                  </p>
                ) : (
                  <div className="mt-3 grid gap-3">
                    {members.map((member) => (
                      <div
                        key={member.user_id}
                        className="rounded-2xl border border-[color:var(--border)] bg-[#fcfaf7] p-3 text-sm"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold text-[color:var(--foreground)]">
                            {member.email}
                          </span>
                          <span className="text-xs text-[color:var(--muted)]">
                            Added {formatMemberTimestamp(member.created_at)}
                          </span>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <select
                            value={member.role}
                            onChange={(event) =>
                              updateWorkspaceMemberRole(
                                member.user_id,
                                event.target.value as WorkspaceRole
                              )
                            }
                            disabled={busyMemberMutationId === member.user_id}
                            className="rounded-full border border-[color:var(--border)] bg-white px-3 py-1 text-xs text-[color:var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <option value="member">Member</option>
                            <option value="admin">Admin</option>
                          </select>
                          <button
                            type="button"
                            onClick={() => removeWorkspaceMember(member.user_id)}
                            disabled={
                              busyMemberMutationId === member.user_id ||
                              currentUser?.id === member.user_id
                            }
                            className="rounded-full border border-red-200 bg-white px-3 py-1 text-xs text-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-[color:var(--border)] bg-white px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    Audit Log
                  </p>
                  <button
                    type="button"
                    onClick={() => loadAudit()}
                    disabled={!canUseApi || busyAudit}
                    className="rounded-full border border-[color:var(--border)] px-3 py-1 text-xs text-[color:var(--muted)] transition hover:border-[color:var(--accent)] hover:text-[color:var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busyAudit ? "Loading..." : "Refresh"}
                  </button>
                </div>
                {auditEvents.length === 0 ? (
                  <p className="mt-3 text-sm text-[color:var(--muted)]">
                    No audit events yet. Ingest or query to generate entries.
                  </p>
                ) : (
                  <div className="mt-3 grid gap-3">
                    {auditEvents.map((event) => (
                      <div
                        key={event.id}
                        className="rounded-2xl border border-[color:var(--border)] bg-[#fcfaf7] p-3 text-sm"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold text-[color:var(--foreground)]">
                            {event.action}
                          </span>
                          <span className="text-xs text-[color:var(--muted)]">
                            {formatAuditTimestamp(event.created_at)}
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-[color:var(--muted)]">
                          User: {event.user_id ?? "system"}
                        </div>
                        <pre className="mt-2 whitespace-pre-wrap text-[12px] text-[color:var(--muted)]">
                          {JSON.stringify(event.payload, null, 2)}
                        </pre>
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
