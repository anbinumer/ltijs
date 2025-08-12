#!/usr/bin/env python3
"""
Canvas Alt Text Compliance Checker - LTI Enhanced Version
=========================================================

A comprehensive tool that audits Canvas courses for alt text compliance with accessibility standards.
Enhanced for LTI integration with Phase 2 preview-first workflow and parallel processing.

Features:
- Analyzes images within <figure> tags for alt text compliance
- Accesses ACU Online Design Library for standards reference
- Provides safety-first analysis with clear categorization
- Generates structured JSON output for LTI integration
- Supports approved action execution mode
- Parallel processing for faster data fetching and analysis
- Thread-safe Canvas API operations

Performance Enhancements:
- Concurrent fetching of target course and design library pages
- Parallel analysis of design standards and course compliance
- Configurable rate limiting for Canvas API respect
- Optimized thread pool management

Author: ACU Canvas Tools Team
Version: 2.1 (Parallel Processing Enhanced)
Date: 2025-01-28
"""

import requests
import json
import re
import time
import sys
import argparse
import hashlib
import logging
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from common.progress import ProgressReporter
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class CanvasAPIConnector:
    """Canvas API connector with error handling, rate limiting, and thread safety"""
    
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = f'https://{self.base_url}'
        self.api_token = api_token
        
        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        # Rate limiting configuration for concurrent requests
        self.rate_limit_delay = 0.3  # Reduced from 0.5 for parallel processing
        self.max_concurrent_requests = 3
        
    def _create_session(self) -> requests.Session:
        """Create a new session for thread safety"""
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))
        session.headers.update({
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        })
        return session
        
    def validate_connection(self) -> bool:
        """Test Canvas API connection"""
        try:
            session = self._create_session()
            response = session.get(f"{self.base_url}/api/v1/users/self", timeout=30)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"❌ Canvas connection failed: {e}")
            return False
    
    def get_course_pages(self, course_id: str) -> List[Dict]:
        """Get all pages from a course with content (thread-safe)"""
        try:
            pages = []
            session = self._create_session()  # Thread-safe session
            url = f"{self.base_url}/api/v1/courses/{course_id}/pages"
            
            self.logger.info(f"📄 Fetching pages from course {course_id}...")
            
            while url:
                response = session.get(url, timeout=30)
                if response.status_code != 200:
                    self.logger.warning(f"⚠ Failed to get pages: HTTP {response.status_code}")
                    break
                
                page_list = response.json()
                
                # Get full content for each page
                for i, page in enumerate(page_list):
                    # Skip common exclusions
                    page_title = page.get('title', 'Untitled')
                    if any(skip in page_title for skip in ['[ARCHIVE]', 'Your Teaching Team']):
                        self.logger.info(f"  ⏩ Skipping: {page_title}")
                        continue

                    self.logger.info(f"  📖 Processing page {i+1}/{len(page_list)}: {page_title}")
                    page_response = session.get(
                        f"{self.base_url}/api/v1/courses/{course_id}/pages/{page['url']}", 
                        timeout=30
                    )
                    if page_response.status_code == 200:
                        full_page = page_response.json()
                        full_page['course_id'] = course_id
                        full_page['page_url'] = f"{self.base_url}/courses/{course_id}/pages/{page['url']}"
                        pages.append(full_page)
                    time.sleep(self.rate_limit_delay)  # Configurable rate limiting
                
                # Handle pagination
                url = self._get_next_page_url(response.headers.get('Link', ''))
            
            self.logger.info(f"✓ Retrieved {len(pages)} pages")
            return pages
            
        except Exception as e:
            self.logger.error(f"❌ Error getting course pages: {e}")
            return []
    
    def _get_next_page_url(self, link_header: str) -> Optional[str]:
        """Extract next page URL from Link header"""
        if not link_header:
            return None
        
        links = link_header.split(',')
        for link in links:
            if 'rel="next"' in link:
                return link.split('<')[1].split('>')[0]
        return None

