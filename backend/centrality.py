"""Centrality materialization and precomputed retrieval.
Ensures request-time endpoints do not execute expensive graph algorithms.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

try:
    from backend.graph_client import execute_graph_query, validate_repo, DEFAULT_REPO, invalidate_repo_cache
    from backend.cache import METADATA_CACHE
except ImportError:
    from graph_client import execute_graph_query, validate_repo, DEFAULT_REPO, invalidate_repo_cache
    from cache import METADATA_CACHE

logger = logging.getLogger("keystone.centrality")


def get_centrality_status(repo: str = DEFAULT_REPO) -> dict:
    """Return status indicating whether centrality is current, stale, or unavailable."""
    key = validate_repo(repo)
    cache_key = f"centrality_status:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Check for metadata node first
    rows = execute_graph_query(
        """
        MATCH (m:KeystoneMetadata {key: 'centrality'})
        RETURN m.status, m.updated_at, m.file_count, m.algorithm
        LIMIT 1
        """,
        repo=key
    ).result_set

    if rows and len(rows[0]) >= 1:
        row = rows[0]
        status = row[0] if len(row) > 0 else "current"
        updated_at = row[1] if len(row) > 1 else None
        file_count = row[2] if len(row) > 2 else 0
        algo = row[3] if len(row) > 3 else "betweenness"
        result = {
            "status": status or "current",
            "updated_at": updated_at,
            "file_count": int(file_count or 0),
            "algorithm": algo or "betweenness",
            "message": f"Centrality materialized ({file_count} files scored).",
        }
    else:
        # Check if File nodes have pre-existing centrality values
        count_rows = execute_graph_query(
            "MATCH (f:File) WHERE f.centrality IS NOT NULL RETURN count(f)",
            repo=key
        ).result_set
        n_scored = int(count_rows[0][0]) if count_rows else 0
        if n_scored > 0:
            result = {
                "status": "current",
                "updated_at": None,
                "file_count": n_scored,
                "algorithm": "betweenness",
                "message": f"Precomputed centrality present on {n_scored} files.",
            }
        else:
            result = {
                "status": "unavailable",
                "updated_at": None,
                "file_count": 0,
                "algorithm": "betweenness",
                "message": "Centrality has not been computed for this repository graph.",
            }

    METADATA_CACHE.set(cache_key, result, ttl=30.0)
    return result


def get_precomputed_critical_files(limit: int = 20, repo: str = DEFAULT_REPO) -> dict:
    """Retrieve top files using precomputed File.centrality without running graph algorithms."""
    key = validate_repo(repo)
    status_info = get_centrality_status(key)

    rows = execute_graph_query(
        """
        MATCH (f:File)
        WHERE f.centrality IS NOT NULL AND f.centrality > 0
          AND NOT f.path STARTS WITH 'docs/'
          AND NOT f.path STARTS WITH 'website/'
          AND NOT f.path ENDS WITH '.md'
        RETURN f.path, f.centrality
        ORDER BY f.centrality DESC
        LIMIT $limit
        """,
        {"limit": limit},
        repo=key,
    ).result_set

    files = [{"path": str(r[0]), "score": round(float(r[1]), 4)} for r in rows]

    return {
        "files": files,
        "count": len(files),
        "status": status_info["status"],
        "updated_at": status_info.get("updated_at"),
        "message": status_info.get("message"),
    }


def ensure_co_changes(repo: str = DEFAULT_REPO) -> int:
    """Construct or update CO_CHANGES relationships from co-touched PR files."""
    key = validate_repo(repo)
    # Build bidirectional co-change edges weighted by shared PR count
    q = """
    MATCH (pr:PullRequest)-[:TOUCHES]->(f1:File)
    MATCH (pr)-[:TOUCHES]->(f2:File)
    WHERE id(f1) < id(f2)
    WITH f1, f2, count(pr) AS weight
    MERGE (f1)-[c1:CO_CHANGES]->(f2)
    SET c1.weight = weight
    MERGE (f2)-[c2:CO_CHANGES]->(f1)
    SET c2.weight = weight
    RETURN count(c1)
    """
    try:
        res = execute_graph_query(q, repo=key).result_set
        return int(res[0][0]) if res else 0
    except Exception as e:
        logger.warning(f"Error computing co-changes for {key}: {e}")
        return 0


def materialize_centrality(repo: str = DEFAULT_REPO) -> dict:
    """Run betweenness algorithm and store scores on File.centrality.
    
    Restricted to offline migration, post-ingestion, or authorized refresh.
    """
    key = validate_repo(repo)
    logger.info(f"Starting centrality materialization for {key}...")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Ensure co-change topology exists
    ensure_co_changes(key)

    try:
        # Run FalkorDB betweenness centrality algorithm on File nodes via CO_CHANGES
        algo_q = """
        CALL algo.betweenness({
            nodeLabels: ['File'],
            relationshipTypes: ['CO_CHANGES']
        }) YIELD node, score
        RETURN node.path, score
        """
        raw_res = execute_graph_query(algo_q, repo=key).result_set
        if not raw_res:
            return {
                "ok": False,
                "status": "unavailable",
                "message": "Algorithm produced no scores (empty subgraph or algorithm unsupported).",
                "updated_count": 0,
            }

        # Normalize and batch write back onto File.centrality
        scores = [(str(r[0]), float(r[1])) for r in raw_res if r[0] is not None]
        max_score = max((s[1] for s in scores), default=1.0) or 1.0

        batch = [{"path": path, "c": round(score / max_score, 4)} for path, score in scores]

        write_q = """
        UNWIND $batch AS item
        MATCH (f:File {path: item.path})
        SET f.centrality = item.c
        """
        execute_graph_query(write_q, {"batch": batch}, repo=key)

        # Record metadata
        meta_q = """
        MERGE (m:KeystoneMetadata {key: 'centrality'})
        SET m.status = 'current',
            m.updated_at = $now,
            m.file_count = $cnt,
            m.algorithm = 'betweenness'
        """
        execute_graph_query(meta_q, {"now": now_iso, "cnt": len(batch)}, repo=key)

        invalidate_repo_cache(key)

        return {
            "ok": True,
            "status": "current",
            "updated_at": now_iso,
            "file_count": len(batch),
            "message": f"Successfully materialized centrality for {len(batch)} files.",
        }

    except Exception as e:
        logger.error(f"Failed to materialize centrality for {key}: {e}")
        # Record failure metadata honestly
        fail_meta_q = """
        MERGE (m:KeystoneMetadata {key: 'centrality'})
        SET m.status = 'unavailable',
            m.updated_at = $now,
            m.error = $err
        """
        try:
            execute_graph_query(fail_meta_q, {"now": now_iso, "err": str(e)[:200]}, repo=key)
        except Exception:
            pass
        return {
            "ok": False,
            "status": "unavailable",
            "error": str(e),
            "message": f"FalkorDB graph algorithm failed: {type(e).__name__}: {e}",
            "file_count": 0,
        }
