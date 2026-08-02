"use client";

import { useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Download,
  FileArchive,
  FileText,
  Film,
  Image as ImageIcon,
  X,
} from "lucide-react";
import type { Artifact } from "../lib/types";

type AssetRow = {
  id: string;
  job_id: string;
  service: string;
  prompt: string | null;
  status: string;
  artifacts: Artifact[];
  created_at: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
};

function kindOf(a: Artifact): "video" | "pdf" | "zip" | "image" | "file" {
  const mime = (a.mime_type || "").toLowerCase();
  const type = (a.type || "").toLowerCase();
  const url = (a.url || a.object_key || "").toLowerCase();
  if (mime.includes("video") || type === "video" || url.endsWith(".mp4")) return "video";
  if (mime.includes("pdf") || type.includes("pdf") || type.includes("report") || url.endsWith(".pdf"))
    return "pdf";
  if (mime.includes("zip") || type.includes("zip") || type.includes("kit") || url.endsWith(".zip"))
    return "zip";
  if (mime.startsWith("image/") || type.includes("chart") || type.includes("image") || /\.(png|jpe?g|webp|gif)$/.test(url))
    return "image";
  return "file";
}

function KindIcon({ kind }: { kind: ReturnType<typeof kindOf> }) {
  if (kind === "video") return <Film className="h-4 w-4" />;
  if (kind === "pdf") return <FileText className="h-4 w-4" />;
  if (kind === "zip") return <FileArchive className="h-4 w-4" />;
  if (kind === "image") return <ImageIcon className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
}

export function AssetsDialog({ open, onClose }: Props) {
  const { data: session } = useSession();
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<"all" | "video" | "pdf" | "zip" | "image">("all");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !session?.user) return;
    let cancelled = false;
    setLoading(true);
    fetch("/api/assets")
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setAssets(d.assets || []);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, session?.user]);

  const flat = useMemo(() => {
    const items: Array<{
      key: string;
      service: string;
      prompt: string | null;
      status: string;
      created_at: string;
      artifact: Artifact;
      kind: ReturnType<typeof kindOf>;
    }> = [];
    for (const row of assets) {
      for (let i = 0; i < (row.artifacts || []).length; i++) {
        const a = row.artifacts[i];
        if (!a?.url && !a?.type) continue;
        const kind = kindOf(a);
        if (filter !== "all" && kind !== filter) continue;
        items.push({
          key: `${row.id}-${i}`,
          service: row.service,
          prompt: row.prompt,
          status: row.status,
          created_at: row.created_at,
          artifact: a,
          kind,
        });
      }
    }
    return items;
  }, [assets, filter]);

  if (!open) return null;

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="assets-dialog-title"
      onClick={onClose}
    >
      <div
        className="assets-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="assets-dialog-head">
          <div>
            <p className="panel-kicker">Library</p>
            <h2 id="assets-dialog-title" className="modal-title">
              My assets
            </h2>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {!session?.user ? (
          <div className="assets-guest">
            <p className="sidebar-muted">
              Sign in to save and browse your generated assets.
            </p>
          </div>
        ) : (
          <>
            <div className="assets-filters">
              {(["all", "video", "pdf", "zip", "image"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={filter === f ? "filter-chip active" : "filter-chip"}
                  onClick={() => setFilter(f)}
                >
                  {f}
                </button>
              ))}
            </div>

            <div className="assets-grid">
              {loading ? <p className="sidebar-muted">Loading…</p> : null}
              {!loading && flat.length === 0 ? (
                <p className="sidebar-muted">
                  No assets yet. Run a pipeline to fill this library.
                </p>
              ) : null}
              {flat.map((item) => (
                <article key={item.key} className="asset-tile">
                  <div className="asset-tile-head">
                    <span className="asset-kind">
                      <KindIcon kind={item.kind} />
                      {item.kind}
                    </span>
                    <span className="mono asset-service">{item.service}</span>
                  </div>

                  {item.kind === "video" && item.artifact.url ? (
                    <video src={item.artifact.url} controls preload="metadata" />
                  ) : null}
                  {item.kind === "image" && item.artifact.url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.artifact.url} alt={item.artifact.type || "image"} />
                  ) : null}
                  {item.kind === "pdf" && item.artifact.url ? (
                    <div className="asset-pdf-preview">
                      <FileText className="h-8 w-8" />
                      <a href={item.artifact.url} target="_blank" rel="noreferrer">
                        Open PDF
                      </a>
                    </div>
                  ) : null}
                  {item.kind === "zip" ? (
                    <div className="asset-pdf-preview">
                      <FileArchive className="h-8 w-8" />
                      <span>ZIP package</span>
                    </div>
                  ) : null}
                  {item.kind === "file" ? (
                    <div className="asset-pdf-preview">
                      <span>{item.artifact.type || "file"}</span>
                    </div>
                  ) : null}

                  <p className="asset-prompt">{item.prompt || "—"}</p>
                  <div className="asset-tile-foot">
                    <span className="mono">
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                    {item.artifact.url ? (
                      <a
                        href={item.artifact.url}
                        target="_blank"
                        rel="noreferrer"
                        className="icon-btn"
                        title="Download"
                      >
                        <Download className="h-4 w-4" />
                      </a>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
