"""
Canvas Table Caption Compliance Audit Tool - LTI Enhanced Version
===============================================================

A comprehensive tool that audits Canvas courses for table caption compliance with ACU Online Design Library standards.

LTI Integration Features:
- Analysis-only mode with detailed findings categorization
- Enhanced JSON output for UI consumption
- Risk assessment for findings categorization
- Human-centered approach with clear explanations
- Phase 2 workflow support (analyze → approve → execute)

Steps performed:
1. Access ACU Online Design Library (Course 26333) to extract table caption standards
2. Analyze target course for tables with class "acuo-table"
3. Check caption presence and styling compliance
4. Generate detailed JSON report with recommendations

Requirements:
pip install requests beautifulsoup4 openpyxl pandas

Author: AI Assistant (LTI Integration Version)
Version: 1.0 - LTI Enhanced
"""

import requests
import json
import re
import time
import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from bs4 import BeautifulSoup, Tag
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from common.progress import ProgressReporter

# Script Configuration
LOGGING_LEVEL = logging.INFO
REQUEST_TIMEOUT = 30
MAX_API_WORKERS = 10  # Increased for parallel processing
MAX_CONCURRENT_REQUESTS = 8  # Limit concurrent API calls
MAX_CONTENT_WORKERS = 6  # Workers for HTML content analysis

