import type { ServicePersona } from "./types";

/**
 * FounderBlaze service → progress UI copy + Genblaze provider step names.
 * Provider strings must match the `name = "..."` on each SyncProvider.
 */
export const SERVICE_PERSONAS: Record<string, ServicePersona> = {
  "promo-video": {
    title: "Promo Video",
    accent: "var(--ember)",
    service: "promo-video",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "research",
        label: "Researching your product",
        detail: "Crawling pages and capturing screenshots",
        icon: "scan",
        providers: ["promo-video-research"],
      },
      {
        key: "script",
        label: "Writing the script",
        detail: "Hook, proof points, and shot list",
        icon: "pen",
        providers: ["promo-video-script"],
      },
      {
        key: "generate",
        label: "Generating the video",
        detail: "Rendering scenes with synced audio",
        icon: "film",
        providers: ["promo-video-seedance", "promo-video-concat"],
      },
      {
        key: "publish",
        label: "Publishing deliverable",
        detail: "Uploading the final MP4",
        icon: "rocket",
        providers: ["promo-video-persist", "promo-video-emit", "completed"],
      },
    ],
  },
  "automated-product-demo": {
    title: "Product Demo",
    accent: "var(--ember)",
    service: "automated-product-demo",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "plan",
        label: "Planning the walkthrough",
        detail: "Turning your script into browser actions",
        icon: "pen",
        providers: ["apd-plan"],
      },
      {
        key: "record",
        label: "Recording the live site",
        detail: "Driving the browser and capturing the screencast",
        icon: "film",
        providers: ["apd-record"],
      },
      {
        key: "assemble",
        label: "Assembling the demo",
        detail: "Muxing narration and finalizing the video",
        icon: "rocket",
        providers: ["apd-assemble", "completed"],
      },
    ],
  },
  "brand-kit": {
    title: "Brand Kit",
    accent: "var(--ember)",
    service: "brand-kit",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "analyze",
        label: "Reading the brief",
        detail: "Concepts, palette direction, and type DNA",
        icon: "scan",
        providers: ["brand-kit-analyze"],
      },
      {
        key: "visuals",
        label: "Rendering brand assets",
        detail: "Logos, icons, banners, palette, and fonts",
        icon: "spark",
        providers: [
          "brand-kit-logos",
          "brand-kit-icons",
          "brand-kit-banners",
          "brand-kit-visuals",
          "brand-kit-palette",
          "brand-kit-fonts",
        ],
      },
      {
        key: "pack",
        label: "Packaging the kit",
        detail: "Building the ZIP and uploading assets",
        icon: "rocket",
        providers: ["brand-kit-zip", "completed"],
      },
    ],
  },
  "app-kit": {
    title: "App Kit",
    accent: "var(--ember)",
    service: "app-kit",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "brand",
        label: "Loading brand context",
        detail: "Colors, type, and voice for the UI kit",
        icon: "scan",
        providers: ["app-kit-brand-context"],
      },
      {
        key: "plan",
        label: "Planning screens",
        detail: "Desktop and mobile screen architecture",
        icon: "pen",
        providers: ["app-kit-plan"],
      },
      {
        key: "screens",
        label: "Rendering screens",
        detail: "Generating mock UIs for each planned surface",
        icon: "spark",
        providers: ["app-kit-screens"],
      },
      {
        key: "pack",
        label: "Packaging the kit",
        detail: "Building the ZIP and uploading assets",
        icon: "rocket",
        providers: ["app-kit-zip", "completed"],
      },
    ],
  },
  "pitch-deck": {
    title: "Pitch Deck",
    accent: "var(--ember)",
    service: "pitch-deck",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "research",
        label: "Researching the product",
        detail: "Product brief and market context from your URL",
        icon: "scan",
        providers: ["pitch-deck-research"],
      },
      {
        key: "design",
        label: "Matching design language",
        detail: "Colors, type, and visual tone from the site",
        icon: "spark",
        providers: ["pitch-deck-design"],
      },
      {
        key: "plan",
        label: "Planning the deck",
        detail: "6–8 slide narrative and funding story",
        icon: "pen",
        providers: ["pitch-deck-plan"],
      },
      {
        key: "slides",
        label: "Rendering slides",
        detail: "Generating each investor slide as an image",
        icon: "film",
        providers: ["pitch-deck-slides"],
      },
      {
        key: "pdf",
        label: "Compiling the PDF",
        detail: "Assembling slides into the final deck",
        icon: "rocket",
        providers: ["pitch-deck-pdf", "completed"],
      },
    ],
  },
  outreach: {
    title: "Investor Outreach",
    accent: "var(--ember)",
    service: "outreach",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "ingest",
        label: "Ingesting your inputs",
        detail: "Website analysis and revenue spreadsheet",
        icon: "scan",
        providers: ["outreach-sheet", "outreach-website", "outreach-revenue"],
      },
      {
        key: "research",
        label: "Finding investors",
        detail: "Matching funds, partners, and contacts",
        icon: "globe",
        providers: [
          "outreach-investors",
          "outreach-portfolio",
          "outreach-partners",
          "outreach-enrich",
        ],
      },
      {
        key: "report",
        label: "Composing the report",
        detail: "PDF brief with charts and outreach targets",
        icon: "pen",
        providers: ["outreach-insights", "outreach-report", "completed"],
      },
    ],
  },
  "social-listening": {
    title: "Social Listening",
    accent: "var(--ember)",
    service: "social-listening",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "product",
        label: "Profiling the product",
        detail: "Landing page → positioning summary",
        icon: "scan",
        providers: ["social-listening-product"],
      },
      {
        key: "threads",
        label: "Finding live threads",
        detail: "Surfacing relevant Reddit conversations",
        icon: "globe",
        providers: ["social-listening-threads"],
      },
      {
        key: "draft",
        label: "Drafting replies",
        detail: "Compliance-safe engagement copy",
        icon: "pen",
        providers: ["social-listening-drafts", "social-listening-insights"],
      },
      {
        key: "report",
        label: "Building the playbook",
        detail: "PDF report ready for download",
        icon: "rocket",
        providers: ["social-listening-report", "completed"],
      },
    ],
  },
  "competitor-research": {
    title: "Competitor Research",
    accent: "var(--ember)",
    service: "competitor-research",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker to pick up the job",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "find",
        label: "Finding competitors",
        detail: "Mapping the category landscape",
        icon: "globe",
        providers: ["competitor-research-find"],
      },
      {
        key: "evidence",
        label: "Gathering evidence",
        detail: "Features, pricing, and positioning",
        icon: "scan",
        providers: [
          "competitor-research-evidence",
          "competitor-research-features",
          "competitor-research-pricing",
          "competitor-research-positioning",
        ],
      },
      {
        key: "report",
        label: "Composing the brief",
        detail: "PDF with SWOT and comparison charts",
        icon: "pen",
        providers: [
          "competitor-research-insights",
          "competitor-research-report",
          "completed",
        ],
      },
    ],
  },
};

