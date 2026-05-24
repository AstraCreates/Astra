import hashlib
import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_VERCEL_API = "https://api.vercel.com"


def vercel_deploy(project_slug: str, html: str, css: str = "", js: str = "") -> dict:
    """
    Deploy a landing page to Vercel.
    Requires VERCEL_TOKEN in environment. Falls back to saving files locally.
    """
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

        # Create deployment
        payload = {
            "name": project_slug,
            "files": files,
            "projectSettings": {"framework": None},
            "target": "production",
        }
        resp = requests.post(f"{_VERCEL_API}/v13/deployments", json=payload, headers=headers, timeout=30)
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
) -> str:
    props_html = "\n".join(
        f"<li>{prop}</li>" for prop in value_props
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{page_title}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111;background:#fff}}
    header{{padding:20px 40px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}}
    .logo{{font-weight:700;font-size:1.2rem}}
    .hero{{max-width:760px;margin:80px auto;padding:0 24px;text-align:center}}
    h1{{font-size:3rem;font-weight:800;line-height:1.15;margin-bottom:20px}}
    .sub{{font-size:1.25rem;color:#555;margin-bottom:40px;line-height:1.5}}
    .cta{{display:inline-block;background:#000;color:#fff;padding:16px 36px;border-radius:8px;font-size:1rem;font-weight:600;text-decoration:none;transition:opacity .2s}}
    .cta:hover{{opacity:.85}}
    .props{{max-width:680px;margin:60px auto;padding:0 24px;list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:16px}}
    .props li{{background:#f8f8f8;padding:20px;border-radius:10px;font-size:.95rem;line-height:1.5}}
    footer{{text-align:center;padding:40px;color:#999;font-size:.85rem;border-top:1px solid #eee;margin-top:60px}}
  </style>
</head>
<body>
  <header>
    <span class="logo">{company_name or page_title}</span>
    <a href="{cta_url}" class="cta">{cta_text}</a>
  </header>
  <section class="hero">
    <h1>{headline}</h1>
    <p class="sub">{subheadline}</p>
    <a href="{cta_url}" class="cta">{cta_text}</a>
  </section>
  <ul class="props">
    {props_html}
  </ul>
  <footer>&copy; 2025 {company_name or page_title}. Built with Astra.</footer>
</body>
</html>"""
