#!/usr/bin/env python3
"""
Canvas Transcript Button Compliance Checker - LTI Phase 2 (Preview-First) with Parallel Processing
=================================================================================================

Purpose:
- Analyze transcript buttons within a single Canvas course for compliance with ACU Online Design Library standards
- Classify items into:
  - safe_actions: N/A (analysis-only tool, no destructive actions)
  - requires_manual_review: transcript buttons needing compliance corrections
- Generate comprehensive compliance report with actionable recommendations
- Optimized with concurrent processing for Design Library and target course analysis

Phase 2 Architecture Compliance:
- Args: --canvas-url, --api-token, --course-id, (--analyze-only | --execute-from-json FILE)
- Output: ENHANCED_ANALYSIS_JSON: {...} for analysis, EXECUTION_RESULTS_JSON: {...} for execution
- Non-interactive; robust error handling; conservative classification on API uncertainties
- Parallel processing for Design Library (26333) and target course fetching

Human-Centered Design:
- Confidence-building analysis with clear explanations
- Risk-free analysis (no destructive operations)
- Actionable recommendations with Canvas editing guidance
- Clear categorization of compliance levels with link validation

Notes:
- This script is additive-only for the LTI integration. It does not modify existing scripts.
- Based on original transcript audit script but adapted for LTI Phase 2 architecture
- Includes concurrent fetching of Design Library standards and target course content
"""

import argparse
import json
import logging
import sys
import time
import concurrent.futures
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup, Tag
import re
from threading import Lock

# Configuration
LOGGING_LEVEL = logging.INFO
REQUEST_TIMEOUT = 30
DEFAULT_PER_PAGE = 100
ACU_DESIGN_LIBRARY_COURSE_ID = "26333"
MAX_CONCURRENT_REQUESTS = 3

def setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=LOGGING_LEVEL,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr,
    )
    return logging.getLogger(__name__)

