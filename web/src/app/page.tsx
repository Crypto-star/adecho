"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

export default function Landing() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !url) return;
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append("landing_url", url);
    fd.append("ad", file);
    try {
      const r = await fetch("/api/sessions", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const { session_id } = await r.json();
      router.push(`/session/${session_id}`);
    } catch (e: any) {
      setErr(e.message || "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center px-6">
      <div className="w-full max-w-2xl">
        <div className="mb-10 text-center">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs text-white/60 ring-1 ring-white/10">
            <span className="size-1.5 rounded-full bg-[var(--accent)]" />
            Troopod — AI landing personalizer
          </div>
          <h1 className="mt-6 text-4xl font-semibold tracking-tight sm:text-5xl">
            Match your landing page to the ad <br /> that brought them in.
          </h1>
          <p className="mt-4 text-white/60">
            Upload an ad. Paste your landing URL. We enhance the page in-place — same layout, same
            assets, CRO-tuned and personalized.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="rounded-2xl bg-white/[0.03] p-4 ring-1 ring-white/10 backdrop-blur"
        >
          <input
            type="url"
            required
            placeholder="https://your-landing-page.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="w-full rounded-xl bg-white/5 px-4 py-3 text-sm outline-none ring-1 ring-white/10 placeholder-white/30 focus:ring-[var(--accent)]"
          />

          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="flex-1 rounded-xl bg-white/5 px-4 py-3 text-left text-sm text-white/70 ring-1 ring-white/10 hover:bg-white/10"
            >
              {file ? `📎 ${file.name}` : "Upload ad creative (PNG/JPG)…"}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <button
              type="submit"
              disabled={busy || !file || !url}
              className="rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy ? "Working…" : "Personalize →"}
            </button>
          </div>
          {err && <p className="mt-3 text-sm text-red-400">{err}</p>}
        </form>

        <p className="mt-6 text-center text-xs text-white/40">
          No-code friendly · Powered by a multi-agent pipeline (Agno · Gemini · GPT · Exa)
        </p>
      </div>
    </main>
  );
}