class AltTextAnalyzer:
    """Analyzes alt text for compliance with accessibility standards"""
    
    def __init__(self):
        self.design_standards = {}
        self.logger = logging.getLogger(__name__)
        
    def extract_design_standards(self, design_library_pages: List[Dict]) -> Dict[str, Any]:
        """Extract alt text design standards from ACU Online Design Library"""
        self.logger.info("🎨 Analyzing ACU Online Design Library for alt text standards...")
        
        standards = {
            'good_alt_text_examples': [],
            'decorative_examples': [],
            'avoid_patterns': ['image', 'picture', 'photo', 'graphic'],
            'decorative_indicators': ['decorative', '', 'decoration']
        }
        
        for page in design_library_pages:
            if not page.get('body'):
                continue
                
            soup = BeautifulSoup(page['body'], 'html.parser')
            
            # Find all images within figure tags
            figures = soup.find_all('figure')
            for figure in figures:
                images = figure.find_all('img')
                for img in images:
                    alt_text = img.get('alt', '')
                    src = img.get('src', '')
                    
                    img_data = {
                        'alt_text': alt_text,
                        'src': src,
                        'page_title': page.get('title', 'Unknown'),
                        'page_url': page.get('page_url', ''),
                        'is_decorative': self._is_likely_decorative(img, alt_text)
                    }
                    
                    if alt_text and self._is_good_alt_text(alt_text):
                        standards['good_alt_text_examples'].append(img_data)
                    elif self._is_decorative_alt_text(alt_text):
                        standards['decorative_examples'].append(img_data)
        
        self.logger.info(f"✓ Found {len(standards['good_alt_text_examples'])} good examples")
        self.logger.info(f"✓ Found {len(standards['decorative_examples'])} decorative examples")
        
        self.design_standards = standards
        return standards
    
    def analyze_content_compliance(self, pages: List[Dict], course_name: str = "Target Course") -> List[Dict]:
        """Analyze content for alt text compliance"""
        compliance_results = []
        total_images_found = 0
        figure_images_analyzed = 0
        
        self.logger.info(f"🔍 Analyzing {course_name} for alt text compliance...")
        self.logger.info("📋 Focus: Images within <figure> tags only")
        
        for page_num, page in enumerate(pages, 1):
            if not page.get('body'):
                continue
            
            self.logger.info(f"  📄 Page {page_num}/{len(pages)}: {page.get('title', 'Untitled')}")
            
            soup = BeautifulSoup(page['body'], 'html.parser')
            course_id = page.get('course_id', 'unknown')
            page_url = f"{page.get('page_url', '')}"
            
            # Count all images for reporting
            all_images = soup.find_all('img')
            total_images_found += len(all_images)
            
            # Find images within figure tags only
            figures = soup.find_all('figure')
            figure_images = []
            for figure in figures:
                figure_images.extend(figure.find_all('img'))
            
            # Filter out banner images
            non_banner_figure_images = [img for img in figure_images if not self._is_banner_image(img)]
            
            self.logger.info(f"    📊 Found {len(figure_images)} images in figure tags")
            self.logger.info(f"    ✅ Analyzing {len(non_banner_figure_images)} non-banner figure images")
            
            for img in non_banner_figure_images:
                result = self._analyze_image_alt_text(img, page, page_url)
                if result:
                    compliance_results.append(result)
                    figure_images_analyzed += 1

        self.logger.info(f"📊 Analysis Complete: {figure_images_analyzed} images analyzed")
        return compliance_results
    
    def _is_likely_decorative(self, img: Tag, alt_text: str) -> bool:
        """Determine if image is likely decorative based on context"""
        # Check for decorative indicators in classes
        classes = img.get('class', [])
        if any('decorative' in str(cls).lower() for cls in classes):
            return True
        
        # Check alt text for decorative indicators
        if alt_text.lower().strip() in ['', 'decorative', 'decoration', 'ornament']:
            return True
        
        # Check src for common decorative patterns
        src = img.get('src', '').lower()
        decorative_patterns = ['icon', 'bullet', 'arrow', 'divider', 'spacer', 'border']
        return any(pattern in src for pattern in decorative_patterns)
    
    def _is_banner_image(self, img: Tag) -> bool:
        """Check if image is a banner (should be excluded from analysis)"""
        # Check if image is within a banner container
        parent = img.parent
        while parent:
            if parent.name == 'div' and 'img-header' in parent.get('class', []):
                return True
            parent = parent.parent
        
        # Check for banner-related attributes
        classes = img.get('class', [])
        if any('banner' in str(cls).lower() for cls in classes):
            return True
        
        # Check src for banner patterns
        src = img.get('src', '').lower()
        return 'banner' in src or 'header' in src
    
    def _is_good_alt_text(self, alt_text: str) -> bool:
        """Check if alt text follows good practices"""
        if not alt_text or len(alt_text.strip()) < 3:
            return False
        
        # Avoid generic terms
        generic_terms = ['image', 'picture', 'photo', 'graphic', 'img']
        alt_lower = alt_text.lower().strip()
        
        if alt_lower in generic_terms:
            return False
        
        # Good alt text should be descriptive but not too long
        return 3 <= len(alt_text.strip()) <= 125
    
    def _is_decorative_alt_text(self, alt_text: str) -> bool:
        """Check if alt text indicates decorative image"""
        decorative_indicators = ['', 'decorative', 'decoration', 'ornament']
        return alt_text.lower().strip() in decorative_indicators
    
    def _analyze_image_alt_text(self, img: Tag, page: Dict, page_url: str) -> Optional[Dict]:
        """Analyze individual image for alt text compliance"""
        
        alt_text = img.get('alt', '')
        src = img.get('src', '')
        
        result = {
            'page_title': page.get('title', 'Unknown'),
            'page_url': page_url,
            'image_src': src,
            'alt_text': alt_text,
            'has_alt_attribute': img.has_attr('alt'),
            'alt_text_length': len(alt_text) if alt_text else 0,
            'is_likely_decorative': self._is_likely_decorative(img, alt_text),
            'compliance_status': 'unknown',
            'compliance_details': [],
            'recommendations': [],
            'confidence': 'high',
            'severity': 'medium'
        }
        
        # Analyze alt text compliance
        compliance_check = self._check_alt_text_compliance(img, alt_text, result['is_likely_decorative'])
        result.update(compliance_check)
        
        return result
    
    def _check_alt_text_compliance(self, img: Tag, alt_text: str, is_decorative: bool) -> Dict:
        """Check if alt text complies with accessibility standards"""
        compliance = {
            'compliance_status': 'unknown',
            'compliance_details': [],
            'recommendations': [],
            'confidence': 'high',
            'severity': 'medium'
        }
        
        has_alt_attr = img.has_attr('alt')
        
        if not has_alt_attr:
            compliance.update({
                'compliance_status': 'missing',
                'compliance_details': ['Missing alt attribute entirely'],
                'recommendations': ['Add alt attribute to image'],
                'severity': 'high'
            })
            return compliance
        
        if is_decorative:
            # Decorative images should have empty alt text
            if alt_text == '':
                compliance.update({
                    'compliance_status': 'good_quality',
                    'compliance_details': ['Correctly marked as decorative with empty alt text'],
                    'severity': 'low'
                })
            elif alt_text.lower().strip() in ['decorative', 'decoration']:
                compliance.update({
                    'compliance_status': 'good_quality',
                    'compliance_details': ['Correctly marked as decorative'],
                    'severity': 'low'
                })
            else:
                compliance.update({
                    'compliance_status': 'poor_quality',
                    'compliance_details': ['Decorative image has unnecessary alt text'],
                    'recommendations': ['Remove alt text for decorative images (use alt="")'],
                    'severity': 'medium'
                })
        else:
            # Non-decorative images need descriptive alt text
            if alt_text == '':
                compliance.update({
                    'compliance_status': 'empty_non_decorative',
                    'compliance_details': ['Informative image missing alt text'],
                    'recommendations': ['Add descriptive alt text explaining what the image shows'],
                    'severity': 'high'
                })
            elif len(alt_text.strip()) < 3:
                compliance.update({
                    'compliance_status': 'poor_quality',
                    'compliance_details': ['Alt text too short to be descriptive'],
                    'recommendations': ['Provide more detailed alt text'],
                    'severity': 'medium'
                })
            elif len(alt_text.strip()) > 125:
                compliance.update({
                    'compliance_status': 'poor_quality',
                    'compliance_details': ['Alt text very long (consider using caption instead)'],
                    'recommendations': ['Shorten alt text to essential information'],
                    'severity': 'medium'
                })
            elif self._has_poor_alt_text_patterns(alt_text):
                compliance.update({
                    'compliance_status': 'poor_quality',
                    'compliance_details': ['Alt text uses generic terms'],
                    'recommendations': ['Use specific, descriptive language instead of generic terms'],
                    'severity': 'medium'
                })
            else:
                compliance.update({
                    'compliance_status': 'good_quality',
                    'compliance_details': ['Good descriptive alt text'],
                    'severity': 'low'
                })
        
        return compliance
    
    def _has_poor_alt_text_patterns(self, alt_text: str) -> bool:
        """Check for poor alt text patterns"""
        poor_patterns = [
            'image', 'picture', 'photo', 'graphic', 'img', 'icon',
            'click here', 'link to', 'image of', 'picture of'
        ]
        
        alt_lower = alt_text.lower().strip()
        
        # Check if alt text is exactly a poor pattern
        if alt_lower in poor_patterns:
            return True
        
        # Check if alt text starts with poor patterns
        for pattern in ['image of', 'picture of', 'photo of']:
            if alt_lower.startswith(pattern):
                return True
        
        return False

