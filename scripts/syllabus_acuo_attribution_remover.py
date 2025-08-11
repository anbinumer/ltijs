#!/usr/bin/env python3
"""
Syllabus ACUO Attribution Remover - Phase 2 (Preview-First)
==========================================================

Purpose
  - Analyze a Canvas course syllabus for occurrences of the pattern
    "(ACU Online, YYYY)" and stage safe removals.
  - Execute only when explicitly approved, using a precondition hash to
    avoid stale writes.

Integration Notes
  - This script conforms to the QA LTI V3 contract:
    - Analysis prints: ENHANCED_ANALYSIS_JSON: { ... }
    - Execution prints: EXECUTION_RESULTS_JSON: { ... }
  - Args used by the LTI backend:
    --canvas-url, --api-token, --course-id, --analyze-only, --execute-from-json

Requirements
  - requests, beautifulsoup4

"""

import argparse
import hashlib
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


ATTRIBUTION_REGEX = re.compile(r"\(ACU\s+Online,\s*\d{4}\)", re.IGNORECASE)
SENSITIVE_ANCESTOR_TAGS = {"blockquote", "code", "pre", "li"}
HEADING_TAGS = {f"h{i}" for i in range(1, 7)}
SENSITIVE_SECTION_KEYWORDS = re.compile(
    r"references|bibliography|citations|citation", re.IGNORECASE
)


def build_base_url(canvas_url: str) -> str:
    if canvas_url.startswith("http://") or canvas_url.startswith("https://"):
        return canvas_url.rstrip("/")
    return f"https://{canvas_url.rstrip('/')}"


