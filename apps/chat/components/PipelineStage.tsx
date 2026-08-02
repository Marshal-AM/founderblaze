"use client";

import type { CSSProperties } from "react";
import {
  Scan,
  PenLine,
  Film,
  Rocket,
  Globe,
  Check,
  Code2,
  Sparkles,
  Download,
  FileArchive,
  FileText,
  Image as ImageIcon,
  Play,
  AlertTriangle,
  Circle,
} from "lucide-react";
import type { Artifact, JobStatus, PipelineStep, ServicePersona } from "../lib/types";
import { currentStepLabel, stepIndexForJob } from "../lib/services";

const ICONS = {
  scan: Scan,
  pen: PenLine,
  film: Film,
  rocket: Rocket,
  globe: Globe,
  check: Check,
  code: Code2,
  spark: Sparkles,
} as const;

type StepState = "pending" | "active" | "done" | "failed";

function StepRow({
  step,
  index,
  state,
  accent,
  isLast,
}: {
  step: PipelineStep;
  index: number;
  state: StepState;
  accent: string;
  isLast: boolean;
}) {
  const Icon = ICONS[step.icon] ?? Sparkles;
  const statusText =
    state === "pending"
      ? "Waiting"
      : state === "active"
        ? "In progress"
        : state === "failed"
          ? "Failed"
          : "Done";

  return (
    <li
      className={`pipeline-step pipeline-step--${state}`}
      style={
        {
          "--step-accent": accent,
        } as CSSProperties
      }
    >
      <div className="pipeline-rail" aria-hidden>
        <span className="pipeline-rail-node">
          {state === "done" ? (
            <Check className="pipeline-rail-check" strokeWidth={2.5} />
          ) : state === "failed" ? (
            <AlertTriangle className="pipeline-rail-check" strokeWidth={2.5} />
          ) : state === "active" ? (
            <Circle className="pipeline-rail-active" strokeWidth={2.5} />
          ) : (
            <span className="pipeline-rail-pending" />
          )}
        </span>
        {!isLast ? <span className="pipeline-rail-line" /> : null}
      </div>

      <div className="pipeline-step-body">
        <div className="pipeline-step-head">
          <span className="pipeline-step-icon" aria-hidden>
            <Icon className="h-4 w-4" strokeWidth={1.75} />
          </span>
          <div className="pipeline-step-copy">
            <p className="pipeline-step-label">
              <span className="pipeline-step-num">
                {String(index + 1).padStart(2, "0")}
              </span>
              {step.label}
            </p>
            <p className="pipeline-step-detail">{step.detail}</p>
          </div>
          <span className="pipeline-step-status">{statusText}</span>
        </div>
      </div>
    </li>
  );
}

function artifactKind(a: Artifact): "video" | "pdf" | "zip" | "image" | "file" {
  const mime = (a.mime_type || "").toLowerCase();
  const type = (a.type || "").toLowerCase();
  const url = (a.url || a.object_key || "").toLowerCase();
  if (
    mime.includes("video") ||
    type === "video" ||
    url.endsWith(".mp4") ||
    url.endsWith(".webm")
  ) {
    return "video";
  }
  if (
    mime.includes("pdf") ||
    type.includes("pdf") ||
    type.includes("report") ||
    url.endsWith(".pdf")
  ) {
    return "pdf";
  }
  if (
    mime.includes("zip") ||
    type.includes("zip") ||
    type.includes("kit") ||
    url.endsWith(".zip")
  ) {
    return "zip";
  }
  if (
    mime.startsWith("image/") ||
    type.includes("chart") ||
    type.includes("image") ||
    /\.(png|jpe?g|webp|gif)$/.test(url)
  ) {
    return "image";
  }
  return "file";
}