def categorize_findings(compliance_results: List[Dict]) -> Dict[str, List[Dict]]:
    """Categorize findings into safe actions vs manual review"""
    
    safe_actions = []
    manual_review = []
    
    for result in compliance_results:
        status = result.get('compliance_status', '')
        severity = result.get('severity', 'medium')
        
        # Define what constitutes a "safe action" for alt text
        # Safe actions are clear-cut improvements with low risk
        if status == 'good_quality':
            # Already compliant - no action needed
            continue
        elif status == 'missing' and severity == 'high':
            # Missing alt attributes are clear violations
            safe_actions.append({
                **result,
                'action_type': 'add_alt_attribute',
                'recommended_action': 'Add alt attribute with appropriate descriptive text',
                'confidence_level': 'high'
            })
        elif status == 'empty_non_decorative' and not result.get('is_likely_decorative', False):
            # Informative images missing alt text
            safe_actions.append({
                **result,
                'action_type': 'add_descriptive_alt',
                'recommended_action': 'Add descriptive alt text for this informative image',
                'confidence_level': 'high'
            })
        else:
            # Complex cases requiring human judgment
            manual_review.append({
                **result,
                'action_type': 'review_and_improve',
                'recommended_action': f"Review and improve: {result.get('recommendations', ['Manual review needed'])[0] if result.get('recommendations') else 'Manual review needed'}",
                'confidence_level': 'medium'
            })
    
    return {
        'safe_actions': safe_actions,
        'requires_manual_review': manual_review
    }