class CanvasSession:
    """Thread-safe Canvas API session handler with robust error handling"""
    
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = f'https://{self.base_url}'
        self.api_token = api_token
        self.logger = logging.getLogger(__name__)
        
        # Thread safety
        self._session_lock = Lock()
        
        # Rate limiting for concurrent requests
        self.rate_limit_delay = 0.3
        self.max_concurrent_requests = MAX_CONCURRENT_REQUESTS
        
    def _create_session(self) -> requests.Session:
        """Create a new session for thread safety"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
            'User-Agent': 'Canvas-Transcript-Checker/1.0'
        })
        return session
    
    def validate_connection(self) -> bool:
        """Test Canvas API connection"""
        try:
            session = self._create_session()
            response = session.get(f"{self.base_url}/api/v1/users/self", timeout=REQUEST_TIMEOUT)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"❌ Canvas connection failed: {e}")
            return False
    
    def get_paginated(self, endpoint: str, params: Dict = None) -> List[Dict]:
        """Get all items from a paginated Canvas API endpoint (thread-safe)"""
        items = []
        url = f"{self.base_url}/api/v1/{endpoint}"
        
        if params is None:
            params = {}
        params['per_page'] = DEFAULT_PER_PAGE
        
        session = self._create_session()
        
        while url:
            try:
                self.logger.debug(f"Fetching: {url}")
                response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                
                batch = response.json()
                items.extend(batch)
                
                # Get next page URL from Link header
                url = self._extract_next_url(response.headers.get('Link', ''))
                params = None  # Clear params for subsequent requests
                
                # Rate limiting
                time.sleep(self.rate_limit_delay)
                
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Error fetching {url}: {e}")
                break
        
        return items
    
    def get_course_pages_with_content(self, course_id: str) -> List[Dict]:
        """Get all pages from a course with full content using parallel processing"""
        try:
            # First, get the list of pages
            pages_list = self.get_paginated(f"courses/{course_id}/pages")
            
            if not pages_list:
                self.logger.warning(f"No pages found for course {course_id}")
                return []
            
            self.logger.info(f"Fetching content for {len(pages_list)} pages in parallel...")
            
            # Fetch page content in parallel
            pages_with_content = []
            
            def fetch_page_content(page_info: Dict) -> Optional[Dict]:
                """Fetch full content for a single page"""
                try:
                    session = self._create_session()
                    page_url = page_info.get('url')
                    if not page_url:
                        return None
                        
                    # Skip specific pages
                    if page_url == 'your-teaching-team':
                        return None
                    
                    response = session.get(
                        f"{self.base_url}/api/v1/courses/{course_id}/pages/{page_url}",
                        timeout=REQUEST_TIMEOUT
                    )
                    response.raise_for_status()
                    
                    full_page = response.json()
                    full_page['course_id'] = course_id
                    return full_page
                    
                except Exception as e:
                    self.logger.warning(f"Failed to fetch content for page {page_info.get('title', 'Unknown')}: {e}")
                    return None
            
            # Use ThreadPoolExecutor for parallel page content fetching
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrent_requests) as executor:
                # Submit all page content requests
                future_to_page = {
                    executor.submit(fetch_page_content, page): page 
                    for page in pages_list
                }
                
                # Collect results as they complete
                for future in concurrent.futures.as_completed(future_to_page):
                    try:
                        page_content = future.result()
                        if page_content:
                            pages_with_content.append(page_content)
                    except Exception as e:
                        page = future_to_page[future]
                        self.logger.warning(f"Exception fetching page {page.get('title', 'Unknown')}: {e}")
            
            self.logger.info(f"Successfully fetched content for {len(pages_with_content)} pages")
            return pages_with_content
            
        except Exception as e:
            self.logger.error(f"Error getting course pages: {e}")
            return []
    
    def _extract_next_url(self, link_header: str) -> Optional[str]:
        """Extract next page URL from Link header"""
        if not link_header:
            return None
        
        links = link_header.split(',')
        for link in links:
            if 'rel="next"' in link:
                return link.split('<')[1].split('>')[0]
        return None

class TranscriptStandardsAnalyzer:
    """Analyzes ACU Design Library for transcript button standards"""
    
    def __init__(self, canvas_session: CanvasSession):
        self.canvas_session = canvas_session
        self.logger = logging.getLogger(__name__)
        
    def extract_design_standards(self, design_library_pages: List[Dict]) -> Dict[str, Any]:
        """Extract transcript button design standards from ACU Online Design Library"""
        self.logger.info("🎨 Analyzing ACU Online Design Library for transcript button standards...")
        
        standards = {
            'transcript_button_examples': [],
            'common_classes': set(),
            'common_patterns': [],
            'link_patterns': [],
            'standard_attributes': {
                'recommended_classes': ['acuo-btn', 'external'],
                'recommended_role': 'button',
                'recommended_title': 'Transcript'
            }
        }
        
        for page in design_library_pages:
            if not page.get('body'):
                continue
                
            soup = BeautifulSoup(page['body'], 'html.parser')
            
            # Find all transcript buttons
            transcript_buttons = self._find_transcript_buttons(soup)
            
            for button_data in transcript_buttons:
                button_data['page_title'] = page.get('title', 'Unknown')
                standards['transcript_button_examples'].append(button_data)
                
                # Collect common classes
                for class_name in button_data.get('classes', []):
                    standards['common_classes'].add(class_name)
                
                # Collect link patterns
                if button_data.get('href'):
                    standards['link_patterns'].append(button_data['href'])
        
        # Convert set to list for JSON serialization
        standards['common_classes'] = list(standards['common_classes'])
        
        self.logger.info(f"✓ Found {len(standards['transcript_button_examples'])} transcript button examples")
        self.logger.info(f"✓ Identified {len(standards['common_classes'])} common CSS classes")
        
        return standards
    
    def _find_transcript_buttons(self, soup: BeautifulSoup) -> List[Dict]:
        """Find transcript buttons in HTML content"""
        transcript_buttons = []
        
        # Look for links with transcript-related content
        patterns = [
            soup.find_all('a', string=re.compile(r'transcript', re.IGNORECASE)),
            soup.find_all('a', title=re.compile(r'transcript', re.IGNORECASE)),
            soup.find_all('a', href=re.compile(r'transcript', re.IGNORECASE))
        ]
        
        # Flatten and deduplicate
        all_links = set()
        for pattern_results in patterns:
            for link in pattern_results:
                all_links.add(link)
        
        for link in all_links:
            button_data = {
                'text': link.get_text(strip=True),
                'href': link.get('href', ''),
                'title': link.get('title', ''),
                'classes': link.get('class', []),
                'role': link.get('role', ''),
                'html': str(link),
                'parent_html': str(link.parent) if link.parent else '',
                'in_figure': bool(link.find_parent('figure'))
            }
            transcript_buttons.append(button_data)
        
        return transcript_buttons

class TranscriptComplianceAnalyzer:
    """Analyzes course content for transcript button compliance"""
    
    def __init__(self, canvas_session: CanvasSession, design_standards: Dict):
        self.canvas_session = canvas_session
        self.design_standards = design_standards
        self.logger = logging.getLogger(__name__)
        
    def analyze_course_compliance(self, pages: List[Dict], course_id: str) -> List[Dict]:
        """Analyze course pages for transcript button compliance - only images with transcript buttons"""
        compliance_results = []
        
        self.logger.info(f"🔍 Analyzing course {course_id} for transcript button compliance...")
        
        for page_num, page in enumerate(pages, 1):
            if not page.get('body'):
                continue
            
            self.logger.debug(f"Processing page {page_num}/{len(pages)}: {page.get('title', 'Untitled')}")
            
            soup = BeautifulSoup(page['body'], 'html.parser')
            page_url = self._build_page_url(course_id, page)
            
            # Find all figures with images that have transcript buttons
            figures = soup.find_all('figure')
            
            for figure in figures:
                img = figure.find('img')
                if img:
                    # Only analyze if transcript button is present
                    transcript_buttons = self._find_transcript_buttons_in_figure(figure)
                    if transcript_buttons:
                        result = self._analyze_figure_transcript_compliance(
                            figure, img, page, page_url, course_id, transcript_buttons[0]
                        )
                        if result:
                            compliance_results.append(result)

        self.logger.info(f"✓ Analyzed {len(compliance_results)} images with transcript buttons")
        return compliance_results
    
    def _find_transcript_buttons_in_figure(self, figure: Tag) -> List[Dict]:
        """Find transcript buttons specifically within a figure element"""
        transcript_buttons = []
        
        # Look for links with transcript-related content within the figure
        links = figure.find_all('a')
        
        for link in links:
            link_text = link.get_text(strip=True).lower()
            link_title = (link.get('title') or '').lower()
            link_href = (link.get('href') or '').lower()
            
            if any(keyword in text for keyword in ['transcript'] 
                   for text in [link_text, link_title, link_href]):
                
                button_data = {
                    'text': link.get_text(strip=True),
                    'href': link.get('href', ''),
                    'title': link.get('title', ''),
                    'classes': link.get('class', []),
                    'role': link.get('role', ''),
                    'html': str(link)
                }
                transcript_buttons.append(button_data)
        
        return transcript_buttons
    
    def _analyze_figure_transcript_compliance(self, figure: Tag, img: Tag, page: Dict, 
                                            page_url: str, course_id: str, transcript_button: Dict) -> Optional[Dict]:
        """Analyze figure with image that has transcript button for compliance"""
        
        result = {
            'page_title': page.get('title', 'Unknown'),
            'page_url': page_url,
            'page_number': self._extract_page_number(page.get('title', '')),
            'image_src': img.get('src', ''),
            'figcaption_text': '',
            'in_figure': True,
            'has_transcript_button': True,
            'transcript_button_html': transcript_button['html'],
            'transcript_link': transcript_button['href'],
            'transcript_page_content': '',
            'compliance_status': 'present_invalid_link',  # Default to invalid, will update if valid
            'compliance_details': [],
            'recommendations': [],
            'image_preview': self._get_image_preview(img),
            'button_attributes': {
                'classes': transcript_button.get('classes', []),
                'role': transcript_button.get('role', ''),
                'title': transcript_button.get('title', ''),
                'text': transcript_button.get('text', '')
            }
        }
        
        # Get figcaption if present
        figcaption = figure.find('figcaption')
        if figcaption:
            result['figcaption_text'] = figcaption.get_text(strip=True)
        
        # Validate the transcript link and button attributes
        validation_result = self._validate_transcript_compliance(
            transcript_button, 
            course_id, 
            result['page_number'], 
            result['figcaption_text']
        )
        
        result.update(validation_result)
        
        return result
    
    def _validate_transcript_compliance(self, transcript_button: Dict, course_id: str, 
                                      page_number: str, figcaption_text: str) -> Dict:
        """Validate transcript button compliance with ACU standards"""
        validation = {
            'compliance_status': 'present_invalid_link',
            'compliance_details': [],
            'recommendations': []
        }
        
        href = transcript_button.get('href', '')
        classes = transcript_button.get('classes', [])
        role = transcript_button.get('role', '')
        title = transcript_button.get('title', '')
        
        # Check link validity first
        link_valid = False
        if href and '/courses/' in href and '/pages/' in href:
            link_validation = self._validate_transcript_link(href, course_id, page_number, figcaption_text)
            validation['transcript_page_content'] = link_validation.get('transcript_page_content', '')
            if link_validation.get('link_valid', False):
                link_valid = True
                validation['compliance_details'].extend(link_validation.get('details', []))
            else:
                validation['compliance_details'].extend(link_validation.get('details', []))
                validation['recommendations'].extend(link_validation.get('recommendations', []))
        else:
            validation['compliance_details'].append('Transcript button has invalid or missing link')
            validation['recommendations'].append('Add valid link to transcript page in same course')
        
        # Check button attributes compliance
        attributes_compliant = True
        
        # Check classes
        recommended_classes = self.design_standards['standard_attributes']['recommended_classes']
        missing_classes = [cls for cls in recommended_classes if cls not in classes]
        if missing_classes:
            attributes_compliant = False
            validation['compliance_details'].append(f'Missing recommended classes: {", ".join(missing_classes)}')
            validation['recommendations'].append(f'Add classes: {" ".join(missing_classes)}')
        
        # Check role
        if role != self.design_standards['standard_attributes']['recommended_role']:
            attributes_compliant = False
            validation['compliance_details'].append(f'Role should be "button", found: "{role}"')
            validation['recommendations'].append('Add role="button" attribute')
        
        # Check title
        if title != self.design_standards['standard_attributes']['recommended_title']:
            attributes_compliant = False
            validation['compliance_details'].append(f'Title should be "Transcript", found: "{title}"')
            validation['recommendations'].append('Add title="Transcript" attribute')
        
        # Determine final compliance status
        if link_valid and attributes_compliant:
            validation['compliance_status'] = 'present_valid'
        elif link_valid:
            validation['compliance_status'] = 'present_valid_link_poor_attributes'
        # else remains 'present_invalid_link'
        
        return validation
    
    def _validate_transcript_link(self, href: str, course_id: str, page_number: str, figcaption_text: str) -> Dict:
        """Validate that transcript link contains required information"""
        result = {
            'link_valid': False,
            'details': [],
            'recommendations': [],
            'transcript_page_content': ''
        }
        
        try:
            # Extract course and page info from link
            if '/courses/' in href and '/pages/' in href:
                link_parts = href.split('/courses/')[-1].split('/pages/')
                if len(link_parts) >= 2:
                    link_course_id = link_parts[0]
                    link_page_slug = link_parts[1]
                    
                    # Fetch the transcript page content
                    try:
                        transcript_pages = self.canvas_session.get_paginated(f"courses/{link_course_id}/pages/{link_page_slug}")
                        if transcript_pages:
                            transcript_page = transcript_pages[0]
                            transcript_title = transcript_page.get('title', '')
                            result['transcript_page_content'] = f"Title: {transcript_title}"
                            
                            # Check if transcript page contains page number or figcaption text
                            contains_page_number = page_number and page_number in transcript_title
                            contains_figcaption = figcaption_text and any(
                                word.lower() in transcript_title.lower() 
                                for word in figcaption_text.split() 
                                if len(word) > 3  # Only check significant words
                            )
                            
                            if contains_page_number and contains_figcaption:
                                result['link_valid'] = True
                                result['details'].append(f'Transcript page contains both page number ({page_number}) and figcaption text')
                            elif contains_page_number:
                                result['link_valid'] = True
                                result['details'].append(f'Transcript page contains page number ({page_number})')
                            elif contains_figcaption:
                                result['link_valid'] = True
                                result['details'].append('Transcript page contains figcaption text')
                            else:
                                result['details'].append('Transcript page does not contain page number or figcaption text')
                                result['recommendations'].append(f'Update transcript page title to include page number ({page_number}) or figcaption text')
                        else:
                            result['details'].append('Could not access transcript page')
                            result['recommendations'].append('Verify transcript link is valid and accessible')
                    except Exception as e:
                        result['details'].append(f'Error accessing transcript page: {str(e)}')
                        result['recommendations'].append('Check transcript link accessibility')
                        
        except Exception as e:
            result['details'].append(f'Error validating transcript link: {str(e)}')
            result['recommendations'].append('Check transcript link format')
        
        return result
    
    def _extract_page_number(self, page_title: str) -> str:
        """Extract page number from page title"""
        # Look for patterns like "1.5", "2.3", "10.2", etc.
        match = re.search(r'\b(\d+(?:\.\d+)?)\b', page_title)
        if match:
            return match.group(1)
        return ''
    
    def _get_image_preview(self, img: Tag) -> str:
        """Get a preview of the image element for reporting"""
        img_str = str(img)
        if len(img_str) > 150:
            return img_str[:150] + '...'
        return img_str
    
    def _build_page_url(self, course_id: str, page: Dict) -> str:
        """Build Canvas page URL"""
        page_url = page.get('url', page.get('page_id', 'unknown'))
        return f"https://canvas.acu.edu.au/courses/{course_id}/pages/{page_url}"

def fetch_data_parallel(canvas_session: CanvasSession, target_course_id: str) -> Tuple[List[Dict], List[Dict]]:
    """Fetch Design Library standards and target course pages in parallel"""
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting parallel data fetch...")
    
    def fetch_design_library() -> List[Dict]:
        """Fetch ACU Design Library pages"""
        logger.info(f"📚 Fetching Design Library (Course {ACU_DESIGN_LIBRARY_COURSE_ID})...")
        return canvas_session.get_course_pages_with_content(ACU_DESIGN_LIBRARY_COURSE_ID)
    
    def fetch_target_course() -> List[Dict]:
        """Fetch target course pages"""
        logger.info(f"📖 Fetching target course (Course {target_course_id})...")
        return canvas_session.get_course_pages_with_content(target_course_id)
    
    # Use ThreadPoolExecutor for parallel fetching
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        # Submit both tasks
        design_future = executor.submit(fetch_design_library)
        target_future = executor.submit(fetch_target_course)
        
        # Get results
        try:
            design_library_pages = design_future.result(timeout=300)  # 5 minute timeout
            target_course_pages = target_future.result(timeout=300)   # 5 minute timeout
            
            logger.info(f"✓ Parallel fetch complete: {len(design_library_pages)} design pages, {len(target_course_pages)} target pages")
            return design_library_pages, target_course_pages
            
        except concurrent.futures.TimeoutError:
            logger.error("❌ Timeout during parallel data fetch")
            return [], []
        except Exception as e:
            logger.error(f"❌ Error during parallel data fetch: {e}")
            return [], []

def generate_enhanced_analysis_output(compliance_results: List[Dict], design_standards: Dict, course_info: Dict) -> Dict:
    """Generate Phase 2 enhanced analysis output with statistics and categorization"""
    
    # Calculate statistics
    total_items = len(compliance_results)
    valid_count = len([r for r in compliance_results if r.get('compliance_status') == 'present_valid'])
    valid_link_poor_attrs = len([r for r in compliance_results if r.get('compliance_status') == 'present_valid_link_poor_attributes'])
    invalid_link_count = len([r for r in compliance_results if r.get('compliance_status') == 'present_invalid_link'])
    
    # Categorize for Phase 2 workflow
    safe_actions = []  # No safe automated actions for this analysis-only tool
    requires_manual_review = []
    
    for result in compliance_results:
        status = result.get('compliance_status', '')
        
        if status in ['present_invalid_link', 'present_valid_link_poor_attributes']:
            # These need manual review to fix links or attributes
            requires_manual_review.append({
                'type': 'transcript_button_compliance',
                'page_title': result.get('page_title', ''),
                'page_url': result.get('page_url', ''),
                'issue_type': 'Invalid Link' if status == 'present_invalid_link' else 'Poor Attributes',
                'current_button_html': result.get('transcript_button_html', ''),
                'compliance_details': result.get('compliance_details', []),
                'recommendations': result.get('recommendations', []),
                'image_preview': result.get('image_preview', ''),
                'priority': 'high' if status == 'present_invalid_link' else 'medium'
            })
    
    enhanced_output = {
        "phase": 2,
        "mode": "preview_first",
        "analysis_complete": True,
        "summary": {
            "total_images_with_transcript_buttons": total_items,
            "valid_transcript_buttons": valid_count,
            "buttons_with_valid_links_poor_attributes": valid_link_poor_attrs,
            "buttons_with_invalid_links": invalid_link_count,
            "compliance_rate_percent": round((valid_count / total_items * 100) if total_items > 0 else 0, 1)
        },
        "findings": {
            "safe_actions": safe_actions,
            "requires_manual_review": requires_manual_review
        },
        "design_standards_summary": {
            "examples_found": len(design_standards.get('transcript_button_examples', [])),
            "common_classes": design_standards.get('common_classes', []),
            "recommended_attributes": design_standards.get('standard_attributes', {})
        },
        "course_info": course_info,
        "detailed_results": compliance_results,
        "risk_assessment": {
            "analysis_only_tool": True,
            "no_destructive_actions": True,
            "manual_review_required": len(requires_manual_review),
            "confidence_level": "high"
        }
    }
    
    return enhanced_output

def main():
    """Main execution function with LTI integration support and parallel processing"""
    parser = argparse.ArgumentParser(description='Transcript Button Compliance Checker for Canvas LTI')
    parser.add_argument('--canvas-url', required=True, help='Canvas base URL')
    parser.add_argument('--api-token', required=True, help='Canvas API token')
    parser.add_argument('--course-id', required=True, help='Target course ID')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze, do not execute (Phase 2)')
    parser.add_argument('--execute-from-json', type=str, help='Execute from approved actions JSON file')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger()
    
    try:
        # Validate connection
        logger.info("🔌 Connecting to Canvas API...")
        canvas_session = CanvasSession(args.canvas_url, args.api_token)
        
        if not canvas_session.validate_connection():
            logger.error("❌ Canvas API connection failed")
            sys.exit(1)
        
        logger.info("✅ Canvas connection successful")
        
        if args.analyze_only:
            # Phase 2 Analysis Mode
            logger.info("📊 Starting transcript button compliance analysis...")
            
            # Parallel data fetching
            design_library_pages, target_course_pages = fetch_data_parallel(canvas_session, args.course_id)
            
            if not design_library_pages:
                logger.error("❌ Failed to fetch Design Library standards")
                sys.exit(1)
            
            if not target_course_pages:
                logger.error("❌ Failed to fetch target course pages")
                sys.exit(1)
            
            # Extract design standards
            standards_analyzer = TranscriptStandardsAnalyzer(canvas_session)
            design_standards = standards_analyzer.extract_design_standards(design_library_pages)
            
            # Analyze target course compliance
            compliance_analyzer = TranscriptComplianceAnalyzer(canvas_session, design_standards)
            compliance_results = compliance_analyzer.analyze_course_compliance(target_course_pages, args.course_id)
            
            # Generate enhanced output
            course_info = {
                'course_id': args.course_id,
                'total_pages': len(target_course_pages),
                'analysis_timestamp': datetime.now().isoformat()
            }
            
            enhanced_output = generate_enhanced_analysis_output(compliance_results, design_standards, course_info)
            
            # Output for LTI integration
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(enhanced_output))
            
        elif args.execute_from_json:
            # Phase 2 Execution Mode (not applicable for analysis-only tool)
            logger.info("ℹ️ This is an analysis-only tool. No execution actions available.")
            
            execution_result = {
                "summary": {
                    "analysis_only_tool": True,
                    "no_execution_available": True,
                    "timestamp": datetime.now().isoformat()
                },
                "message": "Transcript Button Compliance Checker is an analysis-only tool. Use the analysis results to manually update transcript buttons in Canvas."
            }
            
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_result))
            
        else:
            logger.error("❌ Please specify either --analyze-only or --execute-from-json")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("⏹️ Analysis interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
