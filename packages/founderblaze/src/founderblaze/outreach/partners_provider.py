from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import find_input_json, json_file_asset
from founderblaze.outreach.exa_client import (
    create_exa_client,
    format_exa_results_for_prompt,
    run_exa_search,
    unwrap_exa_output,
)
from founderblaze.outreach.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.outreach.partners")


class PartnerContactsProvider(SyncProvider):
    name = "outreach-partners"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        exa_api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.exa_api_key = exa_api_key
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        inputs = list(step.inputs or [])
        website = find_input_json(inputs, "outreach_website")
        investors = find_input_json(inputs, "outreach_investors")
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        product = website.get("productSummary") or ""
        investor_summary = investors.get("investorSummary") or ""
        investor_results = investors.get("exaResults") or investors.get("sources") or []

        firm_hints = "\n".join(
            f"- {(r.get('title') or '')} {(r.get('url') or '')}".strip()
            for r in investor_results[:8]
            if isinstance(r, dict) and (r.get("title") or r.get("url"))
        )

        plan = gemini_json(
            f"""Create an Exa search plan to find partners and their public contacts at these investor firms.

Investor shortlist:
\"\"\"{investor_summary}\"\"\"

Product context (optional):
\"\"\"{product or "(none)"}\"\"\"

Investor search hints:
\"\"\"{firm_hints or "(none)"}\"\"\"

Return JSON:
{{
  "firms": ["up to 6 firm names extracted from the shortlist"],
  "query": "one rich natural-language Exa query asking for partners/GPs at these firms with LinkedIn, email, Twitter/X, and other socials",
  "additionalQueries": ["up to 3 alternate deep-search queries focused on team pages, LinkedIn directories, and partner bios"]
}}

Rules:
- Extract real firm names from the shortlist.
- Explicitly ask for partner / general partner / investing partner names.
- Explicitly ask for LinkedIn URLs, public emails, Twitter/X, and other social profiles.
- Prefer official team pages, firm sites, and LinkedIn profiles.
- Do not invent contact details in the query itself.""",
            model=model,
            api_key=self.api_key,
            system=(
                "You write Exa search queries to find named partners, GPs, and "
                "investing partners at specific VC/angel firms, plus their public "
                "contact links (LinkedIn, email, X/Twitter, personal sites). "
                "Return JSON only."
            ),
        )
        query = str(plan.get("query") or "").strip()
        if not query:
            raise RuntimeError("Partner query planner returned empty query")
        firms = [str(f).strip() for f in (plan.get("firms") or []) if str(f).strip()][:6]
        additional = [
            str(q).strip()
            for q in (plan.get("additionalQueries") or [])
            if str(q).strip()
        ][:3]
        log.info("partners Exa query=%s firms=%s", query[:120], firms[:5])

        exa = create_exa_client(self.exa_api_key)
        num = int(os.environ.get("EXA_CONTACT_NUM_RESULTS", "10"))
        search = run_exa_search(
            exa,
            query,
            additional_queries=additional,
            num_results=num,
            output_schema={
                "type": "object",
                "properties": {
                    "contacts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "firm": {"type": "string"},
                                "role": {"type": "string"},
                                "linkedin": {"type": "string"},
                                "email": {"type": "string"},
                                "twitter": {"type": "string"},
                                "otherSocials": {"type": "string"},
                                "sourceUrl": {"type": "string"},
                            },
                            "required": ["name", "firm"],
                        },
                    },
                    "notes": {"type": "string"},
                },
                "required": ["contacts"],
            },
        )

        structured = unwrap_exa_output(search.get("output"))
        log.info(
            "partners Exa hits=%s structured_contacts=%s",
            search["resultCount"],
            len((structured or {}).get("contacts") or [])
            if isinstance(structured, dict)
            else 0,
        )

        synthesized = gemini_json(
            f"""Build a partner contact list from the Exa evidence.

Target firms:
\"\"\"{", ".join(firms) or "(from investor shortlist)"}\"\"\"

Investor shortlist context:
\"\"\"{investor_summary}\"\"\"

Exa query used:
\"\"\"{query}\"\"\"

Exa results:
\"\"\"{format_exa_results_for_prompt(search, max_results=8, max_highlight_chars=320)}\"\"\"

Exa structured output (if any):
\"\"\"{json.dumps(structured or {}, indent=2)[:3000]}\"\"\"

Return JSON:
{{
  "contacts": [
    {{
      "name": "Full name",
      "firm": "Firm name",
      "role": "Partner / GP / etc",
      "linkedin": "url or empty string",
      "email": "public email or empty string",
      "twitter": "X/Twitter url or handle or empty string",
      "otherSocials": ["optional other public profile urls"],
      "sourceUrl": "best evidence url"
    }}
  ],
  "summary": "short bullet list: - Name — Firm (Role) — LinkedIn: url · Email: x (no pipe characters)"
}}

Rules:
- Deduplicate by name+firm.
- Prefer partners / GPs / investing partners over analysts or ops staff when possible.
- Leave unknown fields as empty string / empty array.
- Do not fabricate contact details.
- Include people even if only LinkedIn (or another public URL) is known.
- Never use the | character in summary (it breaks PDF layout). Separate fields with · or — only.""",
            model=model,
            api_key=self.api_key,
            system=(
                "You extract a clean contact list of partners at investment firms "
                "from search evidence. Only include contacts supported by the Exa "
                "results. Never invent emails or profile URLs. Return JSON only."
            ),
        )

        contacts = normalize_contacts(synthesized.get("contacts"))
        if not contacts and isinstance(structured, dict):
            contacts = normalize_contacts(structured.get("contacts"))
        # Also harvest LinkedIn URLs from Exa result titles/URLs when synthesis is thin.
        contacts = merge_contacts_from_results(contacts, search.get("results") or [], firms)

        summary = str(synthesized.get("summary") or "").strip()
        if not summary:
            summary = format_contact_summary(contacts)
        if not contacts and not summary:
            raise RuntimeError("Contact synthesis returned no contacts")

        log.info("partners synthesized contacts=%s", len(contacts))
        payload = {
            "model": model,
            "firms": firms,
            "query": query,
            "additionalQueries": additional,
            "exaResultCount": search["resultCount"],
            "exaResults": search["results"],
            "structuredOutput": structured,
            "contactSummary": summary,
            "contacts": contacts,
            "sources": [
                {"title": r.get("title"), "url": r.get("url")}
                for r in search["results"]
            ],
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="partners",
                metadata={"kind": "outreach_partners"},
            )
        )
        return step


