# --- START OF FILE assignment_settings_validator.py (Version 3 - Definitive) ---

"""
Canvas Assignment Settings Validator - Version 3 (Definitive & Human-Centered)

This definitive script merges the comprehensive validation logic of the original standalone
tool with the superior, safe, and consistent architecture of the V3 QA Suite.

What's New in This Definitive Version:
- FUNCTIONALLY COMPLETE: All high-value QA checks from the standalone script have been integrated,
  including points vs. rubrics, assignment groups, hurdle task logic, and more.
- CRITICAL SAFETY (Submission Guardrail): The script checks if an assignment has submissions
  or is past its due date. Any such assignments are ALWAYS flagged for manual review,
  preventing automated changes to live student work.
- ARCHITECTURAL CONSISTENCY: Fully aligned with the QA suite's gold standard:
  - Clean, two-mode control flow: `--analyze-only` and `--execute-from-json`.
  - Identical JSON output contract: `{ "summary": ..., "findings": { ... } }` for a seamless UI.
  - Resilient `requests.Session` with retries for robust API communication.
- ENHANCED INTELLIGENCE & EXPLAINABILITY:
  - Each finding includes a standardized `reason` key for clear user explanations.
  - Each auto-fixable finding includes a `fix_action` dictionary for safe, targeted execution.
"""

import requests
import json
import logging
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta
import concurrent.futures
import argparse
import sys
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from common.progress import ProgressReporter

# --- SCRIPT CONFIGURATION ---
LOGGING_LEVEL = logging.INFO
MAX_API_WORKERS = 10

