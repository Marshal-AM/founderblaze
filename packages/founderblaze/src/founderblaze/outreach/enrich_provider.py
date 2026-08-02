from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import find_input_json, json_file_asset
from founderblaze.outreach.exa_client import create_exa_client, run_exa_search, sleep_ms
from founderblaze.outreach.partners_provider import format_contact_summary

log = logging.getLogger("founderblaze.outreach.enrich")

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


class ContactEnrichProvider(SyncProvider):
    name = "outreach-enrich"

    def __init__(
        self,
        *,
        exa_api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.exa_api_key = exa_api_key
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        partners = find_input_json(list(step.inputs or []), "outreach_partners")
        contacts = list(partners.get("contacts") or [])
        limit = int(os.environ.get("EXA_PERSON_ENRICHMENT_LIMIT", "0") or "0")
        selected = contacts[:limit] if limit > 0 else contacts
        delay = int(os.environ.get("EXA_PERSON_SEARCH_DELAY_MS", "250") or "250")
        exa = create_exa_client(self.exa_api_key)
        enriched: list[dict[str, Any]] = []
        searches: list[dict[str, Any]] = []

        log.info("enriching %s contacts", len(selected))
        for i, contact in enumerate(selected):
            name = str(contact.get("name") or "").strip()
            firm = str(contact.get("firm") or "").strip()
            if not name or not firm:
                enriched.append(contact)
                continue
            log.info("[%s/%s] %s — %s", i + 1, len(selected), name, firm)
            query = (
                f'"{name}" "{firm}" partner LinkedIn email Twitter X '
                "personal website social profile"
            )
            additional = [
                f'"{name}" "{firm}" site:linkedin.com/in',
                f'"{name}" "{firm}" (site:x.com OR site:twitter.com OR site:instagram.com)',
                f'"{name}" "{firm}" email contact',
            ]
            try:
                search = run_exa_search(
                    exa,
                    query,
                    additional_queries=additional,
                    search_type=os.environ.get("EXA_PERSON_SEARCH_TYPE", "deep-lite"),
                    num_results=int(os.environ.get("EXA_PERSON_NUM_RESULTS", "5")),
                    output_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "firm": {"type": "string"},
                            "role": {"type": "string"},
                            "linkedin": {"type": "string"},
                            "email": {"type": "string"},
                            "twitter": {"type": "string"},
                            "instagram": {"type": "string"},
                            "personalWebsite": {"type": "string"},
                            "otherSocials": {"type": "string"},
                        },
                        "required": ["name", "firm"],
                    },
                )
                updated = merge_enrichment(contact, search)
                enriched.append(updated)
                searches.append(
                    {
                        "name": name,
                        "firm": firm,
                        "query": query,
                        "resultCount": search["resultCount"],
                        "sources": [
                            {"title": r.get("title"), "url": r.get("url")}
                            for r in search["results"]
                        ],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("enrichment failed for %s: %s", name, exc)
                enriched.append(contact)
                searches.append(
                    {
                        "name": name,
                        "firm": firm,
                        "query": query,
                        "resultCount": 0,
                        "error": str(exc),
                        "sources": [],
                    }
                )
            sleep_ms(delay)

        if limit > 0 and len(contacts) > limit:
            enriched.extend(contacts[limit:])

        payload = {
            **partners,
            "contacts": enriched,
            "enrichmentSearches": searches,
            "contactSummary": format_contact_summary(enriched),
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="enriched_partners",
                metadata={"kind": "outreach_enriched"},
            )
        )
        return step


def merge_enrichment(contact: dict[str, Any], search: dict[str, Any]) -> dict[str, Any]:
    structured = search.get("output") if isinstance(search.get("output"), dict) else {}
    evidence = "\n".join(
        [
            str(structured),
            *(r.get("url") or "" for r in search.get("results") or []),
            *(r.get("title") or "" for r in search.get("results") or []),
            *(
                " ".join(r.get("highlights") or [])
                for r in search.get("results") or []
            ),
            *(r.get("text") or "" for r in search.get("results") or []),
        ]
    )
    urls = unique(
        [*extract_urls(evidence), *[r.get("url") for r in search.get("results") or []]]
    )
    emails = [e for e in unique(EMAIL_RE.findall(evidence)) if is_plausible_email(e)]

    linkedin = (
        clean_value(structured.get("linkedin"))
        or next((u for u in urls if re.search(r"linkedin\.com/in/", u, re.I)), "")
        or contact.get("linkedin")
        or ""
    )
    twitter = (
        clean_value(structured.get("twitter"))
        or next(
            (
                u
                for u in urls
                if re.search(r"(?:x|twitter)\.com/(?!home|search|share)[^/?#]+", u, re.I)
            ),
            "",
        )
        or contact.get("twitter")
        or ""
    )
    instagram = clean_value(structured.get("instagram")) or next(
        (u for u in urls if re.search(r"instagram\.com/[^/?#]+", u, re.I)),
        "",
    )
    personal = clean_value(structured.get("personalWebsite")) or next(
        (u for u in urls if is_possible_personal_site(u, str(contact.get("firm") or ""))),
        "",
    )
    structured_email = clean_value(structured.get("email"))
    existing_email = clean_value(contact.get("email"))
    email = (
        (structured_email if is_plausible_email(structured_email) else "")
        or (emails[0] if emails else "")
        or (existing_email if is_plausible_email(existing_email) else "")
        or ""
    )
    other = unique(
        [
            *(contact.get("otherSocials") or []),
            *split_socials(structured.get("otherSocials")),
            *( [instagram] if instagram else []),
            *( [personal] if personal else []),
            *[
                u
                for u in urls
                if re.search(
                    r"(?:github\.com|threads\.net|bsky\.app|medium\.com|substack\.com|youtube\.com)",
                    u,
                    re.I,
                )
            ],
        ]
    )
    return {
        **contact,
        "role": contact.get("role") or clean_value(structured.get("role")),
        "linkedin": linkedin,
        "email": email,
        "twitter": twitter,
        "otherSocials": other,
        "sourceUrl": contact.get("sourceUrl")
        or next(
            (
                r.get("url")
                for r in (search.get("results") or [])
                if r.get("url")
            ),
            "",
        ),
        "enrichmentSources": [
            r.get("url")
            for r in (search.get("results") or [])
            if r.get("url")
        ],
    }


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;:") for u in URL_RE.findall(str(text))]


def clean_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or re.match(r"^(?:n/a|none|null|unknown|not found)$", text, re.I):
        return ""
    return text


def split_socials(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_value(v) for v in value if clean_value(v)]
    return [
        clean_value(v)
        for v in re.split(r"[,;|]", str(value or ""))
        if clean_value(v)
    ]


def unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not v:
            continue
        s = str(v)
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def is_plausible_email(email: str) -> bool:
    if not email or re.search(r"[*…]", email):
        return False
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return False
    return not re.search(r"\.(?:png|jpg|jpeg|gif|svg|webp)$", email, re.I)


def is_possible_personal_site(url: str, firm: str) -> bool:
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        blocked = [
            "linkedin.com",
            "twitter.com",
            "x.com",
            "instagram.com",
            "facebook.com",
            "github.com",
            "exa.ai",
            "openvc.app",
            "crunchbase.com",
        ]
        if any(d in host for d in blocked):
            return False
        firm_token = re.sub(r"[^a-z0-9]", "", firm.lower())
        host_token = re.sub(r"[^a-z0-9]", "", host)
        return not firm_token or firm_token not in host_token
    except Exception:  # noqa: BLE001
        return False
