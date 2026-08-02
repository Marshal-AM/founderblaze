"""Outreach intelligence report HTML — port of services/outreach-service report/template.ts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def build_report_html(data: dict[str, Any]) -> str:
    generated = data.get("generatedAt") or datetime.now(timezone.utc).isoformat()
    try:
        date_label = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime(
            "%B %d, %Y"
        )
    except ValueError:
        date_label = str(generated)

    website = data.get("website") or {}
    revenue = data.get("revenue") or {}
    investors = data.get("investors") or {}
    portfolio = data.get("portfolioBenchmarks") or {}
    contacts = data.get("partnerContacts") or {}

    product_label = (
        extract_product_name(website.get("productSummary"))
        or host_from_url(website.get("url") or "")
        or "Company"
    )
    product_bits = parse_labeled_summary(website.get("productSummary"))
    performance_bits = parse_performance(revenue.get("performanceSummary"))
    investor_rows = normalize_investors(investors)
    benchmark_rows = normalize_benchmarks(portfolio)
    all_contacts = normalize_contacts(contacts.get("contacts"), require_reach=False)
    contact_rows = normalize_contacts(contacts.get("contacts"), require_reach=True)
    with_reach = len(contact_rows)
    firm_list = unique(
        list(contacts.get("firms") or [])
        + [c["firm"] for c in all_contacts if c.get("firm")]
    )
    evidence = collect_evidence(data)
    sheet = revenue.get("sheet") if isinstance(revenue.get("sheet"), dict) else {}
    tools = website.get("toolsUsed") if isinstance(website.get("toolsUsed"), list) else []
    insights = data.get("insights") or {}
    charts = list(data.get("charts") or [])
    headline = esc(str(insights.get("headline") or ""))
    chart_blocks = []
    for c in charts:
        data_uri = c.get("data_uri") or ""
        if not data_uri:
            continue
        chart_blocks.append(
            f"""
      <section class="chart avoid">
        <h3>{esc(str(c.get("title") or c.get("id")))}</h3>
        <p class="chart-cap">{esc(str(c.get("caption") or ""))}</p>
        <img class="chart-img" src="{data_uri}" alt="{esc(str(c.get("title") or "chart"))}" />
      </section>"""
        )
    intel_section = ""
    if chart_blocks or headline:
        intel_section = f"""
  <div class="section-head break"><span class="num">02</span><h2>Visual diligence</h2><span class="tag">Gemini charts</span></div>
  {f'<p class="headline">{headline}</p>' if headline else ""}
  <p class="lead">Board-ready visuals synthesized from this run — positioning, fit, conflicts, who to email, cadence, check size, and thesis language.</p>
  {"".join(chart_blocks)}
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Investor Outreach Report — {esc(product_label)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --ink: #122028;
      --muted: #5a6d76;
      --line: #d5e2e7;
      --line-strong: #b7c9d1;
      --teal: #0c7268;
      --teal-deep: #065048;
      --teal-soft: #e7f4f1;
      --teal-tint: #f3faf8;
      --wash: #fff;
      --shadow: 0 1px 2px rgba(18,32,40,0.04);
    }}
    * {{ box-sizing: border-box; }}
    @page {{
      size: A4;
      margin: 12mm 11mm 15mm;
    }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      color: var(--ink);
      background: var(--wash);
      font-family: "Source Sans 3", system-ui, sans-serif;
      font-size: 9.4pt;
      line-height: 1.45;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    h1, h2, h3 {{
      font-family: "Fraunces", Georgia, serif;
      font-weight: 700;
      letter-spacing: -0.015em;
      margin: 0;
    }}
    p {{ margin: 0 0 7px; }}
    .muted {{ color: var(--muted); }}
    .avoid {{ break-inside: avoid; page-break-inside: avoid; }}
    .prose p {{ margin: 0 0 5px; }}
    .prose p:last-child {{ margin-bottom: 0; }}
    .prose ul, .prose ol {{ margin: 2px 0 6px; padding-left: 1.1em; }}
    .prose li {{ margin: 2px 0; }}
    .prose strong {{ font-weight: 700; }}
    .prose h3 {{
      font-size: 10pt; margin: 8px 0 4px; color: var(--teal-deep);
      break-after: avoid;
    }}
    .headline {{
      font-size: 10.5pt; font-weight: 600; color: var(--ink);
      margin: 0 0 8px; padding: 10px 12px; background: var(--teal-soft);
      border-left: 3px solid var(--teal);
    }}
    .chart {{ margin: 0 0 16px; }}
    .chart h3 {{ font-size: 11pt; margin: 0 0 4px; color: var(--teal-deep); }}
    .chart-cap {{ color: var(--muted); font-size: 8.5pt; margin: 0 0 8px; }}
    .chart-img {{
      width: 100%; max-height: 270px; object-fit: contain;
      border: 1px solid var(--line); border-radius: 8px; background: #fff;
      display: block;
    }}
    .break {{ break-before: page; }}
    .cover {{
      border-radius: 14px;
      color: #fff;
      padding: 20px 22px 16px;
      margin-bottom: 8px;
      background:
        radial-gradient(80% 70% at 100% 0%, rgba(180,240,230,0.25), transparent 55%),
        linear-gradient(145deg, #043833 0%, #0c7268 55%, #149687 120%);
      box-shadow: var(--shadow);
    }}
    .cover-top {{
      display: flex; justify-content: space-between; align-items: center;
      font-size: 8pt; letter-spacing: 0.12em; text-transform: uppercase;
      color: rgba(255,255,255,0.8); font-weight: 600;
    }}
    .eyebrow {{
      font-size: 8.5pt; letter-spacing: 0.18em; text-transform: uppercase;
      color: rgba(255,255,255,0.7); font-weight: 600; margin-top: 12px;
    }}
    .cover h1 {{ font-size: 28pt; line-height: 1.05; margin: 6px 0 0; color: #fff; }}
    .cover .lede {{ margin-top: 8px; max-width: 36rem; font-size: 10pt; color: rgba(255,255,255,0.92); line-height: 1.4; }}
    .cover .url {{
      display: inline-block; margin-top: 8px; font-size: 8.5pt; font-weight: 600;
      padding: 3px 10px; border-radius: 999px; background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.25);
    }}
    .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }}
    .kpi {{
      background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.18);
      border-radius: 10px; padding: 8px 10px;
    }}
    .kpi .k-label {{ font-size: 7pt; letter-spacing: 0.08em; text-transform: uppercase; color: rgba(255,255,255,0.7); }}
    .kpi .k-value {{ font-family: "Fraunces", serif; font-size: 15pt; margin-top: 2px; }}
    .kpi .k-sub {{ font-size: 7pt; color: rgba(255,255,255,0.65); margin-top: 1px; }}
    .cover-bottom {{
      display: flex; justify-content: space-between; align-items: flex-end; gap: 16px;
      border-top: 1px solid rgba(255,255,255,0.2); padding-top: 10px; margin-top: 12px;
    }}
    .contents {{
      display: flex; flex-wrap: wrap; gap: 4px 16px;
      font-size: 8pt; color: rgba(255,255,255,0.9); max-width: 70%;
    }}
    .contents div {{ display: flex; gap: 6px; white-space: nowrap; }}
    .contents span.n {{ color: rgba(255,255,255,0.55); font-weight: 600; }}
    .cover-date {{ text-align: right; font-size: 8pt; color: rgba(255,255,255,0.78); }}
    .cover-date strong {{ display:block; font-family:"Fraunces"; font-size: 11pt; color:#fff; margin-top:2px; }}
    .section-head {{
      display: flex; align-items: baseline; gap: 8px;
      margin: 10px 0 4px;
      break-after: avoid; page-break-after: avoid;
    }}
    .section-head .num {{
      font-family: "Fraunces", serif; font-size: 11pt; color: var(--teal);
      background: var(--teal-soft); border: 1px solid #c4e4de; border-radius: 7px;
      padding: 2px 8px;
    }}
    .section-head h2 {{ font-size: 15pt; }}
    .section-head .tag {{
      margin-left: auto; font-size: 7.5pt; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--muted); font-weight: 600;
    }}
    .lead {{ color: var(--muted); font-size: 8.4pt; margin: 0 0 5px; max-width: 46rem; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .card {{
      border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px;
      background: #fff; box-shadow: var(--shadow);
    }}
    .kicker {{
      font-size: 7.2pt; letter-spacing: 0.1em; text-transform: uppercase;
      color: var(--teal); font-weight: 700; margin-bottom: 6px;
    }}
    .fact {{
      display: grid; grid-template-columns: 88px 1fr; gap: 2px 8px;
      padding: 2px 0; align-items: start;
    }}
    .fact .k {{ color: var(--muted); font-size: 7.2pt; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700; }}
    .fact .v {{ font-weight: 600; font-size: 9pt; }}
    ul.clean {{ margin: 6px 0 0; padding-left: 1.1em; }}
    ul.clean li {{ margin: 2px 0; }}
    table.data {{
      width: 100%; border-collapse: collapse; font-size: 8.3pt;
      margin: 8px 0 6px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
      table-layout: fixed;
    }}
    table.data th, table.data td {{
      border-bottom: 1px solid var(--line); padding: 7px 8px;
      text-align: left; vertical-align: top;
      overflow-wrap: anywhere; word-break: break-word;
    }}
    table.data th {{
      background: var(--teal-tint); color: var(--teal-deep);
      font-size: 7.3pt; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700;
      border-bottom: 1px solid var(--line-strong);
    }}
    table.data tr:last-child td {{ border-bottom: 0; }}
    table.data tr:nth-child(even) td {{ background: #f8fbfa; }}
    table.data a {{ color: var(--teal-deep); text-decoration: none; font-weight: 600; }}
    .tiny {{ font-size: 7.4pt; color: #4d616a; font-weight: 500; }}
    .contact-links {{ display: grid; gap: 5px; }}
    .contact-link {{
      display: block; padding: 4px 7px; border: 1px solid #d8e8e5;
      border-radius: 6px; background: #f5fbf9; line-height: 1.25;
      overflow-wrap: anywhere; word-break: break-word;
    }}
    .contact-kind {{
      display: block; margin-bottom: 1px; color: var(--muted);
      font-size: 6.6pt; font-weight: 700; letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .contact-value {{ color: var(--teal-deep); font-size: 7.8pt; font-weight: 600; }}
    .pill-row {{ display: flex; flex-wrap: wrap; gap: 5px; margin: 0 0 8px; }}
    .pill {{
      font-size: 7.5pt; font-weight: 600; color: var(--teal-deep);
      background: var(--teal-soft); border: 1px solid #c4e4de;
      border-radius: 999px; padding: 2px 8px;
    }}
    .note {{ font-size: 7.6pt; color: var(--muted); margin-top: 4px; }}
    .analysis {{
      border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px;
      background: #fff; margin: 0 0 6px; box-shadow: var(--shadow);
    }}
    table.data tr {{ break-inside: avoid; page-break-inside: avoid; }}
    .sources {{ font-size: 7.9pt; columns: 2; column-gap: 18px; margin: 0; padding-left: 1.1em; }}
    .sources li {{ margin-bottom: 4px; break-inside: avoid; word-break: break-word; }}
    ul.method {{ list-style: none; margin: 0; padding: 0; }}
    ul.method li {{
      display: flex; justify-content: space-between; gap: 10px;
      padding: 5px 0; border-bottom: 1px dashed var(--line); font-size: 8.6pt;
    }}
    ul.method li:last-child {{ border-bottom: 0; }}
    ul.method span {{ color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-size: 7.4pt; font-weight: 700; }}
    ul.method b {{ text-align: right; font-weight: 600; }}
  </style>
</head>
<body>
  <section class="cover">
      <div class="cover-top">
        <div>Outreach Forge</div>
        <div>Investor Outreach Intelligence</div>
      </div>
      <div class="eyebrow">Full Findings Report</div>
      <h1>{esc(product_label)}</h1>
      <p class="lede">{esc(cover_lede(product_bits))}</p>
      {f'<span class="url">{esc(website.get("url") or "")}</span>' if website.get("url") else ""}
      <div class="kpis">
        <div class="kpi"><div class="k-label">Investors</div><div class="k-value">{len(investor_rows) or investors.get("exaResultCount") or 0}</div><div class="k-sub">shortlisted</div></div>
        <div class="kpi"><div class="k-label">Benchmarks</div><div class="k-value">{len(benchmark_rows) or portfolio.get("exaResultCount") or 0}</div><div class="k-sub">portfolio comps</div></div>
        <div class="kpi"><div class="k-label">Contacts</div><div class="k-value">{len(all_contacts)}</div><div class="k-sub">partners / GPs found</div></div>
        <div class="kpi"><div class="k-label">With reach</div><div class="k-value">{with_reach}</div><div class="k-sub">shown in §06</div></div>
      </div>
    <div class="cover-bottom">
      <div class="contents">
        <div><span class="n">01</span> Executive overview</div>
        <div><span class="n">02</span> Visual diligence</div>
        <div><span class="n">03</span> Product analysis</div>
        <div><span class="n">04</span> Company performance</div>
        <div><span class="n">05</span> Investor shortlist</div>
        <div><span class="n">06</span> Portfolio benchmarks</div>
        <div><span class="n">07</span> Partner contacts</div>
        <div><span class="n">08</span> Sources &amp; method</div>
      </div>
      <div class="cover-date">Generated<strong>{esc(date_label)}</strong></div>
    </div>
  </section>

  <div class="section-head"><span class="num">01</span><h2>Executive overview</h2><span class="tag">Synthesis</span></div>
  <p class="lead">Compact readout of product, traction, and the outreach posture before the full findings.</p>
  <div class="grid-2">
    <div class="card">
      <div class="kicker">Product snapshot</div>
      {render_product_card(product_bits, website.get("url"))}
    </div>
    <div class="card">
      <div class="kicker">Performance snapshot</div>
      {render_performance_card(performance_bits)}
    </div>
  </div>
  <div class="card" style="margin-top:8px">
    <div class="kicker">Outreach posture</div>
    <div class="pill-row">
      <span class="pill">Firms: {len(firm_list) or "—"}</span>
      <span class="pill">Reachable contacts: {len(contact_rows)}</span>
      <span class="pill">Investors listed: {len(investor_rows)}</span>
      <span class="pill">Benchmarks: {len(benchmark_rows)}</span>
    </div>
    <p class="muted" style="margin:0">Section 02 is the visual diligence pack. Sections 05–07 carry the full investor thesis, revenue comps, and partner reach.</p>
  </div>

  {intel_section}

  <div class="section-head"><span class="num">03</span><h2>Product analysis</h2><span class="tag">Website</span></div>
  <p class="lead">Full product readout from the website analysis{f" (tools: {esc(', '.join(str(t) for t in tools))})" if tools else ""}.</p>
  <div class="analysis prose">{md(website.get("productSummary") or "No product summary.")}</div>

  <div class="section-head"><span class="num">04</span><h2>Company performance</h2><span class="tag">Spreadsheet</span></div>
  <p class="lead">Financial synthesis across the uploaded workbook{f" ({sheet.get('sheetCount')} sheets)" if sheet.get("sheetCount") else ""}.</p>
  <div class="analysis prose">{md(revenue.get("performanceSummary") or "No performance summary.")}</div>

  <div class="section-head"><span class="num">05</span><h2>Investor shortlist</h2><span class="tag">Exa + Gemini</span></div>
  <p class="lead">Full AI shortlist of investors and firms matched to product category and stage — thesis fit, focus, portfolio examples, and confidence gaps.</p>
  <div class="analysis prose">{md(investors.get("investorSummary") or "No investor shortlist.")}</div>
  {f'<div class="kicker" style="margin-top:6px">Structured shortlist</div>{render_investor_table(investor_rows)}' if investor_rows else ""}

  <div class="section-head"><span class="num">06</span><h2>Portfolio revenue benchmarks</h2><span class="tag">Pre-investment</span></div>
  <p class="lead">ARR / MRR / revenue reported for portfolio companies before or around investor entry.</p>
  <div class="analysis prose">{md(portfolio.get("portfolioRevenueSummary") or "No portfolio benchmark synthesis.")}</div>
  {f'<div class="kicker" style="margin-top:6px">Structured benchmarks</div>{render_benchmark_table(benchmark_rows)}' if benchmark_rows else ""}

  <div class="section-head"><span class="num">07</span><h2>Partner contacts</h2><span class="tag">Outreach list</span></div>
  <p class="lead">Partners / GPs at target firms who have at least one public LinkedIn, email, X, or other social URL.</p>
  {_firm_pills(firm_list)}
  {_contact_summary_block(contacts.get("contactSummary"), has_table=bool(contact_rows))}
  {render_contact_table(contact_rows)}
  <p class="note">People without any public contact channel are omitted from this table — nothing is invented.</p>

  <div class="section-head"><span class="num">08</span><h2>Sources &amp; method</h2><span class="tag">Evidence</span></div>
  <div class="grid-2">
    <div class="card">
      <div class="kicker">Pipeline method</div>
      <ul class="method">
        <li><span>Website</span><b>{esc(website.get("model") or "Exa + Gemini")}</b></li>
        <li><span>Revenue</span><b>{esc(revenue.get("model") or "Gemini")}</b></li>
        <li><span>Investors</span><b>Exa deep search + Gemini synthesis</b></li>
        <li><span>Portfolio</span><b>Exa deep search + Gemini synthesis</b></li>
        <li><span>Contacts</span><b>Firm search → Gemini extract → per-person enrichment</b></li>
        <li><span>Visuals</span><b>Gemini image charts from diligence JSON</b></li>
      </ul>
    </div>
    <div class="card">
      <div class="kicker">Coverage</div>
      <ul class="method">
        <li><span>Product URL</span><b>{esc(host_from_url(website.get("url") or "") or website.get("url") or "—")}</b></li>
        <li><span>Workbook sheets</span><b>{sheet.get("sheetCount") or 0}</b></li>
        <li><span>Investor Exa hits</span><b>{investors.get("exaResultCount") or 0}</b></li>
        <li><span>Portfolio Exa hits</span><b>{portfolio.get("exaResultCount") or 0}</b></li>
        <li><span>Contacts listed</span><b>{len(contact_rows)}</b></li>
      </ul>
    </div>
  </div>
  <div class="card" style="margin-top:10px">
    <div class="kicker">Evidence titles &amp; URLs</div>
    <ol class="sources">
      {"".join(f'<li><strong>{esc(s.get("title") or host_from_url(s.get("url") or "") or "Source")}</strong><br/><span class="tiny">{esc(s.get("url") or "")}</span></li>' for s in evidence) or '<li class="muted">No source URLs captured.</li>'}
    </ol>
  </div>
</body>
</html>"""


# -------------------- renderers --------------------


def _firm_pills(firm_list: list[Any]) -> str:
    if not firm_list:
        return ""
    pills = "".join(f'<span class="pill">{esc(f)}</span>' for f in firm_list)
    return f'<div class="pill-row">{pills}</div>'


def _contact_summary_block(summary: Any, *, has_table: bool = False) -> str:
    """Render contact prose only when there is no structured table.

    Gemini summaries often use ``|`` between LinkedIn/Email/Social fields.
    That made ``md()`` treat the bullets as a markdown table — a second,
    broken contacts layout next to the real Name/Firm/Public-contacts table.
    """
    if not summary or has_table:
        return ""
    return f'<div class="analysis prose">{md(summary)}</div>'


def render_product_card(bits: dict[str, Any], url: Any) -> str:
    rows: list[tuple[str, str]] = []
    if bits.get("name"):
        rows.append(("Name", bits["name"]))
    if bits.get("forWhom"):
        rows.append(("Audience", bits["forWhom"]))
    if bits.get("what"):
        rows.append(("What it does", bits["what"]))
    if not rows and bits.get("blurb"):
        return f"<p>{esc(bits['blurb'])}</p>"
    bullets = bits.get("bullets") or []
    return f"""
    <div>
      {"".join(f'<div class="fact"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in rows)}
      {f'<div class="fact"><div class="k">Website</div><div class="v">{esc(host_from_url(url) or url)}</div></div>' if url else ""}
    </div>
    {f'<ul class="clean">{"".join(f"<li>{esc(b)}</li>" for b in bullets[:4])}</ul>' if bullets else ""}
  """


def render_performance_card(bits: dict[str, Any]) -> str:
    metrics = [
        m
        for m in (bits.get("metrics") or [])
        if m.get("label") and is_meaningful_metric_value(m.get("value"))
    ]
    if not metrics:
        return f"<p>{esc(clean_prose(bits.get('raw') or 'No metrics extracted.'))}</p>"
    notes = bits.get("notes") or []
    return f"""
    <div>
      {"".join(f'<div class="fact"><div class="k">{esc(m["label"])}</div><div class="v">{esc(m["value"])}</div></div>' for m in metrics[:8])}
    </div>
    {f'<ul class="clean">{"".join(f"<li>{esc(n)}</li>" for n in notes[:4])}</ul>' if notes else ""}
  """


def render_investor_table(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f"""<tr>
      <td><strong>{esc(r["name"])}</strong>{f'<div class="tiny">{esc(r["type"])}</div>' if r.get("type") else ""}</td>
      <td>{esc(r.get("whyRelevant") or r.get("thesis") or "—")}</td>
      <td>{esc(r.get("examplePortfolioCompanies") or "—")}</td>
    </tr>"""
        for r in rows
    )
    return (
        '<table class="data"><thead><tr>'
        '<th style="width:22%">Investor</th><th>Why relevant</th>'
        '<th style="width:26%">Example portfolio</th>'
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def render_benchmark_table(rows: list[dict[str, Any]]) -> str:
    show_metric = any(
        r.get("metricType")
        and is_short_metric_type(r["metricType"])
        and r["metricType"] != r.get("preInvestmentRevenue")
        for r in rows
    )
    body_parts = []
    for r in rows:
        metric_cell = (
            f'<td style="width:18%">{esc(r["metricType"] if is_short_metric_type(r.get("metricType")) else "—")}</td>'
            if show_metric
            else ""
        )
        body_parts.append(
            f"""<tr>
      <td style="width:24%"><strong>{esc(r["company"])}</strong>{f'<div class="tiny">{esc(r["round"])}</div>' if r.get("round") else ""}</td>
      <td style="width:24%">{esc(r.get("investor") or "—")}</td>
      <td style="width:{"34%" if show_metric else "52%"}">{esc(r.get("preInvestmentRevenue") or "")}</td>
      {metric_cell}
    </tr>"""
        )
    metric_head = '<th style="width:18%">Metric</th>' if show_metric else ""
    return (
        f'<table class="data"><thead><tr>'
        f'<th style="width:24%">Company</th><th style="width:24%">Investor</th>'
        f'<th style="width:{"34%" if show_metric else "52%"}">Pre-investment revenue</th>'
        f"{metric_head}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"
    )


def render_contact_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<div class="card"><p class="muted">'
            "No partner contacts with public LinkedIn, email, or social URLs were found."
            "</p></div>"
        )
    body_parts = []
    for c in rows:
        links: list[str] = []
        if c.get("linkedin"):
            links.append(render_contact_link("LinkedIn", c["linkedin"]))
        if c.get("email"):
            links.append(
                f'<a class="contact-link" href="mailto:{esc(c["email"])}">'
                f'<span class="contact-kind">Email</span>'
                f'<span class="contact-value">{esc(c["email"])}</span></a>'
            )
        if c.get("twitter"):
            links.append(render_contact_link("X / Twitter", c["twitter"]))
        for s in c.get("otherSocials") or []:
            if s:
                links.append(render_contact_link("Website / profile", s))
        body_parts.append(
            f"""<tr>
        <td><strong>{esc(c["name"])}</strong>{f'<div class="tiny">{esc(c["role"])}</div>' if c.get("role") else ""}</td>
        <td>{esc(c["firm"])}</td>
        <td><div class="contact-links">{"".join(links)}</div></td>
      </tr>"""
        )
    return (
        '<table class="data"><thead><tr>'
        '<th style="width:28%">Name</th><th style="width:28%">Firm</th>'
        f"<th>Public contacts</th></tr></thead><tbody>{''.join(body_parts)}</tbody></table>"
    )


def render_contact_link(kind: str, value: str) -> str:
    href = contact_href(value)
    display = display_contact_url(href)
    return (
        f'<a class="contact-link" href="{esc(href)}">'
        f'<span class="contact-kind">{esc(kind)}</span>'
        f'<span class="contact-value">{esc(display)}</span></a>'
    )


def contact_href(value: str) -> str:
    raw = str(value or "").strip()
    if re.match(r"^https?://", raw, re.I):
        return raw
    if re.match(r"^@?[A-Za-z0-9_]{1,30}$", raw):
        return f"https://x.com/{raw.lstrip('@')}"
    return raw


def display_contact_url(value: str) -> str:
    try:
        url = urlparse(value)
        path = (url.path or "").rstrip("/")
        host = (url.hostname or "").replace("www.", "")
        return f"{host}{path}{url.query and ('?' + url.query) or ''}"
    except Exception:
        return value


# -------------------- normalizers --------------------


def normalize_investors(investors: dict[str, Any]) -> list[dict[str, Any]]:
    structured = as_object(investors.get("structuredOutput"))
    rows = structured.get("investors") if isinstance(structured, dict) else None
    if not isinstance(rows, list) or not rows:
        rows = parse_investors_from_markdown(investors.get("investorSummary"))
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = clean_cell(r.get("name") or r.get("firm") or r.get("investor"))
        if not name:
            continue
        out.append(
            {
                "name": name,
                "type": clean_cell(r.get("type") or r.get("stage") or ""),
                "thesis": clean_cell(r.get("thesis") or ""),
                "whyRelevant": clean_cell(
                    r.get("whyRelevant")
                    or r.get("reason")
                    or r.get("fit")
                    or r.get("thesis")
                    or ""
                ),
                "examplePortfolioCompanies": clean_cell(
                    r.get("examplePortfolioCompanies")
                    or r.get("portfolio")
                    or r.get("examples")
                    or ""
                ),
            }
        )
    return out[:25]


def normalize_benchmarks(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    structured = as_object(portfolio.get("structuredOutput")) or {}
    nested = as_object(structured.get("content")) if isinstance(structured, dict) else None
    rows = None
    if isinstance(structured, dict) and isinstance(structured.get("benchmarks"), list):
        rows = structured["benchmarks"]
    elif isinstance(nested, dict) and isinstance(nested.get("benchmarks"), list):
        rows = nested["benchmarks"]
    if not rows:
        rows = parse_benchmarks_from_markdown(portfolio.get("portfolioRevenueSummary"))
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        company = clean_cell(r.get("company") or r.get("name"))
        investor = clean_cell(r.get("investor") or r.get("firm") or "")
        round_ = clean_cell(r.get("round") or r.get("stage") or r.get("timing") or "")
        pre = clean_cell(
            r.get("preInvestmentRevenue")
            or r.get("revenue")
            or r.get("arr")
            or r.get("mrr")
            or ""
        )
        metric_type = clean_cell(r.get("metricType") or r.get("metric") or "")
        if is_date_like(pre):
            if not round_:
                round_ = pre
            pre = ""
        if not pre and metric_type and not is_short_metric_type(metric_type):
            pre = metric_type
            metric_type = ""
        if pre and metric_type and not is_short_metric_type(metric_type):
            metric_type = (
                guess_metric_type(pre) or guess_metric_type(metric_type) or ""
            )
        if not metric_type:
            metric_type = guess_metric_type(pre)
        if company and pre:
            out.append(
                {
                    "company": company,
                    "investor": investor,
                    "round": round_,
                    "preInvestmentRevenue": pre,
                    "metricType": metric_type,
                }
            )
    return out[:25]


def normalize_contacts(
    list_: Any, *, require_reach: bool = False
) -> list[dict[str, Any]]:
    rows = list_ if isinstance(list_, list) else []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in rows:
        if not isinstance(c, dict):
            continue
        name = clean_cell(c.get("name"))
        firm = clean_cell(c.get("firm"))
        if not name or not firm:
            continue
        linkedin = clean_url(c.get("linkedin"))
        email = clean_email(c.get("email"))
        twitter = clean_cell(c.get("twitter") or "")
        other_raw = c.get("otherSocials")
        if isinstance(other_raw, list):
            other = [u for u in (clean_url(x) for x in other_raw) if u]
        else:
            other = [
                u
                for u in (
                    clean_url(x)
                    for x in re.split(r"[,;|]", str(other_raw or ""))
                    if x.strip()
                )
                if u
            ]
        # Drop junk / duplicate social URLs from enrichment noise.
        other = _dedupe_urls(
            [
                u
                for u in other
                if u
                and not re.search(r"not available|no personal|mentions her", u, re.I)
                and "instagram.com/popular/" not in u.lower()
            ]
        )
        if require_reach and not linkedin and not email and not twitter and not other:
            continue
        key = f"{name.lower()}|{firm.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "firm": firm,
                "role": clean_cell(c.get("role") or ""),
                "linkedin": linkedin,
                "email": email,
                "twitter": twitter,
                "otherSocials": other,
            }
        )
    return out[:50]


def collect_evidence(data: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for bucket in (
        (data.get("investors") or {}).get("sources"),
        (data.get("portfolioBenchmarks") or {}).get("sources"),
        (data.get("partnerContacts") or {}).get("sources"),
    ):
        for s in bucket or []:
            if not isinstance(s, dict):
                continue
            url = s.get("url")
            if not url or url in seen:
                continue
            seen.add(str(url))
            out.append({"title": str(s.get("title") or ""), "url": str(url)})
    return out[:40]


def parse_labeled_summary(text: Any) -> dict[str, Any]:
    raw = str(text or "").strip()
    name = (
        match_line(raw, r"(?:\*\*)?product name(?:\*\*)?[:\s]+(.+)", re.I)
        or match_line(raw, r"^\d+\)\s*product name[:\s]+(.+)", re.I | re.M)
        or match_line(raw, r"^product:\s*(.+)", re.I | re.M)
    )
    what = match_line(raw, r"(?:\d+\)\s*)?what it does[:\s]+(.+)", re.I) or match_line(
        raw, r"(?:description)[:\s]+(.+)", re.I
    )
    for_whom = match_line(
        raw, r"(?:\d+\)\s*)?(?:who it is for|audience)[:\s]+(.+)", re.I
    )
    bullets = [
        strip_md(m.group(1))
        for m in re.finditer(r"^[-*•]\s+(.+)$", raw, re.M)
        if strip_md(m.group(1))
    ]
    prose_line = ""
    for line in raw.splitlines():
        l = line.strip()
        if not l:
            continue
        if re.match(r"^\d+\)", l):
            continue
        if re.search(
            r"product name|who it is for|notable|capabilities|^[-*•]|^#{1,3}",
            l,
            re.I,
        ):
            continue
        if len(l) > 40:
            prose_line = l
            break
    return {
        "name": re.sub(r"^\d+\)\s*", "", clean_label(name)),
        "what": clean_label(what),
        "forWhom": clean_label(for_whom),
        "bullets": [clean_label(b) for b in bullets[:4] if clean_label(b)],
        "blurb": clean_label(prose_line)[:220],
    }


def parse_performance(text: Any) -> dict[str, Any]:
    raw = str(text or "").strip()
    metrics: list[dict[str, str]] = []
    patterns = [
        (r"\bARR\b[^$0-9]{0,20}(\$?\d[\d.,]*\s*[kmb]?)", "ARR"),
        (r"\bMRR\b[^$0-9]{0,20}(\$?\d[\d.,]*\s*[kmb]?)", "MRR"),
        (r"\brevenue\b[^$0-9]{0,20}(\$?\d[\d.,]*\s*[kmb]?)", "Revenue"),
        (r"gross margin[^0-9%]{0,12}(\d[\d.]*\s*%)", "Gross margin"),
        (r"net.?margin[^0-9%]{0,12}(\d[\d.]*\s*%)", "Net margin"),
        (r"churn[^0-9%]{0,12}(\d[\d.]*\s*%?)", "Churn"),
        (r"customers?[^0-9]{0,12}(\d[\d,]*)", "Customers"),
        (r"growth[^0-9%]{0,16}(\d[\d.]*\s*%[^.\n]*)", "Growth"),
    ]
    for pat, label in patterns:
        m = re.search(pat, raw, re.I)
        if m and is_meaningful_metric_value(m.group(1)):
            metrics.append({"label": label, "value": m.group(1).strip()})
    for line in raw.splitlines():
        m = re.match(
            r"^\s*[-*]?\s*\*?\*?([A-Za-z][A-Za-z /%]{1,24})\*?\*?\s*[:=]\s*(.+)$",
            line,
        )
        if not m:
            continue
        label = strip_md(m.group(1)).strip()
        value = strip_md(m.group(2)).strip()
        if not label or not is_meaningful_metric_value(value) or len(value) > 60:
            continue
        if not any(x["label"].lower() == label.lower() for x in metrics):
            metrics.append({"label": label, "value": value})
    notes = [
        strip_md(m.group(1))
        for m in re.finditer(r"^[-*•]\s+(.+)$", raw, re.M)
        if strip_md(m.group(1)) and not re.match(r"^(arr|mrr|revenue)\b", strip_md(m.group(1)), re.I)
    ][:5]
    return {
        "metrics": [m for m in metrics if is_meaningful_metric_value(m["value"])][:8],
        "notes": notes,
        "raw": raw,
    }


def parse_investors_from_markdown(summary: Any) -> list[dict[str, Any]]:
    text = str(summary or "")
    table_rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "|" not in line or re.match(r"^\s*\|?\s*-+", line):
            continue
        cells = [strip_md(c).strip() for c in line.split("|") if strip_md(c).strip()]
        if len(cells) < 2:
            continue
        if re.match(r"^(investor|name|firm)", cells[0], re.I):
            continue
        table_rows.append(
            {
                "name": cells[0],
                "type": cells[1] if len(cells) > 1 else "",
                "whyRelevant": cells[2] if len(cells) > 2 else (cells[1] if len(cells) > 1 else ""),
                "examplePortfolioCompanies": cells[3] if len(cells) > 3 else "",
            }
        )
    if table_rows:
        return table_rows
    bullets: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(
            r"^\s*(?:\d+[.)]\s+|[-*•]\s+)\*?\*?(.+?)\*?\*?(?:\s*(?:—+|-+|:)\s*(.+))?$",
            line,
        )
        if not m:
            continue
        name = strip_md(m.group(1)).split("—")[0].split("–")[0].split("(")[0].strip()
        if not name or len(name) > 80 or re.match(r"^(top|gaps|focus|example)", name, re.I):
            continue
        why = strip_md(
            m.group(2) or re.sub(r"^\s*(?:\d+[.)]\s+|[-*•]\s+)", "", line)
        )[:280]
        bullets.append(
            {"name": name, "whyRelevant": why, "examplePortfolioCompanies": ""}
        )
    return bullets


def parse_benchmarks_from_markdown(summary: Any) -> list[dict[str, Any]]:
    text = str(summary or "")
    table_rows: list[dict[str, Any]] = []
    headers: list[str] = []
    for line in text.splitlines():
        if "|" not in line or re.match(r"^\s*\|?\s*[-:| ]+\s*$", line):
            continue
        cells = [strip_md(c).strip() for c in line.split("|") if strip_md(c).strip()]
        if len(cells) < 2:
            continue
        if _is_benchmark_header_row(cells):
            headers = [c.lower() for c in cells]
            continue

        def idx(names: list[str]) -> int:
            for i, h in enumerate(headers):
                if any(n in h for n in names):
                    return i
            return -1

        company_i = max(0, idx(["company", "name"])) if headers else 0
        investor_i = idx(["investor", "firm"]) if headers else 1
        revenue_i = (
            idx(["pre-investment", "pre investment", "revenue", "arr", "mrr"])
            if headers
            else (3 if len(cells) >= 4 else 2)
        )
        metric_i = idx(["metric type", "metric", "type"]) if headers else -1
        round_i = (
            idx(["round", "stage", "timing", "date", "funding"])
            if headers
            else (2 if len(cells) >= 4 else -1)
        )
        company = cells[company_i] if company_i < len(cells) else cells[0]
        if not company or re.match(
            r"^\(?(no other|benchmark note|outlier)", company, re.I
        ):
            continue
        investor = (
            (cells[investor_i] if 0 <= investor_i < len(cells) else "")
            or (cells[1] if len(cells) > 1 else "")
        )
        pre = cells[revenue_i] if 0 <= revenue_i < len(cells) else ""
        metric_type = cells[metric_i] if 0 <= metric_i < len(cells) else ""
        round_ = cells[round_i] if 0 <= round_i < len(cells) else ""
        if not pre and len(cells) >= 3:
            pre = cells[3 if len(cells) >= 4 else 2]
        if is_date_like(pre) or _is_round_like(pre):
            if not round_:
                round_ = pre
            pre = metric_type if metric_type and not is_short_metric_type(metric_type) else ""
            if not is_short_metric_type(metric_type):
                metric_type = ""
        if not pre:
            continue
        table_rows.append(
            {
                "company": company,
                "investor": investor,
                "preInvestmentRevenue": pre,
                "metricType": metric_type,
                "round": round_,
            }
        )
    return table_rows


# -------------------- markdown → html --------------------


def md(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return '<p class="muted">—</p>'
    blocks = [b.strip() for b in re.split(r"\n{2,}", raw) if b.strip()]
    rendered: list[str] = []
    for block in blocks:
        lines = [l.rstrip() for l in block.splitlines()]
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            continue
        heading_text = re.sub(r"^#{1,6}\s+", "", non_empty[0]).replace("\u2013", "-")
        looks_like_heading = bool(re.match(r"^#{1,6}\s+", non_empty[0])) or bool(
            re.match(
                r"^(Quick take-?aways?|Top relevant|Their apparent|Example portfolio|Gaps|Focus|Notes|Summary|Strongest matches|Secondary matches|Take-?away)\b",
                heading_text,
                re.I,
            )
        )
        if looks_like_heading:
            title = strip_md(re.sub(r"^#{1,6}\s+", "", non_empty[0]))
            rest = non_empty[1:]
            if not rest:
                rendered.append(f"<h3>{esc(title)}</h3>")
                continue
            if looks_like_markdown_table(rest):
                table = render_markdown_table(rest)
                if table:
                    rendered.append(f"<h3>{esc(title)}</h3>{table}")
                    continue
            if all(re.match(r"^([-•*]|\d+[.)])\s+", l.strip()) for l in rest):
                ordered = all(re.match(r"^\d+[.)]\s+", l.strip()) for l in rest)
                tag = "ol" if ordered else "ul"
                items = "".join(
                    f"<li>{inline_md(esc(strip_md(re.sub(r'^([-•*]|\\d+[.)])\\s+', '', l.strip()))))}</li>"
                    for l in rest
                )
                rendered.append(f"<h3>{esc(title)}</h3><{tag}>{items}</{tag}>")
                continue
            rendered.append(
                f"<h3>{esc(title)}</h3><p>{inline_md(esc(strip_md(chr(10).join(rest))).replace(chr(10), '<br/>'))}</p>"
            )
            continue
        if looks_like_markdown_table(non_empty):
            table = render_markdown_table(non_empty)
            if table:
                rendered.append(table)
                continue
        if all(re.match(r"^([-•*]|\d+[.)])\s+", l.strip()) for l in non_empty):
            ordered = all(re.match(r"^\d+[.)]\s+", l.strip()) for l in non_empty)
            tag = "ol" if ordered else "ul"
            items = "".join(
                f"<li>{inline_md(esc(strip_md(re.sub(r'^([-•*]|\\d+[.)])\\s+', '', l.strip()))))}</li>"
                for l in non_empty
            )
            rendered.append(f"<{tag}>{items}</{tag}>")
            continue
        if any(re.match(r"^([-•*]|\d+[.)])\s+", l.strip()) for l in non_empty):
            parts: list[str] = []
            buf: list[str] = []
            list_buf: list[str] = []

            def flush_buf() -> None:
                nonlocal buf
                if buf:
                    parts.append(
                        f"<p>{inline_md(esc(strip_md(chr(10).join(buf))).replace(chr(10), '<br/>'))}</p>"
                    )
                    buf = []

            def flush_list() -> None:
                nonlocal list_buf
                if list_buf:
                    items = "".join(
                        f"<li>{inline_md(esc(strip_md(re.sub(r'^([-•*]|\\d+[.)])\\s+', '', l))))}</li>"
                        for l in list_buf
                    )
                    parts.append(f"<ul>{items}</ul>")
                    list_buf = []

            for line in non_empty:
                if re.match(r"^([-•*]|\d+[.)])\s+", line.strip()):
                    flush_buf()
                    list_buf.append(line.strip())
                else:
                    flush_list()
                    buf.append(line)
            flush_buf()
            flush_list()
            rendered.append("".join(parts))
            continue
        rendered.append(
            f"<p>{inline_md(esc(strip_md(block)).replace(chr(10), '<br/>'))}</p>"
        )
    return "".join(rendered)


def inline_md(escaped: str) -> str:
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"#{1,6}\s+", "", escaped)
    return escaped


def looks_like_markdown_table(lines: list[str]) -> bool:
    # Bullet / numbered lines with " | " separators are NOT tables
    # (common in contact summaries: "LinkedIn: … | Email: …").
    non_list = [
        l
        for l in lines
        if not re.match(r"^\s*([-•*]|\d+[.)])\s+", l.strip())
    ]
    pipe_lines = [l for l in non_list if "|" in l]
    if len(pipe_lines) < 2:
        return False
    has_sep = any(re.match(r"^\s*\|?\s*[-:| ]+\s*\|?\s*$", l) for l in lines)
    if has_sep:
        return True
    return len(pipe_lines) >= max(2, (len(non_list) + 1) // 2) and all(
        "|" in l for l in non_list[:2]
    )


def parse_markdown_row(line: str) -> list[str]:
    parts = [c.strip() for c in line.split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def repair_table_cells(cells: list[str], expected_cols: int) -> list[str]:
    if len(cells) >= expected_cols:
        return cells[:expected_cols]
    if expected_cols == 2 and len(cells) == 1:
        text = cells[0]
        split = re.split(r"\s+[–—-]\s+|\s{2,}|:\s+", text)
        if len(split) >= 2:
            return [split[0].strip(), " — ".join(split[1:]).strip()]
    while len(cells) < expected_cols:
        cells.append("")
    return cells


def render_markdown_table(lines: list[str]) -> str:
    rows = [
        l
        for l in lines
        if "|" in l and not re.match(r"^\s*\|?\s*[-:| ]+\s*\|?\s*$", l)
    ]
    if len(rows) < 2:
        return ""
    header = [c for c in parse_markdown_row(rows[0]) if c]
    if not header:
        return ""
    col_count = len(header)
    widths = (
        ["28%", "72%"]
        if col_count == 2
        else (["24%", "38%", "38%"] if col_count == 3 else None)
    )
    def _style(i: int) -> str:
        if widths and i < len(widths):
            return f' style="width:{widths[i]}"'
        return ""

    body = []
    for r in rows[1:]:
        cells = repair_table_cells(parse_markdown_row(r), col_count)
        body.append(
            "<tr>"
            + "".join(
                f"<td{_style(i)}>{inline_md(esc(strip_md(c)))}</td>"
                for i, c in enumerate(cells)
            )
            + "</tr>"
        )
    head = "".join(
        f"<th{_style(i)}>{inline_md(esc(strip_md(h)))}</th>"
        for i, h in enumerate(header)
    )
    return f'<table class="data avoid"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


# -------------------- helpers --------------------


def as_object(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        # Exa sometimes nests under content
        content = value.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            nested = as_object(content)
            return nested or value
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            start = value.find("{")
            end = value.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(value[start : end + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def cover_lede(bits: dict[str, Any]) -> str:
    if bits.get("what"):
        return str(bits["what"])[:240]
    blurb = bits.get("blurb") or ""
    if blurb and not re.search(r"product name", blurb, re.I):
        return str(blurb)[:240]
    return (
        "Full investor outreach findings — product, traction, shortlist, "
        "benchmarks, and partner contacts."
    )


def clean_prose(text: Any) -> str:
    return re.sub(r"\n{3,}", "\n\n", strip_md(str(text or ""))).strip()[:800]


def clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", strip_md(str(value if value is not None else ""))).strip()[
        :320
    ]


def clean_label(value: Any) -> str:
    return re.sub(r"\s+", " ", strip_md(str(value or "")).lstrip(":- ").strip())


def clean_url(value: Any) -> str:
    v = str(value or "").strip()
    if not v or not re.match(r"^https?://", v, re.I):
        return ""
    return v


def clean_email(value: Any) -> str:
    v = str(value or "").strip()
    if not v or not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
        return ""
    if "*" in v:
        return ""
    return v


def strip_md(value: Any) -> str:
    s = str(value or "")
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    s = re.sub(r"[\u00A0\u202F\u2007]", " ", s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.M)
    s = re.sub(r"\*\*([\s\S]+?)\*\*", r"\1", s)
    s = re.sub(r"__([\s\S]+?)__", r"\1", s)
    s = re.sub(r"(^|[\s(])\*([^*\n]+?)\*(?=[\s).,;:!?]|$)", r"\1\2", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
    s = re.sub(r"\*{1,2}", "", s)
    s = re.sub(r"^#+\s*", "", s, flags=re.M)
    s = re.sub(r"\s*#+\s*$", "", s, flags=re.M)
    return s.strip()


def match_line(text: Any, pattern: str, flags: int = 0) -> str:
    m = re.search(pattern, str(text or ""), flags)
    return m.group(1).strip() if m else ""


def extract_product_name(summary: Any) -> str:
    return parse_labeled_summary(summary).get("name") or ""


def host_from_url(url: Any) -> str:
    try:
        host = urlparse(str(url or "")).hostname or ""
        return host.replace("www.", "")
    except Exception:
        return ""


def unique(arr: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for v in arr:
        k = str(v).lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        key = u.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def esc(value: Any) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def is_meaningful_metric_value(value: Any) -> bool:
    v = (
        re.sub(r"[\u2010-\u2015\u2212]", "-", str(value or ""))
        .replace("\u00a0", " ")
        .strip()
    )
    if not v or len(v) < 2 or not re.search(r"\d", v):
        return False
    if re.match(r"^[\s$]?[\d]?[.,]+$", v):
        return False
    if re.match(r"^\d{1,2}\.$", v):
        return False
    if re.match(r"^(19|20)\d{2}$", v):
        return False
    if re.match(r"^\$?[\d,]+(\.\d+)?\s*[kmb%]?\b", v, re.I):
        return True
    if re.search(r"\d", v) and re.search(r"[$%kmb]", v, re.I):
        return True
    return len(v) >= 4 and bool(re.sub(r"[.,\s]", "", v))


def is_date_like(value: Any) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return True
    if re.match(
        r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}", v, re.I
    ):
        return True
    if re.match(r"^q[1-4]\s*'?\d{2,4}$", v, re.I):
        return True
    return bool(re.search(r"timing of round", v, re.I))


def is_short_metric_type(value: Any) -> bool:
    v = str(value or "").strip()
    if not v or len(v) > 24:
        return False
    return bool(
        re.match(r"^(arr|mrr|revenue|gmv|arr/mrr|net revenue|bookings)$", v, re.I)
    )


def guess_metric_type(value: Any) -> str:
    v = str(value or "").lower()
    if not v:
        return ""
    if re.search(r"\b(no|not|without|undisclosed)\b.{0,24}\b(arr|mrr|revenue|gmv)\b", v):
        return ""
    if re.search(r"\$?\d[\d.,]*\s*[kmb]?\s*arr\b|\barr\b\s*[:of]|\bpre-investment arr\b", v):
        return "ARR"
    if re.search(r"\$?\d[\d.,]*\s*[kmb]?\s*mrr\b|\bmrr\b\s*[:of]", v):
        return "MRR"
    if re.search(r"\bgmv\b", v):
        return "GMV"
    if re.search(r"\$?\d[\d.,]*\s*[kmb]?\s*revenue\b|\brevenue\b\s*[:of]", v):
        return "Revenue"
    return ""


def _is_benchmark_header_row(cells: list[str]) -> bool:
    first = str(cells[0] or "").lower()
    if re.search(r"portfolio\s*company|^company\b|^name\b", first):
        return True
    joined = " ".join(cells).lower()
    return "investor" in joined and bool(
        re.search(r"(revenue|arr|mrr|metric)", joined)
    ) and len(cells) >= 3


def _is_round_like(value: Any) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    if re.match(r"^(pre-?seed|seed|series\s*[a-d]|angel|bridge)\b", v, re.I):
        return True
    if re.search(r"\b(closed|raised)\s+\$", v) and not re.search(
        r"\$?\d[\d.]*\s*[kmb]?\s*(arr|mrr|revenue)", v, re.I
    ):
        return True
    return False
