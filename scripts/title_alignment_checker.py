"""
Canvas Course Title Alignment Checker - LTI Enhanced Version

This script analyzes Canvas courses for consistency between syllabus schedule
and module titles, enforcing stylistic rules and validating welcome messages.

LTI Integration Features:
- Analysis-only mode (no automated fixes)
- Enhanced JSON output for UI consumption
- Risk assessment for findings categorization
- Human-centered approach with clear explanations

What This Script Does:
1. Parses syllabus schedule tables to extract week/module titles
2. Compares module titles with syllabus entries for consistency
3. Validates style compliance (sentence case, colon rules)
4. Checks welcome message alignment in introduction pages
5. Categorizes findings for manual review (no auto-execution)

Prerequisites:
  pip install requests beautifulsoup4 lxml difflib

Author: AI Assistant (LTI Integration Version)
Version: 1.0 - LTI Enhanced
"""

import requests
import json
import re
import sys
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
import argparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Script Configuration
LOGGING_LEVEL = logging.INFO
MAX_API_WORKERS = 5
REQUEST_TIMEOUT = 30

class TitleAlignmentChecker:
    """Analyzes Canvas courses for title consistency and style compliance."""

    def __init__(self, base_url: str, api_token: str):
        """Initialize the checker with Canvas API credentials."""
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
        
        # Regex patterns for analysis - more specific to avoid date confusion
        self.module_key_pattern = re.compile(r'^(week|module)\s*(\d{1,2})(?:\s|$|:)', re.IGNORECASE)
        self.welcome_pattern = re.compile(r'Welcome\s+to\s+([^\.!?]+)[\.!?]?', re.IGNORECASE)

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
        
        if params is None:
            params = {}
        params['per_page'] = 100
        
        while url:
            try:
                response = self.session.get(
                    url, 
                    headers=self.headers, 
                    params=params if url == f"{self.base_url}/api/v1/{endpoint.lstrip('/')}" else None,
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                all_items.extend(data)
                
                # Get next page URL from Link header
                links = response.headers.get('Link', '')
                url = None
                for link in links.split(','):
                    if 'rel="next"' in link:
                        url = link.split('<')[1].split('>')[0]
                        break
                        
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Paginated request failed: {e}")
                break
                
        return all_items

    def _parse_syllabus_schedule(self, html_body: str) -> Dict[str, str]:
        """Parse the syllabus HTML to extract week/module titles."""
        schedule = {}
        if not html_body:
            self.logger.warning("No syllabus content found")
            return schedule
            
        soup = BeautifulSoup(html_body, 'lxml')
        tables = soup.find_all('table')
        
        self.logger.info(f"Found {len(tables)} tables in syllabus")
        
        for table_idx, table in enumerate(tables):
            headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
            
            # Skip tables without relevant headers
            if not any(keyword in ' '.join(headers) for keyword in ['week', 'module', 'topic', 'title']):
                self.logger.debug(f"Table {table_idx + 1} skipped - no relevant headers: {headers}")
                continue
                
            self.logger.info(f"Processing table {table_idx + 1} with headers: {headers}")
            
            # Find the week/module column and title column
            week_col_idx = None
            title_col_idx = None
            
            for idx, header in enumerate(headers):
                if 'week' in header or 'module' in header:
                    week_col_idx = idx
                    self.logger.debug(f"Found week/module column at index {idx}: '{header}'")
                if any(keyword in header for keyword in ['topic', 'title', 'content']):
                    title_col_idx = idx
                    self.logger.debug(f"Found title column at index {idx}: '{header}'")
            
            # If we have both columns, process the table
            if week_col_idx is not None and title_col_idx is not None:
                self.logger.info(f"Table has both week column ({week_col_idx}) and title column ({title_col_idx})")
                
                # Process each row
                rows = table.find_all('tr')[1:]  # Skip header row
                for row_idx, row in enumerate(rows):
                    cells = row.find_all('td')
                    if len(cells) <= max(week_col_idx, title_col_idx):
                        continue
                        
                    week_cell = cells[week_col_idx]
                    title_cell = cells[title_col_idx]
                    
                    # Extract week text - handle multiline cells by taking first line that matches Week/Module pattern
                    week_text = week_cell.get_text(strip=True)
                    week_lines = [line.strip() for line in week_text.split('\n') if line.strip()]
                    
                    self.logger.debug(f"Row {row_idx}: Raw week text: '{week_text}'")
                    self.logger.debug(f"Row {row_idx}: Week lines: {week_lines}")
                    
                    # Find the line that contains Week/Module pattern
                    actual_week_text = None
                    for line in week_lines:
                        self.logger.debug(f"Row {row_idx}: Testing line '{line}' against pattern")
                        
                        # Handle format like "Week 103 / 02 / 2025" (with space)
                        # Extract only the first digit after Week/Module (the actual week number)
                        week_match = re.search(r'(week|module)\s+(\d)', line, re.IGNORECASE)
                        if week_match:
                            week_type = week_match.group(1)
                            week_num = week_match.group(2)
                            
                            # Now week_num should be clean (1-2 digits only)
                            actual_week_text = f"{week_type.capitalize()} {week_num}"
                            self.logger.debug(f"Row {row_idx}: Extracted week text: '{actual_week_text}' from '{line}'")
                            break
                    
                    # If no Week/Module pattern found in individual lines, use the first line
                    if not actual_week_text and week_lines:
                        actual_week_text = week_lines[0]
                        self.logger.debug(f"Row {row_idx}: No pattern match, using first line: '{actual_week_text}'")
                    elif not actual_week_text:
                        actual_week_text = week_text
                        self.logger.debug(f"Row {row_idx}: No lines found, using raw text: '{actual_week_text}'")
                    
                    title_text = title_cell.get_text(strip=True).replace('\n', ' ').strip()
                    
                    if not actual_week_text or not title_text:
                        continue
                    
                    # Check if actual_week_text matches Week/Module pattern
                    match = self.module_key_pattern.search(actual_week_text)
                    if match:
                        key = f"{match.group(1).capitalize()} {match.group(2)}"
                        # Store only the title part (not the concatenated "Week X: Title")
                        # This allows proper comparison with module topic parts
                        schedule[key] = title_text
                        self.logger.info(f"Found schedule entry: {key} -> {title_text} (from combined: {actual_week_text}: {title_text})")
                        
            # Also check for single-column format (original logic as fallback)
            elif title_col_idx is not None:
                self.logger.info(f"Table has only title column ({title_col_idx}), checking for combined format")
                
                # Process each row looking for combined Week/Module + Title format
                rows = table.find_all('tr')[1:]  # Skip header row
                for row_idx, row in enumerate(rows):
                    cells = row.find_all('td')
                    if len(cells) <= title_col_idx:
                        continue
                        
                    title_cell = cells[title_col_idx]
                    full_title = title_cell.get_text(strip=True).replace('\n', ' ').strip()
                    
                    if not full_title:
                        continue
                    
                    # Look for Week/Module pattern in the combined title
                    match = self.module_key_pattern.search(full_title)
                    if match:
                        key = f"{match.group(1).capitalize()} {match.group(2)}"
                        schedule[key] = full_title
                        self.logger.info(f"Found schedule entry (combined format): {key} -> {full_title}")
            else:
                self.logger.debug(f"Table {table_idx + 1} - no usable columns found")
                    
        self.logger.info(f"Extracted {len(schedule)} entries from syllabus schedule")
        return schedule

    def _extract_welcome_title(self, content: str) -> Optional[str]:
        """Extract the title from the welcome message in introduction pages."""
        if not content:
            return None
            
        soup = BeautifulSoup(content, 'lxml')
        text = soup.get_text(separator=' ', strip=True)
        
        # Look for welcome message in the first few paragraphs
        paragraphs = text.split('\n')[:3]
        for paragraph in paragraphs:
            match = self.welcome_pattern.search(paragraph)
            if match:
                return match.group(1).strip()
        return None

    def _is_sentence_case(self, text: str) -> bool:
        """Check if text follows sentence case rules."""
        if not text or not text[0].isalpha():
            return True
        if not text[0].isupper():
            return False
        if text.upper() == text and len(text) > 3:
            return False
        
        words = text.split()
        if len(words) > 2:
            capitalized_words = sum(1 for word in words if word and word[0].isupper())
            if capitalized_words / len(words) > 0.5:
                return False
        return True

    def _check_colon_rule(self, title: str) -> bool:
        """Check if title follows the single colon rule."""
        return title.count(':') <= 1

    def _get_title_parts(self, full_title: str) -> Tuple[str, str]:
        """Split title into week/module part and topic part."""
        parts = full_title.split(':', 1)
        return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (full_title, "")

    def _compare_titles(self, title1: str, title2: str) -> Tuple[bool, str, float]:
        """Compare two titles and return match status, explanation, and similarity."""
        if title1 == title2:
            return True, "Exact match", 1.0
        
        # Clean and normalize titles
        title1_clean = ' '.join(title1.split())
        title2_clean = ' '.join(title2.split())
        
        if title1_clean == title2_clean:
            return True, "Match (after whitespace normalization)", 1.0
            
        # Calculate similarity
        matcher = SequenceMatcher(None, title1_clean.lower(), title2_clean.lower())
        similarity = matcher.ratio()
        
        if similarity >= 0.9:
            return True, f"Very similar match ({similarity:.1%})", similarity
        elif similarity >= 0.7:
            return False, f"Similar but different ({similarity:.1%})", similarity
        else:
            return False, f"Different titles ({similarity:.1%})", similarity

    def analyze_course(self, course_id: str) -> Dict:
        """Analyze a single course for title alignment and style compliance."""
        self.logger.info(f"Starting analysis for course {course_id}")
        
        try:
            # Get course information including syllabus
            course_info = self._make_api_request(
                f'courses/{course_id}', 
                params={'include[]': ['syllabus_body', 'sis_course_id']}
            )
            
            if not course_info:
                raise Exception("Could not retrieve course information")

            course_name = course_info.get('name', 'Unknown Course')
            sis_id = course_info.get('sis_course_id', 'N/A')
            
            self.logger.info(f"Analyzing: {course_name} (SIS: {sis_id})")

            # Parse syllabus schedule
            syllabus_schedule = self._parse_syllabus_schedule(
                course_info.get('syllabus_body', '')
            )
            
            # Get course modules
            modules = self._get_paginated_results(f'courses/{course_id}/modules')
            
            if not modules:
                return self._create_analysis_result(
                    course_id, course_name, sis_id,
                    error="No modules found in course"
                )

            # Analyze each module
            findings = {
                'total_modules_analyzed': 0,
                'title_matches': [],
                'title_mismatches': [],
                'style_violations': [],
                'welcome_message_issues': [],
                'missing_syllabus_entries': []
            }

            for module in modules:
                module_title_full = module.get('name', '').strip()
                match = self.module_key_pattern.search(module_title_full)
                
                if not match:
                    continue  # Skip non-week/module items
                
                findings['total_modules_analyzed'] += 1
                module_key = f"{match.group(1).capitalize()} {match.group(2)}"
                
                # Check title alignment with syllabus
                self._check_title_alignment(
                    course_id, module, module_key, module_title_full, 
                    syllabus_schedule, findings
                )
                
                # Check style compliance
                self._check_style_compliance(
                    module_key, module_title_full, findings
                )

            # Create comprehensive analysis result
            return self._create_analysis_result(
                course_id, course_name, sis_id, findings=findings
            )
            
        except Exception as e:
            self.logger.error(f"Analysis failed for course {course_id}: {e}")
            return self._create_analysis_result(
                course_id, "Unknown", "N/A", error=str(e)
            )

    def _check_title_alignment(self, course_id: str, module: Dict, module_key: str, 
                             module_title_full: str, syllabus_schedule: Dict, 
                             findings: Dict):
        """Check if module title aligns with syllabus schedule."""
        syllabus_title_full = syllabus_schedule.get(module_key)
        
        if not syllabus_title_full:
            findings['missing_syllabus_entries'].append({
                'module_key': module_key,
                'module_title': module_title_full,
                'issue': f"No corresponding entry found in syllabus schedule",
                'severity': 'medium',
                'recommendation': f"Add '{module_title_full}' to syllabus schedule table"
            })
            return

        # Smart comparison logic: Check multiple scenarios for better accuracy
        
        # First check: Try exact comparison between syllabus and full module title
        matches_exact, explanation_exact, similarity_exact = self._compare_titles(
            syllabus_title_full, module_title_full
        )
        
        if matches_exact:
            # Perfect match - syllabus and module titles are identical
            matches, explanation, similarity = matches_exact, explanation_exact, similarity_exact
            comparison_title = module_title_full
        else:
            # Second check: Compare syllabus with module topic part (ignoring Week/Module prefix)
            _, module_topic_part = self._get_title_parts(module_title_full)
            comparison_title = module_topic_part if module_topic_part else module_title_full
            
            matches_topic, explanation_topic, similarity_topic = self._compare_titles(
                syllabus_title_full, comparison_title
            )
            
            if matches_topic:
                # Good match - difference is just the Week/Module prefix
                matches, explanation, similarity = matches_topic, f"Match (ignoring Week/Module prefix): {explanation_topic}", similarity_topic
            else:
                # Real mismatch - flag as issue
                matches, explanation, similarity = matches_topic, explanation_topic, similarity_topic
        
        if matches:
            findings['title_matches'].append({
                'module_key': module_key,
                'module_title': module_title_full,
                'syllabus_title': syllabus_title_full,
                'match_explanation': explanation,
                'similarity_score': similarity
            })
        else:
            # Split module title to show what we're actually comparing
            module_prefix, module_topic = self._get_title_parts(module_title_full)
            # Since syllabus_title_full is now just the title part, construct the expected full title
            expected_full_title = f"{module_prefix}: {syllabus_title_full}" if module_prefix else syllabus_title_full
            
            findings['title_mismatches'].append({
                'module_key': module_key,
                'module_title': module_title_full,
                'syllabus_title': syllabus_title_full,
                'module_topic_part': comparison_title,
                'difference_explanation': explanation,
                'similarity_score': similarity,
                'severity': 'high' if similarity < 0.5 else 'medium',
                'recommendation': f"Update module title to: '{expected_full_title}'"
            })

        # Check welcome message in introduction page
        self._check_welcome_message(
            course_id, module, module_key, syllabus_title_full, findings
        )

    def _check_welcome_message(self, course_id: str, module: Dict, module_key: str, 
                              expected_title: str, findings: Dict):
        """Check welcome message consistency in introduction pages."""
        try:
            # Get module items
            module_items = self._get_paginated_results(
                f"courses/{course_id}/modules/{module['id']}/items"
            )
            
            # Find introduction page
            intro_page = None
            for item in module_items:
                if (item.get('type') == 'Page' and 
                    'introduction' in item.get('title', '').lower()):
                    intro_page = item
                    break
            
            if not intro_page:
                findings['welcome_message_issues'].append({
                    'module_key': module_key,
                    'issue': 'No introduction page found in module',
                    'severity': 'low',
                    'recommendation': 'Consider adding an introduction page'
                })
                return
            
            # Get page content
            page_url = intro_page.get('page_url')
            if page_url:
                page_data = self._make_api_request(f"courses/{course_id}/pages/{page_url}")
                if page_data:
                    page_content = page_data.get('body', '')
                    welcome_title = self._extract_welcome_title(page_content)
                    
                    if welcome_title:
                        matches, explanation, similarity = self._compare_titles(
                            expected_title, welcome_title
                        )
                        
                        if not matches:
                            findings['welcome_message_issues'].append({
                                'module_key': module_key,
                                'expected_title': expected_title,
                                'found_title': welcome_title,
                                'difference_explanation': explanation,
                                'similarity_score': similarity,
                                'severity': 'medium',
                                'recommendation': f"Update welcome message to: 'Welcome to {expected_title}'"
                            })
                    else:
                        findings['welcome_message_issues'].append({
                            'module_key': module_key,
                            'issue': 'Welcome message not found or does not follow expected format',
                            'severity': 'low',
                            'recommendation': f"Add welcome message: 'Welcome to {expected_title}'"
                        })
                        
        except Exception as e:
            self.logger.error(f"Error checking welcome message for {module_key}: {e}")

    def _check_style_compliance(self, module_key: str, module_title_full: str, findings: Dict):
        """Check style compliance for module titles."""
        _, topic_part = self._get_title_parts(module_title_full)
        
        if not topic_part:
            return  # No topic part to check
        
        style_issues = []
        
        # Check sentence case
        if not self._is_sentence_case(topic_part):
            style_issues.append({
                'rule': 'sentence_case',
                'issue': f"Topic '{topic_part}' is not in sentence case",
                'recommendation': 'Use sentence case (first word capitalized, rest lowercase except proper nouns)'
            })
        
        # Check colon rule
        if not self._check_colon_rule(topic_part):
            style_issues.append({
                'rule': 'colon_rule',
                'issue': f"Topic '{topic_part}' contains more than one colon",
                'recommendation': 'Use maximum one colon in topic titles'
            })
        
        if style_issues:
            findings['style_violations'].append({
                'module_key': module_key,
                'module_title': module_title_full,
                'topic_part': topic_part,
                'violations': style_issues,
                'severity': 'low'
            })

    def _create_analysis_result(self, course_id: str, course_name: str, sis_id: str, 
                               findings: Dict = None, error: str = None) -> Dict:
        """Create standardized analysis result for LTI consumption."""
        
        if error:
            return {
                "success": False,
                "error": error,
                "phase": 2,
                "mode": "analysis_only",
                "course_info": {
                    "course_id": course_id,
                    "course_name": course_name,
                    "sis_id": sis_id
                }
            }
        
        if not findings:
            findings = {
                'total_modules_analyzed': 0,
                'title_matches': [],
                'title_mismatches': [],
                'style_violations': [],
                'welcome_message_issues': [],
                'missing_syllabus_entries': []
            }
        
        # Calculate summary metrics
        total_issues = (
            len(findings['title_mismatches']) +
            len(findings['style_violations']) +
            len(findings['welcome_message_issues']) +
            len(findings['missing_syllabus_entries'])
        )
        
        total_matches = len(findings['title_matches'])
        total_analyzed = findings['total_modules_analyzed']
        
        # Categorize all findings as requiring manual review (analysis-only task)
        manual_review_items = []
        
        # Add title mismatches
        for mismatch in findings['title_mismatches']:
            # Get the topic part for clearer explanation
            topic_part = mismatch.get('module_topic_part', 'N/A')
            manual_review_items.append({
                'type': 'title_mismatch',
                'module_key': mismatch['module_key'],
                'title': f"Title Mismatch: {mismatch['module_key']}",
                'description': f"Module topic '{topic_part}' doesn't match syllabus '{mismatch['syllabus_title']}'",
                'reason': f"Manual review required. {mismatch['difference_explanation']}",
                'severity': mismatch['severity'],
                'recommendation': mismatch['recommendation'],
                'current_value': mismatch['module_title'],
                'suggested_value': mismatch['recommendation'].split("': '")[1].rstrip("'") if "': '" in mismatch['recommendation'] else mismatch['syllabus_title']
            })
        
        # Add style violations
        for violation in findings['style_violations']:
            for issue in violation['violations']:
                manual_review_items.append({
                    'type': 'style_violation',
                    'module_key': violation['module_key'],
                    'title': f"Style Issue: {violation['module_key']} - {issue['rule'].replace('_', ' ').title()}",
                    'description': issue['issue'],
                    'reason': f"Manual review required. {issue['recommendation']}",
                    'severity': 'low',
                    'recommendation': issue['recommendation'],
                    'current_value': violation['topic_part']
                })
        
        # Add welcome message issues
        for welcome_issue in findings['welcome_message_issues']:
            manual_review_items.append({
                'type': 'welcome_message_issue',
                'module_key': welcome_issue['module_key'],
                'title': f"Welcome Message: {welcome_issue['module_key']}",
                'description': welcome_issue.get('issue', 'Welcome message inconsistency'),
                'reason': f"Manual review required. {welcome_issue['recommendation']}",
                'severity': welcome_issue['severity'],
                'recommendation': welcome_issue['recommendation'],
                'current_value': welcome_issue.get('found_title', 'Not found'),
                'suggested_value': welcome_issue.get('expected_title', 'N/A')
            })
        
        # Add missing syllabus entries
        for missing in findings['missing_syllabus_entries']:
            manual_review_items.append({
                'type': 'missing_syllabus_entry',
                'module_key': missing['module_key'],
                'title': f"Missing Syllabus Entry: {missing['module_key']}",
                'description': missing['issue'],
                'reason': f"Manual review required. {missing['recommendation']}",
                'severity': missing['severity'],
                'recommendation': missing['recommendation'],
                'current_value': 'Not in syllabus',
                'suggested_value': missing['module_title']
            })

        return {
            "success": True,
            "phase": 2,
            "mode": "analysis_only",
            "analysis_complete": True,
            "course_info": {
                "course_id": course_id,
                "course_name": course_name,
                "sis_id": sis_id
            },
            "summary": {
                "modules_analyzed": total_analyzed,
                "total_matches": total_matches,
                "total_issues": total_issues,
                "title_mismatches": len(findings['title_mismatches']),
                "style_violations": len(findings['style_violations']),
                "welcome_message_issues": len(findings['welcome_message_issues']),
                "missing_syllabus_entries": len(findings['missing_syllabus_entries']),
                "consistency_rate": f"{(total_matches / max(total_analyzed, 1)) * 100:.1f}%" if total_analyzed > 0 else "0%"
            },
            "findings": {
                "safe_actions": [],  # No safe actions for this analysis-only task
                "requires_manual_review": manual_review_items
            },
            "detailed_findings": findings,
            "risk_assessment": {
                "high_priority_issues": len([item for item in manual_review_items if item['severity'] == 'high']),
                "medium_priority_issues": len([item for item in manual_review_items if item['severity'] == 'medium']),
                "low_priority_issues": len([item for item in manual_review_items if item['severity'] == 'low']),
                "syllabus_parsing_successful": len(findings.get('title_matches', [])) > 0 or len(findings.get('title_mismatches', [])) > 0
            }
        }


def main():
    """Main function for command-line execution."""
    parser = argparse.ArgumentParser(
        description="Canvas Course Title Alignment Checker - LTI Enhanced Version"
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
    
    args = parser.parse_args()
    
    try:
        # Initialize checker
        checker = TitleAlignmentChecker(args.canvas_url, args.api_token)
        
        # Perform analysis
        print(f"Analyzing course {args.course_id} for title alignment...", file=sys.stderr)
        analysis_result = checker.analyze_course(args.course_id)
        
        # Output results in JSON format for LTI consumption
        print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis_result, indent=2))
        
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