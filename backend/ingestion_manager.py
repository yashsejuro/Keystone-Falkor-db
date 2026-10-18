"""Production-ready repository ingestion engine and job manager for Keystone.

Implements:
- Asynchronous in-process job queue with thread safety
- Verification of GitHub repository accessibility
- Collision-safe multi-tenant graph registration
- Paginated retrieval of merged PRs, changed files, and reviews
- GitHub API rate limit handling respecting Retry-After
- Resumable, idempotent batched graph writes (UNWIND)
- Safe cancellation, error tracking, and progress reporting
- Provenance recording and post-ingestion cache invalidation
"""
import os
import re
import time
import uuid
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from backend.graph_client import (
        register_repo, get_graph, execute_graph_query,
        invalidate_repo_cache, node_count, edge_count,
        graph_provenance, REPOS, REPO_SLUGS
    )
    from backend.centrality import materialize_centrality
except ImportError:
    from graph_client import (
        register_repo, get_graph, execute_graph_query,
        invalidate_repo_cache, node_count, edge_count,
        graph_provenance, REPOS, REPO_SLUGS
    )
    from centrality import materialize_centrality

logger = logging.getLogger("keystone.ingestion")


class IngestionJob:
    def __init__(self, job_id: str, repo_slug: str, target_limit: int = 100,
                 materialize_centrality_flag: bool = True):
        self.job_id = job_id
        self.repo_slug = repo_slug
        self.target_limit = target_limit
        self.materialize_centrality_flag = materialize_centrality_flag
        self.graph_name = ""
        self.status = "QUEUED"  # QUEUED, IN_PROGRESS, COMPLETED, FAILED, CANCELLED, PARTIALLY_COMPLETED
        self.prs_processed = 0
        self.files_processed = 0
        self.reviews_processed = 0
        self.current_page = 1
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.updated_time = self.start_time
        self.end_time: Optional[str] = None
        self.error: Optional[str] = None
        self.is_cancelled = False
        self._lock = threading.Lock()

    def update_progress(self, pr_inc: int = 0, file_inc: int = 0, rev_inc: int = 0, page: Optional[int] = None):
        with self._lock:
            self.prs_processed += pr_inc
            self.files_processed += file_inc
            self.reviews_processed += rev_inc
            if page is not None:
                self.current_page = page
            self.updated_time = datetime.now(timezone.utc).isoformat()

    def set_status(self, status: str, error: Optional[str] = None):
        with self._lock:
            self.status = status
            self.updated_time = datetime.now(timezone.utc).isoformat()
            if error:
                self.error = error
            if status in ("COMPLETED", "FAILED", "CANCELLED", "PARTIALLY_COMPLETED"):
                self.end_time = self.updated_time

    def cancel(self):
        with self._lock:
            self.is_cancelled = True
            if self.status in ("QUEUED", "IN_PROGRESS"):
                self.status = "CANCELLED"
            self.updated_time = datetime.now(timezone.utc).isoformat()
            self.end_time = self.updated_time

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "job_id": self.job_id,
                "repo_slug": self.repo_slug,
                "graph_name": self.graph_name,
                "status": self.status,
                "prs_processed": self.prs_processed,
                "target_limit": self.target_limit,
                "files_processed": self.files_processed,
                "reviews_processed": self.reviews_processed,
                "current_page": self.current_page,
                "start_time": self.start_time,
                "updated_time": self.updated_time,
                "end_time": self.end_time,
                "error": self.error,
                "is_cancelled": self.is_cancelled,
            }


