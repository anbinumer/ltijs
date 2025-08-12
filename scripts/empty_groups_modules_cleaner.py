"""
Canvas Empty Groups and Modules Cleaner - LTI Enhanced (Phase 2)

Purpose
- Analyze a single Canvas course for empty assignment groups and empty modules
- Output UI-ready JSON with safe actions vs manual review
- Execute only user-approved deletions from a JSON file

Invocation (required args)
  python3 empty_groups_modules_cleaner.py \
    --canvas-url <domain or https://domain> \
    --api-token <token> \
    --course-id <id> \
    (--analyze-only | --execute-from-json <file>)

Output contract (stdout)
- ENHANCED_ANALYSIS_JSON: { ... }
- EXECUTION_RESULTS_JSON: { ... }
- On fatal error: CRITICAL_ERROR_JSON: { ... }
"""

import sys
import re
import json
import logging
import argparse
from typing import Dict, List, Any, Optional
from common.progress import ProgressReporter

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOGGING_LEVEL = logging.INFO
REQUEST_TIMEOUT = 30


class CanvasClient:
    def __init__(self, base_url: str, api_token: str):
        base_url = base_url.rstrip('/')
        if not base_url.startswith('http'):
            base_url = f'https://{base_url}'
        self.base_url = base_url
        self.api_base = f"{self.base_url}/api/v1"
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({'Authorization': f'Bearer {api_token}'})

    def _get(self, url: str, params: Dict[str, Any] = None) -> Any:
        resp = self.session.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp

    def _request_all_pages(self, endpoint: str, params: Dict[str, Any] = None) -> List[Dict]:
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        params = params or {}
        params.setdefault('per_page', 100)
        items: List[Dict] = []
        while url:
            resp = self._get(url, params=params)
            params = None  # only for first call
            if resp.content:
                data = resp.json()
                if isinstance(data, list):
                    items.extend(data)
                else:
                    items.append(data)
            # pagination
            links = resp.headers.get('Link', '')
            next_link = None
            for link in links.split(','):
                if 'rel="next"' in link:
                    next_link = link.split('<')[1].split('>')[0]
                    break
            url = next_link
        return items

    def get_course(self, course_id: str) -> Dict:
        resp = self._get(f"{self.api_base}/courses/{course_id}")
        return resp.json()

    def get_assignment_groups(self, course_id: str) -> List[Dict]:
        return self._request_all_pages(
            f"courses/{course_id}/assignment_groups",
            params={'include[]': ['assignments']}
        )

    def get_modules(self, course_id: str) -> List[Dict]:
        return self._request_all_pages(
            f"courses/{course_id}/modules",
            params={'include[]': ['items']}
        )

    def delete_assignment_group(self, course_id: str, group_id: int) -> Dict:
        resp = self.session.delete(
            f"{self.api_base}/courses/{course_id}/assignment_groups/{group_id}",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def delete_module(self, course_id: str, module_id: int) -> Dict:
        resp = self.session.delete(
            f"{self.api_base}/courses/{course_id}/modules/{module_id}",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}


def analyze_course(canvas: CanvasClient, course_id: str, progress: ProgressReporter | None = None) -> Dict:
    logging.info(f"Analyzing course {course_id} for empty groups and modules")
    if progress:
        progress.update(step="initialize", message="Preparing analysis")

    course = canvas.get_course(course_id)
    is_weighted = bool(course.get('apply_assignment_group_weights'))

    if progress:
        progress.update(step="fetch_groups_modules", message="Fetching groups & modules")
    groups = canvas.get_assignment_groups(course_id)
    modules = canvas.get_modules(course_id)

    # Build prerequisite set from modules
    prerequisite_targets = set()
    for m in modules:
        for pid in m.get('prerequisite_module_ids') or []:
            prerequisite_targets.add(pid)

    safe_actions: List[Dict[str, Any]] = []
    manual_review: List[Dict[str, Any]] = []

    # Assignment groups
    total = len(groups) + len(modules) or 1
    processed = 0
    for g in groups:
        assignments = g.get('assignments') or []
        is_empty = len(assignments) == 0
        weight = g.get('group_weight', 0) or 0
        item = {
            'type': 'delete_assignment_group',
            'course_id': course_id,
            'group_id': g.get('id'),
            'group_name': g.get('name'),
            'weight': weight,
            'is_weighted_course': is_weighted,
        }
        if is_empty:
            if (not is_weighted) or (is_weighted and weight == 0):
                item.update({'reason': 'Group has 0 assignments' + ('' if not is_weighted else ' and weight is 0 in a weighted course'), 'severity': 'low'})
                safe_actions.append(item)
            else:
                item.update({'reason': 'Weighted grading enabled and group has non-zero weight', 'severity': 'medium'})
                manual_review.append(item)
        processed += 1
        if progress:
            progress.update(step="analyze_groups_modules", current=processed, total=total, message=f"Processed {processed}/{total} items")

    # Modules
    for m in modules:
        items = m.get('items') or []
        is_empty = len(items) == 0
        is_published = bool(m.get('published'))
        module_id = m.get('id')
        is_prereq_target = module_id in prerequisite_targets
        item = {
            'type': 'delete_module',
            'course_id': course_id,
            'module_id': module_id,
            'module_name': m.get('name'),
            'published': is_published,
            'is_prerequisite_target': is_prereq_target,
        }
        if is_empty:
            if (not is_published) and (not is_prereq_target):
                item.update({'reason': 'Module is empty, unpublished, and not a prerequisite of another module', 'severity': 'low'})
                safe_actions.append(item)
            else:
                reason_bits = []
                if is_published:
                    reason_bits.append('published')
                if is_prereq_target:
                    reason_bits.append('referenced as prerequisite')
                reason_text = ' and '.join(reason_bits) if reason_bits else 'needs review'
                item.update({'reason': f'Module is empty but {reason_text}', 'severity': 'medium'})
                manual_review.append(item)
        processed += 1
        if progress:
            progress.update(step="analyze_groups_modules", current=processed, total=total, message=f"Processed {processed}/{total} items")

    summary = {
        'groups_scanned': len(groups),
        'modules_scanned': len(modules),
        'safe_actions_found': len(safe_actions),
        'manual_review_needed': len(manual_review),
        'weighted_course': is_weighted,
        'prerequisite_linked_modules': len([1 for m in manual_review if m['type'] == 'delete_module' and m.get('is_prerequisite_target')]),
    }

    result = {
        'success': True,
        'phase': 2,
        'mode': 'preview_first',
        'analysis_complete': True,
        'summary': summary,
        'findings': {
            'safe_actions': safe_actions,
            'requires_manual_review': manual_review,
        },
        'risk_assessment': {
            'weighted_course': is_weighted,
            'groups_with_weight': len([1 for g in groups if (g.get('group_weight') or 0) > 0]),
            'published_empty_modules': len([1 for m in manual_review if m['type'] == 'delete_module' and m.get('published') is True]),
        }
    }
    if progress:
        progress.done({"summary": summary})
    return result


def execute_actions(canvas: CanvasClient, course_id: str, actions: List[Dict[str, Any]]) -> Dict:
    successful: List[Dict] = []
    failed: List[Dict] = []

    for action in actions or []:
        try:
            if action.get('type') == 'delete_assignment_group':
                gid = action.get('group_id')
                if gid is None:
                    raise ValueError('Missing group_id')
                canvas.delete_assignment_group(course_id, gid)
                successful.append(action)
            elif action.get('type') == 'delete_module':
                mid = action.get('module_id')
                if mid is None:
                    raise ValueError('Missing module_id')
                canvas.delete_module(course_id, mid)
                successful.append(action)
            else:
                raise ValueError(f"Unknown action type: {action.get('type')}")
        except Exception as e:
            action_copy = dict(action)
            action_copy['failure_reason'] = str(e)
            failed.append(action_copy)

    return {
        'summary': {
            'successful': len(successful),
            'failed': len(failed)
        },
        'results': {
            'successful': successful,
            'failed': failed
        }
    }


def main():
    parser = argparse.ArgumentParser(description='Canvas Empty Groups and Modules Cleaner - LTI Enhanced')
    parser.add_argument('--canvas-url', required=True)
    parser.add_argument('--api-token', required=True)
    parser.add_argument('--course-id', required=True)
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--execute-from-json', type=str)
    args = parser.parse_args()

    logging.basicConfig(level=LOGGING_LEVEL, format='%(levelname)s: %(message)s', stream=sys.stderr)

    try:
        client = CanvasClient(args.canvas_url, args.api_token)

        if args.execute_from_json:
            with open(args.execute_from_json, 'r') as f:
                approved = json.load(f)
            results = execute_actions(client, args.course_id, approved)
            print('EXECUTION_RESULTS_JSON:', json.dumps(results, indent=2))
            return

        # default to analysis
        progress = ProgressReporter(enabled=True)
        analysis = analyze_course(client, args.course_id, progress=progress)
        print('ENHANCED_ANALYSIS_JSON:', json.dumps(analysis, indent=2))

    except Exception as e:
        logging.getLogger(__name__).critical(f"Critical error: {e}")
        print('CRITICAL_ERROR_JSON:', json.dumps({'success': False, 'error': str(e), 'phase': 2}), file=sys.stdout)
        sys.exit(1)


if __name__ == '__main__':
    main()


