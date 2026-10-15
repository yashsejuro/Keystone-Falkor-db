import os, requests
from dotenv import load_dotenv
load_dotenv()

H = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}",
     "Accept": "application/vnd.github+json"}

for repo in ["pydantic/pydantic", "fastapi/fastapi", "redis/redis"]:
    r = requests.get(
        "https://api.github.com/search/issues",
        headers=H,
        params={"q": f"repo:{repo} is:pr is:merged", "per_page": 1},
    )
    j = r.json()
    if "total_count" in j:
        print(f"{repo}: {j['total_count']}")
    else:
        print(f"{repo}: ERROR -> {j}")