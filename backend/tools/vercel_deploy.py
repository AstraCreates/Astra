import hashlib
import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_VERCEL_API = "https://api.vercel.com"


def vercel_deploy(project_slug: str, html: str, css: str = "", js: str = "") -> dict:
    """Deploy HTML to Vercel. Args: project_slug (url-safe name), html (full HTML string), css (optional), js (optional). Returns: {deployed, url} or {deployed: false, local_path}."""
    token = getattr(settings, "vercel_token", None)

    if not token:
        return _local_fallback(project_slug, html, css, js)

    files = [
        {"file": "index.html", "data": html, "encoding": "utf-8"},
    ]
    if css:
        files.append({"file": "styles.css", "data": css, "encoding": "utf-8"})
    if js:
        files.append({"file": "app.js", "data": js, "encoding": "utf-8"})

    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Resolve team ID from the token owner
        user_resp = requests.get(f"{_VERCEL_API}/v2/user", headers=headers, timeout=10)
        team_id = None
        if user_resp.ok:
            team_id = user_resp.json().get("user", {}).get("defaultTeamId")

        deploy_url = f"{_VERCEL_API}/v13/deployments"
        if team_id:
            deploy_url += f"?teamId={team_id}"

        # Create deployment
        payload = {
            "name": project_slug,
            "files": files,
            "projectSettings": {"framework": None},
            "target": "production",
        }
        resp = requests.post(deploy_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        url = f"https://{data.get('url', '')}"
        return {
            "deployed": True,
            "url": url,
            "deployment_id": data.get("id"),
            "project": project_slug,
        }
    except Exception as e:
        logger.error("vercel_deploy failed: %s", e)
        return _local_fallback(project_slug, html, css, js)


def _local_fallback(project_slug: str, html: str, css: str, js: str) -> dict:
    import os
    out_dir = f"/tmp/astra_sites/{project_slug}"
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/index.html", "w") as f:
        f.write(html)
    if css:
        with open(f"{out_dir}/styles.css", "w") as f:
            f.write(css)
    if js:
        with open(f"{out_dir}/app.js", "w") as f:
            f.write(js)
    return {
        "deployed": False,
        "local_path": out_dir,
        "note": "VERCEL_TOKEN not set — files saved locally. Set VERCEL_TOKEN to auto-deploy.",
    }


def generate_landing_page_html(
    page_title: str,
    headline: str,
    subheadline: str,
    value_props: list[str],
    cta_text: str,
    cta_url: str,
    company_name: str = "",
    business_context: str = "",
) -> str:
    """Generate a complete, production-quality landing page HTML. Args: page_title, headline, subheadline, value_props (list of strings), cta_text, cta_url, company_name (optional), business_context (optional)."""
    name = company_name or page_title

    icons = ["◆", "◈", "◉", "◎", "◇", "◊"]
    steps = ["Define your goal", "Astra builds it", "You launch"]

    props_cards = ""
    for i, prop in enumerate(value_props[:6]):
        icon = icons[i % len(icons)]
        props_cards += f"""
        <div class="feat">
          <div class="feat-icon">{icon}</div>
          <p class="feat-text">{prop}</p>
        </div>"""

    steps_html = ""
    for i, step in enumerate(steps, 1):
        steps_html += f"""
        <div class="step">
          <div class="step-num">{i:02d}</div>
          <p class="step-text">{step}</p>
        </div>"""

    year = 2025
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{page_title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg: #06080f;
      --bg2: #0d1117;
      --bg3: #141b26;
      --line: rgba(148,163,200,.1);
      --line2: rgba(148,163,200,.18);
      --fg: #f0f4ff;
      --fg2: rgba(240,244,255,.6);
      --fg3: rgba(240,244,255,.35);
      --blue: #3b82f6;
      --blue2: #2563eb;
      --r: 12px;
    }}

    html {{ background: var(--bg); color: var(--fg); scroll-behavior: smooth; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      -webkit-font-smoothing: antialiased;
      min-height: 100vh;
    }}

    a {{ color: inherit; text-decoration: none; }}

    /* NAV */
    nav {{
      position: sticky; top: 0; z-index: 50;
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px clamp(20px,5vw,64px);
      background: rgba(6,8,15,.88);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--line2);
    }}
    .nav-brand {{ font-weight: 700; font-size: 1rem; letter-spacing: -.01em; }}
    .nav-cta {{
      background: var(--blue); color: #fff;
      padding: 10px 22px; border-radius: 8px;
      font-size: .875rem; font-weight: 600;
      transition: background .15s;
    }}
    .nav-cta:hover {{ background: var(--blue2); }}

    /* HERO */
    .hero {{
      max-width: 860px; margin: 0 auto;
      padding: clamp(72px,10vw,120px) clamp(20px,5vw,48px) clamp(56px,8vw,96px);
      text-align: center;
    }}
    .hero-eyebrow {{
      display: inline-block;
      font-size: .75rem; font-weight: 500; letter-spacing: .18em; text-transform: uppercase;
      color: var(--blue); margin-bottom: 24px;
    }}
    .hero h1 {{
      font-size: clamp(2.4rem,6vw,4.5rem);
      font-weight: 800; line-height: 1.06; letter-spacing: -.03em;
      margin-bottom: 24px;
    }}
    .hero h1 em {{ font-style: normal; color: var(--fg2); }}
    .hero-sub {{
      font-size: clamp(1rem,1.8vw,1.2rem);
      line-height: 1.65; color: var(--fg2);
      max-width: 580px; margin: 0 auto 40px;
    }}
    .hero-actions {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }}
    .btn-primary {{
      display: inline-flex; align-items: center; gap: 8px;
      background: var(--blue); color: #fff;
      padding: 14px 28px; border-radius: 8px;
      font-size: 1rem; font-weight: 600;
      transition: background .15s, transform .15s;
    }}
    .btn-primary:hover {{ background: var(--blue2); transform: translateY(-1px); }}
    .btn-ghost {{
      display: inline-flex; align-items: center;
      padding: 14px 28px; border-radius: 8px;
      border: 1px solid var(--line2);
      font-size: 1rem; color: var(--fg2);
      transition: border-color .15s, color .15s;
    }}
    .btn-ghost:hover {{ border-color: var(--fg2); color: var(--fg); }}

    /* STATS */
    .stats {{
      display: flex; justify-content: center; gap: 0;
      border-top: 1px solid var(--line2); border-bottom: 1px solid var(--line2);
      background: var(--bg2);
    }}
    .stat {{
      flex: 1; max-width: 220px;
      padding: 32px 24px; text-align: center;
      border-right: 1px solid var(--line2);
    }}
    .stat:last-child {{ border-right: none; }}
    .stat-val {{ font-size: 2rem; font-weight: 800; letter-spacing: -.03em; }}
    .stat-label {{ font-size: .8rem; color: var(--fg3); margin-top: 4px; letter-spacing: .08em; text-transform: uppercase; }}

    /* FEATURES */
    .section {{ padding: clamp(56px,8vw,96px) clamp(20px,5vw,64px); max-width: 1120px; margin: 0 auto; }}
    .section-label {{ font-size: .75rem; font-weight: 500; letter-spacing: .18em; text-transform: uppercase; color: var(--blue); margin-bottom: 16px; }}
    .section-title {{ font-size: clamp(1.6rem,3.5vw,2.6rem); font-weight: 800; letter-spacing: -.025em; margin-bottom: 48px; }}

    .feats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
    .feat {{
      background: var(--bg2); border: 1px solid var(--line2);
      border-radius: var(--r); padding: 28px 24px;
      transition: border-color .2s;
    }}
    .feat:hover {{ border-color: rgba(59,130,246,.4); }}
    .feat-icon {{ font-size: 1.4rem; color: var(--blue); margin-bottom: 16px; }}
    .feat-text {{ font-size: .95rem; line-height: 1.6; color: var(--fg2); }}

    /* HOW IT WORKS */
    .how {{ background: var(--bg2); border-top: 1px solid var(--line2); border-bottom: 1px solid var(--line2); }}
    .steps {{ display: flex; gap: 0; }}
    .step {{
      flex: 1; padding: 40px 32px;
      border-right: 1px solid var(--line2);
      text-align: center;
    }}
    .step:last-child {{ border-right: none; }}
    .step-num {{
      font-size: 2.5rem; font-weight: 900; letter-spacing: -.04em;
      color: var(--blue); opacity: .6; margin-bottom: 12px;
    }}
    .step-text {{ font-size: .95rem; color: var(--fg2); line-height: 1.5; }}

    /* CTA BANNER */
    .cta-section {{
      text-align: center;
      padding: clamp(64px,10vw,112px) clamp(20px,5vw,64px);
    }}
    .cta-section h2 {{
      font-size: clamp(1.8rem,4vw,3rem);
      font-weight: 800; letter-spacing: -.03em; margin-bottom: 16px;
    }}
    .cta-section p {{ font-size: 1.1rem; color: var(--fg2); margin-bottom: 36px; }}

    /* FOOTER */
    footer {{
      border-top: 1px solid var(--line2);
      padding: 32px clamp(20px,5vw,64px);
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 12px;
    }}
    footer span {{ font-size: .85rem; color: var(--fg3); }}
    .footer-links {{ display: flex; gap: 24px; }}
    .footer-links a {{ font-size: .85rem; color: var(--fg3); transition: color .15s; }}
    .footer-links a:hover {{ color: var(--fg); }}

    @media (max-width: 640px) {{
      .stats {{ flex-wrap: wrap; }}
      .stat {{ max-width: 50%; border-bottom: 1px solid var(--line2); }}
      .steps {{ flex-direction: column; }}
      .step {{ border-right: none; border-bottom: 1px solid var(--line2); }}
      .step:last-child {{ border-bottom: none; }}
      footer {{ flex-direction: column; text-align: center; }}
    }}
  </style>