def normalize_contacts(raw_contacts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_contacts, list):
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw_contacts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        firm = str(item.get("firm") or "").strip()
        if not name or not firm:
            continue
        key = f"{name.lower()}::{firm.lower()}"
        if key in seen:
            continue
        seen.add(key)
        other = item.get("otherSocials")
        if isinstance(other, list):
            other_socials = [str(s).strip() for s in other if str(s).strip()]
        else:
            other_socials = [
                s.strip()
                for s in str(other or "").split(",")
                if s.strip()
            ]
            if not other_socials and other:
                other_socials = [
                    s.strip()
                    for s in str(other).replace(";", ",").replace("|", ",").split(",")
                    if s.strip()
                ]
        out.append(
            {
                "name": name,
                "firm": firm,
                "role": str(item.get("role") or "").strip(),
                "linkedin": str(item.get("linkedin") or "").strip(),
                "email": str(item.get("email") or "").strip(),
                "twitter": str(item.get("twitter") or "").strip(),
                "otherSocials": other_socials,
                "sourceUrl": str(item.get("sourceUrl") or "").strip() or None,
            }
        )
    return out


def format_contact_summary(contacts: list[dict[str, Any]]) -> str:
    if not contacts:
        return "(no contacts found)"
    lines = []
    for c in contacts:
        socials = [
            f"LinkedIn: {c['linkedin']}" if c.get("linkedin") else None,
            f"Email: {c['email']}" if c.get("email") else None,
            f"X: {c['twitter']}" if c.get("twitter") else None,
            *[f"Social: {s}" for s in (c.get("otherSocials") or [])],
        ]
        # Use middot — never "|", which the PDF markdown renderer treats as a table.
        socials_s = " · ".join(x for x in socials if x)
        role = f" ({c['role']})" if c.get("role") else ""
        extra = f" — {socials_s}" if socials_s else ""
        lines.append(f"- {c['name']} — {c['firm']}{role}{extra}")
    return "\n".join(lines)


def merge_contacts_from_results(
    contacts: list[dict[str, Any]],
    results: list[dict[str, Any]],
    firms: list[str],
) -> list[dict[str, Any]]:
    """If Gemini returned few people, pull LinkedIn profiles from Exa hits."""
    if len(contacts) >= 3:
        return contacts

    seen = {f"{c['name'].lower()}::{c['firm'].lower()}" for c in contacts}
    out = list(contacts)
    firm_l = [f.lower() for f in firms if f]

    for r in results:
        url = str(r.get("url") or "")
        title = str(r.get("title") or "")
        if "linkedin.com/in" not in url.lower():
            continue
        # Title often like "Jane Doe - Partner at Acme Ventures | LinkedIn"
        name = ""
        firm = ""
        m = re.match(
            r"^(.+?)\s*[-–—|]\s*(?:.*?\b(?:Partner|GP|Principal|Managing)\b.*?\bat\s+)?(.+?)(?:\s*[|].*)?$",
            title,
            re.I,
        )
        if m:
            name = m.group(1).strip()
            firm = m.group(2).strip()
            firm = re.sub(r"\s*\|\s*LinkedIn.*$", "", firm, flags=re.I).strip()
        if not name or len(name) > 80:
            continue
        if not firm and firm_l:
            blob = f"{title} {url}".lower()
            for f in firms:
                if f.lower() in blob:
                    firm = f
                    break
        if not firm:
            firm = firms[0] if firms else "Unknown firm"
        key = f"{name.lower()}::{firm.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "firm": firm,
                "role": "Partner",
                "linkedin": url,
                "email": "",
                "twitter": "",
                "otherSocials": [],
                "sourceUrl": url,
            }
        )
    return out