def generate_enhanced_analysis_output(compliance_results: List[Dict], design_standards: Dict, course_info: Dict) -> Dict:
    """Generate enhanced analysis output in LTI-compatible JSON format"""
    
    # Calculate statistics
    total = len(compliance_results)
    good_quality = len([r for r in compliance_results if r.get('compliance_status') == 'good_quality'])
    poor_quality = len([r for r in compliance_results if r.get('compliance_status') == 'poor_quality'])
    missing_empty = len([r for r in compliance_results if r.get('compliance_status') in ['missing', 'empty_non_decorative']])
    
    # Categorize findings
    categorized = categorize_findings(compliance_results)
    
    # Calculate compliance rate
    compliant_count = good_quality
    compliance_rate = (compliant_count / total * 100) if total > 0 else 100
    
    # Risk assessment
    high_severity = len([r for r in compliance_results if r.get('severity') == 'high'])
    medium_severity = len([r for r in compliance_results if r.get('severity') == 'medium'])
    
    enhanced_output = {
        "phase": 2,
        "mode": "preview_first",
        "analysis_complete": True,
        "summary": {
            "course_info": course_info,
            "total_images_analyzed": total,
            "compliance_rate": round(compliance_rate, 1),
            "good_quality_count": good_quality,
            "issues_found": poor_quality + missing_empty,
            "safe_actions_count": len(categorized['safe_actions']),
            "manual_review_count": len(categorized['requires_manual_review'])
        },
        "findings": {
            "safe_actions": categorized['safe_actions'],
            "requires_manual_review": categorized['requires_manual_review']
        },
        "risk_assessment": {
            "high_severity_issues": high_severity,
            "medium_severity_issues": medium_severity,
            "accessibility_impact": "Medium" if missing_empty > 0 else "Low",
            "compliance_status": "Good" if compliance_rate >= 80 else "Needs Improvement"
        },
        "design_standards": {
            "good_examples_found": len(design_standards.get('good_alt_text_examples', [])),
            "decorative_examples_found": len(design_standards.get('decorative_examples', [])),
            "standards_source": "ACU Online Design Library (Course 26333)"
        },
        "metadata": {
            "analysis_timestamp": datetime.now().isoformat(),
            "scope": "Images within figure tags only (banners excluded)",
            "methodology": "ACU accessibility standards compliance check"
        }
    }
    
    return enhanced_output