function ArtifactCard({ artifact, accent }: { artifact: Artifact; accent: string }) {
  const kind = artifactKind(artifact);
  const url = artifact.url || undefined;
  const title =
    artifact.type?.replace(/_/g, " ") ||
    artifact.object_key?.split("/").pop() ||
    "Deliverable";

  return (
    <div
      className="artifact-card"
      style={{
        borderColor: `color-mix(in oklab, ${accent} 28%, transparent)`,
      }}
    >
      <div className="artifact-head">
        <p className="artifact-title">{title}</p>
        <span
          className="artifact-pill"
          style={{
            background: `color-mix(in oklab, ${accent} 14%, transparent)`,
            color: accent,
          }}
        >
          Ready
        </span>
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="artifact-dl"
            style={{
              background: `color-mix(in oklab, ${accent} 12%, transparent)`,
              color: accent,
            }}
            title="Download"
          >
            <Download className="h-4 w-4" />
          </a>
        ) : null}
      </div>

      <div className="artifact-body">
        {kind === "video" && url ? (
          <div className="artifact-media">
            <video src={url} controls playsInline preload="metadata" />
          </div>
        ) : null}

        {kind === "pdf" && url ? (
          <div className="artifact-pdf">
            <iframe src={`${url}#toolbar=0`} title={title} />
            <div className="artifact-pdf-fallback">
              <FileText className="h-5 w-5" style={{ color: accent }} />
              <a href={url} target="_blank" rel="noreferrer">
                Open PDF in new tab
              </a>
            </div>
          </div>
        ) : null}

        {kind === "image" && url ? (
          <div className="artifact-media">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={title} />
          </div>
        ) : null}

        {kind === "zip" ? (
          <div
            className="artifact-zip"
            style={{
              background: `color-mix(in oklab, ${accent} 8%, transparent)`,
              borderColor: `color-mix(in oklab, ${accent} 25%, transparent)`,
            }}
          >
            <FileArchive className="h-10 w-10" style={{ color: accent }} />
            <div>
              <p className="artifact-zip-title">Downloadable package</p>
              <p className="artifact-zip-cap">
                ZIP archive ready — logos, assets, and kit files.
              </p>
              {url ? (
                <a href={url} className="artifact-zip-btn" style={{ background: accent }}>
                  Download ZIP
                </a>
              ) : null}
            </div>
          </div>
        ) : null}

        {kind === "file" ? (
          <div className="artifact-file">
            <ImageIcon className="h-5 w-5" style={{ color: accent }} />
            <span>{artifact.mime_type || "file"}</span>
            {url ? (
              <a href={url} target="_blank" rel="noreferrer">
                Open
              </a>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="artifact-meta">
        {artifact.mime_type ? <span>{artifact.mime_type}</span> : null}
        {artifact.object_key ? (
          <span className="mono truncate">{artifact.object_key}</span>
        ) : null}
      </div>
    </div>
  );
}

export function PipelineStage({
  persona,
  prompt,
  job,
  artifacts,
}: {
  persona: ServicePersona;
  prompt?: string;
  job: JobStatus | JobRefLike;
  artifacts?: Artifact[];
}) {
  const accent = persona.accent;
  const status = job.status || "queued";
  const step = "step" in job ? job.step : null;
  const done = status === "completed";
  const failed = status === "failed" || status === "cancelled";
  const stepIndex = stepIndexForJob(persona, step, status);
  const statusLabel = currentStepLabel(persona, step, status);
  const deliverables =
    artifacts && artifacts.length > 0
      ? artifacts
      : (job as JobStatus).artifacts || [];

  return (
    <section className="pipeline-stage">
      <header className="pipeline-head">
        <div className="pipeline-titles">
          <p className="pipeline-name">{persona.title}</p>
          {prompt ? (
            <p className="pipeline-prompt-inline" title={prompt}>
              {prompt}
            </p>
          ) : null}
        </div>
        <div className="pipeline-status-chip">
          <span
            className={
              done || failed ? "live-dot live-dot--static" : "live-dot"
            }
            style={{
              background: failed
                ? "var(--destructive)"
                : done
                  ? "var(--ember)"
                  : accent,
            }}
          />
          <span>{statusLabel}</span>
        </div>
      </header>

      <ol className="pipeline-steps">
        {persona.steps.map((s, i) => {
          let state: StepState = "pending";
          if (failed && i === stepIndex) state = "failed";
          else if (done || i < stepIndex) state = "done";
          else if (i === stepIndex) state = "active";
          return (
            <StepRow
              key={s.key}
              step={s}
              index={i}
              state={state}
              accent={accent}
              isLast={i === persona.steps.length - 1}
            />
          );
        })}
      </ol>

      {failed ? (
        <div className="pipeline-error">
          <AlertTriangle className="h-4 w-4" />
          <span>{(job as JobStatus).error || "Pipeline failed"}</span>
        </div>
      ) : null}

      {done && deliverables.length > 0 ? (
        <div className="pipeline-artifacts">
          {deliverables
            .filter((a) => a.url || a.type)
            .map((a, i) => (
              <ArtifactCard key={`${a.type}-${i}`} artifact={a} accent={accent} />
            ))}
        </div>
      ) : null}

      {done && deliverables.length === 0 ? (
        <div className="pipeline-empty-done">
          <Play className="h-4 w-4" style={{ color: accent }} />
          Pipeline finished — no downloadable artifacts returned.
        </div>
      ) : null}
    </section>
  );
}

type JobRefLike = {
  job_id?: string;
  service?: string;
  status?: string;
  step?: string | null;
  error?: string | null;
  artifacts?: Artifact[];
};
