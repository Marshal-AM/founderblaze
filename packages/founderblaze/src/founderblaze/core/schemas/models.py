from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class ServiceName(str, Enum):
    AUTOMATED_PRODUCT_DEMO = "automated-product-demo"
    BRAND_KIT = "brand-kit"
    OUTREACH = "outreach"
    SOCIAL_LISTENING = "social-listening"
    PROMO_VIDEO = "promo-video"
    COMPETITOR_RESEARCH = "competitor-research"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Artifact(BaseModel):
    type: str
    url: str | None = None
    object_key: str | None = None
    mime_type: str | None = None
    path: str | None = None
    # Genblaze provenance (hash ↔ B2 manifest ↔ sidecar)
    canonical_hash: str | None = None
    manifest_key: str | None = None
    manifest_url: str | None = None
    sidecar_object_key: str | None = None
    sidecar_url: str | None = None
    provenance_verified: bool | None = None
    embed_method: str | None = None


class CostLine(BaseModel):
    vendor: str
    operation: str
    amount_usd: float = 0.0
    units: float | None = None
    meta: dict[str, Any] | None = None


class CreateJobRequest(BaseModel):
    input: dict[str, Any]
    callback_url: HttpUrl | None = None
    priority: Literal["low", "normal", "high"] = "normal"


class ApdInput(BaseModel):
    website_url: HttpUrl
    script: str = Field(min_length=1)


class BrandKitInput(BaseModel):
    brand_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=10, max_length=2000)
    pick: int = Field(default=0, ge=0, le=5)


class OutreachInput(BaseModel):
    website_url: HttpUrl
    sheet_url: HttpUrl


class SocialListeningInput(BaseModel):
    product_url: HttpUrl
    product_name: str | None = Field(default=None, min_length=1, max_length=120)
    max_posts: int | None = Field(default=None, ge=1, le=20)
    live: bool = False  # deprecated / ignored — no auto-post


class PromoVideoInput(BaseModel):
    product_url: HttpUrl
    # Segmind Seedance 2.0 durations (match TS PromoVideoDurationSchema)
    duration: Literal[4, 5, 6, 8, 10, 12, 15] = 10
    resolution: Literal["480p", "720p", "1080p", "4k"] = "720p"