def fetch_course_pages_parallel(canvas_api: CanvasAPIConnector, course_ids: List[str]) -> Dict[str, List[Dict]]:
    """Fetch pages from multiple courses in parallel"""
    
    def fetch_single_course(course_id: str) -> Tuple[str, List[Dict]]:
        """Fetch pages for a single course"""
        pages = canvas_api.get_course_pages(course_id)
        return course_id, pages
    
    results = {}
    
    # Use ThreadPoolExecutor for parallel Canvas API calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        # Submit tasks for parallel execution
        future_to_course = {
            executor.submit(fetch_single_course, course_id): course_id 
            for course_id in course_ids
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_course):
            course_id = future_to_course[future]
            try:
                returned_course_id, pages = future.result()
                results[returned_course_id] = pages
                canvas_api.logger.info(f"✓ Completed fetching pages for Course {returned_course_id}")
            except Exception as exc:
                canvas_api.logger.error(f"❌ Course {course_id} generated an exception: {exc}")
                results[course_id] = []  # Empty list on failure
    
    return results

def main():
    """Main execution function with LTI integration support and parallel processing"""
    
    parser = argparse.ArgumentParser(description='Canvas Alt Text Compliance Checker - LTI Enhanced')
    parser.add_argument('--canvas-url', required=True, help='Canvas base URL')
    parser.add_argument('--api-token', required=True, help='Canvas API token')
    parser.add_argument('--course-id', required=True, help='Course ID to analyze')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze, do not execute')
    parser.add_argument('--execute-approved', type=str, help='Execute approved actions from JSON file')
    
    args = parser.parse_args()
    
    try:
        progress = ProgressReporter(enabled=True)
        if args.execute_approved:
            print("❌ Execute mode not implemented yet. Alt text fixes require manual intervention.")
            sys.exit(1)
        
        # Initialize Canvas connection
        canvas_api = CanvasAPIConnector(args.canvas_url, args.api_token)
        
        if not canvas_api.validate_connection():
            print("❌ Canvas API connection failed.")
            sys.exit(1)
        
        progress.update(step="initialize", message="Preparing analysis")
        progress.update(step="fetch_courses", current=0, total=2, message="Fetching target & design library")
        
        # Fetch both courses in parallel
        start_time = time.time()
        course_data = fetch_course_pages_parallel(
            canvas_api, 
            [args.course_id, '26333']
        )
        fetch_time = time.time() - start_time
        
        # Extract results
        course_pages = course_data.get(args.course_id, [])
        design_library_pages = course_data.get('26333', [])
        
        progress.update(step="fetch_courses", current=2, total=2, message=f"Fetch complete in {fetch_time:.1f}s")
        
        if not course_pages:
            print(f"❌ Could not access Course {args.course_id}")
            sys.exit(1)
        
        if not design_library_pages:
            print("⚠️  Could not access ACU Online Design Library - continuing with fallback standards")
        
        # Perform analysis
        progress.update(step="analyze_course", current=0, total=len(course_pages) or 1, message="Analyzing course content")
        analyzer = AltTextAnalyzer()
        
        # Process design standards and course analysis in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both analysis tasks
            if design_library_pages:
                standards_future = executor.submit(analyzer.extract_design_standards, design_library_pages)
            else:
                standards_future = None
                
            # Wrap analysis to emit per-page progress
            def analyze_with_progress(pages, course_label):
                results = []
                total = len(pages) or 1
                for idx, _ in enumerate(pages, 1):
                    progress.update(step="analyze_course", current=idx-1, total=total, message=f"Analyzing page {idx}/{total}")
                # Use existing analyzer method once to compute full results
                results = analyzer.analyze_content_compliance(pages, course_label)
                progress.update(step="analyze_course", current=total, total=total, message="Analysis complete")
                return results

            compliance_future = executor.submit(analyze_with_progress, course_pages, f"Course {args.course_id}")
            
            # Collect results
            if standards_future:
                design_standards = standards_future.result()
            else:
                design_standards = {'good_alt_text_examples': [], 'decorative_examples': []}
                
            compliance_results = compliance_future.result()
        
        # Generate enhanced output
        course_info = {
            'course_id': args.course_id,
            'name': f"Course {args.course_id}",
            'pages_analyzed': len(course_pages),
            'processing_time_seconds': round(fetch_time, 1)
        }
        
        enhanced_output = generate_enhanced_analysis_output(
            compliance_results, 
            design_standards, 
            course_info
        )
        
        # Output for LTI integration
        progress.done({"summary": enhanced_output.get("summary", {})})
        print("ENHANCED_ANALYSIS_JSON:", json.dumps(enhanced_output, indent=2))
        
    except KeyboardInterrupt:
        print("\n⏹️  Analysis interrupted by user.")
        sys.exit(1)
    except Exception as e:
        progress.error(str(e))
        print(f"❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
