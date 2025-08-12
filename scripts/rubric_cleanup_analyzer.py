#!/usr/bin/env python3
"""
Canvas Rubric Cleanup Analyzer - LTI Phase 2 (Preview-First)
===========================================================

Purpose
- Analyze rubrics within a single Canvas course and classify items into:
  - safe_actions: deletion candidates safe to execute
  - requires_manual_review: items needing human decision (duplicates, protected, used, uncertain)
- Execute approved deletions from a JSON file when requested.

Phase 2 Architecture Compliance
- Args: --canvas-url, --api-token, --course-id, (--analyze-only | --execute-from-json FILE)
- Output: ENHANCED_ANALYSIS_JSON: {...} for analysis, EXECUTION_RESULTS_JSON: {...} for execution
- Non-interactive; robust error handling; conservative classification on API uncertainties

Notes
- This script is additive-only for the LTI integration. It does not modify existing scripts.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from common.progress import ProgressReporter


LOGGING_LEVEL = logging.INFO
REQUEST_TIMEOUT = 30
DEFAULT_PER_PAGE = 100

# Heuristics and safety configuration (aligned with standalone tool, simplified for LTI)
RETENTION_MONTHS_DEFAULT = 24
SIMILARITY_THRESHOLD_DEFAULT = 0.85  # Not content-diff; we use content hash equality, this is unused but kept for future
MIN_AGE_DAYS_DEFAULT = 30

TEST_KEYWORDS = {
    "test", "draft", "sample", "example", "temp", "temporary", "xxx", "123", "asdf",
    "qwerty", "demo", "practice", "untitled", "new rubric", "placeholder", "copy", "backup"
}
PROTECTED_PATTERNS = {
    "official", "template", "standard", "required", "institutional", "master", "final"
}


def setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=LOGGING_LEVEL,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr,
    )
    return logging.getLogger(__name__)


class CanvasSession:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = f'https://{self.base_url}'
        self.api_base = f"{self.base_url}/api/v1"
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({'Authorization': f'Bearer {api_token}', 'Content-Type': 'application/json'})

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[requests.Response]:
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        try:
            response = self.session.get(
                url,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )
            return response
        except requests.RequestException:
            return None

    def delete(self, endpoint: str) -> Optional[requests.Response]:
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        try:
            response = self.session.delete(url, timeout=REQUEST_TIMEOUT)
            return response
        except requests.RequestException:
            return None

    def paginated(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        results: List[Dict[str, Any]] = []
        if params is None:
            params = {}
        params['per_page'] = DEFAULT_PER_PAGE

        while url:
            try:
                resp = self.session.get(url, params=params if url.endswith(endpoint) or url.endswith(endpoint.lstrip('/')) else None, timeout=REQUEST_TIMEOUT)
                if resp.status_code >= 400:
                    break
                data = resp.json()
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
                # Parse Link header for next
                link_header = resp.headers.get('Link', '')
                next_url = None
                for part in link_header.split(','):
                    if 'rel="next"' in part:
                        try:
                            next_url = part.split('<')[1].split('>')[0]
                        except Exception:
                            next_url = None
                        break
                url = next_url
                time.sleep(0.05)
            except requests.RequestException:
                break
        return results


def calculate_rubric_hash(rubric: Dict[str, Any]) -> str:
    import hashlib
    parts: List[str] = []
    title = (rubric.get('title') or '').strip().lower()
    if title:
        parts.append(title)
    data = rubric.get('data') or []
    for criterion in data:
        desc = (criterion.get('description') or '').strip().lower()
        if desc:
            parts.append(desc)
        for rating in criterion.get('ratings') or []:
            rdesc = (rating.get('description') or '').strip().lower()
            if rdesc:
                parts.append(rdesc)
    content = '|'.join(parts)
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def looks_like_test_rubric(title: str, criteria_count: int) -> bool:
    t = (title or '').strip().lower()
    if any(k in t for k in TEST_KEYWORDS):
        return True
    if criteria_count <= 1:
        return True
    if any(p in t for p in ['rubric', 'untitled', 'new rubric']) and criteria_count <= 2:
        return True
    return False


def looks_protected(rubric: Dict[str, Any]) -> bool:
    t = (rubric.get('title') or '').strip().lower()
    if any(p in t for p in PROTECTED_PATTERNS):
        return True
    if rubric.get('read_only'):
        return True
    if rubric.get('reusable'):
        return True
    return False


def parse_iso(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        # Canvas returns ISO8601, sometimes with 'Z'
        return datetime.fromisoformat(dt.replace('Z', '+00:00'))
    except Exception:
        return None


def analyze_rubrics(logger: logging.Logger, cs: CanvasSession, course_id: str,
                    retention_months: int, min_age_days: int, progress: ProgressReporter | None = None) -> Dict[str, Any]:
    start = time.time()
    if progress:
        progress.update(step="initialize", message="Preparing analysis")

    # Course info (for workflow_state and term)
    course_info = None
    resp_course = cs.get(f"courses/{course_id}")
    if resp_course and resp_course.status_code == 200:
        try:
            course_info = resp_course.json()
        except Exception:
            course_info = {}
    else:
        course_info = {}

    workflow_state = (course_info or {}).get('workflow_state', 'available')
    term_name = (course_info or {}).get('term', {}).get('name', 'Unknown')

    # Fetch rubrics for course
    if progress:
        progress.update(step="fetch_rubrics", message="Fetching rubrics")
    rubrics = cs.paginated(f"courses/{course_id}/rubrics", params={"include[]": ["assessments", "graded_assessments", "peer_assessments"]})

    # Build map rubric_id -> associations
    associations_by_rubric: Dict[int, List[Dict[str, Any]]] = {}
    total = len(rubrics) or 1
    processed = 0
    for r in rubrics:
        rid = r.get('id')
        if not rid:
            continue
        assoc = cs.paginated(f"courses/{course_id}/rubrics/{rid}/associations")
        associations_by_rubric[rid] = assoc
        processed += 1
        if progress:
            progress.update(step="fetch_associations", current=processed, total=total, message=f"Fetched {processed}/{total} associations")

    # For usage_count, attempt to resolve assessments by association
    usage_count_by_rubric: Dict[int, int] = {}
    last_used_by_rubric: Dict[int, Optional[str]] = {}
    for rid, assocs in associations_by_rubric.items():
        total_assessments = 0
        last_used: Optional[str] = None
        for assoc in assocs:
            assoc_id = assoc.get('id')
            if not assoc_id:
                continue
            # Best-effort: rubric assessments require association id
            resp = cs.paginated(f"courses/{course_id}/rubric_associations/{assoc_id}/rubric_assessments")
            total_assessments += len(resp)
            for a in resp:
                date = a.get('updated_at') or a.get('created_at')
                if date and (not last_used or date > last_used):
                    last_used = date
        usage_count_by_rubric[rid] = total_assessments
        last_used_by_rubric[rid] = last_used

    # Enrich rubrics with computed fields
    enriched: List[Dict[str, Any]] = []
    for r in rubrics:
        rid = r.get('id')
        if not rid:
            continue
        content_hash = calculate_rubric_hash(r)
        criteria_count = len(r.get('data') or [])
        enriched.append({
            'id': rid,
            'title': r.get('title') or 'Untitled',
            'created_at': r.get('created_at'),
            'updated_at': r.get('updated_at'),
            'points_possible': r.get('points_possible', 0),
            'criteria_count': criteria_count,
            'content_hash': content_hash,
            'association_count': len(associations_by_rubric.get(rid, [])),
            'usage_count': usage_count_by_rubric.get(rid, 0),
            'last_used_date': last_used_by_rubric.get(rid),
            'is_draft': r.get('workflow_state') == 'draft',
            'read_only': bool(r.get('read_only')),
            'reusable': bool(r.get('reusable')),
        })

    # Identify categories
    cutoff_date = datetime.utcnow() - timedelta(days=retention_months * 30)

    duplicates_groups: List[List[Dict[str, Any]]] = []
    grouped_by_hash: Dict[str, List[Dict[str, Any]]] = {}
    total_enriched = len(enriched) or 1
    for idx, er in enumerate(enriched, 1):
        grouped_by_hash.setdefault(er['content_hash'], []).append(er)
        if progress and idx % 10 == 0:
            progress.update(step="analyze_rubrics", current=idx, total=total_enriched, message=f"Processed {idx}/{total_enriched} rubrics")
    for h, group in grouped_by_hash.items():
        if h and len(group) > 1:
            # Sort keep-first by last_used_date desc then updated_at desc
            group_sorted = sorted(
                group,
                key=lambda x: (x.get('last_used_date') or x.get('updated_at') or x.get('created_at') or '1900'),
                reverse=True,
            )
            duplicates_groups.append(group_sorted)

    test_rubrics: List[Dict[str, Any]] = [er for er in enriched if looks_like_test_rubric(er['title'], er['criteria_count'])]
    protected_rubrics: List[Dict[str, Any]] = []
    for r in rubrics:
        if looks_protected(r):
            rid = r.get('id')
            match = next((er for er in enriched if er['id'] == rid), None)
            if match:
                protected_rubrics.append(match)

    outdated_rubrics: List[Dict[str, Any]] = []
    for er in enriched:
        out = False
        if er.get('last_used_date'):
            lu = parse_iso(er['last_used_date'])
            if lu and lu < cutoff_date:
                out = True
        else:
            created = parse_iso(er.get('created_at'))
            if created and created < cutoff_date and er.get('usage_count', 0) == 0:
                out = True
        if workflow_state in ['completed', 'deleted']:
            out = True
        if out:
            outdated_rubrics.append(er)

    # Safe candidates
    protected_ids = {r['id'] for r in protected_rubrics}
    safe_candidates: List[Dict[str, Any]] = []
    for er in enriched:
        if er['id'] in protected_ids:
            continue
        if er['association_count'] == 0 and er['usage_count'] == 0:
            created_dt = parse_iso(er.get('created_at'))
            old_enough = True
            if created_dt:
                old_enough = (datetime.utcnow() - created_dt).days >= min_age_days
            if old_enough:
                safe_candidates.append(er)

    # Compose findings
    safe_actions: List[Dict[str, Any]] = []
    for er in safe_candidates:
        safe_actions.append({
            'type': 'delete_rubric',
            'rubric_id': er['id'],
            'rubric_title': er['title'],
            'course_id': course_id,
            'reason': 'No associations; never used; older than minimum age',
            'risk_level': 'LOW',
            'canvas_url': f"{cs.base_url}/courses/{course_id}/rubrics/{er['id']}"
        })

    requires_manual_review: List[Dict[str, Any]] = []

    # Duplicate groups (keep first, review others)
    for group in duplicates_groups:
        keep = group[0]
        delete_candidates = [
            {
                'rubric_id': g['id'],
                'rubric_title': g['title'],
                'last_used_date': g['last_used_date'],
                'usage_count': g['usage_count'],
                'associations': g['association_count'],
                'canvas_url': f"{cs.base_url}/courses/{course_id}/rubrics/{g['id']}"
            } for g in group[1:]
        ]
        if delete_candidates:
            requires_manual_review.append({
                'type': 'duplicate_rubric_group',
                'group_key': group[0]['content_hash'][:12],
                'keep_rubric_id': keep['id'],
                'keep_rubric_title': keep['title'],
                'delete_candidates': delete_candidates,
                'reason': 'Duplicate content detected; verify before deletion',
                'risk_level': 'MEDIUM'
            })

    # Protected
    for pr in protected_rubrics:
        requires_manual_review.append({
            'type': 'protected_rubric',
            'rubric_id': pr['id'],
            'rubric_title': pr['title'],
            'reason': 'Matches protected pattern or read-only/reusable',
            'risk_level': 'HIGH',
            'canvas_url': f"{cs.base_url}/courses/{course_id}/rubrics/{pr['id']}"
        })

    # Outdated but not clearly safe (e.g., had usage or unsure)
    for od in outdated_rubrics:
        if od['id'] in {a['rubric_id'] for a in safe_actions}:
            continue
        requires_manual_review.append({
            'type': 'outdated_rubric',
            'rubric_id': od['id'],
            'rubric_title': od['title'],
            'usage_count': od['usage_count'],
            'last_used_date': od['last_used_date'],
            'reason': 'Rubric is older than retention period; confirm before deletion',
            'risk_level': 'MEDIUM',
            'canvas_url': f"{cs.base_url}/courses/{course_id}/rubrics/{od['id']}"
        })

    processing_time = time.time() - start

    result = {
        'phase': 2,
        'mode': 'preview_first',
        'analysis_complete': True,
        'course_info': {
            'course_id': str(course_id),
            'course_name': (course_info or {}).get('name', 'Unknown Course'),
            'term_name': term_name,
            'workflow_state': workflow_state
        },
        'summary': {
            'rubrics_scanned': len(enriched),
            'unused_rubrics': len([er for er in enriched if er['association_count'] == 0]),
            'duplicate_groups': len(duplicates_groups),
            'test_rubrics': len(test_rubrics),
            'outdated_rubrics': len(outdated_rubrics),
            'protected_rubrics': len(protected_rubrics),
            'safe_actions_found': len(safe_actions),
            'manual_review_needed': len(requires_manual_review),
            'api_calls': None,  # Not tracked precisely here
            'processing_time_seconds': round(processing_time, 1)
        },
        'findings': {
            'safe_actions': safe_actions,
            'requires_manual_review': requires_manual_review
        },
        'risk_assessment': {
            'protected_by_patterns': len(protected_rubrics),
            'recently_updated': len([er for er in enriched if er.get('updated_at') and parse_iso(er.get('updated_at')) and (datetime.utcnow() - parse_iso(er.get('updated_at'))).days < MIN_AGE_DAYS_DEFAULT]),
            'api_uncertainties': 0
        }
    }

    if progress:
        progress.done({"summary": result.get("summary", {})})
    return result


def execute_deletions(logger: logging.Logger, cs: CanvasSession, course_id: str, approved_actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    successful: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for idx, action in enumerate(approved_actions):
        if action.get('type') != 'delete_rubric':
            continue
        rid = action.get('rubric_id')
        title = action.get('rubric_title') or 'Unknown'
        if not rid:
            failed.append({**action, 'failure_reason': 'Missing rubric_id'})
            continue
        resp = cs.delete(f"courses/{course_id}/rubrics/{rid}")
        if resp and 200 <= resp.status_code < 300:
            successful.append({'rubric_id': rid, 'rubric_title': title, 'reason': 'Deleted successfully'})
        else:
            reason = 'Unknown error'
            if resp is not None:
                try:
                    j = resp.json()
                    reason = j.get('message') or j.get('errors') or f"HTTP {resp.status_code}"
                except Exception:
                    reason = f"HTTP {resp.status_code}"
            failed.append({'rubric_id': rid, 'rubric_title': title, 'failure_reason': str(reason)})
        time.sleep(0.05)

    return {
        'summary': {
            'successful': len(successful),
            'failed': len(failed)
        },
        'results': {
            'successful_fixes': successful,
            'failed_fixes': failed
        }
    }


def main():
    logger = setup_logger()
    parser = argparse.ArgumentParser(description='Canvas Rubric Cleanup Analyzer - LTI Phase 2')
    parser.add_argument('--canvas-url', required=True, help='Canvas base URL (e.g., canvas.instructure.com)')
    parser.add_argument('--api-token', required=True, help='Canvas API token')
    parser.add_argument('--course-id', required=True, help='Course ID to analyze')
    parser.add_argument('--analyze-only', action='store_true', help='Perform analysis only (default)')
    parser.add_argument('--execute-from-json', type=str, help='Execute approved actions from JSON file')
    parser.add_argument('--retention-months', type=int, default=RETENTION_MONTHS_DEFAULT, help='Retention months for outdated detection')
    parser.add_argument('--min-age-days', type=int, default=MIN_AGE_DAYS_DEFAULT, help='Minimum age (days) for safe deletion')

    args = parser.parse_args()

    try:
        cs = CanvasSession(args.canvas_url, args.api_token)

        if args.execute_from_json:
            with open(args.execute_from_json, 'r') as f:
                approved_actions = json.load(f)
            exec_result = execute_deletions(logger, cs, args.course_id, approved_actions or [])
            print("EXECUTION_RESULTS_JSON:", json.dumps(exec_result))
            return

        # Default: analyze
        progress = ProgressReporter(enabled=True)
        result = analyze_rubrics(logger, cs, args.course_id, args.retention_months, args.min_age_days, progress=progress)
        print("ENHANCED_ANALYSIS_JSON:", json.dumps(result))
    except Exception as e:
        # Structured error output for Node caller
        error_output = {
            'success': False,
            'error': str(e),
            'phase': 2,
            'mode': 'analysis_only'
        }
        print(f"CRITICAL_ERROR_JSON: {json.dumps(error_output)}")
        sys.exit(1)


if __name__ == '__main__':
    main()


