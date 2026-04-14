"use client";

import { use, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

type SessionRow = {
  id: string;
  status: string;
  current_version: number;
  landing_url: string;
  error: string | null;
};

type ChatMsg = { id: number | string; role: "user" | "assistant"; content: string; created_at?: string };

// Iframe / <img> content is large (scraped HTML, screenshots). On Vercel,
// routing these through the `/api/*` rewrite can hit edge payload limits
// and truncate the response. In production we talk to Railway directly;
// locally we continue to use the rewrite (which points at localhost:8000).
const API_DIRECT = process.env.NEXT_PUBLIC_API_BASE_URL || "";
function apiUrl(path: string): string {
  return API_DIRECT ? `${API_DIRECT}${path}` : `/api${path}`;
}

// Merge helper: accepts optimistic items (id starting with "tmp-") and
// de-dupes by id. Real rows from the DB replace matching tmp rows by content.
function mergeByIdOrTempKey(a: ChatMsg[], b: ChatMsg[]): ChatMsg[] {
  const byId = new Map<string, ChatMsg>();
  for (const m of [...a, ...b]) byId.set(String(m.id), m);
  // Remove any tmp- entry whose content matches a non-tmp entry.
  const real = [...byId.values()].filter((m) => !String(m.id).startsWith("tmp-"));
  const stillOptimistic = [...byId.values()].filter(
    (m) => String(m.id).startsWith("tmp-") &&
           !real.some((r) => r.role === m.role && r.content === m.content)
  );
  return [...real, ...stillOptimistic].sort((x, y) =>
    (x.created_at || "").localeCompare(y.created_at || "")
  );
}

export default function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [session, setSession] = useState<SessionRow | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [view, setView] = useState<"personalized" | "original">("personalized");

  // Poll + realtime session status
  useEffect(() => {
    let cancelled = false;
    async function load() {
      const r = await fetch(`/api/sessions/${id}`);
      if (r.ok && !cancelled) setSession(await r.json());
    }
    load();
    const t = setInterval(load, 2500);
    return () => { cancelled = true; clearInterval(t); };
  }, [id]);

  // Realtime chat subscription (+ poll fallback in case Realtime isn't
  // configured). We also log errors so we can see in the console if the
  // supabase client is null or the anon RLS blocks reads.
  useEffect(() => {
    if (!supabase) {
      console.error("[chat] Supabase client is null — check NEXT_PUBLIC_SUPABASE_* env vars");
      return;
    }
    const client = supabase;
    let cancelled = false;

    async function reload() {
      const { data, error } = await client
        .from("chat_messages").select("id,role,content,created_at")
        .eq("session_id", id).order("created_at", { ascending: true });
      if (error) { console.error("[chat] load error", error); return; }
      if (!cancelled && data) {
        // Merge rather than replace — preserves any optimistic items not yet in DB.
        setMessages((prev) => mergeByIdOrTempKey(prev, data as ChatMsg[]));
      }
    }
    reload();
    const pollId = setInterval(reload, 3000);  // fallback every 3s

    const ch = client
      .channel(`chat:${id}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "chat_messages",
          filter: `session_id=eq.${id}` },
        (p) => setMessages((m) => mergeByIdOrTempKey(m, [p.new as ChatMsg]))
      )
      .subscribe((status) => console.info("[chat] realtime", status));

    return () => { cancelled = true; clearInterval(pollId); client.removeChannel(ch); };
  }, [id]);

  // Iframe `src` is driven entirely by JSX below — `view` and `version` are
  // reactive so React re-renders the correct `src` without imperative updates.
  const version = session?.current_version ?? 0;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg) return;
    setInput("");
    // Optimistic append — user sees their message instantly regardless of
    // Realtime latency or RLS quirks. Gets deduped by mergeByIdOrTempKey
    // when the real row arrives.
    const tmpId = `tmp-${Date.now()}`;
    setMessages((m) => [...m, {
      id: tmpId, role: "user", content: msg,
      created_at: new Date().toISOString(),
    }]);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: id, message: msg }),
      });
      if (!r.ok) {
        const body = await r.text().catch(() => "");
        console.error("[chat] /api/chat failed", r.status, body);
        setMessages((m) => [...m, {
          id: `tmp-err-${Date.now()}`, role: "assistant",
          content: `(Couldn't queue that — ${r.status}. Check API logs.)`,
          created_at: new Date().toISOString(),
        }]);
      }
    } catch (err) {
      console.error("[chat] /api/chat threw", err);
    }
  }

  const ready = session?.status === "ready";
  const failed = session?.status === "failed";

  return (
    <main className="grid h-screen grid-cols-[380px_1fr]">
      {/* Left: chat */}
      <aside className="flex h-full flex-col border-r border-white/10">
        <header className="flex items-center justify-between px-4 py-3 text-sm">
          <div className="font-medium">Refine</div>
          <StatusPill status={session?.status} />
        </header>
        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
          {messages.length === 0 && (
            <p className="text-white/40">
              Ask for tweaks: <em>“make the CTA louder”</em>,
              <em> “emphasize the 50% discount near the hero”</em>…
            </p>
          )}
          {messages.map((m) => (
            <div key={m.id}
              className={`rounded-xl px-3 py-2 ${m.role === "user"
                ? "ml-auto max-w-[80%] bg-white/10"
                : "mr-auto max-w-[85%] bg-[var(--accent)]/15 ring-1 ring-[var(--accent)]/30"
                }`}>{m.content}</div>
          ))}
        </div>
        <form onSubmit={send} className="flex gap-2 border-t border-white/10 p-3">
          <input
            value={input} onChange={(e) => setInput(e.target.value)}
            placeholder={ready ? "Refine the page…" : "Waiting for first render…"}
            disabled={!ready}
            className="flex-1 rounded-lg bg-white/5 px-3 py-2 text-sm outline-none ring-1 ring-white/10 placeholder-white/30 disabled:opacity-50"
          />
          <button disabled={!ready} className="rounded-lg bg-[var(--accent)] px-4 text-sm disabled:opacity-40">
            Send
          </button>
        </form>
      </aside>

      {/* Right: render */}
      <section className="flex h-full flex-col">
        <header className="flex items-center gap-3 border-b border-white/10 px-4 py-2 text-sm">
          <div className="inline-flex rounded-lg bg-white/5 p-1 ring-1 ring-white/10">
            <button onClick={() => setView("original")}
              className={`rounded-md px-3 py-1 ${view === "original" ? "bg-white/10" : ""}`}>Original</button>
            <button onClick={() => setView("personalized")}
              className={`rounded-md px-3 py-1 ${view === "personalized" ? "bg-white/10" : ""}`}>Personalized</button>
          </div>
          <div className="ml-auto truncate text-white/40">
            {session?.landing_url} · v{version}
          </div>
        </header>

        <div className="relative flex-1 bg-white">
          {!ready && !failed && (
            <div className="absolute inset-0 grid place-items-center bg-white/95 text-black">
              <Spinner status={session?.status} />
            </div>
          )}
          {failed && (
            <div className="absolute inset-0 grid place-items-center bg-red-50 p-8 text-red-700">
              <div className="max-w-md text-center">
                <h2 className="text-lg font-semibold">Pipeline failed</h2>
                <p className="mt-2 text-sm">{session?.error ?? "Unknown error."}</p>
              </div>
            </div>
          )}
          {view === "original" && ready ? (
            <img
              key={`orig-${id}`}
              src={apiUrl(`/render/${id}/original.png`)}
              alt="Original landing page"
              className="h-full w-full object-contain object-top bg-white"
            />
          ) : (
            <iframe
              key={`${view}-${version}`}
              title="Rendered landing"
              className="h-full w-full"
              src={ready ? apiUrl(`/render/${id}?v=${version}`) : "about:blank"}
            />
          )}
        </div>
      </section>
    </main>
  );
}

function StatusPill({ status }: { status?: string }) {
  const map: Record<string, string> = {
    created: "bg-white/10 text-white/70",
    extracting: "bg-sky-500/20 text-sky-300",
    strategizing: "bg-violet-500/20 text-violet-300",
    building: "bg-amber-500/20 text-amber-300",
    verifying: "bg-emerald-500/20 text-emerald-300",
    ready: "bg-emerald-500/25 text-emerald-200",
    failed: "bg-red-500/25 text-red-200",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ring-white/10 ${map[status ?? ""] ?? "bg-white/5 text-white/60"}`}>
      {status ?? "…"}
    </span>
  );
}

function Spinner({ status }: { status?: string }) {
  const text: Record<string, string> = {
    created: "Queued…",
    extracting: "Reading your ad and scraping the page…",
    strategizing: "Planning the personalization…",
    building: "Patching the page…",
    verifying: "Verifying the result…",
  };
  return (
    <div className="text-center">
      <div className="mx-auto size-8 animate-spin rounded-full border-2 border-black/20 border-t-black" />
      <p className="mt-3 text-sm text-black/70">{text[status ?? ""] ?? "Working…"}</p>
    </div>
  );
}