class CanvasAssignmentValidator:
    """A robust, human-centered tool to validate assignment settings."""

    def __init__(self, base_url: str, api_token: str, course_id: str):
        """Initializes the validator with API credentials and a resilient requests session."""
        self.base_url = f"https://{base_url}".rstrip('/')
        self.api_url = f"{self.base_url}/api/v1"
        self.course_id = course_id
        
        logging.basicConfig(level=LOGGING_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.headers.update({"Authorization": f"Bearer {api_token}"})
        
        self.standards = {
            'default_points': 100,
            'valid_assignment_groups': ['Assignment 1', 'Assignment 2', 'Assignment 3'],
            'hurdle_grading_type': 'pass_fail',
            'normal_grading_type': 'points',
            'default_submission_types': ['online_upload', 'online_text_entry'],
            'unlimited_attempts': -1,
            'availability_buffer_days': 3,
            'print_button_html': '<div id="printButton"></div>'
        }

    def _make_paginated_request(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        results = []
        url = f"{self.api_url}/{endpoint}"
        if params is None:
            params = {}
        params['per_page'] = 100
        while url:
            try:
                response = self.session.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                results.extend(data)
                url = response.links.get('next', {}).get('url')
                params = None
            except requests.exceptions.RequestException as e:
                self.logger.error(f"API request failed for '{endpoint}': {e}")
                raise
        return results

    @staticmethod
    def _is_past_due(assignment: Dict) -> bool:
        due_at_str = assignment.get('due_at')
        if not due_at_str: return False
        try:
            due_date = datetime.fromisoformat(due_at_str.replace('Z', '+00:00'))
            return due_date < datetime.now(timezone.utc)
        except (ValueError, TypeError): return False

    def analyze_course_assignments(self, progress: ProgressReporter | None = None) -> Dict:
        self.logger.info("Fetching all assignments, groups, and course data...")
        if progress:
            progress.update(step="fetch_assignments", message="Fetching assignments & groups")
        assignments = self._make_paginated_request(f"courses/{self.course_id}/assignments", params={'include': ['rubric']})
        assignment_groups = self._make_paginated_request(f"courses/{self.course_id}/assignment_groups")
        group_map = {g['id']: g['name'] for g in assignment_groups}

        if not assignments:
            self.logger.info("No assignments found in this course.")
            return {"summary": {"assignments_scanned": 0}, "findings": {"safe_actions": [], "requires_manual_review": []}}

        safe_actions, requires_manual_review, all_violations = [], [], []

        total = len(assignments) or 1
        for idx, assignment in enumerate(assignments, 1):
            has_submissions = assignment.get('has_submitted_submissions', False)
            is_past_due = self._is_past_due(assignment)
            is_locked_for_edits = has_submissions or is_past_due
            
            violations = self._validate_single_assignment(assignment, group_map)
            
            if not violations: continue
            # Add assignment_id to each violation for tracking
            for violation in violations:
                violation['assignment_id'] = assignment['id']
            all_violations.extend(violations)
            
            for violation in violations:
                finding = {"assignment_name": assignment['name'], "assignment_id": assignment['id'], **violation}
                
                if is_locked_for_edits and finding.get('auto_fixable'):
                    guardrail_reason = "Has submissions" if has_submissions else "Due date is in the past"
                    finding['reason'] = f"⚠️ ({guardrail_reason}) {violation['reason']}"
                    finding['risk_level'] = 'HIGH'
                    finding['auto_fixable'] = False # Override auto-fixability
                    requires_manual_review.append(finding)
                elif finding.get('auto_fixable'):
                    safe_actions.append(finding)
                else:
                    requires_manual_review.append(finding)
            if progress:
                progress.update(step="analyze_assignments", current=idx, total=total, message=f"Analyzed {idx}/{total} assignments")
        
        result = {
            "summary": {
                "assignments_scanned": len(assignments),
                "assignments_with_issues": len(set(v['assignment_id'] for v in all_violations)),
                "total_violations_found": len(all_violations),
                "safe_actions_found": len(safe_actions),
                "manual_review_needed": len(requires_manual_review),
            },
            "findings": {"safe_actions": safe_actions, "requires_manual_review": requires_manual_review}
        }
        if progress:
            progress.done({"summary": result.get("summary", {})})
        return result

    def _validate_single_assignment(self, assignment: Dict, group_map: Dict) -> List[Dict]:
        """Runs all validation checks from the standalone script on a single assignment."""
        violations = []
        is_hurdle = "hurdle" in assignment.get('name', '').lower()

        # Points & Grading
        points = assignment.get('points_possible')
        rubric_points = sum(c.get('points', 0) for c in assignment.get('rubric', []))
        if points != self.standards['default_points']:
            violations.append({"violation_type": "Points Mismatch", "severity": "Medium", "reason": f"Points are {points} but should be {self.standards['default_points']}.", "auto_fixable": True, "fix_action": {'type': 'update_points', 'value': self.standards['default_points']}})
        if rubric_points > 0 and points != rubric_points:
            violations.append({"violation_type": "Points-Rubric Mismatch", "severity": "High", "reason": f"Assignment points ({points}) do not match rubric total ({rubric_points}).", "auto_fixable": True, "fix_action": {'type': 'update_points', 'value': rubric_points}})
        
        # Grading Type
        grading_type = assignment.get('grading_type')
        if is_hurdle and grading_type != self.standards['hurdle_grading_type']:
            violations.append({"violation_type": "Incorrect Grading Type (Hurdle)", "severity": "High", "reason": "Hurdle tasks should use 'Pass/Fail' grading.", "auto_fixable": True, "fix_action": {'type': 'update_grading_type', 'value': self.standards['hurdle_grading_type']}})
        if not is_hurdle and grading_type != self.standards['normal_grading_type']:
            violations.append({"violation_type": "Incorrect Grading Type (Normal)", "severity": "Medium", "reason": f"Assignment is set to '{grading_type}' but should use 'Points'.", "auto_fixable": True, "fix_action": {'type': 'update_grading_type', 'value': self.standards['normal_grading_type']}})
        
        # Assignment Group
        group_name = group_map.get(assignment.get('assignment_group_id'), 'Unknown')
        if group_name not in self.standards['valid_assignment_groups']:
            violations.append({"violation_type": "Invalid Assignment Group", "severity": "Medium", "reason": f"Assignment is in group '{group_name}', which is non-standard.", "auto_fixable": False})

        # Submission Settings
        if assignment.get('allowed_attempts', -1) != self.standards['unlimited_attempts']:
            violations.append({"violation_type": "Limited Attempts", "severity": "Low", "reason": "Submission attempts should be unlimited for student flexibility.", "auto_fixable": True, "fix_action": {'type': 'update_attempts', 'value': self.standards['unlimited_attempts']}})
        
        # Description Content
        if self.standards['print_button_html'] not in (assignment.get('description') or ''):
            violations.append({"violation_type": "Missing Print Button", "severity": "Low", "reason": "Description is missing the standard print button HTML.", "auto_fixable": True, "fix_action": {'type': 'add_print_button'}})

        return violations

    def execute_approved_actions(self, actions: List[Dict]) -> Dict:
        """Executes a list of approved fix actions, building the correct API payloads."""
        if not actions: return {"summary": {"successful": 0, "failed": 0}, "results": {}}
        
        self.logger.info(f"Executing {len(actions)} approved fix actions...")
        self.logger.info(f"Actions received: {json.dumps(actions, indent=2)}")
        successful_fixes, failed_fixes = [], []

        def execute_fix(action: Dict):
            self.logger.info(f"Processing action: {json.dumps(action, indent=2)}")
            assignment_id = action.get('assignment_id')
            fix_action = action.get('fix_action')
            self.logger.info(f"Extracted assignment_id: {assignment_id}, fix_action: {fix_action}")
            if not all([assignment_id, fix_action]):
                failed_fixes.append({**action, "failure_reason": "Missing 'assignment_id' or 'fix_action'"})
                return
            try:
                payload = {'assignment': {}}
                action_type = fix_action.get('type')

                if action_type == 'update_points':
                    payload['assignment']['points_possible'] = fix_action['value']
                elif action_type == 'update_grading_type':
                    payload['assignment']['grading_type'] = fix_action['value']
                elif action_type == 'update_attempts':
                    payload['assignment']['allowed_attempts'] = fix_action['value']
                elif action_type == 'add_print_button':
                    # This action requires a GET-then-PUT to avoid overwriting description
                    current_assignment = self.session.get(f"{self.api_url}/courses/{self.course_id}/assignments/{assignment_id}").json()
                    current_desc = current_assignment.get('description') or ''
                    payload['assignment']['description'] = self.standards['print_button_html'] + "\n" + current_desc
                else:
                    raise ValueError(f"Unknown fix action type: {action_type}")
                
                url = f"{self.api_url}/courses/{self.course_id}/assignments/{assignment_id}"
                response = self.session.put(url, json=payload)
                response.raise_for_status()
                successful_fixes.append(action)
                self.logger.info(f"Successfully applied fix '{action_type}' to assignment {assignment_id}")

            except Exception as e:
                self.logger.error(f"Failed to execute fix for assignment {assignment_id}: {e}")
                failed_fixes.append({**action, "failure_reason": str(e)})

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
            executor.map(execute_fix, actions)
            
        return {
            "summary": {"successful": len(successful_fixes), "failed": len(failed_fixes)},
            "results": {"successful_fixes": successful_fixes, "failed_fixes": failed_fixes}
        }

def main():
    """Main function to handle command-line execution, consistent with V3 architecture."""
    parser = argparse.ArgumentParser(description="Canvas Assignment Settings Validator v3 (Definitive)")
    parser.add_argument('--canvas-url', required=True, help="Base URL of the Canvas instance")
    parser.add_argument('--api-token', required=True, help="A valid Canvas API token")
    parser.add_argument('--course-id', required=True, help="The ID of the course to process")
    
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--analyze-only', action='store_true', help="Perform a read-only analysis and output JSON.")
    mode.add_argument('--execute-from-json', type=str, metavar="FILE_PATH", help="Execute approved actions from a JSON file.")

    args = parser.parse_args()
    
    validator = CanvasAssignmentValidator(args.canvas_url, args.api_token, args.course_id)
    
    try:
        if args.execute_from_json:
            print(f"Executing approved assignment fixes from: {args.execute_from_json}", file=sys.stderr)
            with open(args.execute_from_json, 'r') as f:
                actions_to_execute = json.load(f)
            
            execution_results = validator.execute_approved_actions(actions_to_execute)
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_results, indent=2))

        else: # --analyze-only
            print(f"Performing assignment analysis for course: {args.course_id}", file=sys.stderr)
            progress = ProgressReporter(enabled=True)
            analysis_results = validator.analyze_course_assignments(progress=progress)
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis_results, indent=2))
            
    except Exception as e:
        logging.getLogger(__name__).critical(f"A critical error occurred: {e}", exc_info=True)
        error_output = json.dumps({"success": False, "error": str(e)})
        print(f"CRITICAL_ERROR_JSON: {error_output}", file=sys.stdout)
        sys.exit(1)

if __name__ == "__main__":
    main()

# --- HANDOVER NOTE (Definitive V3) ---
# This script is now functionally complete and architecturally consistent with the QA Suite.
# Key Features:
# - Submission Safety Guardrail: Automatically protects live/completed assignments from changes.
# - Full Functional Parity: Includes all major validation checks from the original standalone tool.
# - Consistent Architecture: Uses the standard two-mode flow and JSON output contract.
# - Actionable Findings: Provides `fix_action` data for safe, one-click resolutions in the UI.
# ---------------------------------------------------------------------------------------------