export function personaForService(service?: string | null): ServicePersona {
  if (service && SERVICE_PERSONAS[service]) return SERVICE_PERSONAS[service];
  return {
    title: service
      ? service
          .split("-")
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(" ")
      : "Pipeline",
    accent: "var(--ember)",
    service: service || "unknown",
    steps: [
      {
        key: "queued",
        label: "Queued",
        detail: "Waiting for a worker",
        icon: "spark",
        providers: ["starting", "queued"],
      },
      {
        key: "running",
        label: "Running",
        detail: "Pipeline in progress",
        icon: "code",
        providers: ["running"],
      },
      {
        key: "completed",
        label: "Complete",
        detail: "Deliverable ready",
        icon: "check",
        providers: ["completed"],
      },
    ],
  };
}

/** Resolve which catalog step index is active given the live job.step provider name. */
export function stepIndexForJob(
  persona: ServicePersona,
  step: string | null | undefined,
  status: string | null | undefined
): number {
  if (status === "completed" || step === "completed") {
    return Math.max(0, persona.steps.length - 1);
  }
  if (status === "failed" || status === "cancelled") {
    // Stay on the step that was running when it failed
    if (step && step !== "starting" && step !== "queued") {
      const idx = matchStepIndex(persona, step);
      if (idx >= 0) return idx;
    }
    return Math.min(1, persona.steps.length - 1);
  }
  if (status === "queued" || !step || step === "starting") {
    return 0;
  }
  const idx = matchStepIndex(persona, step);
  if (idx >= 0) return idx;
  if (status === "running") return Math.min(1, persona.steps.length - 1);
  return 0;
}

function matchStepIndex(persona: ServicePersona, step: string): number {
  const needle = step.toLowerCase();
  for (let i = 0; i < persona.steps.length; i++) {
    const providers = persona.steps[i].providers.map((p) => p.toLowerCase());
    if (
      providers.some(
        (p) => needle === p || needle.includes(p) || p.includes(needle)
      )
    ) {
      return i;
    }
  }
  return -1;
}

/** Human-readable label for the current pipeline step (prefer catalog copy). */
export function currentStepLabel(
  persona: ServicePersona,
  step: string | null | undefined,
  status: string | null | undefined
): string {
  if (status === "completed") return "Complete";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  if (status === "queued" || !step || step === "starting") return "Queued";
  const idx = stepIndexForJob(persona, step, status);
  return persona.steps[idx]?.label || humanizeStep(step);
}

export function humanizeStep(step?: string | null): string {
  if (!step) return "queued";
  return step
    .replace(/Provider$/i, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
}