class CompetitorResearchInput(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    product_url: HttpUrl | None = None


class JobRecord(BaseModel):
    id: str
    service: ServiceName
    status: JobStatus
    input: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    cost_breakdown: list[CostLine] = Field(default_factory=list)
    list_price_usd: float
    error: str | None = None
    error_code: str | None = None
    callback_url: str | None = None
    idempotency_key: str | None = None
    workflow_id: str | None = None
    dispatched_at: datetime | None = None
    dispatch_error: str | None = None
    eta_seconds: int | None = None
    step: str | None = None
    created_at: datetime
    updated_at: datetime


SERVICE_MANIFESTS: dict[ServiceName, dict[str, Any]] = {
    ServiceName.AUTOMATED_PRODUCT_DEMO: {
        "name": ServiceName.AUTOMATED_PRODUCT_DEMO.value,
        "title": "Automated Product Demo",
        "a2mcp_price_usd": 1.49,
        "sla_minutes": 30,
        "endpoint_path": "/v1/services/automated-product-demo/jobs",
        "summary": "Records a narrated product demo video from a website URL and script.",
        "provide": "website_url and a natural-language demo script",
        "deliverable": "MP4 demo video with voiceover (Backblaze URL)",
        "example_request": {
            "input": {
                "website_url": "https://linear.app",
                "script": "Show the homepage, open pricing, highlight the free tier.",
            }
        },
        "example_artifacts": [
            {
                "type": "video",
                "mime_type": "video/mp4",
                "description": "Narrated product demo MP4",
            }
        ],
    },
    ServiceName.BRAND_KIT: {
        "name": ServiceName.BRAND_KIT.value,
        "title": "Brand Identity Kit",
        "a2mcp_price_usd": 1.49,
        "sla_minutes": 15,
        "endpoint_path": "/v1/services/brand-kit/jobs",
        "summary": "Generates a downloadable brand identity zip from a name and creative brief.",
        "provide": "brand_name, description, optional pick (logo concept index)",
        "deliverable": "ZIP with logos, palette, fonts, icons, banners (Backblaze URL)",
        "example_request": {
            "input": {
                "brand_name": "Solace",
                "description": "calm meditation app, minimalist, organic, wellness",
                "pick": 0,
            }
        },
        "example_artifacts": [
            {
                "type": "brand_kit_zip",
                "mime_type": "application/zip",
                "description": "Brand kit ZIP (logos, fonts, assets, guide)",
            }
        ],
    },
    ServiceName.OUTREACH: {
        "name": ServiceName.OUTREACH.value,
        "title": "Investor Outreach Report",
        "a2mcp_price_usd": 1.0,
        "sla_minutes": 15,
        "endpoint_path": "/v1/services/outreach/jobs",
        "summary": "Builds an investor intelligence PDF from a company website and revenue spreadsheet.",
        "provide": "website_url and a public sheet_url (.xlsx/.csv)",
        "deliverable": "PDF investor outreach report (Backblaze URL)",
        "example_request": {
            "input": {
                "website_url": "https://example.com",
                "sheet_url": "https://cdn.example/revenue.xlsx",
            }
        },
        "example_artifacts": [
            {
                "type": "pdf_report",
                "mime_type": "application/pdf",
                "description": "Investor intelligence PDF",
            }
        ],
    },
    ServiceName.SOCIAL_LISTENING: {
        "name": ServiceName.SOCIAL_LISTENING.value,
        "title": "Reddit Engagement Pack",
        "a2mcp_price_usd": 1.0,
        "sla_minutes": 15,
        "endpoint_path": "/v1/services/social-listening/jobs",
        "summary": "Finds live Reddit threads and drafts ready-to-post replies into a PDF playbook.",
        "provide": "product_url (required). Optional: product_name, max_posts (1–20).",
        "deliverable": "PDF playbook (pdf_report) plus thread URLs (reddit_thread) on Backblaze",
        "example_request": {
            "input": {
                "product_url": "https://example.com",
                "product_name": "Example App",
                "max_posts": 5,
            }
        },
        "example_artifacts": [
            {
                "type": "pdf_report",
                "mime_type": "application/pdf",
                "description": "Engagement playbook PDF — primary deliverable",
            },
            {
                "type": "reddit_thread",
                "mime_type": "text/uri-list",
                "description": "Reddit thread URL referenced in the playbook",
            },
        ],
    },
    ServiceName.PROMO_VIDEO: {
        "name": ServiceName.PROMO_VIDEO.value,
        "title": "Product Promo Video",
        "a2mcp_price_usd": 2.99,
        "sla_minutes": 15,
        "endpoint_path": "/v1/services/promo-video/jobs",
        "summary": "Generates a short cinematic promo video from a product URL via Gemini grounding + Segmind Seedance.",
        "provide": "product_url (required). Optional: duration (4|5|6|8|10|12|15, default 10), resolution (480p|720p|1080p|4k, default 720p).",
        "deliverable": "MP4 promo video (Backblaze URL)",
        "example_request": {
            "input": {
                "product_url": "https://linear.app",
                "duration": 10,
                "resolution": "720p",
            }
        },
        "example_artifacts": [
            {
                "type": "video",
                "mime_type": "video/mp4",
                "description": "Cinematic product promo MP4",
            }
        ],
    },
    ServiceName.COMPETITOR_RESEARCH: {
        "name": ServiceName.COMPETITOR_RESEARCH.value,
        "title": "Competitor Research Report",
        "a2mcp_price_usd": 1.0,
        "sla_minutes": 20,
        "endpoint_path": "/v1/services/competitor-research/jobs",
        "summary": "Discovers peer competitors and delivers a branded competitive-intelligence PDF (features, pricing, positioning).",
        "provide": "product_name (required). Optional: product_url homepage for category/features/pricing ground truth.",
        "deliverable": "PDF competitor research report (Backblaze URL)",
        "example_request": {
            "input": {
                "product_name": "Notion",
                "product_url": "https://www.notion.so",
            }
        },
        "example_artifacts": [
            {
                "type": "report_pdf",
                "mime_type": "application/pdf",
                "description": "Competitive intelligence PDF",
            }
        ],
    },
}
