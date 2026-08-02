from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


def esc(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def build_report_html(data: dict[str, Any]) -> str:
    product_name = str(data.get("product_name") or "Product")
    product_url = data.get("product_url")
    competitors = list(data.get("competitors") or [])
    feature_diff = dict(data.get("feature_diff") or {})
    pricing = dict(data.get("pricing") or {})
    positioning = dict(data.get("positioning") or {})
    insights = dict(data.get("insights") or {})
    charts = list(data.get("charts") or [])
    generated_at = str(
        data.get("generated_at") or datetime.now(timezone.utc).isoformat()
    )
    try:
        date_label = datetime.fromisoformat(
            generated_at.replace("Z", "+00:00")
        ).strftime("%B %d, %Y")
    except ValueError:
        date_label = generated_at[:10]

    swot = positioning.get("swot") or {}
    pos_map = positioning.get("positioning_map") or {
        "axes": ["price", "feature breadth"],
        "points": [],
    }
    recs = list(positioning.get("recommended_positioning") or [])
    risks = list(positioning.get("risks") or [])
    coverage = _coverage_scores(feature_diff)
    price_rng = _price_range(pricing)
    undisclosed = sum(
        1
        for c in pricing.get("competitor_pricing") or []
        if not any(isinstance(t.get("price"), (int, float)) for t in (c.get("tiers") or []))
    )
    edges = _feature_edges(feature_diff, product_name)
    axes = list(pos_map.get("axes") or ["price", "feature breadth"])
    if len(axes) < 2:
        axes = ["price", "feature breadth"]

    lead_bullets = (
        "".join(f"<li>{esc(e)}</li>" for e in edges["edges"])
        or "".join(f"<li>{esc(s)}</li>" for s in (swot.get("strengths") or [])[:3])
        or "<li class='muted'>No clear feature lead detected from public pages.</li>"
    )
    gap_bullets = (
        "".join(f"<li>{esc(e)}</li>" for e in edges["gaps"])
        or "".join(f"<li>{esc(s)}</li>" for s in (swot.get("weaknesses") or [])[:3])
        or "<li class='muted'>No obvious gaps versus peers.</li>"
    )
    rec_exec = (
        "".join(
            f"<li><strong>{esc(r.get('angle'))}</strong><br/>"
            f"<span class=\"muted\">{esc('; '.join(r.get('supporting_facts') or []))}</span></li>"
            for r in recs[:4]
        )
        or "<li class='muted'>Positioning synthesis unavailable.</li>"
    )
    competitor_rows = "".join(
        f"""<tr>
            <td class="feat">{esc(c.get('name'))}</td>
            <td class="muted">{esc(c.get('url'))}</td>
            <td>{_confidence_badge(float(c.get('confidence') or 0))}</td>
            <td class="muted">{esc(', '.join(c.get('sources') or []))}</td>
          </tr>"""
        for c in competitors
    )
    url_chip = (
        f'<span class="url">{esc(product_url)}</span>' if product_url else ""
    )
    map_html = _render_map(pos_map, product_name, axes)
    competitor_price_cards = "".join(
        _competitor_price_card(c, price_rng["max"])
        for c in pricing.get("competitor_pricing") or []
    )
    rec_cards = (
        "".join(
            f"""<div class="rec-card"><div class="rec-n">{str(i + 1).zfill(2)}</div>
            <div><strong>{esc(r.get('angle'))}</strong>
            <div class="muted" style="margin-top:4px">{esc('; '.join(r.get('supporting_facts') or []))}</div>
            </div></div>"""
            for i, r in enumerate(recs)
        )
        or "<div class='rec-card muted'>No recommendations generated.</div>"
    )
    sources = "".join(f"<li>{esc(s)}</li>" for s in _collect_sources(data))
    risk_lis = (
        "".join(f"<li>{esc(r)}</li>" for r in risks)
        or "<li class='muted'>None flagged.</li>"
    )
    leaders = "".join(
        f"<li><strong>{esc(c['name'])}</strong> — {round(c['score'] * 100)}% of tracked dimensions evidenced</li>"
        for c in _coverage_leaders(coverage)
    )
    insight_headline = esc(str(insights.get("headline") or ""))
    chart_blocks = []
    for c in charts:
        data_uri = c.get("data_uri") or ""
        if not data_uri:
            continue
        chart_blocks.append(
            f"""
      <section class="viz avoid">
        <h3>{esc(str(c.get("title") or "Chart"))}</h3>
        <p class="viz-cap">{esc(str(c.get("caption") or ""))}</p>
        <img class="viz-img" src="{data_uri}" alt="{esc(str(c.get("title") or "chart"))}" />
      </section>"""
        )
    visuals_section = ""
    if chart_blocks or insight_headline:
        visuals_section = f"""
  <div class="section-head break"><span class="num">02</span><h2>Attack visuals</h2><span class="tag">Gemini charts</span></div>
  {"<p class='lead'>" + insight_headline + "</p>" if insight_headline else ""}
  <p class="lead">Strategy charts synthesized from this run — steal-share priority, ICP ownership, category posture, and lock-in forces (when public signal exists).</p>
  {"".join(chart_blocks)}
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Competitor Research — {esc(product_name)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:ital,opsz,wght@0,14..32,400;0,14..32,500;0,14..32,600;0,14..32,700;1,14..32,400&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --ink: #241a1c; --muted: #7c6b6e; --wash: #ffffff; --card: #ffffff;
      --line: #ecdcdd; --line-strong: #ddc7c9; --red: #c1202a; --red-deep: #8f1119;
      --red-bright: #e8443a; --red-soft: #fbeceb; --red-tint: #fdf5f4;
      --ok: #1c7a4a; --ok-soft: #e7f4ec; --warn: #9a5a17; --warn-soft: #fbf0e0;
      --bad: #b52a20; --bad-soft: #fbe8e6;
      --shadow: 0 1px 2px rgba(36,26,28,0.05), 0 10px 28px rgba(143,17,25,0.06);
    }}
    * {{ box-sizing: border-box; }}
    @page {{ size: A4; margin: 12mm 11mm 15mm; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      color: var(--ink); background: var(--wash);
      font-family: "Inter", system-ui, sans-serif; font-size: 9.6pt; line-height: 1.45;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}
    h1, h2, h3, h4, .display {{
      font-family: "Space Grotesk", "Inter", sans-serif;
      font-weight: 700; letter-spacing: -0.01em; margin: 0;
    }}
    p {{ margin: 0 0 6px; }}
    .muted {{ color: var(--muted); }}
    .break {{ break-before: page; }}
    .avoid {{ break-inside: avoid; }}
    .cover {{
      break-after: page; position: relative; overflow: hidden;
      min-height: 262mm; border-radius: 16px; color: #fff;
      padding: 30px; display: flex; flex-direction: column; justify-content: space-between;
      background:
        radial-gradient(90% 60% at 88% 4%, rgba(255,180,170,0.30), transparent 60%),
        linear-gradient(155deg, #7d0f16 0%, #b81d26 46%, #e8443a 120%);
      box-shadow: var(--shadow);
    }}
    .cover > * {{ position: relative; }}
    .cover-top {{
      display: flex; justify-content: space-between; align-items: center;
      font-size: 8.5pt; letter-spacing: 0.14em; text-transform: uppercase;
      color: rgba(255,255,255,0.82); font-weight: 600;
    }}
    .cover-mark {{ display: flex; align-items: center; gap: 8px; }}
    .cover-mark .dot {{ width: 9px; height: 9px; border-radius: 2px; background:#fff; }}
    .eyebrow {{ font-size: 10pt; letter-spacing: 0.22em; text-transform: uppercase; color: rgba(255,255,255,0.72); font-weight: 600; }}
    .cover h1 {{ font-size: 58pt; line-height: 0.98; margin: 12px 0 0; color: #fff; }}
    .cover .lede {{ margin-top: 16px; max-width: 30rem; font-size: 12pt; color: rgba(255,255,255,0.9); }}
    .cover .url {{
      display: inline-block; margin-top: 16px; font-size: 9pt; font-weight: 600;
      padding: 5px 12px; border-radius: 999px; background: rgba(255,255,255,0.14);
      border: 1px solid rgba(255,255,255,0.28);
    }}
    .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 30px; }}
    .kpi {{
      background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.20);
      border-radius: 12px; padding: 13px 14px;
    }}
    .kpi .k-label {{ font-size: 7.5pt; letter-spacing: 0.08em; text-transform: uppercase; color: rgba(255,255,255,0.72); }}
    .kpi .k-value {{ font-family: "Space Grotesk", sans-serif; font-weight: 700; font-size: 19pt; margin-top: 5px; }}
    .kpi .k-sub {{ font-size: 7.5pt; color: rgba(255,255,255,0.66); margin-top: 2px; }}
    .cover-bottom {{
      display: flex; justify-content: space-between; align-items: flex-end; gap: 20px;
      border-top: 1px solid rgba(255,255,255,0.22); padding-top: 16px; margin-top: 26px;
    }}
    .contents {{ columns: 2; column-gap: 26px; font-size: 9pt; color: rgba(255,255,255,0.9); max-width: 60%; }}
    .contents div {{ break-inside: avoid; padding: 3px 0; display: flex; gap: 8px; }}
    .contents span.n {{ color: rgba(255,255,255,0.55); font-weight: 600; }}
    .cover-date {{ text-align: right; font-size: 8.5pt; color: rgba(255,255,255,0.78); }}
    .cover-date strong {{ display:block; font-family:"Space Grotesk"; font-size: 12pt; color:#fff; margin-top:3px; }}
    .section-head {{ display: flex; align-items: baseline; gap: 12px; margin: 22px 0 12px; break-after: avoid; }}
    .section-head .num {{
      font-family: "Space Grotesk"; font-weight: 700; font-size: 12pt; color: var(--red);
      background: var(--red-soft); border: 1px solid #f3d3d1; border-radius: 8px; padding: 2px 9px;
    }}
    .section-head h2 {{ font-size: 17pt; }}
    .section-head .tag {{ margin-left: auto; font-size: 7.5pt; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); font-weight: 600; }}
    .lead {{ color: var(--muted); font-size: 9.4pt; margin: -4px 0 12px; max-width: 46rem; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .card {{
      background: var(--card); border: 1px solid var(--line); border-radius: 12px;
      padding: 13px 15px; box-shadow: var(--shadow); break-inside: avoid;
    }}
    .card h3 {{ font-size: 10.5pt; margin-bottom: 8px; }}
    .card h3 .accent {{ color: var(--red); }}
    .kicker {{ font-size: 7.5pt; letter-spacing: 0.12em; text-transform: uppercase; color: var(--red); font-weight: 700; margin-bottom: 6px; }}
    ul.clean {{ padding-left: 1.05em; margin: 6px 0; }}
    ul.clean li {{ margin: 4px 0; }}
    ol.rec {{ padding-left: 1.1em; margin: 6px 0; }}
    ol.rec li {{ margin: 0 0 9px; break-inside: avoid; }}
    .rec-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 6px; }}
    .rec-card {{
      display: flex; gap: 12px; background: var(--card); border: 1px solid var(--line);
      border-left: 3px solid var(--red); border-radius: 12px; padding: 13px 15px; box-shadow: var(--shadow); break-inside: avoid;
    }}
    .rec-n {{ font-family: "Space Grotesk"; font-weight: 700; font-size: 15pt; color: var(--red); }}
    ul.method {{ list-style: none; margin: 4px 0 0; padding: 0; }}
    ul.method li {{ display: flex; justify-content: space-between; gap: 10px; padding: 5px 0; border-bottom: 1px dashed var(--line); font-size: 8.8pt; }}
    ul.method li:last-child {{ border-bottom: 0; }}
    ul.method span {{ color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; font-size: 7.6pt; font-weight: 700; }}
    ul.method b {{ text-align: right; font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 8.6pt; margin: 6px 0; background:#fff; border-radius: 10px; overflow: hidden; box-shadow: var(--shadow); }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 7px 9px; text-align: left; vertical-align: middle; }}
    thead th {{ background: linear-gradient(180deg,#fff,#fdf2f1); color: var(--red-deep); font-family:"Space Grotesk"; font-weight: 600; font-size: 8pt; text-transform: uppercase; letter-spacing: 0.04em; }}
    tbody tr:nth-child(even) td {{ background: #fdf8f8; }}
    td.feat {{ font-weight: 600; }}
    .coverage-row td {{ background: var(--red-tint) !important; font-weight: 700; color: var(--red-deep); }}
    .badge {{ display: inline-flex; align-items: center; gap: 4px; border-radius: 6px; padding: 2px 7px; font-size: 7.6pt; font-weight: 700; white-space: nowrap; }}
    .badge-yes {{ background: var(--ok-soft); color: var(--ok); }}
    .badge-partial {{ background: var(--warn-soft); color: var(--warn); }}
    .badge-no {{ background: var(--bad-soft); color: var(--bad); }}
    .badge-unknown, .badge-muted {{ background: #f1ebec; color: var(--muted); }}
    .price-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }}
    .tier-list {{ margin: 0; padding: 0; list-style: none; }}
    .tier-list li {{ display: flex; justify-content: space-between; gap: 8px; padding: 5px 0; border-bottom: 1px dashed var(--line); font-size: 9pt; }}
    .tier-list li:last-child {{ border-bottom: 0; }}
    .tier-list .amt {{ font-family:"Space Grotesk"; font-weight:600; white-space:nowrap; }}
    .price-bar {{ margin-top: 8px; height: 7px; border-radius: 999px; background: #f1e6e7; overflow: hidden; }}
    .price-bar > span {{ display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--red), var(--red-bright)); }}
    .chart {{ display: grid; grid-template-columns: 20px 1fr; grid-template-rows: 1fr 20px; gap: 6px; margin-top: 10px; }}
    .chart-yaxis {{ grid-row:1; grid-column:1; writing-mode: vertical-rl; transform: rotate(180deg); text-align:center; font-size:7.6pt; color:var(--muted); text-transform:uppercase; letter-spacing:0.08em; font-weight:600; }}
    .chart-xaxis {{ grid-row:2; grid-column:2; text-align:center; font-size:7.6pt; color:var(--muted); text-transform:uppercase; letter-spacing:0.08em; font-weight:600; }}
    .map-wrap {{
      grid-row:1; grid-column:2; position: relative; height: 300px;
      border: 1px solid var(--line-strong); border-radius: 14px; overflow: hidden;
      background:
        linear-gradient(#f4e9ea 1px, transparent 1px) 0 0 / 100% 25%,
        linear-gradient(90deg, #f4e9ea 1px, transparent 1px) 0 0 / 25% 100%, #fff;
    }}
    .midline {{ position:absolute; background: #f0dede; }}
    .midline.h {{ left:0; right:0; top:50%; height:1px; }}
    .midline.v {{ top:0; bottom:0; left:50%; width:1px; }}
    .quad-label {{ position:absolute; font-size:6.8pt; color:#c3a9ab; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; max-width:40%; }}
    .quad-tl {{ top:6px; left:8px; }} .quad-tr {{ top:6px; right:8px; text-align:right; }}
    .quad-bl {{ bottom:6px; left:8px; }} .quad-br {{ bottom:6px; right:8px; text-align:right; }}
    .map-point {{ position:absolute; transform: translate(-50%, 50%); width:10px; height:10px; border-radius:50%; background: var(--red); border:2px solid #fff; box-shadow: 0 0 0 1px var(--red); z-index:2; }}
    .map-point.product {{ background:#1c1c1c; box-shadow:0 0 0 1px #1c1c1c; width:12px; height:12px; border-radius:3px; z-index:3; }}
    .map-label {{ position:absolute; font-size:7.2pt; white-space:nowrap; color:var(--ink); font-weight:600; background:rgba(255,255,255,0.94); padding:1px 5px; border:1px solid var(--line); border-radius:4px; z-index:2; }}
    .map-label.product {{ color:#000; border-color:#cfcfcf; }}
    .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:9px; font-size:8pt; color:var(--muted); }}
    .legend span {{ display:inline-flex; align-items:center; gap:6px; }}
    .legend i {{ display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--red); }}
    .legend i.product {{ background:#1c1c1c; border-radius:2px; }}
    .swot {{ display:grid; grid-template-columns: 1fr 1fr; gap:10px; }}
    .swot .card {{ padding: 11px 13px; }}
    .swot .card h3 {{ display:flex; align-items:center; gap:7px; }}
    .swot-s {{ border-color:#cfe8db; background: linear-gradient(180deg,#f2fbf6,#fff); }} .swot-s h3 {{ color: var(--ok); }}
    .swot-w {{ border-color:#f0dcb9; background: linear-gradient(180deg,#fdf6ea,#fff); }} .swot-w h3 {{ color: var(--warn); }}
    .swot-o {{ border-color:#f2cfcd; background: linear-gradient(180deg,#fdf1f0,#fff); }} .swot-o h3 {{ color: var(--red); }}
    .swot-t {{ border-color:#efc9c4; background: linear-gradient(180deg,#fceae7,#fff); }} .swot-t h3 {{ color: var(--bad); }}
    .note {{ font-size: 7.8pt; color: var(--muted); margin-top: 6px; }}
    .sources {{ font-size: 7.9pt; columns: 2; column-gap: 22px; }}
    .sources li {{ margin-bottom: 3px; word-break: break-all; break-inside: avoid; }}
    .viz {{ margin: 0 0 16px; }}
    .viz h3 {{ font-size: 11pt; margin: 0 0 4px; color: var(--red-deep); }}
    .viz-cap {{ color: var(--muted); font-size: 8.5pt; margin: 0 0 8px; }}
    .viz-img {{
      width: 100%; max-height: 210mm; object-fit: contain;
      border: 1px solid var(--line); border-radius: 12px; background: #fff;
      box-shadow: var(--shadow);
    }}
  </style>
</head>
<body>
  <section class="cover">
    <div class="cover-top">
      <div class="cover-mark"><span class="dot"></span> FounderBlaze</div>
      <div>Competitive Intelligence Report</div>
    </div>
    <div class="cover-mid">
      <div class="eyebrow">Competitor Research</div>
      <h1>{esc(product_name)}</h1>
      <p class="lede">A data-backed read of the competitive landscape — feature coverage, pricing posture, and where to position against the field.</p>
      {url_chip}
      <div class="kpis">
        <div class="kpi"><div class="k-label">Competitors</div><div class="k-value">{len(competitors)}</div><div class="k-sub">direct peers analyzed</div></div>
        <div class="kpi"><div class="k-label">Dimensions</div><div class="k-value">{len(feature_diff.get('features') or [])}</div><div class="k-sub">category-fit criteria</div></div>
        <div class="kpi"><div class="k-label">Price range</div><div class="k-value">{esc(price_rng['label'])}</div><div class="k-sub">public monthly list</div></div>
        <div class="kpi"><div class="k-label">Undisclosed</div><div class="k-value">{undisclosed}</div><div class="k-sub">peers hide pricing</div></div>
      </div>
    </div>
    <div class="cover-bottom">
      <div class="contents">
        <div><span class="n">01</span> Executive summary</div>
        <div><span class="n">02</span> Attack visuals</div>
        <div><span class="n">03</span> Competitive landscape</div>
        <div><span class="n">04</span> Feature comparison</div>
        <div><span class="n">05</span> Pricing comparison</div>
        <div><span class="n">06</span> Positioning map</div>
        <div><span class="n">07</span> SWOT analysis</div>
        <div><span class="n">08</span> Recommended positioning</div>
        <div><span class="n">09</span> Risks &amp; sources</div>
      </div>
      <div class="cover-date">Generated<strong>{esc(date_label)}</strong></div>
    </div>
  </section>

  <div class="section-head"><span class="num">01</span><h2>Executive summary</h2><span class="tag">Synthesis</span></div>
  <p class="lead">Findings synthesized strictly from each vendor's own marketing, product, and pricing pages — every claim traces to a source in section 08.</p>
  <div class="grid-2">
    <div class="card"><div class="kicker">Where {esc(product_name)} leads</div><ul class="clean">{lead_bullets}</ul></div>
    <div class="card"><div class="kicker">Where rivals are ahead</div><ul class="clean">{gap_bullets}</ul></div>
  </div>
  <div class="card avoid" style="margin-top:12px">
    <div class="kicker">Recommended angles</div>
    <ol class="rec">{rec_exec}</ol>
  </div>
{visuals_section}
  <div class="section-head"><span class="num">03</span><h2>Competitive landscape</h2><span class="tag">Discovery</span></div>
  <table>
    <thead><tr><th>Competitor</th><th>Website</th><th>Confidence</th><th>Sourced via</th></tr></thead>
    <tbody>{competitor_rows}</tbody>
  </table>
  <p class="note">Confidence reflects search overlap and model scoring across public pages; direct category peers rank higher than adjacent tools.</p>

  <div class="section-head break"><span class="num">04</span><h2>Feature comparison</h2><span class="tag">Evidence</span></div>
  <p class="lead">Dimensions are chosen for {esc(product_name)}'s category, then scored only from each vendor's public pages. "—" means the page didn't mention it — not proven absence.</p>
  {_render_feature_table(feature_diff, coverage, product_name)}
  <div class="grid-2" style="margin-top:12px">
    <div class="card"><div class="kicker">Coverage leaders</div><ul class="clean">{leaders}</ul></div>
    <div class="card">
      <div class="kicker">Reading this matrix</div>
      <p class="muted" style="margin:0">Each cell is graded <span class="badge badge-yes">✓ Yes</span> <span class="badge badge-partial">◐ Partial</span> <span class="badge badge-no">✕ No</span> <span class="badge badge-unknown">— n/a</span>.</p>
    </div>
  </div>

  <div class="section-head break"><span class="num">05</span><h2>Pricing comparison</h2><span class="tag">Public list</span></div>
  <p class="lead">Entry prices taken from public pricing pages. {undisclosed} of {len(competitors)} peers keep pricing behind a sales conversation.</p>
  <div class="card avoid" style="margin-bottom:12px">
    <div class="price-head"><h3 style="margin:0"><span class="accent">{esc(product_name)}</span> — your pricing</h3>{_pricing_model_badge(None)}</div>
    {_render_tiers((pricing.get('product_pricing') or {}).get('tiers') or [])}
    {_render_price_bar((pricing.get('product_pricing') or {}).get('tiers') or [], price_rng['max'])}
  </div>
  <div class="grid-2">{competitor_price_cards}</div>

  <div class="section-head break"><span class="num">06</span><h2>Positioning map</h2><span class="tag">Synthesis</span></div>
  <p class="lead">Each dot is placed by <strong>{esc(axes[0])}</strong> (horizontal) and <strong>{esc(axes[1])}</strong> (vertical), derived from sections 04–05.</p>
  {map_html}

  <div class="section-head"><span class="num">07</span><h2>SWOT analysis</h2><span class="tag">Strategy</span></div>
  <div class="swot">
    {_swot_card("Strengths", "swot-s", "▲", swot.get("strengths") or [])}
    {_swot_card("Weaknesses", "swot-w", "▼", swot.get("weaknesses") or [])}
    {_swot_card("Opportunities", "swot-o", "◆", swot.get("opportunities") or [])}
    {_swot_card("Threats", "swot-t", "⚑", swot.get("threats") or [])}
  </div>

  <div class="section-head"><span class="num">08</span><h2>Recommended positioning</h2><span class="tag">Action</span></div>
  <p class="lead">Prioritized go-to-market angles, each grounded in a concrete price or feature point from the sections above.</p>
  <div class="rec-grid">{rec_cards}</div>

  <div class="section-head"><span class="num">09</span><h2>Risks &amp; sources</h2><span class="tag">Appendix</span></div>
  <div class="grid-2">
    <div class="card avoid"><div class="kicker">Risks &amp; caveats</div><ul class="clean">{risk_lis}</ul></div>
    <div class="card avoid">
      <div class="kicker">How this report was built</div>
      <ul class="method">
        <li><span>Discovery</span><b>Web search → LLM ranking of direct peers</b></li>
        <li><span>Evidence</span><b>Each vendor's own site via Jina Reader (cleaned)</b></li>
        <li><span>Dimensions</span><b>{len(feature_diff.get('features') or [])} category-fit criteria, model-scored</b></li>
        <li><span>Pricing</span><b>Public list pages only; no scraping of gated data</b></li>
        <li><span>Visuals</span><b>Gemini attack charts from matrix + evidence JSON</b></li>
        <li><span>Competitors</span><b>{len(competitors)} analyzed</b></li>
        <li><span>Generated</span><b>{esc(date_label)}</b></li>
      </ul>
    </div>
  </div>
  <div class="card avoid" style="margin-top:12px">
    <div class="kicker">Evidence sources</div>
    <ul class="sources clean">{sources}</ul>
  </div>
  <p class="note">Generated by FounderBlaze Feature 5 · {esc(generated_at)} · Public-web evidence only · Not financial advice.</p>
</body>
</html>"""


def _swot_card(title: str, cls: str, icon: str, items: list[str]) -> str:
    lis = "".join(f"<li>{esc(x)}</li>" for x in items) or "<li class='muted'>—</li>"
    return f'<div class="card {cls}"><h3><span>{icon}</span> {esc(title)}</h3><ul class="clean">{lis}</ul></div>'


def _confidence_badge(conf: float) -> str:
    pct = round(max(0.0, min(1.0, conf)) * 100)
    cls = "badge-yes" if pct >= 80 else "badge-partial" if pct >= 60 else "badge-unknown"
    return f'<span class="badge {cls}">{pct}%</span>'


def _pricing_model_badge(model: str | None) -> str:
    if not model:
        return '<span class="badge badge-muted">public list</span>'
    return f'<span class="badge badge-partial">{esc(model)}</span>'


def _status_badge(status: str) -> str:
    mapping = {
        "yes": ("badge-yes", "✓", "Yes"),
        "partial": ("badge-partial", "◐", "Partial"),
        "no": ("badge-no", "✕", "No"),
        "unknown": ("badge-unknown", "—", ""),
    }
    cls, icon, label = mapping.get(status, mapping["unknown"])
    return f'<span class="badge {cls}">{icon}{(" " + esc(label)) if label else ""}</span>'


def _coverage_scores(diff: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    features = list(diff.get("features") or [])
    for entity, cells in (diff.get("matrix") or {}).items():
        known = sum(
            1
            for f in features
            if (cells or {}).get(f, {}).get("status", "unknown") != "unknown"
        )
        out[entity] = known / len(features) if features else 0.0
    return out


def _coverage_leaders(coverage: dict[str, float]) -> list[dict[str, Any]]:
    return sorted(
        [{"name": n, "score": s} for n, s in coverage.items()],
        key=lambda x: x["score"],
        reverse=True,
    )[:4]


def _feature_edges(diff: dict[str, Any], product_name: str) -> dict[str, list[str]]:
    edges: list[str] = []
    gaps: list[str] = []
    competitors = [k for k in (diff.get("matrix") or {}) if k != product_name]

    def st(entity: str, f: str) -> str:
        return (diff.get("matrix") or {}).get(entity, {}).get(f, {}).get("status", "unknown")

    for f in diff.get("features") or []:
        prod = st(product_name, f)
        comp_yes = sum(1 for c in competitors if st(c, f) == "yes")
        comp_no = sum(1 for c in competitors if st(c, f) in ("no", "unknown"))
        if prod == "yes" and competitors and comp_yes <= len(competitors) // 2:
            suffix = f", unlike {comp_no} of {len(competitors)} peers" if comp_no else ""
            edges.append(f"{f}: offered by {product_name}{suffix}")
        if prod in ("no", "unknown") and competitors and comp_yes >= (
            len(competitors) + 1
        ) // 2:
            gaps.append(f"{f}: available from {comp_yes} of {len(competitors)} peers")
    return {"edges": edges[:4], "gaps": gaps[:4]}


def _render_feature_table(
    diff: dict[str, Any], coverage: dict[str, float], product_name: str
) -> str:
    cols = list((diff.get("matrix") or {}).keys())
    header_cells = []
    for c in cols:
        style = ' style="color:#000"' if c == product_name else ""
        header_cells.append(f"<th{style}>{esc(c)}</th>")
    header = "<tr><th>Dimension</th>" + "".join(header_cells) + "</tr>"
    rows = []
    for f in diff.get("features") or []:
        cells = "".join(
            f"<td>{_status_badge((diff.get('matrix') or {}).get(c, {}).get(f, {}).get('status', 'unknown'))}</td>"
            for c in cols
        )
        rows.append(f'<tr><td class="feat">{esc(f)}</td>{cells}</tr>')
    coverage_row = (
        '<tr class="coverage-row"><td>Coverage</td>'
        + "".join(f"<td>{round((coverage.get(c) or 0) * 100)}%</td>" for c in cols)
        + "</tr>"
    )
    return f"<table><thead>{header}</thead><tbody>{''.join(rows)}{coverage_row}</tbody></table>"


def _render_tiers(tiers: list[dict[str, Any]]) -> str:
    if not tiers:
        return '<p class="muted" style="margin:0"><span class="badge badge-muted">Not publicly disclosed</span></p>'
    items = []
    for t in tiers:
        if t.get("price") is not None:
            price = f"{t.get('currency') or 'USD'} {t['price']}"
            if t.get("period"):
                price += f" / {t['period']}"
        elif "no public" in str(t.get("notes") or "").lower():
            price = "Not disclosed"
        else:
            price = "Contact / custom"
        notes = (
            f' <span class="muted">({esc(t["notes"])})</span>' if t.get("notes") else ""
        )
        items.append(
            f'<li><span><strong>{esc(t.get("name") or "Plan")}</strong>{notes}</span>'
            f'<span class="amt">{esc(price)}</span></li>'
        )
    return f'<ul class="tier-list">{"".join(items)}</ul>'


def _price_range(pricing: dict[str, Any]) -> dict[str, Any]:
    prices: list[float] = []
    for t in (pricing.get("product_pricing") or {}).get("tiers") or []:
        if isinstance(t.get("price"), (int, float)) and t["price"] > 0:
            prices.append(float(t["price"]))
    for c in pricing.get("competitor_pricing") or []:
        for t in c.get("tiers") or []:
            if isinstance(t.get("price"), (int, float)) and t["price"] > 0:
                prices.append(float(t["price"]))
    if not prices:
        return {"min": 0.0, "max": 1.0, "label": "n/a"}
    mn, mx = min(prices), max(prices)
    label = f"${mn:g}" if mn == mx else f"${mn:g}–{mx:g}"
    return {"min": mn, "max": mx, "label": label}


def _render_price_bar(tiers: list[dict[str, Any]], max_price: float) -> str:
    priced = [
        float(t["price"])
        for t in tiers
        if isinstance(t.get("price"), (int, float)) and t["price"] > 0
    ]
    if not priced:
        return ""
    pct = max(6, min(100, (min(priced) / max(1.0, max_price)) * 100))
    return f'<div class="price-bar" title="Relative entry price"><span style="width:{pct}%"></span></div>'


def _competitor_price_card(c: dict[str, Any], max_price: float) -> str:
    tiers = list(c.get("tiers") or [])
    model = c.get("pricing_model")
    if model == "unknown":
        model = None
    has_price = any(t.get("price") is not None for t in tiers)
    enterprise = (
        '<div style="margin-bottom:6px"><span class="badge badge-partial">enterprise custom</span></div>'
        if c.get("enterprise_custom")
        else ""
    )
    body = (
        _render_tiers(tiers)
        if has_price or tiers
        else '<p class="muted" style="margin:0"><span class="badge badge-muted">Not publicly disclosed</span></p>'
    )
    return f"""<div class="card">
      <div class="price-head"><h3 style="margin:0">{esc(c.get('competitor'))}</h3>{_pricing_model_badge(model)}</div>
      {enterprise}{body}{_render_price_bar(tiers, max_price)}
    </div>"""


def _render_map(pos_map: dict[str, Any], product_name: str, axes: list[str]) -> str:
    points = list(pos_map.get("points") or [])
    if not points:
        return '<div class="card"><p class="muted" style="margin:0">Insufficient pricing/feature evidence to place competitors on the map.</p></div>'
    ordered = sorted(
        [{"i": i, **p} for i, p in enumerate(points)],
        key=lambda p: (-float(p.get("y") or 0), float(p.get("x") or 0)),
    )
    dots = []
    for order, p in enumerate(ordered):
        left = max(7, min(92, float(p.get("x") or 0) * 100))
        bottom = max(8, min(84, float(p.get("y") or 0) * 100))
        is_product = p.get("name") == product_name
        tx = "-8%" if left < 17 else "-92%" if left > 83 else "-50%"
        place_below = bottom > 66 or (order % 2 == 1 and 22 < bottom < 66)
        ty = "150%" if place_below else "-200%"
        cls = " product" if is_product else ""
        dots.append(
            f'<div class="map-point{cls}" style="left:{left}%;bottom:{bottom}%"></div>'
            f'<div class="map-label{cls}" style="left:{left}%;bottom:{bottom}%;'
            f'transform:translate({tx}, {ty})">{esc(p.get("name"))}</div>'
        )
    return f"""<div class="chart">
    <div class="chart-yaxis">{esc(axes[1])} →</div>
    <div class="map-wrap">
      <div class="midline h"></div><div class="midline v"></div>
      <div class="quad-label quad-tl">Feature-rich</div>
      <div class="quad-label quad-tr">Premium &amp; broad</div>
      <div class="quad-label quad-bl">Lean &amp; low-cost</div>
      <div class="quad-label quad-br">Premium &amp; focused</div>
      {"".join(dots)}
    </div>
    <div class="chart-xaxis">{esc(axes[0])} →</div>
  </div>
  <div class="legend">
    <span><i class="product"></i> {esc(product_name)} (you)</span>
    <span><i></i> Competitors</span>
    <span class="muted">Right edge = custom / undisclosed pricing</span>
  </div>"""


def _collect_sources(data: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    if data.get("product_url"):
        out.append(str(data["product_url"]))
        seen.add(str(data["product_url"]))
    for c in data.get("competitors") or []:
        u = str(c.get("url") or "")
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    for entity in (data.get("feature_diff") or {}).get("matrix", {}).values():
        for cell in (entity or {}).values():
            eu = cell.get("evidence_url")
            if eu:
                item = f"{eu} @ {cell.get('scraped_at') or '?'}"
                if item not in seen:
                    out.append(item)
                    seen.add(item)
    return out
