export type Artifact = {
  type?: string;
  url?: string | null;
  object_key?: string | null;
  mime_type?: string | null;
  path?: string | null;
  canonical_hash?: string | null;
};

export type JobRef = {
  job_id?: string;
  service?: string;
  status?: string;
  error?: string | null;
  step?: string | null;
};

export type AgentResponse = {
  session_id: string;
  reply: string;
  tool_calls?: Array<{
    name: string;
    ok?: boolean;
    blocked?: boolean;
    error?: string;
  }>;
  jobs?: JobRef[];
  artifacts?: Artifact[];
  pending?: boolean;
  thread_id?: string | null;
  saved?: boolean;
};

export type JobStatus = {
  id: string;
  service: string;
  status: string;
  step?: string | null;
  artifacts?: Artifact[];
  error?: string | null;
  eta_seconds?: number | null;
  list_price_usd?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type PipelineStep = {
  key: string;
  label: string;
  detail: string;
  icon: "scan" | "pen" | "film" | "rocket" | "globe" | "check" | "code" | "spark";
  /** Genblaze provider `name` values (and status tokens) that map to this step. */
  providers: string[];
};

/** Catalog entry for a FounderBlaze service pipeline (progress UI). */
export type ServicePersona = {
  title: string;
  accent: string;
  service: string;
  steps: PipelineStep[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "agent";
  content: string;
  meta?: AgentResponse;
  jobs?: JobRef[];
  artifacts?: Artifact[];
  liveJob?: JobStatus | null;
};