def sha256_hex(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def canvas_get(session: requests.Session, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    resp = session.get(url, params=params or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def canvas_put(session: requests.Session, url: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    resp = session.put(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_course_with_syllabus(session: requests.Session, base_url: str, course_id: str) -> Optional[Dict[str, Any]]:
    try:
        url = f"{base_url}/api/v1/courses/{course_id}"
        return canvas_get(session, url, params={"include[]": ["syllabus_body"]})
    except requests.HTTPError as e:
        sys.stderr.write(f"HTTP error fetching course {course_id}: {e}\n")
    except Exception as e:
        sys.stderr.write(f"Error fetching course {course_id}: {e}\n")
    return None


def find_attribution_occurrences(html: str) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Returns: (total_occurrences, manual_review_count, detailed_matches)
    detailed_matches: list of dicts with keys:
      - text: matched text
      - context_excerpt: short excerpt around match
      - is_manual: bool
      - reason: str
    """
    if not html:
        return 0, 0, []

    # Count occurrences via regex on raw HTML
    raw_occurrences = len(ATTRIBUTION_REGEX.findall(html))
    if raw_occurrences == 0:
        return 0, 0, []

    details: List[Dict[str, Any]] = []
    manual_count = 0

    try:
        soup = BeautifulSoup(html, "html.parser")
        # Walk all NavigableString nodes that match the regex
        for text_node in soup.find_all(string=ATTRIBUTION_REGEX):
            text_value = str(text_node)
            match = ATTRIBUTION_REGEX.search(text_value)
            if not match:
                continue

            # Determine context
            is_sensitive_context = False
            reason_parts: List[str] = []

            # Check ancestor tags
            for ancestor in text_node.parents:
                if ancestor.name in SENSITIVE_ANCESTOR_TAGS or ancestor.name in HEADING_TAGS:
                    is_sensitive_context = True
                    reason_parts.append(f"Inside <{ancestor.name}> element")
                    break

                # If a section contains sensitive keywords
                if ancestor.get_text(strip=True) and SENSITIVE_SECTION_KEYWORDS.search(
                    ancestor.get_text(separator=" ", strip=True)[:400]
                ):
                    is_sensitive_context = True
                    reason_parts.append("Located in references/citations section")
                    break

            # Create excerpt around the match within the text node
            start, end = match.span()
            prefix = text_value[max(0, start - 40) : start]
            suffix = text_value[end : end + 40]
            excerpt = f"{prefix}[{match.group(0)}]{suffix}"

            if is_sensitive_context:
                manual_count += 1
                details.append(
                    {
                        "text": match.group(0),
                        "context_excerpt": excerpt,
                        "is_manual": True,
                        "reason": ", ".join(reason_parts) or "Context requires manual review",
                    }
                )
            else:
                details.append(
                    {
                        "text": match.group(0),
                        "context_excerpt": excerpt,
                        "is_manual": False,
                        "reason": "Plain paragraph context; safe removal",
                    }
                )
    except Exception:
        # If parsing fails, treat all as manual review for safety
        return raw_occurrences, raw_occurrences, [
            {
                "text": "(parse_error)",
                "context_excerpt": "",
                "is_manual": True,
                "reason": "HTML parsing error; manual review",
            }
        ]

    return raw_occurrences, manual_count, details


def build_analysis_output(
    course_id: str,
    course_name: str,
    syllabus_html: str,
) -> Dict[str, Any]:
    occurrences, manual_count, details = find_attribution_occurrences(syllabus_html)
    syllabus_hash = sha256_hex(syllabus_html or "")

    # Heuristic: if occurrences > 3, push to manual review bucket entirely
    high_density = occurrences > 3

    safe_details = [d for d in details if not d.get("is_manual")]
    manual_details = [d for d in details if d.get("is_manual")]

    if high_density and safe_details:
        manual_details.extend(
            {
                **d,
                "is_manual": True,
                "reason": (d.get("reason") or "") + "; high-density occurrences (>3)",
            }
            for d in safe_details
        )
        safe_details = []

    safe_actions: List[Dict[str, Any]] = []
    if occurrences > 0 and not safe_details == []:
        # Stage one consolidated safe action for all safe occurrences
        safe_occurrences = len(safe_details)
        if safe_occurrences > 0:
            safe_actions.append(
                {
                    "type": "remove_acuo_attribution",
                    "course_id": course_id,
                    "course_name": course_name,
                    "occurrence_count": safe_occurrences,
                    "syllabus_hash": syllabus_hash,
                    "reason": "Remove ACU Online attributions in safe contexts",
                    "severity": "Low",
                }
            )

    manual_items: List[Dict[str, Any]] = []
    for d in manual_details:
        manual_items.append(
            {
                "type": "review_syllabus_attribution",
                "course_id": course_id,
                "course_name": course_name,
                "excerpt": d.get("context_excerpt"),
                "reason": d.get("reason") or "Context requires manual review",
                "severity": "Medium",
            }
        )

    analysis: Dict[str, Any] = {
        "phase": 2,
        "mode": "preview_first",
        "analysis_complete": True,
        "summary": {
            "items_scanned": 1,
            "issues_found": occurrences,
            "safe_actions_found": len(safe_actions),
            "manual_review_needed": len(manual_items),
        },
        "findings": {
            "safe_actions": safe_actions,
            "requires_manual_review": manual_items,
        },
        "risk_assessment": {
            "occurrences_found": occurrences,
            "protected_by_context": len(manual_items),
            "high_density": high_density,
        },
    }

    return analysis


def perform_execution(
    session: requests.Session,
    base_url: str,
    course_id: str,
    approved_actions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    successful: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    # Load current syllabus and hash once for precondition verification
    course = fetch_course_with_syllabus(session, base_url, course_id)
    if not course:
        return {
            "summary": {"successful": 0, "failed": len(approved_actions)},
            "results": {
                "successful_fixes": successful,
                "failed_fixes": [
                    {
                        **(a or {}),
                        "failure_reason": "Unable to fetch course syllabus",
                    }
                    for a in approved_actions
                ],
            },
        }

    syllabus_html = course.get("syllabus_body") or ""
    current_hash = sha256_hex(syllabus_html)

    # We apply only the action type we support
    executable_actions = [a for a in approved_actions if a.get("type") == "remove_acuo_attribution"]
    non_executable = [a for a in approved_actions if a.get("type") != "remove_acuo_attribution"]

    for a in non_executable:
        failed.append({**a, "failure_reason": "manual_review_only_or_unsupported_action"})

    if not executable_actions:
        return {
            "summary": {"successful": 0, "failed": len(failed)},
            "results": {"successful_fixes": successful, "failed_fixes": failed},
        }

    # Precondition: syllabus_hash must match
    expected_hash = executable_actions[0].get("syllabus_hash")
    if expected_hash and expected_hash != current_hash:
        for a in executable_actions:
            failed.append({**a, "failure_reason": "content_changed_since_analysis"})
        return {
            "summary": {"successful": 0, "failed": len(failed)},
            "results": {"successful_fixes": successful, "failed_fixes": failed},
        }

    # Apply removal across the syllabus HTML
    before_count = len(ATTRIBUTION_REGEX.findall(syllabus_html))
    updated_html = ATTRIBUTION_REGEX.sub("", syllabus_html)
    after_count = len(ATTRIBUTION_REGEX.findall(updated_html))
    removed = max(0, before_count - after_count)

    if removed == 0:
        for a in executable_actions:
            failed.append({**a, "failure_reason": "no_occurrences_found_at_execution_time"})
        return {
            "summary": {"successful": 0, "failed": len(failed)},
            "results": {"successful_fixes": successful, "failed_fixes": failed},
        }

    # PUT update
    try:
        url = f"{base_url}/api/v1/courses/{course_id}"
        payload = {"course": {"syllabus_body": updated_html}}
        canvas_put(session, url, payload)

        successful.append(
            {
                "type": "remove_acuo_attribution",
                "course_id": course_id,
                "reason": f"Removed {removed} attribution(s)",
            }
        )

        return {
            "summary": {"successful": 1, "failed": len(failed)},
            "results": {"successful_fixes": successful, "failed_fixes": failed},
        }
    except requests.HTTPError as e:
        for a in executable_actions:
            failed.append({**a, "failure_reason": f"HTTP error updating syllabus: {e}"})
        return {
            "summary": {"successful": 0, "failed": len(failed)},
            "results": {"successful_fixes": successful, "failed_fixes": failed},
        }
    except Exception as e:
        for a in executable_actions:
            failed.append({**a, "failure_reason": f"Error updating syllabus: {e}"})
        return {
            "summary": {"successful": 0, "failed": len(failed)},
            "results": {"successful_fixes": successful, "failed_fixes": failed},
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Syllabus ACUO Attribution Remover - Phase 2")
    parser.add_argument("--canvas-url", required=True, help="Canvas instance URL (host or full URL)")
    parser.add_argument("--api-token", required=True, help="Canvas API token")
    parser.add_argument("--course-id", required=True, help="Canvas course ID")
    parser.add_argument("--analyze-only", action="store_true", help="Analyze only; do not execute")
    parser.add_argument("--risk-assessment", action="store_true", help="Include risk assessment details")
    parser.add_argument(
        "--execute-from-json",
        type=str,
        help="Execute only approved actions from JSON file",
    )

    args = parser.parse_args()

    base_url = build_base_url(args.canvas_url)
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {args.api_token}",
        "Content-Type": "application/json",
    })

    try:
        if args.execute_from_json:
            # Load approved actions
            try:
                with open(args.execute_from_json, "r", encoding="utf-8") as f:
                    approved_actions = json.load(f)
            except Exception as e:
                print(
                    "EXECUTION_RESULTS_JSON:",
                    json.dumps(
                        {
                            "summary": {"successful": 0, "failed": 0},
                            "results": {
                                "successful_fixes": [],
                                "failed_fixes": [
                                    {"failure_reason": f"Failed to load actions JSON: {e}"}
                                ],
                            },
                        }
                    ),
                )
                sys.exit(0)

            result = perform_execution(session, base_url, args.course_id, approved_actions or [])
            print("EXECUTION_RESULTS_JSON:", json.dumps(result))
            sys.exit(0)

        # Analysis flow
        course = fetch_course_with_syllabus(session, base_url, args.course_id)
        if not course:
            analysis = {
                "phase": 2,
                "mode": "preview_first",
                "analysis_complete": True,
                "summary": {
                    "items_scanned": 0,
                    "issues_found": 0,
                    "safe_actions_found": 0,
                    "manual_review_needed": 0,
                },
                "findings": {"safe_actions": [], "requires_manual_review": []},
                "risk_assessment": {"error": "Unable to fetch course"},
            }
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis))
            sys.exit(0)

        course_name = course.get("name") or "Unknown"
        syllabus_html = course.get("syllabus_body") or ""

        analysis = build_analysis_output(args.course_id, course_name, syllabus_html)
        print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis))
        sys.exit(0)

    except requests.HTTPError as e:
        # Emit structured error in analysis mode
        analysis = {
            "phase": 2,
            "mode": "preview_first",
            "analysis_complete": False,
            "summary": {
                "items_scanned": 0,
                "issues_found": 0,
                "safe_actions_found": 0,
                "manual_review_needed": 0,
            },
            "findings": {"safe_actions": [], "requires_manual_review": []},
            "risk_assessment": {"http_error": str(e)},
        }
        print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis))
        sys.exit(0)
    except Exception as e:
        analysis = {
            "phase": 2,
            "mode": "preview_first",
            "analysis_complete": False,
            "summary": {
                "items_scanned": 0,
                "issues_found": 0,
                "safe_actions_found": 0,
                "manual_review_needed": 0,
            },
            "findings": {"safe_actions": [], "requires_manual_review": []},
            "risk_assessment": {"error": str(e)},
        }
        print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis))
        sys.exit(0)


if __name__ == "__main__":
    main()


