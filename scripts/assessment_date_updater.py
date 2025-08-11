"""
Canvas Assessment Date Updater - LTI Enhanced Version

This script automates the process of removing specific dates and times from
assessment reminder wells on weekly summary pages and replacing them with
relative week-based deadlines (e.g., "due this week", "due in Week 6").

LTI Integration Features:
- Analysis-only mode with detailed findings categorization
- Enhanced JSON output for UI consumption
- Risk assessment for findings categorization
- Human-centered approach with clear explanations
- Phase 2 workflow support (analyze → approve → execute)

What This Script Does:
1. Parses the course syllabus to create a map of dates to week numbers
2. Scans all modules for pages with "summary" in the title
3. On each summary page, finds the 'reminder-well'
4. Within the well, searches for hard-coded dates and times
5. If found, replaces them with a relative week phrase
6. Categorizes findings for manual review (no auto-execution)

Prerequisites:
  pip install requests beautifulsoup4 lxml openpyxl

Author: AI Assistant (LTI Integration Version)
Version: 1.0 - LTI Enhanced
"""

import requests
import re
import time
import sys
import logging
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Script Configuration
LOGGING_LEVEL = logging.INFO
REQUEST_TIMEOUT = 30
MAX_API_WORKERS = 5

class AssessmentDateUpdater:
    """Finds and replaces hard-coded dates in assessment wells with LTI integration."""

    def __init__(self, base_url: str, api_token: str):
        """Initialize the updater with Canvas API credentials."""
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = f'https://{self.base_url}'
            
        self.api_token = api_token
        self.headers = {'Authorization': f'Bearer {api_token}'}
        self.logger = self._setup_logging()
        
        # Setup requests session with retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Final regex pattern to handle all test cases
        self.due_date_pattern = re.compile(
            r'(due\s+'  # Start with "due" and whitespace
            r'(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+)'  # Day of week
            r'(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?'  # Optional time
            r'(?:\s*(?:AEDT|AEST|UTC|GMT|EST|PDT)\s*)?'  # Optional timezone
            r'(\d{1,2}\s*[/\s]\s*\d{1,2}\s*[/\s]\s*\d{4})'  # Capture date part separately
            r'[^.]*?)'  # Non-greedy match of anything until the period
            r'\.',  # Required period
            re.IGNORECASE
        )

        # Alternative pattern for simpler format (no time)
        self.simple_due_date_pattern = re.compile(
            r'(due\s+'  # Start with "due" and whitespace
            r'(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+)'  # Day of week
            r'(\d{1,2}\s*[/\s]\s*\d{1,2}\s*[/\s]\s*\d{4})'  # Capture date part
            r'[^.]*?)'  # Non-greedy match of anything until the period
            r'\.',  # Required period
            re.IGNORECASE
        )

    def _setup_logging(self):
        """Configure logging for the script."""
        logging.basicConfig(
            level=LOGGING_LEVEL,
            format='%(levelname)s: %(message)s',
            stream=sys.stderr  # Log to stderr to keep stdout clean for JSON
        )
        return logging.getLogger(__name__)

    def _make_api_request(self, endpoint: str, params: Dict = None) -> Optional[Any]:
        """Make a single API request with error handling."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        try:
            response = self.session.get(
                url, 
                headers=self.headers, 
                params=params or {},
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed for {endpoint}: {e}")
            return None

    def _get_paginated_results(self, endpoint: str, params: Dict = None) -> List[Dict]:
        """Get all results from a paginated API endpoint."""
        all_items = []
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        params = params or {}
        params['per_page'] = 100
        
        while url:
            try:
                response = self.session.get(url, headers=self.headers, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                all_items.extend(data)
                
                # Get next page URL from Link header
                links = response.headers.get('Link', '')
                next_link = None
                for link in links.split(','):
                    if 'rel="next"' in link:
                        next_link = link.split('<')[1].split('>')[0]
                        break
                url = next_link
                params = {}  # Clear params for subsequent requests
                
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Pagination failed for {endpoint}: {e}")
                break
                
        return all_items

    def _parse_syllabus_for_date_map(self, html_body: str) -> Dict[datetime.date, str]:
        """Parses the syllabus to create a map from a date to its week name using a final, robust method."""
        date_to_week_map = {}
        if not html_body:
            self.logger.error("Syllabus body is empty")
            return date_to_week_map

        soup = BeautifulSoup(html_body, 'lxml')
        tables = soup.find_all('table')
        if not tables:
            self.logger.error("No tables found in syllabus")
            return date_to_week_map

        week_pattern = re.compile(r'^(?:week|module|wk)\.?\s*(\d+)', re.IGNORECASE)
        date_pattern = re.compile(r'(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})')
        
        self.logger.info("Starting syllabus parsing for date-to-week mapping...")

        for table in tables:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                
                # This logic ensures week and date are found in the same row, but processed separately to avoid crossover
                row_week_num = None
                row_date = None

                # First, find a week number in any cell of the row
                for cell in cells:
                    # Use a separator to handle cases where week and date are in the same cell but on different lines
                    cell_text = cell.get_text(strip=True, separator=' ')
                    week_match = week_pattern.search(cell_text)
                    if week_match:
                        row_week_num = week_match.group(1)
                        self.logger.debug(f"Found week {row_week_num} in a cell.")
                        break # Found the week, no need to check other cells for a week
                
                # If a week was found, now find a date in any cell of the same row
                if row_week_num:
                    for cell in cells:
                        cell_text = cell.get_text(strip=True, separator=' ')
                        date_match = date_pattern.search(cell_text)
                        if date_match:
                            try:
                                day, month, year = map(int, date_match.groups())
                                row_date = datetime(year, month, day).date()
                                self.logger.debug(f"Found date {row_date} in a cell.")
                                break # Found the date, no need to check other cells
                            except ValueError:
                                continue
                
                # If we found a week and a date in the same row, create the mapping
                if row_week_num and row_date:
                    week_name = f"Week {row_week_num}"
                    if row_date not in date_to_week_map:
                        date_to_week_map[row_date] = week_name
                        self.logger.info(f"SYLLABUS MAP: Mapped {row_date} to {week_name}")

        if not date_to_week_map:
            self.logger.error("No valid week-date mappings found in syllabus tables")
        else:
            self.logger.info(f"Successfully created date map with {len(date_to_week_map)} entries")
            
        return date_to_week_map

    def _find_week_for_date(self, target_date: datetime.date, date_map: Dict[datetime.date, str]) -> Optional[str]:
        """Finds which week a given date falls into."""
        if not date_map: 
            return None
            
        sorted_weeks = sorted(date_map.items())
        
        for i, (start_date, week_name) in enumerate(sorted_weeks):
            next_start_date = sorted_weeks[i+1][0] if i + 1 < len(sorted_weeks) else start_date + timedelta(days=7)
            if start_date <= target_date < next_start_date:
                # Ensure we're getting a clean week name
                week_match = re.search(r'Week\s+(\d+)$', week_name)
                if week_match:
                    return f"Week {week_match.group(1)}"
                return week_name
        
        # Check if it falls in the last week
        if sorted_weeks and target_date >= sorted_weeks[-1][0]:
            week_match = re.search(r'Week\s+(\d+)$', sorted_weeks[-1][1])
            if week_match:
                return f"Week {week_match.group(1)}"
            return sorted_weeks[-1][1]
            
        return None

    def _replace_dates_in_well(self, well_html: str, current_week_name: str, date_map: Dict[datetime.date, str]) -> Tuple[str, List[str]]:
        """Uses re.sub with a function to perform intelligent date replacement."""
        changes_made = []

        def replacer(match):
            original_text = match.group(1)
            date_string = match.group(2)
            self.logger.debug(f"Processing match: '{original_text}', with date string: '{date_string}'")

            # Extract numbers only from the date string, not the whole match
            date_numbers = re.findall(r'\d+', date_string)
            if len(date_numbers) != 3:
                self.logger.debug(f"Could not extract 3 numbers from date string: '{date_string}'")
                return original_text
            
            try:
                day, month, year = map(int, date_numbers)
                self.logger.debug(f"Extracted date components: day={day}, month={month}, year={year}")
                found_date = datetime(year, month, day).date()
            except ValueError as e:
                self.logger.debug(f"Date parsing error: {e}")
                return original_text

            due_week_name = self._find_week_for_date(found_date, date_map)
            if not due_week_name:
                self.logger.warning(f"DATE->WEEK FAILED: Could not find a week for date {found_date}. Date map has {len(date_map)} entries.")
                return original_text
            
            self.logger.info(f"DATE->WEEK SUCCESS: Found that {found_date} is in {due_week_name}")

            # Extract just the week number, ensuring we only get the number
            week_match = re.search(r'Week\s+(\d+)$', due_week_name)
            if not week_match:
                self.logger.debug(f"Could not extract week number from: {due_week_name}")
                return original_text

            week_num = week_match.group(1)
            self.logger.debug(f"Extracted week number: {week_num}")

            # Replace with "due in Week X" (no period)
            replacement_text = f"due in Week {week_num}"
            self.logger.debug(f"Replacing '{original_text.strip()}' with '{replacement_text}'")
            changes_made.append(f"Changed '{original_text.strip()}' to '{replacement_text}'")
            return replacement_text

        # Try both patterns
        new_html = self.due_date_pattern.sub(replacer, well_html)
        if new_html == well_html:  # If first pattern didn't match, try the second
            new_html = self.simple_due_date_pattern.sub(replacer, well_html)
        
        # Add periods where needed, being careful not to add to existing periods
        new_html = re.sub(r'(Week \d+)(?!\.)', r'\1.', new_html)
        
        # Clean up any potential double periods
        new_html = re.sub(r'\.+', '.', new_html)
        
        return (new_html, changes_made) if new_html != well_html else (well_html, [])

    def analyze_course(self, course_id: str) -> Dict:
        """Analyzes a single course for date replacement opportunities."""
        try:
            # Get course information with syllabus
            course_info = self._make_api_request(f'courses/{course_id}', params={'include[]': 'syllabus_body'})
            if not course_info:
                return self._create_analysis_result(course_id, "Unknown", "", error="Failed to retrieve course information")
            
            course_name = course_info.get('name', 'Unknown')
            sis_id = course_info.get('sis_course_id', '')
            self.logger.info(f"Analyzing course: {course_name} (ID: {course_id})")

            # Parse syllabus for date mapping
            date_map = self._parse_syllabus_for_date_map(course_info.get('syllabus_body', ''))
            if not date_map:
                return self._create_analysis_result(
                    course_id, course_name, sis_id, 
                    error="Could not parse syllabus for date map. No week-date mappings found."
                )

            # Get course modules
            modules = self._get_paginated_results(f'courses/{course_id}/modules')
            if not modules:
                return self._create_analysis_result(
                    course_id, course_name, sis_id,
                    error="No modules found in course"
                )

            summary_page_pattern = re.compile(r'\bsummary\b', re.I)
            week_pattern = re.compile(r'^(week|module)\s*(\d+)', re.IGNORECASE)

            findings = {
                'date_replacements': [],
                'pages_scanned': 0,
                'dates_found': 0,
                'syllabus_parsing_successful': True
            }

            for module in modules:
                module_match = week_pattern.search(module.get('name', ''))
                if not module_match:
                    continue
                
                current_week_name = f"{module_match.group(1).capitalize()} {module_match.group(2)}"
                self.logger.debug(f"Processing module: {current_week_name}")

                # Get module items
                module_items = self._get_paginated_results(f'courses/{course_id}/modules/{module["id"]}/items')
                for item in module_items:
                    if item.get('type') == 'Page' and summary_page_pattern.search(item.get('title', '')):
                        self.logger.debug(f"Processing page: {item.get('title')}")
                        page_url = item['page_url']
                        page = self._make_api_request(f'courses/{course_id}/pages/{page_url}')
                        
                        if not page or not page.get('body'):
                            self.logger.debug("Page content is empty")
                            continue
                        
                        findings['pages_scanned'] += 1
                        
                        original_body = page['body']
                        soup = BeautifulSoup(original_body, 'lxml')
                        reminder_well = soup.find('div', class_='reminder-well')

                        if not reminder_well:
                            self.logger.debug("No reminder well found")
                            continue
                        
                        original_well_html = str(reminder_well)
                        new_well_html, changes = self._replace_dates_in_well(original_well_html, current_week_name, date_map)

                        if changes:
                            findings['dates_found'] += len(changes)
                            
                            # Create replacement finding
                            replacement_finding = {
                                'type': 'date_replacement',
                                'page_title': item['title'],
                                'module_name': module.get('name', ''),
                                'page_url': page_url,
                                'description': f"Replace {len(changes)} date reference(s) with week-based deadlines",
                                'reason': f"Found {len(changes)} hard-coded date(s) in reminder well that can be replaced with week references",
                                'severity': 'medium',
                                'recommendation': f"Replace date references with 'due in Week X' format for consistency",
                                'current_value': original_well_html,
                                'suggested_value': new_well_html,
                                'changes': changes,
                                'module_id': module['id'],
                                'item_id': item['id']
                            }
                            findings['date_replacements'].append(replacement_finding)

            return self._create_analysis_result(course_id, course_name, sis_id, findings)

        except Exception as e:
            self.logger.error(f"Error analyzing course {course_id}: {e}", exc_info=True)
            return self._create_analysis_result(course_id, "Unknown", "", error=str(e))

    def execute_approved_actions(self, actions: List[Dict]) -> Dict:
        """Executes approved date replacement actions."""
        results = {
            'successful': 0,
            'failed': 0,
            'errors': []
        }

        for action in actions:
            if action.get('type') != 'date_replacement':
                continue
                
            try:
                course_id = action.get('course_id')
                page_url = action.get('page_url')
                new_content = action.get('suggested_value')
                
                if not all([course_id, page_url, new_content]):
                    results['errors'].append(f"Missing required fields for action: {action}")
                    results['failed'] += 1
                    continue

                # Update the page content
                payload = {'wiki_page': {'body': new_content}}
                response = self._make_api_request(f'courses/{course_id}/pages/{page_url}', payload=payload)
                
                if response:
                    results['successful'] += 1
                    self.logger.info(f"Successfully updated page: {action.get('page_title', 'Unknown')}")
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to update page: {action.get('page_title', 'Unknown')}")
                    
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"Error executing action: {str(e)}")
                self.logger.error(f"Error executing action: {e}")

        return results

    def _create_analysis_result(self, course_id: str, course_name: str, sis_id: str, 
                               findings: Dict = None, error: str = None) -> Dict:
        """Creates the standardized analysis result for LTI consumption."""
        if error:
            return {
                "success": False,
                "error": error,
                "phase": 2,
                "mode": "analysis_only"
            }

        # Categorize findings for manual review (no safe actions for content modification)
        manual_review_items = []
        
        for replacement in findings.get('date_replacements', []):
            manual_review_items.append({
                'type': 'date_replacement',
                'page_title': replacement['page_title'],
                'description': replacement['description'],
                'reason': replacement['reason'],
                'severity': replacement['severity'],
                'recommendation': replacement['recommendation'],
                'current_value': replacement['current_value'],
                'suggested_value': replacement['suggested_value'],
                'changes': replacement['changes'],
                'module_id': replacement['module_id'],
                'item_id': replacement['item_id'],
                'course_id': course_id
            })

        return {
            "success": True,
            "phase": 2,
            "mode": "preview_first",
            "analysis_complete": True,
            "course_info": {
                "course_id": course_id,
                "course_name": course_name,
                "sis_id": sis_id
            },
            "summary": {
                "pages_scanned": findings.get('pages_scanned', 0),
                "dates_found": findings.get('dates_found', 0),
                "replacements_proposed": len(manual_review_items),
                "syllabus_parsing_successful": findings.get('syllabus_parsing_successful', False)
            },
            "findings": {
                "safe_actions": [],  # No safe actions for content modification
                "requires_manual_review": manual_review_items
            },
            "detailed_findings": findings,
            "risk_assessment": {
                "content_modification_required": len(manual_review_items) > 0,
                "syllabus_parsing_successful": findings.get('syllabus_parsing_successful', False),
                "date_mapping_confidence": "high" if findings.get('dates_found', 0) > 0 else "low"
            }
        }


def main():
    """Main function for command-line execution."""
    parser = argparse.ArgumentParser(
        description="Canvas Assessment Date Updater - LTI Enhanced Version"
    )
    
    # Required arguments for LTI integration
    parser.add_argument('--canvas-url', required=True, 
                       help="Canvas instance URL (e.g., canvas.instructure.com)")
    parser.add_argument('--api-token', required=True, 
                       help="Canvas API token")
    parser.add_argument('--course-id', required=True, 
                       help="Course ID to analyze")
    
    # LTI-specific arguments
    parser.add_argument('--analyze-only', action='store_true', 
                       help="Perform analysis only (no execution) - default mode")
    parser.add_argument('--execute-from-json', type=str,
                       help="Execute approved actions from JSON file")
    
    args = parser.parse_args()
    
    try:
        # Initialize updater
        updater = AssessmentDateUpdater(args.canvas_url, args.api_token)
        
        if args.analyze_only or not args.execute_from_json:
            # Perform analysis
            print(f"Analyzing course {args.course_id} for date replacement opportunities...", file=sys.stderr)
            analysis_result = updater.analyze_course(args.course_id)
            
            # Output results in JSON format for LTI consumption
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis_result, indent=2))
            
        elif args.execute_from_json:
            # Execute approved actions
            import os
            if not os.path.exists(args.execute_from_json):
                raise FileNotFoundError(f"Approved actions file not found: {args.execute_from_json}")
            
            with open(args.execute_from_json, 'r') as f:
                approved_actions = json.load(f)
            
            print(f"Executing {len(approved_actions)} approved actions...", file=sys.stderr)
            execution_result = updater.execute_approved_actions(approved_actions)
            
            # Output execution results
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_result, indent=2))
        
    except Exception as e:
        # Output structured error for LTI consumption
        error_output = {
            "success": False,
            "error": str(e),
            "phase": 2,
            "mode": "analysis_only"
        }
        print(f"CRITICAL_ERROR_JSON: {json.dumps(error_output)}", file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    main()
