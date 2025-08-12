#!/usr/bin/env python3
"""
Canvas Figcaption Compliance Checker - LTI Phase 2 (Preview-First)
==================================================================

Purpose:
- Analyze figcaptions within a single Canvas course for compliance with ACU Online Design Library standards
- Classify items into:
  - safe_actions: N/A (analysis-only tool, no destructive actions)
  - requires_manual_review: figcaptions needing style/content improvements
- Generate comprehensive compliance report with actionable recommendations

Phase 2 Architecture Compliance:
- Args: --canvas-url, --api-token, --course-id, (--analyze-only | --execute-from-json FILE)
- Output: ENHANCED_ANALYSIS_JSON: {...} for analysis, EXECUTION_RESULTS_JSON: {...} for execution
- Non-interactive; robust error handling; conservative classification on API uncertainties

Human-Centered Design:
- Confidence-building analysis with clear explanations
- Risk-free analysis (no destructive operations)
- Actionable recommendations with Canvas editing guidance
- Clear categorization of compliance levels

Notes:
- This script is additive-only for the LTI integration. It does not modify existing scripts.
- Based on original figcaption_audit.py but adapted for LTI Phase 2 architecture
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup, Tag
from common.progress import ProgressReporter
import re

# Configuration
LOGGING_LEVEL = logging.INFO
REQUEST_TIMEOUT = 30
DEFAULT_PER_PAGE = 100
ACU_DESIGN_LIBRARY_COURSE_ID = "26333"

def setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=LOGGING_LEVEL,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr,
    )
    return logging.getLogger(__name__)

class CanvasSession:
    """Canvas API session handler with robust error handling"""
    
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.logger = logging.getLogger(__name__)
        
        # Setup resilient session
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.session.headers.update({
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
            'User-Agent': 'Canvas-Figcaption-Checker/1.0'
        })
    
    def get_paginated(self, endpoint: str, params: Dict = None) -> List[Dict]:
        """Get all items from a paginated Canvas API endpoint"""
        items = []
        url = f"{self.base_url}/api/v1/{endpoint}"
        
        if params is None:
            params = {}
        params['per_page'] = DEFAULT_PER_PAGE
        
        while url:
            try:
                self.logger.debug(f"Fetching: {url}")
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                
                batch = response.json()
                items.extend(batch)
                
                # Get next page URL from Link header
                url = None
                if 'Link' in response.headers:
                    links = response.headers['Link'].split(',')
                    for link in links:
                        if 'rel="next"' in link:
                            url = link.split('<')[1].split('>')[0]
                            params = {}  # URL already contains params
                            break
                
                # Rate limiting
                time.sleep(0.1)
                
            except requests.exceptions.RequestException as e:
                self.logger.error(f"API request failed for {endpoint}: {e}")
                break
        
        return items
    
    def get_single(self, endpoint: str) -> Optional[Dict]:
        """Get a single item from Canvas API"""
        try:
            url = f"{self.base_url}/api/v1/{endpoint}"
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed for {endpoint}: {e}")
            return None

class FigcaptionComplianceAnalyzer:
    """Analyzes figcaptions for ACU Online Design Library compliance"""
    
    def __init__(self, canvas: CanvasSession):
        self.canvas = canvas
        self.logger = logging.getLogger(__name__)
        self.design_standards = {}
    
    def analyze_course(self, course_id: str, progress: ProgressReporter | None = None) -> Dict[str, Any]:
        """
        Main analysis method that orchestrates the complete figcaption compliance check
        
        Returns comprehensive analysis results for Phase 2 preview
        """
        self.logger.info(f"Starting figcaption compliance analysis for course {course_id}")
        
        try:
            if progress:
                progress.update(step="initialize", message="Preparing analysis")
            # Step 1: Extract design standards from ACU Online Design Library
            if progress:
                progress.update(step="fetch_design_library", message="Fetching design standards")
            design_standards = self._extract_design_standards()
            
            # Step 2: Get all course pages with content
            if progress:
                progress.update(step="fetch_course_pages", message="Fetching course pages")
            course_pages = self._get_course_pages_with_content(course_id)
            
            # Step 3: Analyze each page for figcaption compliance
            total_pages = len(course_pages) or 1
            if progress:
                progress.update(step="analyze_pages", current=0, total=total_pages, message="Analyzing pages")
            compliance_results = []
            for idx, page in enumerate(course_pages, 1):
                compliance_results.extend(self._analyze_pages_compliance([page], course_id))
                if progress:
                    progress.update(step="analyze_pages", current=idx, total=total_pages, message=f"Analyzed {idx}/{total_pages} pages")
            
            # Step 4: Generate summary statistics
            summary = self._generate_summary_statistics(compliance_results)
            
            # Step 5: Categorize findings for Phase 2 structure
            findings = self._categorize_findings(compliance_results)
            
            # Phase 2 Enhanced Analysis JSON structure
            enhanced_output = {
                "phase": 2,
                "mode": "preview_first",
                "analysis_complete": True,
                "summary": summary,
                "findings": findings,
                "design_standards_info": {
                    "library_course_accessed": ACU_DESIGN_LIBRARY_COURSE_ID,
                    "standards_extracted": len(design_standards.get('common_classes', [])) > 0,
                    "image_examples_found": len(design_standards.get('image_figcaptions', [])),
                    "video_examples_found": len(design_standards.get('video_figcaptions', []))
                },
                "risk_assessment": {
                    "analysis_only_tool": True,
                    "no_destructive_actions": True,
                    "manual_fixes_required": True,
                    "canvas_api_limitations": "Figcaption updates require manual Canvas editing"
                }
            }
            
            self.logger.info(f"Analysis complete. Found {summary['items_scanned']} media elements")
            if progress:
                progress.done({"items_scanned": summary.get("items_scanned", 0)})
            return enhanced_output
            
        except Exception as e:
            self.logger.error(f"Analysis failed: {e}", exc_info=True)
            if progress:
                progress.error(str(e))
            return {
                "phase": 2,
                "mode": "preview_first", 
                "analysis_complete": False,
                "error": str(e),
                "summary": {"items_scanned": 0, "issues_found": 0}
            }
    
    def _extract_design_standards(self) -> Dict[str, Any]:
        """Extract figcaption design standards from ACU Online Design Library"""
        self.logger.info(f"Extracting figcaption standards from ACU Online Design Library (Course {ACU_DESIGN_LIBRARY_COURSE_ID})")
        
        standards = {
            'image_figcaptions': [],
            'video_figcaptions': [], 
            'common_classes': set(),
            'common_patterns': [],
            'style_rules': {}
        }
        
        try:
            # Get all pages from design library
            design_pages = self.canvas.get_paginated(f"courses/{ACU_DESIGN_LIBRARY_COURSE_ID}/pages")
            
            # Get full content for each page to analyze figcaptions
            for page_info in design_pages[:10]:  # Limit to first 10 pages for performance
                page_url = page_info.get('url')
                if not page_url:
                    continue
                
                full_page = self.canvas.get_single(f"courses/{ACU_DESIGN_LIBRARY_COURSE_ID}/pages/{page_url}")
                if not full_page or not full_page.get('body'):
                    continue
                
                self._analyze_page_for_standards(full_page, standards)
            
            # Convert set to list for JSON serialization
            standards['common_classes'] = list(standards['common_classes'])
            
            self.logger.info(f"Standards extracted: {len(standards['image_figcaptions'])} image examples, {len(standards['video_figcaptions'])} video examples")
            self.design_standards = standards
            return standards
            
        except Exception as e:
            self.logger.warning(f"Could not access design library: {e}")
            # Return minimal standards if library access fails
            return {
                'image_figcaptions': [],
                'video_figcaptions': [],
                'common_classes': ['sm-font', 'text-muted', 'caption-style'],
                'common_patterns': [],
                'style_rules': {}
            }
    
    def _analyze_page_for_standards(self, page: Dict, standards: Dict):
        """Analyze a single page from design library for figcaption patterns"""
        try:
            soup = BeautifulSoup(page['body'], 'html.parser')
            figcaptions = soup.find_all('figcaption')
            
            for figcaption in figcaptions:
                parent = figcaption.parent
                figcaption_data = {
                    'text': figcaption.get_text(strip=True),
                    'html': str(figcaption),
                    'classes': figcaption.get('class', []),
                    'style': figcaption.get('style', ''),
                    'page_title': page.get('title', 'Unknown'),
                    'parent_tag': parent.name if parent else None
                }
                
                # Collect common classes
                for class_name in figcaption.get('class', []):
                    standards['common_classes'].add(class_name)
                
                # Categorize by media type
                if parent and parent.name == 'figure':
                    if parent.find('img'):
                        standards['image_figcaptions'].append(figcaption_data)
                    elif parent.find('video') or parent.find('iframe'):
                        standards['video_figcaptions'].append(figcaption_data)
        
        except Exception as e:
            self.logger.debug(f"Error analyzing page for standards: {e}")
    
    def _get_course_pages_with_content(self, course_id: str) -> List[Dict]:
        """Get all course pages with full content"""
        self.logger.info(f"Fetching pages with content for course {course_id}")
        
        try:
            # Get basic page list
            basic_pages = self.canvas.get_paginated(f"courses/{course_id}/pages")
            
            # Get full content for each page
            pages_with_content = []
            for page_info in basic_pages:
                page_url = page_info.get('url')
                if not page_url:
                    continue
                
                # Skip 'Your Teaching Team' page as it's typically protected
                if page_url == 'your-teaching-team':
                    self.logger.debug("Skipping 'Your Teaching Team' page")
                    continue
                
                full_page = self.canvas.get_single(f"courses/{course_id}/pages/{page_url}")
                if full_page and full_page.get('body'):
                    full_page['course_id'] = course_id
                    pages_with_content.append(full_page)
                
                time.sleep(0.1)  # Rate limiting
            
            self.logger.info(f"Retrieved {len(pages_with_content)} pages with content")
            return pages_with_content
            
        except Exception as e:
            self.logger.error(f"Error fetching course pages: {e}")
            return []
    
    def _analyze_pages_compliance(self, pages: List[Dict], course_id: str) -> List[Dict]:
        """Analyze all pages for figcaption compliance"""
        compliance_results = []
        
        self.logger.info(f"Analyzing {len(pages)} pages for figcaption compliance")
        
        for page_num, page in enumerate(pages, 1):
            if not page.get('body'):
                continue
            
            self.logger.debug(f"Analyzing page {page_num}/{len(pages)}: {page.get('title', 'Untitled')}")
            
            soup = BeautifulSoup(page['body'], 'html.parser')
            page_url = f"https://canvas.acu.edu.au/courses/{course_id}/pages/{page.get('url', page.get('page_id', 'unknown'))}"
            
            processed_elements = set()
            
            # Find all figures and analyze their media content
            figures = soup.find_all('figure')
            for figure in figures:
                for element_type, tag_names in [('image', ['img']), ('video', ['video', 'iframe'])]:
                    # Handle both single tag and list of tags
                    if isinstance(tag_names, str):
                        tag_names = [tag_names]
                    
                    for tag_name in tag_names:
                        element = figure.find(tag_name)
                        if element and element not in processed_elements:
                            result = self._analyze_media_element(element, element_type, page, page_url)
                            if result:
                                compliance_results.append(result)
                            processed_elements.add(element)
                            break  # Only process first media element found in figure
            
            # Analyze videos not in figures (standalone iframes/videos)
            for tag_name in ['video', 'iframe']:
                standalone_elements = soup.find_all(tag_name)
                for element in standalone_elements:
                    if element not in processed_elements:
                        # Check if it's really standalone (not in a figure)
                        parent = element.parent
                        in_figure = False
                        while parent and parent.name != 'body':
                            if parent.name == 'figure':
                                in_figure = True
                                break
                            parent = parent.parent
                        
                        if not in_figure:
                            result = self._analyze_media_element(element, 'video', page, page_url)
                            if result:
                                compliance_results.append(result)
                            processed_elements.add(element)
        
        self.logger.info(f"Compliance analysis complete. Found {len(compliance_results)} media elements")
        return compliance_results
    
    def _analyze_media_element(self, element: Tag, media_type: str, page: Dict, page_url: str) -> Optional[Dict]:
        """Analyze individual media element for figcaption compliance"""
        
        # For images, only proceed if they are within a <figure> tag
        parent = element.parent
        figure_parent = None
        
        # Search up the DOM tree for figure container
        while parent and parent.name != 'body':
            if parent.name == 'figure':
                figure_parent = parent
                break
            parent = parent.parent
        
        # For images, require figure container
        if media_type == 'image' and not figure_parent:
            return None
        
        result = {
            'media_type': media_type,
            'page_title': page.get('title', 'Unknown'),
            'page_url': page_url,
            'element_preview': self._get_element_preview(element),
            'has_figcaption': False,
            'figcaption_text': '',
            'figcaption_classes': [],
            'figcaption_style': '',
            'compliance_status': 'missing_figcaption',
            'compliance_details': [],
            'recommendations': [],
            'severity': 'Medium'
        }
        
        figcaption = figure_parent.find('figcaption') if figure_parent else None
        
        if figcaption:
            result['has_figcaption'] = True
            result['figcaption_text'] = figcaption.get_text(strip=True)
            result['figcaption_classes'] = figcaption.get('class', [])
            result['figcaption_style'] = figcaption.get('style', '')
            result['figcaption_html'] = str(figcaption)
            
            # Check compliance with design standards
            compliance_check = self._check_figcaption_compliance(figcaption, media_type)
            result.update(compliance_check)
        else:
            result['compliance_details'].append('No figcaption found')
            result['recommendations'].append('Add figcaption element within a containing <figure> tag')
            result['severity'] = 'High'
        
        return result
    
    def _get_element_preview(self, element: Tag) -> str:
        """Get a preview of the element for reporting"""
        element_str = str(element)
        # Clean up and truncate for readability
        element_str = re.sub(r'\s+', ' ', element_str)
        if len(element_str) > 100:
            return element_str[:100] + '...'
        return element_str
    
    def _check_figcaption_compliance(self, figcaption: Tag, media_type: str) -> Dict:
        """Check if figcaption complies with design standards"""
        compliance = {
            'compliance_status': 'needs_improvement',
            'compliance_details': [],
            'recommendations': [],
            'severity': 'Medium'
        }
        
        figcaption_classes = set(figcaption.get('class', []))
        figcaption_text = figcaption.get_text(strip=True)
        
        # Check for ACU standard classes
        standard_classes = set(self.design_standards.get('common_classes', []))
        if standard_classes:
            matching_classes = figcaption_classes.intersection(standard_classes)
            if matching_classes:
                compliance['compliance_status'] = 'compliant'
                compliance['compliance_details'].append(f'Uses ACU standard classes: {", ".join(matching_classes)}')
                compliance['severity'] = 'Low'
            else:
                compliance['compliance_details'].append('Missing ACU standard classes')
                compliance['recommendations'].append(f'Add standard classes: sm-font, text-muted')
        
        # Check text quality
        if len(figcaption_text) < 5:
            compliance['compliance_details'].append('Figcaption text too short')
            compliance['recommendations'].append('Provide more descriptive figcaption text (minimum 5 characters)')
            compliance['severity'] = 'High'
        elif len(figcaption_text) > 200:
            compliance['compliance_details'].append('Figcaption text very long')
            compliance['recommendations'].append('Consider shortening figcaption text for better readability')
        
        # Check for citation pattern
        citation_pattern = r'\([^)]+,\s*\d{4}\)'
        if not re.search(citation_pattern, figcaption_text):
            compliance['compliance_details'].append('Missing citation format')
            compliance['recommendations'].append('Include proper citation: (Source, Year)')
        
        # Media-specific checks
        if media_type == 'image':
            self._check_image_figcaption_specifics(figcaption, compliance)
        elif media_type == 'video':
            self._check_video_figcaption_specifics(figcaption, compliance)
        
        return compliance
    
    def _check_image_figcaption_specifics(self, figcaption: Tag, compliance: Dict):
        """Check image-specific figcaption requirements"""
        text = figcaption.get_text(strip=True).lower()
        
        # Check for image-specific patterns
        if any(word in text for word in ['table', 'figure', 'chart', 'graph', 'diagram']):
            compliance['compliance_details'].append('Contains descriptive terminology')
        else:
            compliance['recommendations'].append('Consider adding descriptive terms (Table, Figure, Chart, etc.)')
    
    def _check_video_figcaption_specifics(self, figcaption: Tag, compliance: Dict):
        """Check video-specific figcaption requirements"""
        text = figcaption.get_text(strip=True).lower()
        
        # Video figcaptions should mention duration, source, or description
        video_keywords = ['video', 'duration', 'watch', 'view', 'minutes', 'seconds']
        if any(keyword in text for keyword in video_keywords):
            compliance['compliance_details'].append('Contains video-specific terminology')
        else:
            compliance['recommendations'].append('Consider adding video duration or description')
    
    def _generate_summary_statistics(self, compliance_results: List[Dict]) -> Dict:
        """Generate summary statistics for the analysis"""
        total = len(compliance_results)
        
        missing = len([r for r in compliance_results if not r.get('has_figcaption')])
        needs_improvement = len([r for r in compliance_results if r.get('compliance_status') == 'needs_improvement'])
        compliant = len([r for r in compliance_results if r.get('compliance_status') == 'compliant'])
        
        # Count by media type
        images = len([r for r in compliance_results if r.get('media_type') == 'image'])
        videos = len([r for r in compliance_results if r.get('media_type') == 'video'])
        
        return {
            "items_scanned": total,
            "issues_found": missing + needs_improvement,
            "safe_actions_found": 0,  # This is an analysis-only tool
            "manual_review_needed": missing + needs_improvement,
            "media_breakdown": {
                "images": images,
                "videos": videos
            },
            "compliance_breakdown": {
                "missing_figcaption": missing,
                "needs_improvement": needs_improvement,
                "compliant": compliant
            }
        }
    
    def _categorize_findings(self, compliance_results: List[Dict]) -> Dict:
        """Categorize findings for Phase 2 structure"""
        # This is an analysis-only tool, so no safe_actions
        safe_actions = []
        
        # All findings requiring manual review
        requires_manual_review = []
        
        for result in compliance_results:
            if not result.get('has_figcaption') or result.get('compliance_status') != 'compliant':
                # Create manual review item
                manual_item = {
                    "page_title": result['page_title'],
                    "page_url": result['page_url'],
                    "media_type": result['media_type'].title(),
                    "issue_type": "Missing figcaption" if not result.get('has_figcaption') else "Compliance issue",
                    "current_value": result.get('figcaption_text', 'No figcaption'),
                    "suggested_value": self._generate_suggested_figcaption(result),
                    "description": self._generate_issue_description(result),
                    "recommendation": '; '.join(result.get('recommendations', [])),
                    "severity": result.get('severity', 'Medium'),
                    "canvas_edit_instructions": self._generate_edit_instructions(result)
                }
                requires_manual_review.append(manual_item)
        
        return {
            "safe_actions": safe_actions,
            "requires_manual_review": requires_manual_review
        }
    
    def _generate_suggested_figcaption(self, result: Dict) -> str:
        """Generate a suggested figcaption based on media type and standards"""
        media_type = result.get('media_type', 'image')
        
        if media_type == 'image':
            return '<figcaption class="sm-font text-muted">Figure 1: [Descriptive title] ([Source], [Year])</figcaption>'
        else:  # video
            return '<figcaption class="sm-font text-muted">Video 1: [Title] - [Duration] ([Source], [Year])</figcaption>'
    
    def _generate_issue_description(self, result: Dict) -> str:
        """Generate a human-readable description of the issue"""
        if not result.get('has_figcaption'):
            return f"{result['media_type'].title()} lacks required figcaption element"
        
        issues = result.get('compliance_details', [])
        if issues:
            return f"Figcaption present but has issues: {'; '.join(issues)}"
        
        return "Figcaption needs review for ACU standards compliance"
    
    def _generate_edit_instructions(self, result: Dict) -> str:
        """Generate Canvas editing instructions"""
        return (
            "1. Open page in Canvas editor "
            "2. Switch to HTML view "
            "3. Locate the media element "
            "4. Add/update figcaption with proper classes and citation "
            "5. Save and publish changes"
        )

def execute_approved_actions(canvas: CanvasSession, course_id: str, actions: List[Dict]) -> Dict:
    """
    Execute approved actions - Note: This tool is analysis-only, no execution needed
    """
    logger = logging.getLogger(__name__)
    logger.info("Figcaption compliance checker is analysis-only - no actions to execute")
    
    return {
        "summary": {
            "successful": 0,
            "failed": 0,
            "total_requested": len(actions)
        },
        "results": {
            "message": "This tool is analysis-only. All figcaption updates must be done manually in Canvas.",
            "manual_instructions": "Use the analysis results to guide manual updates in Canvas editor."
        }
    }

def main():
    """Main function for command-line execution"""
    parser = argparse.ArgumentParser(description="Canvas Figcaption Compliance Checker - LTI Phase 2")
    parser.add_argument('--canvas-url', required=True, help="Canvas instance base URL")
    parser.add_argument('--api-token', required=True, help="Canvas API token")
    parser.add_argument('--course-id', required=True, help="Course ID to analyze")
    
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--analyze-only', action='store_true', help="Perform analysis and output JSON")
    mode.add_argument('--execute-from-json', type=str, metavar="FILE_PATH", help="Execute actions from JSON file (not applicable for this tool)")
    
    args = parser.parse_args()
    
    logger = setup_logger()
    
    try:
        # Initialize Canvas session
        canvas = CanvasSession(args.canvas_url, args.api_token)
        
        if args.execute_from_json:
            # This tool is analysis-only, but we need to handle this mode for LTI compatibility
            logger.info(f"Analysis-only tool: no actions to execute from {args.execute_from_json}")
            execution_results = execute_approved_actions(canvas, args.course_id, [])
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_results, indent=2))
        else:
            # Perform analysis
            logger.info(f"Starting figcaption compliance analysis for course {args.course_id}")
            analyzer = FigcaptionComplianceAnalyzer(canvas)
            progress = ProgressReporter(enabled=True)
            analysis_results = analyzer.analyze_course(args.course_id, progress=progress)
            
            # Output results in LTI Phase 2 format
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis_results, indent=2))
    
    except Exception as e:
        logger.critical(f"Critical error occurred: {e}", exc_info=True)
        error_output = {"success": False, "error": str(e)}
        print(f"CRITICAL_ERROR_JSON: {json.dumps(error_output)}", file=sys.stdout)
        sys.exit(1)

if __name__ == "__main__":
    main()
