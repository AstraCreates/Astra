import base64
import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


def github_create_repo(
    repo_name: str,
    description: str,
    stack: dict,
    mvp_features: list[dict],
    private: bool = False,
) -> dict:
    """Create GitHub repo. Args: repo_name (str, kebab-case), description (str), stack (dict e.g. {"language":"Python","framework":"FastAPI"}), mvp_features (list of dicts e.g. [{"name":"Auth","description":"..."}]), private (bool). Returns: {repo_url, scaffolded}.
    Requires GITHUB_TOKEN. Falls back to returning scaffold content only.
    """
    token = getattr(settings, "github_token", None)
    if not token:
        scaffold = _generate_scaffold(repo_name, description, stack, mvp_features)
        return {
            "created": False,
            "scaffold": scaffold,
            "note": "GITHUB_TOKEN not set — scaffold generated but not pushed.",
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        # Get authenticated user
        user_resp = requests.get(f"{_GH_API}/user", headers=headers, timeout=10)
        user_resp.raise_for_status()
        username = user_resp.json()["login"]

        # Create repo
        repo_resp = requests.post(
            f"{_GH_API}/user/repos",
            headers=headers,
            json={"name": repo_name, "description": description, "private": private, "auto_init": True},
            timeout=15,
        )
        repo_resp.raise_for_status()
        repo_data = repo_resp.json()
        repo_url = repo_data["html_url"]

        # Push scaffold files
        scaffold = _generate_scaffold(repo_name, description, stack, mvp_features)
        for filename, content in scaffold.items():
            encoded = base64.b64encode(content.encode()).decode()
            requests.put(
                f"{_GH_API}/repos/{username}/{repo_name}/contents/{filename}",
                headers=headers,
                json={"message": f"chore: initial scaffold for {filename}", "content": encoded},
                timeout=15,
            )

        return {
            "created": True,
            "repo_url": repo_url,
            "repo_name": repo_name,
            "owner": username,
            "files_pushed": list(scaffold.keys()),
        }
    except Exception as e:
        logger.error("github_create_repo failed: %s", e)
        scaffold = _generate_scaffold(repo_name, description, stack, mvp_features)
        return {"created": False, "scaffold": scaffold, "error": str(e)}


def _generate_scaffold(repo_name: str, description: str, stack: dict, mvp_features: list[dict]) -> dict:
    features_md = "\n".join(
        f"- [ ] **{f.get('name', f)}** ({f.get('priority', 'p1')})" if isinstance(f, dict) else f"- [ ] {f}"
        for f in mvp_features
    )
    backend = stack.get("backend", "FastAPI")
    frontend = stack.get("frontend", "Next.js")
    db = stack.get("db", "PostgreSQL")

    readme = f"""# {repo_name}

{description}

## Stack
- **Backend**: {backend}
- **Frontend**: {frontend}
- **Database**: {db}
- **Hosting**: {stack.get("hosting", "Vercel + Railway")}

## MVP Features
{features_md}

## Getting Started

```bash
# Install dependencies
npm install        # frontend
pip install -r requirements.txt  # backend

# Run dev servers
npm run dev        # frontend (localhost:3000)
uvicorn main:app --reload  # backend (localhost:8000)
```

## Built with [Astra](https://astra.ai) — AI founding team for first-time founders.
"""

    gitignore = """# Python
__pycache__/
*.pyc
.env
venv/
.venv/

# Node
node_modules/
.next/
dist/

# Misc
.DS_Store
*.log
"""

    env_example = """# Backend
DATABASE_URL=postgresql://user:pass@localhost:5432/db
SECRET_KEY=change-me

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
"""

    return {
        "README.md": readme,
        ".gitignore": gitignore,
        ".env.example": env_example,
    }