class IngestionJobManager:
    _instance: Optional["IngestionJobManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(IngestionJobManager, cls).__new__(cls)
                cls._instance._jobs = {}
                cls._instance._active_repos = {}
                cls._instance._manager_lock = threading.RLock()
            return cls._instance

    def get_job(self, job_id: str) -> Optional[IngestionJob]:
        with self._manager_lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._manager_lock:
            return [j.to_dict() for j in self._jobs.values()]

    def is_repo_busy(self, repo_slug: str) -> bool:
        normalized = repo_slug.strip().lower()
        with self._manager_lock:
            active_id = self._active_repos.get(normalized)
            if active_id:
                job = self._jobs.get(active_id)
                if job and job.status in ("QUEUED", "IN_PROGRESS"):
                    return True
            return False

    def start_job(self, repo_slug: str, target_limit: int = 100,
                  materialize_centrality_flag: bool = True) -> IngestionJob:
        clean_slug = repo_slug.strip()
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", clean_slug)
        if not match:
            raise ValueError(f"Invalid repository slug '{repo_slug}'. Format must be owner/name (e.g. 'pydantic/pydantic').")

        normalized = clean_slug.lower()
        with self._manager_lock:
            active_id = self._active_repos.get(normalized)
            if active_id:
                existing_job = self._jobs.get(active_id)
                if existing_job and existing_job.status in ("QUEUED", "IN_PROGRESS"):
                    raise RuntimeError(f"An ingestion job for repository '{clean_slug}' is already in progress.")

            job_id = f"ingest-{uuid.uuid4().hex[:8]}"
            job = IngestionJob(job_id, clean_slug, target_limit, materialize_centrality_flag)
            self._jobs[job_id] = job
            self._active_repos[normalized] = job_id

        # Launch worker in background thread
        thread = threading.Thread(target=self._worker, args=(job,), daemon=True, name=f"Worker-{job_id}")
        thread.start()
        return job

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        job.cancel()
        return True

    def _build_github_session(self) -> requests.Session:
        token = os.getenv("GITHUB_TOKEN", "").strip()
        session = requests.Session()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Keystone-Ingestion-Engine/2.0",
        }
        if token:
            headers["Authorization"] = f"token {token}"
        session.headers.update(headers)

        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def _fetch_github_json(self, session: requests.Session, url: str,
                           params: Optional[dict] = None) -> tuple[Optional[Any], Optional[int], Optional[str]]:
        try:
            resp = session.get(url, params=params, timeout=20)
            if resp.status_code == 404:
                return None, 404, "Repository or resource not found on GitHub."
            if resp.status_code == 401:
                return None, 401, "GitHub API authentication failed. Verify GITHUB_TOKEN."
            if resp.status_code == 403:
                # Check for rate limit
                rate_limit_reset = resp.headers.get("X-RateLimit-Reset")
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait_secs = min(int(retry_after), 60)
                    time.sleep(wait_secs)
                elif "rate limit" in resp.text.lower():
                    return None, 403, "GitHub API rate limit exceeded. Configure a valid GITHUB_TOKEN."
                else:
                    return None, 403, f"GitHub API permission denied: {resp.text[:120]}"
            if resp.status_code >= 400:
                return None, resp.status_code, f"GitHub HTTP {resp.status_code}: {resp.text[:120]}"
            return resp.json(), resp.status_code, None
        except requests.exceptions.RequestException as e:
            return None, 0, f"Network error contacting GitHub: {type(e).__name__}: {e}"

    def _worker(self, job: IngestionJob):
        logger.info(f"[{job.job_id}] Starting ingestion worker for {job.repo_slug}")
        session = self._build_github_session()

        try:
            # 1. Verify repository access on GitHub
            repo_info, status_code, err = self._fetch_github_json(
                session, f"https://api.github.com/repos/{job.repo_slug}"
            )
            if err or not repo_info:
                job.set_status("FAILED", error=f"Repository verification failed: {err}")
                return

            if job.is_cancelled:
                job.set_status("CANCELLED")
                return

            # 2. Register repository safely in multi-tenant graph registry
            graph_key = register_repo(job.repo_slug)
            job.graph_name = REPOS[graph_key]
            job.set_status("IN_PROGRESS")

            # 3. Create database indexes if they don't already exist
            for idx_stmt in [
                "CREATE INDEX FOR (p:Person) ON (p.login)",
                "CREATE INDEX FOR (pr:PullRequest) ON (pr.number)",
                "CREATE INDEX FOR (f:File) ON (f.path)",
            ]:
                try:
                    execute_graph_query(idx_stmt, repo=graph_key)
                except Exception:
                    pass

            # 4. Check already ingested PR numbers to support resumability
            already_ingested_rows = execute_graph_query(
                "MATCH (pr:PullRequest) RETURN pr.number",
                repo=graph_key
            ).result_set
            existing_pr_set = {int(r[0]) for r in already_ingested_rows if r and r[0] is not None}
            start_existing_count = len(existing_pr_set)
            logger.info(f"[{job.job_id}] Existing PRs in {job.graph_name}: {start_existing_count}")

            # 5. Paginated retrieval of merged PRs
            page = 1
            added_prs = 0
            has_more = True

            while added_prs < job.target_limit and has_more:
                if job.is_cancelled:
                    job.set_status("CANCELLED")
                    logger.info(f"[{job.job_id}] Ingestion cancelled by user.")
                    return

                pulls_url = f"https://api.github.com/repos/{job.repo_slug}/pulls"
                pulls_params = {
                    "state": "closed",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": min(50, job.target_limit - added_prs),
                    "page": page,
                }
                prs_batch, code, err = self._fetch_github_json(session, pulls_url, pulls_params)
                if err or not prs_batch or not isinstance(prs_batch, list):
                    if err:
                        logger.warning(f"[{job.job_id}] Error fetching PR page {page}: {err}")
                    has_more = False
                    break

                if len(prs_batch) == 0:
                    has_more = False
                    break

                for pr_data in prs_batch:
                    if job.is_cancelled:
                        job.set_status("CANCELLED")
                        return

                    pr_num = int(pr_data.get("number", 0))
                    merged_at = pr_data.get("merged_at")
                    # Ingest only merged PRs
                    if not merged_at:
                        continue

                    if pr_num in existing_pr_set:
                        continue

                    # Fetch changed files and reviews with pagination
                    files = self._fetch_all_pr_files(session, job.repo_slug, pr_num)
                    reviews = self._fetch_all_pr_reviews(session, job.repo_slug, pr_num)

                    # Ingest single PR atomically with batched Cypher writes
                    self._ingest_single_pr_batch(graph_key, pr_data, files, reviews)
                    existing_pr_set.add(pr_num)
                    added_prs += 1
                    job.update_progress(pr_inc=1, file_inc=len(files), rev_inc=len(reviews), page=page)

                    if added_prs >= job.target_limit:
                        break

                page += 1
                time.sleep(0.2)  # courteous delay between pages

            # 6. Record metadata provenance
            now_iso = datetime.now(timezone.utc).isoformat()
            provenance_query = """
            MERGE (m:KeystoneMetadata {key: 'provenance'})
            SET m.source = 'github_api',
                m.repository = $repo,
                m.last_ingested_at = $now,
                m.last_import_count = $cnt,
                m.status = 'real'
            """
            execute_graph_query(
                provenance_query,
                {"repo": job.repo_slug, "now": now_iso, "cnt": added_prs},
                repo=graph_key
            )

            # Invalidate caches
            invalidate_repo_cache(graph_key)

            # 7. Optional post-ingestion centrality materialization
            if job.materialize_centrality_flag:
                logger.info(f"[{job.job_id}] Materializing centrality after ingestion...")
                materialize_centrality(graph_key)

            if added_prs > 0 or start_existing_count > 0:
                final_status = "COMPLETED" if added_prs >= job.target_limit or not has_more else "PARTIALLY_COMPLETED"
                job.set_status(final_status)
                logger.info(f"[{job.job_id}] Ingestion finished with status {final_status}. Added {added_prs} PRs.")
            else:
                job.set_status("COMPLETED")

        except Exception as e:
            logger.error(f"[{job.job_id}] Unexpected error during ingestion: {e}", exc_info=True)
            job.set_status("FAILED", error=f"Ingestion failed: {type(e).__name__}: {e}")
        finally:
            with self._manager_lock:
                normalized = job.repo_slug.lower()
                if self._active_repos.get(normalized) == job.job_id:
                    del self._active_repos[normalized]

    def _fetch_all_pr_files(self, session: requests.Session, repo_slug: str, pr_num: int) -> list[dict]:
        all_files = []
        page = 1
        while page <= 5:  # cap at 500 files per PR
            url = f"https://api.github.com/repos/{repo_slug}/pulls/{pr_num}/files"
            data, _, err = self._fetch_github_json(session, url, {"per_page": 100, "page": page})
            if err or not data or not isinstance(data, list):
                break
            all_files.extend(data)
            if len(data) < 100:
                break
            page += 1
            time.sleep(0.1)
        return all_files

    def _fetch_all_pr_reviews(self, session: requests.Session, repo_slug: str, pr_num: int) -> list[dict]:
        all_reviews = []
        page = 1
        while page <= 3:
            url = f"https://api.github.com/repos/{repo_slug}/pulls/{pr_num}/reviews"
            data, _, err = self._fetch_github_json(session, url, {"per_page": 100, "page": page})
            if err or not data or not isinstance(data, list):
                break
            all_reviews.extend(data)
            if len(data) < 100:
                break
            page += 1
            time.sleep(0.1)
        return all_reviews

    def _ingest_single_pr_batch(self, graph_key: str, pr: dict, files: list[dict], reviews: list[dict]):
        """Perform batched UNWIND write for PR, files, and reviews to minimize round trips."""
        pr_num = int(pr["number"])
        author = pr.get("user", {}).get("login")
        created_at = pr.get("created_at")
        merged_at = pr.get("merged_at")
        title = (pr.get("title") or "")[:200]
        state = pr.get("state", "closed")
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        files_count = pr.get("changed_files", len(files))

        # 1. PR and Author write
        pr_query = """
        MERGE (pr:PullRequest {number: $num})
        SET pr.title = $title,
            pr.state = $state,
            pr.created_at = $created_at,
            pr.merged_at = $merged_at,
            pr.additions = $additions,
            pr.deletions = $deletions,
            pr.files_changed = $files_changed
        """
        params = {
            "num": pr_num,
            "title": title,
            "state": state,
            "created_at": created_at,
            "merged_at": merged_at,
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_count,
        }
        execute_graph_query(pr_query, params, repo=graph_key)

        if author:
            author_query = """
            MERGE (p:Person {login: $login})
            ON CREATE SET p.first_seen = $created_at, p.is_bot = $is_bot
            ON MATCH SET p.last_seen = $created_at
            WITH p
            MATCH (pr:PullRequest {number: $num})
            MERGE (p)-[a:AUTHORED]->(pr)
            SET a.at = $created_at
            """
            execute_graph_query(author_query, {
                "login": author,
                "created_at": created_at,
                "is_bot": author.endswith("[bot]"),
                "num": pr_num,
            }, repo=graph_key)

        # 2. Batch Touched Files write using UNWIND
        clean_files = []
        for f in files:
            path = f.get("filename")
            if path:
                clean_files.append({
                    "path": path,
                    "additions": int(f.get("additions", 0)),
                    "deletions": int(f.get("deletions", 0)),
                })

        if clean_files:
            files_query = """
            MATCH (pr:PullRequest {number: $num})
            UNWIND $files AS item
            MERGE (f:File {path: item.path})
            MERGE (pr)-[t:TOUCHES]->(f)
            SET t.additions = item.additions,
                t.deletions = item.deletions
            """
            execute_graph_query(files_query, {"num": pr_num, "files": clean_files}, repo=graph_key)

        # 3. Batch Reviews write using UNWIND
        clean_reviews = []
        for r in reviews:
            user = r.get("user", {}).get("login")
            st = r.get("state")
            sub_at = r.get("submitted_at") or created_at
            if user and st:
                clean_reviews.append({
                    "login": user,
                    "state": st,
                    "submitted_at": sub_at,
                    "is_bot": user.endswith("[bot]"),
                })

        if clean_reviews:
            reviews_query = """
            MATCH (pr:PullRequest {number: $num})
            UNWIND $reviews AS rev
            MERGE (p:Person {login: rev.login})
            ON CREATE SET p.first_seen = rev.submitted_at, p.is_bot = rev.is_bot
            ON MATCH SET p.last_seen = rev.submitted_at
            MERGE (p)-[r:REVIEWED]->(pr)
            SET r.state = rev.state,
                r.at = rev.submitted_at
            """
            execute_graph_query(reviews_query, {"num": pr_num, "reviews": clean_reviews}, repo=graph_key)


def get_registered_repositories() -> list[dict]:
    """Return comprehensive list of registered repositories with graph metadata and freshness."""
    results = []
    seen_graphs = set()

    for key, slug in sorted(REPO_SLUGS.items()):
        graph_name = REPOS.get(key, "")
        if graph_name in seen_graphs:
            continue
        seen_graphs.add(graph_name)

        try:
            nodes = node_count(key)
            edges = edge_count(key)
            prov = graph_provenance(key)
            status = "ready" if nodes > 0 else "empty"
        except Exception:
            nodes = 0
            edges = 0
            prov = {"status": "unavailable", "message": "FalkorDB unreachable"}
            status = "offline"

        results.append({
            "key": key,
            "slug": slug,
            "graph_name": graph_name,
            "nodes": nodes,
            "edges": edges,
            "status": status,
            "provenance": prov,
        })

    return results


# Global singleton instance
INGESTION_MANAGER = IngestionJobManager()
