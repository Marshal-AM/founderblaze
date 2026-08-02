"""Reddit engagement playbook HTML (content ported from TS compileReport)."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any


def build_report_html(data: dict[str, Any]) -> str:
    product = data.get("product") or {}
    recs = data.get("recommendations") or []
    website = data.get("websiteUrl") or product.get("website_url") or ""
    generated = data.get("generatedAt") or datetime.now(timezone.utc).isoformat()
    try:
        date_label = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime(
            "%B %d, %Y %H:%M UTC"
        )
    except ValueError:
        date_label = generated

    subs = data.get("subreddits") or []
    if not subs:
        subs = sorted(
            {
                str(r.get("community"))
                for r in recs
                if r.get("community")
            }
        )
    sub_label = "  ·  ".join(_sub_label(s) for s in subs) or "—"
    esc = html.escape
    name = esc(str(product.get("product_name") or "Product"))
    one_liner = esc(
        str(product.get("one_liner") or str(product.get("description") or "")[:200])
    )
    insights = data.get("insights") or {}
    headline = esc(str(insights.get("headline") or ""))
    charts = list(data.get("charts") or [])

    chart_blocks = []
    for c in charts:
        data_uri = c.get("data_uri") or ""
        if not data_uri:
            continue
        chart_blocks.append(
            f"""
      <section class="chart">
        <h3>{esc(str(c.get("title") or c.get("id")))}</h3>
        <p class="chart-cap">{esc(str(c.get("caption") or ""))}</p>
        <img class="chart-img" src="{data_uri}" alt="{esc(str(c.get("title") or "chart"))}" />
      </section>"""
        )

    intel_section = ""
    if chart_blocks or headline:
        intel_section = f"""
  <h2>Community intelligence</h2>
  {f'<p class="headline">{headline}</p>' if headline else ""}
  <p class="hint">Visual synthesis from this run — discovery labor, territory, and demand shape.</p>
  {"".join(chart_blocks)}
"""

    cards = []
    for i, r in enumerate(recs, start=1):
        community = _sub_label(r.get("community"))
        title = esc(str(r.get("title") or "Thread"))
        permalink = esc(str(r.get("targetPermalink") or r.get("permalink") or ""))
        why = esc(str(r.get("threadContext") or "")[:400])
        draft = esc(str(r.get("draftText") or ""))
        notes = esc(str(r.get("draftRationale") or ""))
        cards.append(
            f"""
      <article class="thread">
        <div class="sub">{i}. {esc(community)}</div>
        <h3>{title}</h3>
        <a class="link" href="{permalink}">{permalink}</a>
        {f'<p class="why">Why: {why}</p>' if why else ""}
        <div class="label">Comment to post</div>
        <pre class="draft">{draft}</pre>
        {f'<p class="notes">Notes: {notes}</p>' if notes else ""}
      </article>"""
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Reddit Engagement Plan — {name}</title>
  <style>
    :root {{
      --ink: #1a1f24;
      --muted: #5c6b73;
      --orange: #ff4500;
      --link: #0066cc;
      --line: #e6eaed;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 36px 40px;
      font-family: Helvetica, Arial, sans-serif;
      color: var(--ink); font-size: 10.5pt; line-height: 1.45;
    }}
    h1 {{ font-size: 22pt; margin: 0 0 6px; }}
    h2 {{ font-size: 13pt; margin: 22px 0 8px; }}
    h3 {{ font-size: 11pt; margin: 4px 0 6px; }}
    .product {{ font-size: 16pt; font-weight: 700; margin: 0 0 4px; }}
    .lede {{ color: var(--muted); margin: 0 0 6px; }}
    .url {{ color: var(--orange); font-size: 10pt; text-decoration: none; }}
    .meta {{ color: #888; font-size: 8pt; margin: 8px 0 18px; }}
    .subs {{ color: #333; margin: 0 0 18px; }}
    .hint {{ color: var(--muted); font-size: 9pt; margin: 0 0 12px; }}
    .headline {{
      font-size: 11pt; font-weight: 600; color: var(--ink);
      margin: 0 0 8px; padding: 10px 12px; background: #fff7f4;
      border-left: 3px solid var(--orange);
    }}
    .chart {{
      margin: 0 0 18px; break-inside: avoid; page-break-inside: avoid;
    }}
    .chart-cap {{ color: var(--muted); font-size: 8.5pt; margin: 0 0 8px; }}
    .chart-img {{
      width: 100%; max-height: 280px; object-fit: contain;
      border: 1px solid var(--line); border-radius: 6px; background: #fff;
      display: block;
    }}
    .thread {{
      border-top: 1px solid var(--line);
      padding: 14px 0 8px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .sub {{ color: var(--orange); font-weight: 700; font-size: 11pt; }}
    .link {{ color: var(--link); font-size: 8pt; word-break: break-all; }}
    .why {{ color: #666; font-size: 8pt; margin: 6px 0; }}
    .label {{ font-weight: 700; font-size: 9pt; margin: 8px 0 4px; }}
    .draft {{
      white-space: pre-wrap; font-family: Helvetica, Arial, sans-serif;
      font-size: 10pt; margin: 0; color: #111; line-height: 1.4;
    }}
    .notes {{ color: #888; font-size: 8pt; margin: 6px 0 0; }}
  </style>
</head>
<body>
  <h1>Reddit Engagement Plan</h1>
  <div class="product">{name}</div>
  <p class="lede">{one_liner}</p>
  {f'<a class="url" href="{esc(website)}">{esc(website)}</a>' if website else ""}
  <div class="meta">Generated {esc(date_label)}</div>

  <h2>Target subreddits</h2>
  <p class="subs">{esc(sub_label)}</p>

  {intel_section}

  <h2>Suggested comments ({len(recs)})</h2>
  <p class="hint">Copy-paste ready — review before posting manually.</p>
  {"".join(cards) if cards else "<p class='hint'>No recommendations.</p>"}
</body>
</html>"""


def _sub_label(community: Any) -> str:
    if not community:
        return "Reddit"
    s = str(community)
    return s if s.startswith("r/") else f"r/{s}"
