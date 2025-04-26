import base64, httpx, os, time, logging
GITHUB_API = "https://api.github.com"
log = logging.getLogger("serena.github")

def _headers(token:str):
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

async def upsert_file(owner, repo, path, branch, message, content_b64, token):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    async with httpx.AsyncClient() as client:
        # Get SHA if file already exists (needed for update)
        sha = None
        r = await client.get(url, headers=_headers(token), params={"ref": branch})
        if r.status_code == 200:
            sha = r.json()["sha"]
        payload = {
            "message": message,
            "content": content_b64,
            "branch": branch,
            "sha": sha
        }
        return (await client.put(url, headers=_headers(token), json=payload)).json()

async def create_pr(owner, repo, head, base, title, body, token):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    data = {"title": title, "head": head, "base": base, "body": body}
    async with httpx.AsyncClient() as client:
        return (await client.post(url, headers=_headers(token), json=data)).json()