class CanvasAPIConnector:
    """Canvas API connector with error handling and rate limiting"""
    
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = f'https://{self.base_url}'
            
        self.api_token = api_token
        self.headers = {'Authorization': f'Bearer {api_token}'}
        self.logger = self._setup_logging()
        
        # Thread-local storage for sessions
        self._local = threading.local()
        
    def _get_session(self):
        """Get thread-local session with retry configuration"""
        if not hasattr(self._local, 'session'):
            session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._local.session = session
        return self._local.session
        
    def _setup_logging(self):
        """Configure logging for the script."""
        logging.basicConfig(
            level=LOGGING_LEVEL,
            format='%(levelname)s: %(message)s',
            stream=sys.stderr  # Log to stderr to keep stdout clean for JSON
        )
        return logging.getLogger(__name__)
        
    def validate_connection(self) -> bool:
        """Test Canvas API connection"""
        try:
            session = self._get_session()
            response = session.get(f"{self.base_url}/api/v1/users/self", 
                                 headers=self.headers, timeout=REQUEST_TIMEOUT)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Canvas connection failed: {e}")
            return False
    
    def _make_api_request(self, endpoint: str, params: Dict = None) -> Optional[Any]:
        """Make a single API request with error handling."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        try:
            session = self._get_session()
            response = session.get(
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
    
    def get_course_pages(self, course_id: str) -> List[Dict]:
        """Get all pages from a course with content"""
        try:
            pages = []
            url = f"{self.base_url}/api/v1/courses/{course_id}/pages"
            
            self.logger.info(f"Fetching pages from course {course_id}...")
            
            while url:
                response = self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
                if response.status_code != 200:
                    self.logger.warning(f"Failed to get pages: HTTP {response.status_code}")
                    break
                
                page_list = response.json()
                
                # Get full content for each page
                for i, page in enumerate(page_list):
                    self.logger.debug(f"Processing page {i+1}/{len(page_list)}: {page.get('title', 'Untitled')}")
                    page_response = self.session.get(f"{self.base_url}/api/v1/courses/{course_id}/pages/{page['url']}", 
                                                   headers=self.headers, timeout=REQUEST_TIMEOUT)
                    if page_response.status_code == 200:
                        full_page = page_response.json()
                        full_page['course_id'] = course_id
                        pages.append(full_page)
                    time.sleep(0.5)  # Rate limiting
                
                # Handle pagination
                links = response.headers.get('Link', '')
                next_link = None
                for link in links.split(','):
                    if 'rel="next"' in link:
                        next_link = link.split('<')[1].split('>')[0]
                        break
                url = next_link
            
            self.logger.info(f"Retrieved {len(pages)} pages")
            return pages
            
        except Exception as e:
            self.logger.error(f"Error getting course pages: {e}")
            return []
    
    def get_course_pages_parallel(self, course_id: str) -> List[Dict]:
        """Get all pages from a course using parallel processing."""
        try:
            pages = []
            url = f"{self.base_url}/api/v1/courses/{course_id}/pages"
            
            self.logger.info(f"Fetching pages from course {course_id}...")
            
            # First get the page list
            while url:
                session = self._get_session()
                response = session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
                if response.status_code != 200:
                    self.logger.warning(f"Failed to get pages: HTTP {response.status_code}")
                    break
                
                page_list = response.json()
                
                # Fetch page content in parallel
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
                    # Submit all page content requests
                    future_to_page = {
                        executor.submit(self._fetch_page_content, course_id, page['url']): page 
                        for page in page_list
                    }
                    
                    # Collect results as they complete
                    for future in as_completed(future_to_page):
                        page = future_to_page[future]
                        try:
                            page_content = future.result()
                            if page_content:
                                page.update(page_content)
                                page['course_id'] = course_id
                                pages.append(page)
                        except Exception as e:
                            self.logger.warning(f"Failed to fetch content for page {page.get('title', 'Unknown')}: {e}")
                            page['course_id'] = course_id
                            pages.append(page)
                
                # Handle pagination
                links = response.headers.get('Link', '')
                next_link = None
                for link in links.split(','):
                    if 'rel="next"' in link:
                        next_link = link.split('<')[1].split('>')[0]
                        break
                url = next_link
            
            self.logger.info(f"Successfully fetched content for {len(pages)} pages using parallel processing")
            return pages
            
        except Exception as e:
            self.logger.error(f"Error fetching pages for course {course_id}: {e}")
            return []
    
    def _fetch_page_content(self, course_id: str, page_url: str) -> Optional[Dict]:
        """Fetch content for a single page."""
        try:
            session = self._get_session()
            response = session.get(
                f"{self.base_url}/api/v1/courses/{course_id}/pages/{page_url}",
                headers=self.headers,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.warning(f"Failed to fetch page content for {page_url}: {e}")
            return None

class TableCaptionAnalyzer:
    """Analyzes table captions for compliance with ACU design standards"""
    
    def __init__(self):
        self.design_standards = {}
        self.logger = logging.getLogger(__name__)
        
    def extract_design_standards(self, design_library_pages: List[Dict]) -> Dict[str, Any]:
        """Extract table caption design standards from ACU Online Design Library"""
        self.logger.info("Analyzing ACU Online Design Library for table caption standards...")
        
        standards = {
            'table_captions': [],
            'common_classes': set(),
            'common_patterns': [],
            'style_rules': {},
            'citation_patterns': []
        }
        
        for page in design_library_pages:
            if not page.get('body'):
                continue
                
            soup = BeautifulSoup(page['body'], 'html.parser')
            
            # Find all tables with captions
            tables = soup.find_all('table')
            
            for table in tables:
                caption = table.find('caption')
                
                if caption:
                    caption_data = {
                        'text': caption.get_text(strip=True),
                        'html': str(caption),
                        'classes': caption.get('class', []),
                        'style': caption.get('style', ''),
                        'page_title': page.get('title', 'Unknown'),
                        'table_classes': table.get('class', [])
                    }
                    
                    standards['table_captions'].append(caption_data)
                    
                    # Collect common classes
                    for class_name in caption.get('class', []):
                        standards['common_classes'].add(class_name)
                    
                    # Analyze citation patterns (e.g., "(ACU Online, 2024)")
                    citation_match = re.search(r'\([^)]*\d{4}\)', caption_data['text'])
                    if citation_match:
                        standards['citation_patterns'].append(citation_match.group())
                    
                    # Analyze style patterns
                    if caption.get('style'):
                        self._analyze_style_patterns(caption.get('style'), standards)
        
        # Convert set to list for JSON serialization
        standards['common_classes'] = list(standards['common_classes'])
        
        self.logger.info(f"Found {len(standards['table_captions'])} table caption examples")
        self.logger.info(f"Identified {len(standards['common_classes'])} common CSS classes")
        self.logger.info(f"Found {len(standards['citation_patterns'])} citation patterns")
        
        self.design_standards = standards
        return standards
    
    def _analyze_style_patterns(self, style_string: str, standards: Dict):
        """Analyze CSS style patterns from table captions"""
        style_rules = {}
        if style_string:
            # Parse CSS rules
            rules = style_string.split(';')
            for rule in rules:
                if ':' in rule:
                    prop, value = rule.split(':', 1)
                    style_rules[prop.strip()] = value.strip()
        
        # Store common style properties
        for prop, value in style_rules.items():
            if prop not in standards['style_rules']:
                standards['style_rules'][prop] = {}
            if value not in standards['style_rules'][prop]:
                standards['style_rules'][prop][value] = 0
            standards['style_rules'][prop][value] += 1
    
    def analyze_content_compliance(self, pages: List[Dict], course_name: str = "Target Course") -> List[Dict]:
        """Analyze content for table caption compliance using parallel processing"""
        compliance_results = []
        
        self.logger.info(f"Analyzing {course_name} for table caption compliance using parallel processing...")
        
        # Process pages in parallel
        with ThreadPoolExecutor(max_workers=MAX_CONTENT_WORKERS) as executor:
            # Submit all page analysis tasks
            future_to_page = {
                executor.submit(self._analyze_page_content, page): page 
                for page in pages if page.get('body')
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    page_results = future.result()
                    compliance_results.extend(page_results)
                except Exception as e:
                    self.logger.warning(f"Failed to analyze page {page.get('title', 'Unknown')}: {e}")
        
        self.logger.info(f"Analyzed {len(compliance_results)} ACUO tables using parallel processing")
        return compliance_results
    
    def _analyze_page_content(self, page: Dict) -> List[Dict]:
        """Analyze a single page for table compliance"""
        results = []
        
        soup = BeautifulSoup(page['body'], 'html.parser')
        course_id = page.get('course_id', 'unknown')
        page_url = f"https://canvas.acu.edu.au/courses/{course_id}/pages/{page.get('url', page.get('page_id', 'unknown'))}"
        
        # Find all tables with class "acuo-table"
        acuo_tables = soup.find_all('table', class_='acuo-table')
        
        for table in acuo_tables:
            result = self._analyze_table_element(table, page, page_url)
            if result:
                results.append(result)
        
        return results
    
    def _analyze_table_element(self, table: Tag, page: Dict, page_url: str) -> Optional[Dict]:
        """Analyze individual table element for caption compliance"""
        
        result = {
            'page_title': page.get('title', 'Unknown'),
            'page_url': page_url,
            'table_classes': table.get('class', []),
            'table_preview': self._get_table_preview(table),
            'has_caption': False,
            'caption_text': '',
            'caption_classes': [],
            'caption_style': '',
            'compliance_status': 'missing',  # missing, present_wrong_style, present_correct_style
            'compliance_details': [],
            'recommendations': []
        }
        
        caption = table.find('caption')
        
        if caption:
            result['has_caption'] = True
            result['caption_text'] = caption.get_text(strip=True)
            result['caption_classes'] = caption.get('class', [])
            result['caption_style'] = caption.get('style', '')
            result['caption_html'] = str(caption)
            
            # Check compliance with design standards
            compliance_check = self._check_caption_compliance(caption)
            result.update(compliance_check)
        else:
            result['compliance_details'].append('No caption found')
            result['recommendations'].append('Add <caption> element as the first child of the table.')
        
        return result
    
    def _get_table_preview(self, table: Tag) -> str:
        """Get a preview of the table for reporting"""
        # Get first row or header content
        first_row = table.find('tr')
        if first_row:
            cells = first_row.find_all(['th', 'td'])
            if cells:
                preview_text = ' | '.join([cell.get_text(strip=True)[:20] for cell in cells[:3]])
                return f"Table: {preview_text}..."
        
        table_str = str(table)
        if len(table_str) > 100:
            return table_str[:100] + '...'
        return table_str
    
    def _check_caption_compliance(self, caption: Tag) -> Dict:
        """Check if table caption complies with design standards"""
        compliance = {
            'compliance_status': 'present_wrong_style',
            'compliance_details': [],
            'recommendations': []
        }
        
        if not self.design_standards:
            compliance['compliance_details'].append('No design standards loaded')
            return compliance
        
        # Check for common ACU classes
        caption_classes = set(caption.get('class', []))
        standard_classes = set(self.design_standards.get('common_classes', []))
        
        if standard_classes:
            matching_classes = caption_classes.intersection(standard_classes)
            if matching_classes:
                compliance['compliance_status'] = 'present_correct_style'
                compliance['compliance_details'].append(f'Uses ACU standard classes: {", ".join(matching_classes)}')
            else:
                compliance['compliance_details'].append('Missing ACU standard classes')
                compliance['recommendations'].append(f'Consider adding classes: {", ".join(list(standard_classes)[:3])}')
        
        # Check text quality
        caption_text = caption.get_text(strip=True)
        if len(caption_text) < 5:
            compliance['compliance_details'].append('Caption text too short')
            compliance['recommendations'].append('Provide more descriptive caption text (minimum 5 characters)')
        elif len(caption_text) > 150:
            compliance['compliance_details'].append('Caption text very long')
            compliance['recommendations'].append('Consider shortening caption text for better readability')
        
        # Check for citation pattern (e.g., "(ACU Online, 2024)")
        citation_patterns = self.design_standards.get('citation_patterns', [])
        has_citation = any(re.search(r'\([^)]*\d{4}\)', caption_text) for _ in [1])
        
        if has_citation:
            compliance['compliance_details'].append('Contains proper citation format')
        else:
            compliance['recommendations'].append('Consider adding citation in format: "(Source, Year)"')
        
        # Check for style attributes
        if caption.get('style'):
            compliance['compliance_details'].append('Has inline styling')
        else:
            compliance['recommendations'].append('Consider adding ACU standard styling')
        
        # Check for specific ACU patterns like "sm-font" class
        if 'sm-font' in caption_classes:
            compliance['compliance_details'].append('Uses recommended "sm-font" class')
        else:
            compliance['recommendations'].append('Consider adding "sm-font" class for consistent styling')
        
        return compliance

class TableCaptionChecker:
    """Main class for table caption compliance checking with LTI integration."""

    def __init__(self, base_url: str, api_token: str):
        """Initialize the checker with Canvas API credentials."""
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = f'https://{self.base_url}'
            
        self.api_token = api_token
        self.canvas_api = CanvasAPIConnector(base_url, api_token)
        self.analyzer = TableCaptionAnalyzer()
        self.logger = self.canvas_api.logger

    def analyze_course(self, course_id: str, progress: ProgressReporter | None = None) -> Dict:
        """Analyzes a single course for table caption compliance."""
        try:
            # Get course information
            course_info = self.canvas_api._make_api_request(f'courses/{course_id}')
            if not course_info:
                return self._create_analysis_result(course_id, "Unknown", "", error="Failed to retrieve course information")
            
            course_name = course_info.get('name', 'Unknown')
            sis_id = course_info.get('sis_course_id', '')
            self.logger.info(f"Analyzing course: {course_name} (ID: {course_id})")

            # Validate Canvas connection
            if not self.canvas_api.validate_connection():
                return self._create_analysis_result(
                    course_id, course_name, sis_id, 
                    error="Canvas API connection failed. Please check your credentials."
                )

            # Get course pages using parallel processing
            if progress:
                progress.update(step="fetch_course_pages", message="Fetching course pages")
            course_pages = self.canvas_api.get_course_pages_parallel(course_id)
            if not course_pages:
                return self._create_analysis_result(
                    course_id, course_name, sis_id,
                    error="No accessible pages found in course"
                )

            # Access ACU Online Design Library (Course 26333) using parallel processing
            self.logger.info("Accessing ACU Online Design Library (Course 26333)...")
            if progress:
                progress.update(step="fetch_design_library", message="Fetching design library")
            design_library_pages = self.canvas_api.get_course_pages_parallel('26333')
            
            if not design_library_pages:
                self.logger.warning("Could not access ACU Online Design Library. Proceeding with basic standards.")
                design_standards = self._get_basic_standards()
            else:
                # Extract table caption standards
                design_standards = self.analyzer.extract_design_standards(design_library_pages)
            
            # Analyze content compliance
            if progress:
                progress.update(step="analyze_pages", current=0, total=len(course_pages) or 1, message="Analyzing pages")
            # Emit progress per page via wrapper
            compliance_results = []
            total_pages = len(course_pages) or 1
            for idx, page in enumerate(course_pages, 1):
                compliance_results.extend(self.analyzer._analyze_page_content(page))
                if progress:
                    progress.update(step="analyze_pages", current=idx, total=total_pages, message=f"Analyzed {idx}/{total_pages} pages")
            
            findings = {
                'compliance_results': compliance_results,
                'pages_scanned': len(course_pages),
                'tables_found': len(compliance_results),
                'design_standards_loaded': len(design_standards.get('table_captions', [])) > 0,
                'design_standards': design_standards
            }

            if progress:
                progress.done({"pages": len(course_pages)})
            return self._create_analysis_result(course_id, course_name, sis_id, findings)

        except Exception as e:
            self.logger.error(f"Error analyzing course {course_id}: {e}", exc_info=True)
            if progress:
                progress.error(str(e))
            return self._create_analysis_result(course_id, "Unknown", "", error=str(e))

    def _get_basic_standards(self) -> Dict:
        """Get basic table caption standards when Design Library is inaccessible"""
        return {
            'table_captions': [],
            'common_classes': ['sm-font', 'text-muted', 'caption'],
            'common_patterns': [],
            'style_rules': {},
            'citation_patterns': ['(ACU Online, 2024)', '(Source, Year)']
        }

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
        
        for result in findings.get('compliance_results', []):
            if not result.get('has_caption') or result.get('compliance_status') != 'present_correct_style':
                manual_review_items.append({
                    'type': 'caption_compliance',
                    'page_title': result['page_title'],
                    'description': f"Table caption compliance issue: {result.get('compliance_status', 'unknown')}",
                    'reason': f"Table with class 'acuo-table' {'missing caption' if not result.get('has_caption') else 'has styling issues'}",
                    'severity': 'medium',
                    'recommendation': ' | '.join(result.get('recommendations', [])),
                    'current_value': result.get('caption_html', 'No caption found'),
                    'suggested_value': self._generate_suggested_caption(result),
                    'compliance_details': result.get('compliance_details', []),
                    'page_url': result.get('page_url', ''),
                    'table_preview': result.get('table_preview', ''),
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
                "tables_found": findings.get('tables_found', 0),
                "issues_found": len(manual_review_items),
                "design_standards_loaded": findings.get('design_standards_loaded', False)
            },
            "findings": {
                "safe_actions": [],  # No safe actions for content modification
                "requires_manual_review": manual_review_items
            },
            "detailed_findings": findings,
            "risk_assessment": {
                "content_modification_required": len(manual_review_items) > 0,
                "design_standards_available": findings.get('design_standards_loaded', False),
                "compliance_confidence": "high" if findings.get('tables_found', 0) > 0 else "low"
            }
        }

    def _generate_suggested_caption(self, result: Dict) -> str:
        """Generate a suggested caption based on compliance issues"""
        if not result.get('has_caption'):
            return '<caption class="sm-font">Table Description (Source, Year)</caption>'
        
        # If caption exists but has styling issues, suggest improvements
        current_caption = result.get('caption_html', '')
        if 'sm-font' not in result.get('caption_classes', []):
            # Add sm-font class
            if 'class=' in current_caption:
                current_caption = current_caption.replace('class="', 'class="sm-font ')
                current_caption = current_caption.replace('class=\'', 'class=\'sm-font ')
            else:
                current_caption = current_caption.replace('<caption', '<caption class="sm-font"')
        
        return current_caption
    
    def generate_excel_report(self, results: Dict, course_id: str) -> str:
        """Generate comprehensive Excel report for table caption analysis results."""
        try:
            from datetime import datetime
            import os
            
            # Create reports directory if it doesn't exist
            reports_dir = "reports"
            os.makedirs(reports_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = os.path.join(reports_dir, f"table_caption_analysis_{course_id}_{timestamp}.xlsx")
            
            # Extract data from results
            findings = results.get('findings', {})
            summary = results.get('summary', {})
            course_info = results.get('course_info', {})
            detailed_findings = results.get('detailed_findings', {})
            
            with pd.ExcelWriter(report_file, engine='xlsxwriter') as writer:
                workbook = writer.book
                
                # Create formats
                header_format = workbook.add_format({
                    'bold': True,
                    'bg_color': '#4A1A4A',
                    'font_color': 'white',
                    'border': 1
                })
                
                warning_format = workbook.add_format({
                    'bg_color': '#F4B942',
                    'border': 1
                })
                
                error_format = workbook.add_format({
                    'bg_color': '#D2492A',
                    'font_color': 'white',
                    'border': 1
                })
                
                success_format = workbook.add_format({
                    'bg_color': '#28A745',
                    'font_color': 'white',
                    'border': 1
                })
                
                # 1. Summary Sheet
                summary_data = {
                    'Metric': [
                        'Course ID',
                        'Course Name',
                        'Pages Scanned',
                        'Tables Found',
                        'Issues Found',
                        'Design Standards Loaded',
                        'Analysis Date',
                        'Analysis Duration'
                    ],
                    'Value': [
                        course_info.get('course_id', 'N/A'),
                        course_info.get('course_name', 'N/A'),
                        summary.get('pages_scanned', 0),
                        summary.get('tables_found', 0),
                        summary.get('issues_found', 0),
                        'Yes' if summary.get('design_standards_loaded', False) else 'No',
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'N/A'  # Could be enhanced to track duration
                    ]
                }
                
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                
                # Format summary sheet
                worksheet = writer.sheets['Summary']
                for col_num, value in enumerate(summary_df.columns.values):
                    worksheet.write(0, col_num, value, header_format)
                worksheet.set_column('A:B', 20)
                
                # 2. Issues Detail Sheet
                issues_data = []
                for item in findings.get('requires_manual_review', []):
                    issues_data.append({
                        'Page Title': item.get('page_title', 'N/A'),
                        'Issue Type': item.get('type', 'N/A'),
                        'Description': item.get('description', 'N/A'),
                        'Severity': item.get('severity', 'N/A'),
                        'Current Value': item.get('current_value', 'N/A'),
                        'Suggested Value': item.get('suggested_value', 'N/A'),
                        'Recommendation': item.get('recommendation', 'N/A'),
                        'Page URL': item.get('page_url', 'N/A'),
                        'Table Preview': item.get('table_preview', 'N/A')
                    })
                
                if issues_data:
                    issues_df = pd.DataFrame(issues_data)
                    issues_df.to_excel(writer, sheet_name='Issues Detail', index=False)
                    
                    # Format issues sheet
                    worksheet = writer.sheets['Issues Detail']
                    for col_num, value in enumerate(issues_df.columns.values):
                        worksheet.write(0, col_num, value, header_format)
                    worksheet.set_column('A:I', 15)
                    worksheet.set_column('B:B', 20)  # Description column wider
                    worksheet.set_column('F:G', 30)  # HTML columns wider
                
                # 3. Compliance Analysis Sheet
                compliance_data = []
                for result in detailed_findings.get('compliance_results', []):
                    compliance_data.append({
                        'Page Title': result.get('page_title', 'N/A'),
                        'Page URL': result.get('page_url', 'N/A'),
                        'Has Caption': 'Yes' if result.get('has_caption', False) else 'No',
                        'Caption Text': result.get('caption_text', 'N/A'),
                        'Caption Classes': ', '.join(result.get('caption_classes', [])),
                        'Compliance Status': result.get('compliance_status', 'N/A'),
                        'Table Preview': result.get('table_preview', 'N/A'),
                        'Recommendations': ' | '.join(result.get('recommendations', []))
                    })
                
                if compliance_data:
                    compliance_df = pd.DataFrame(compliance_data)
                    compliance_df.to_excel(writer, sheet_name='Compliance Analysis', index=False)
                    
                    # Format compliance sheet
                    worksheet = writer.sheets['Compliance Analysis']
                    for col_num, value in enumerate(compliance_df.columns.values):
                        worksheet.write(0, col_num, value, header_format)
                    worksheet.set_column('A:H', 15)
                    worksheet.set_column('B:B', 25)  # Page URL wider
                    worksheet.set_column('E:E', 20)  # Classes column wider
                    worksheet.set_column('G:G', 30)  # Table preview wider
                
                # 4. Design Standards Sheet
                design_standards = detailed_findings.get('design_standards', {})
                if design_standards:
                    standards_data = {
                        'Standard Type': [
                            'Common Classes',
                            'Citation Patterns',
                            'Style Rules',
                            'Table Captions Found'
                        ],
                        'Values': [
                            ', '.join(design_standards.get('common_classes', [])),
                            ', '.join(design_standards.get('citation_patterns', [])),
                            str(design_standards.get('style_rules', {})),
                            str(len(design_standards.get('table_captions', [])))
                        ]
                    }
                    
                    standards_df = pd.DataFrame(standards_data)
                    standards_df.to_excel(writer, sheet_name='Design Standards', index=False)
                    
                    # Format standards sheet
                    worksheet = writer.sheets['Design Standards']
                    for col_num, value in enumerate(standards_df.columns.values):
                        worksheet.write(0, col_num, value, header_format)
                    worksheet.set_column('A:B', 20)
                    worksheet.set_column('B:B', 40)  # Values column wider
                
                # 5. Risk Assessment Sheet
                risk_assessment = results.get('risk_assessment', {})
                risk_data = {
                    'Risk Factor': [
                        'Content Modification Required',
                        'Design Standards Available',
                        'Compliance Confidence',
                        'Total Issues Found',
                        'Pages with Issues'
                    ],
                    'Value': [
                        'Yes' if risk_assessment.get('content_modification_required', False) else 'No',
                        'Yes' if risk_assessment.get('design_standards_available', False) else 'No',
                        risk_assessment.get('compliance_confidence', 'N/A'),
                        summary.get('issues_found', 0),
                        len(set([item.get('page_title') for item in findings.get('requires_manual_review', [])]))
                    ]
                }
                
                risk_df = pd.DataFrame(risk_data)
                risk_df.to_excel(writer, sheet_name='Risk Assessment', index=False)
                
                # Format risk sheet
                worksheet = writer.sheets['Risk Assessment']
                for col_num, value in enumerate(risk_df.columns.values):
                    worksheet.write(0, col_num, value, header_format)
                worksheet.set_column('A:B', 25)
            
            return report_file
            
        except Exception as e:
            self.logger.error(f"Failed to generate Excel report: {e}")
            return None

def main():
    """Main function for command-line execution."""
    parser = argparse.ArgumentParser(
        description="Canvas Table Caption Checker - LTI Enhanced Version"
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
        progress = ProgressReporter(enabled=True)
        progress.update(step="initialize", message="Preparing analysis")
        # Initialize checker
        checker = TableCaptionChecker(args.canvas_url, args.api_token)
        
        if args.analyze_only or not args.execute_from_json:
            # Perform analysis
            print(f"Analyzing course {args.course_id} for table caption compliance...", file=sys.stderr)
            analysis_result = checker.analyze_course(args.course_id, progress=progress)
            
            # Output results in JSON format for LTI consumption
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis_result, indent=2))
            
        elif args.execute_from_json:
            # Execute approved actions - provide meaningful guidance instead of empty execution
            import os
            if not os.path.exists(args.execute_from_json):
                raise FileNotFoundError(f"Approved actions file not found: {args.execute_from_json}")
            
            with open(args.execute_from_json, 'r') as f:
                approved_actions = json.load(f)
            
            print(f"Processing {len(approved_actions)} table caption issues...", file=sys.stderr)
            
            # Generate detailed guidance for manual implementation
            guidance_items = []
            for action in approved_actions:
                page_title = action.get('page_title', 'Unknown Page')
                current_value = action.get('current_value', 'No caption found')
                suggested_value = action.get('suggested_value', '')
                
                guidance_items.append({
                    'page': page_title,
                    'current': current_value,
                    'suggested': suggested_value,
                    'url': action.get('page_url', ''),
                    'table_preview': action.get('table_preview', ''),
                    'recommendation': action.get('recommendation', '')
                })
            
            execution_result = {
                "success": True,
                "summary": {
                    "successful": 0,
                    "failed": 0,
                    "manual_required": len(approved_actions),
                    "guidance_provided": len(guidance_items)
                },
                "message": f"Table caption updates require manual implementation. Generated guidance for {len(guidance_items)} items.",
                "guidance": {
                    "overview": "Canvas API limitations prevent automatic table caption updates. Manual implementation required.",
                    "manual_steps": [
                        "1. Open each page with table caption issues in Canvas",
                        "2. Switch to HTML editor mode",
                        "3. Locate tables with class 'acuo-table'",
                        "4. Add or modify <caption> elements as first child of table",
                        "5. Apply CSS classes: 'sm-font', 'text-muted'",
                        "6. Include proper citations: '(Source, Year)'",
                        "7. Save and publish the page"
                    ],
                    "examples": [
                        "✅ Good: <caption class='sm-font text-muted'>Table 1: Student Performance Data (ACU Online, 2024)</caption>",
                        "❌ Bad: <caption>Table 1</caption>",
                        "❌ Missing: No caption element found"
                    ],
                    "items": guidance_items,
                    "resources": [
                        "ACU Online Design Library: Course 26333",
                        "Canvas HTML Editor Guide",
                        "Table Caption Accessibility Standards"
                    ]
                }
            }
            
            # Output execution results
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_result, indent=2))
        
    except Exception as e:
        # Output structured error for LTI consumption
        try:
            progress.error(str(e))
        except Exception:
            pass
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