</head>
<body>

  <nav>
    <span class="nav-brand">{name}</span>
    <a href="{cta_url}" class="nav-cta">{cta_text}</a>
  </nav>

  <section class="hero">
    <span class="hero-eyebrow">Introducing {name}</span>
    <h1>{headline}</h1>
    <p class="hero-sub">{subheadline}</p>
    <div class="hero-actions">
      <a href="{cta_url}" class="btn-primary">{cta_text} &rarr;</a>
      <a href="#features" class="btn-ghost">See how it works</a>
    </div>
  </section>

  <div class="stats">
    <div class="stat"><div class="stat-val">6</div><div class="stat-label">AI Agents</div></div>
    <div class="stat"><div class="stat-val">72h</div><div class="stat-label">To first launch</div></div>
    <div class="stat"><div class="stat-val">1</div><div class="stat-label">Instruction to start</div></div>
  </div>

  <div id="features" class="section">
    <div class="section-label">What you get</div>
    <div class="section-title">Everything you need to launch faster</div>
    <div class="feats">{props_cards}
    </div>
  </div>

  <div class="how">
    <div class="section">
      <div class="section-label">How it works</div>
      <div class="section-title">Three steps to your product</div>
      <div class="steps">{steps_html}
      </div>
    </div>
  </div>

  <div class="cta-section">
    <h2>Ready to build?</h2>
    <p>Join founders who are launching faster with {name}.</p>
    <a href="{cta_url}" class="btn-primary">{cta_text} &rarr;</a>
  </div>

  <footer>
    <span>&copy; {year} {name}. All rights reserved.</span>
    <div class="footer-links">
      <a href="#">Privacy</a>
      <a href="#">Terms</a>
      <a href="#">Contact</a>
    </div>
  </footer>

</body>
</html>"""
