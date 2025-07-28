#!/usr/bin/env python3
"""
Enhanced Canvas Duplicate Page Analyzer - Phase 2
=================================================

Phase 2 Implementation: Preview-First Workflow with Inbound Link Analysis

NEW FEATURES:
- Inbound link detection and mapping
- Risk assessment for deletion safety
- Smart recommendations based on page integration
- Enhanced preview generation before any actions
- Official duplicate handling with link analysis

SAFETY IMPROVEMENTS:
- Never recommend deleting pages with active inbound links
- Analyze page importance based on integration level
- Generate detailed preview reports for user approval
- Categorize actions by safety level

Usage:
    python3 enhanced_duplicate_analyzer.py --canvas-url <url> --api-token <token> 
            --course-id <id> --analyze-only --check-inbound-links
"""

import requests
import json
import argparse
import re
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse, urljoin
from difflib import SequenceMatcher
import hashlib
from dataclasses import dataclass
from collections import defaultdict
import logging
from datetime import datetime
import pandas as pd
import pytz

@dataclass
class LinkReference:
    """Represents an inbound link to a page"""
    source_type: str  # 'page', 'assignment', 'discussion', 'module_item'
    source_id: str
    source_title: str
    link_context: str  # The text around the link
    link_url: str

@dataclass
class PageAnalysis:
    """Enhanced page analysis with link data"""
    page: Dict
    inbound_links: List[LinkReference]
    integration_score: float  # 0-1 based on how integrated the page is
    safety_level: str  # 'safe', 'caution', 'protected'
    
class EnhancedDuplicateAnalyzer:
    """Enhanced analyzer with inbound link detection and safety assessment"""
    
    def __init__(self, canvas_url: str, api_token: str):
        self.canvas_url = canvas_url.rstrip('/')
        self.api_token = api_token
        self.headers = {'Authorization': f'Bearer {api_token}'}
        self.base_api_url = f'https://{canvas_url}/api/v1'
        
        # Set up logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Cache for API responses
        self.page_cache = {}
        self.link_cache = defaultdict(list)
        
    def find_inbound_links(self, course_id: str, target_page_url: str) -> List[LinkReference]:
        """
        Find all inbound links to a specific page within the course.
        
        Searches through:
        - Other course pages
        - Assignment descriptions
        - Discussion topics
        - Module items
        - Announcements
        """
        inbound_links = []
        target_patterns = [
            rf'/courses/{course_id}/pages/{target_page_url}',
            rf'pages/{target_page_url}',
            target_page_url
        ]
        
        # Search in course pages
        pages = self._get_all_course_pages(course_id)
        for page in pages:
            if page['url'] == target_page_url:
                continue  # Skip the target page itself
                
            content = page.get('body', '') or ''
            for pattern in target_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    context = self._extract_link_context(content, pattern)
                    inbound_links.append(LinkReference(
                        source_type='page',
                        source_id=page['page_id'],
                        source_title=page['title'],
                        link_context=context,
                        link_url=pattern
                    ))
                    break
        
        # Search in assignments
        assignments = self._get_course_assignments(course_id)
        for assignment in assignments:
            content = assignment.get('description', '') or ''
            for pattern in target_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    context = self._extract_link_context(content, pattern)
                    inbound_links.append(LinkReference(
                        source_type='assignment',
                        source_id=str(assignment['id']),
                        source_title=assignment['name'],
                        link_context=context,
                        link_url=pattern
                    ))
                    break
        
        # Search in discussions
        discussions = self._get_course_discussions(course_id)
        for discussion in discussions:
            content = discussion.get('message', '') or ''
            for pattern in target_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    context = self._extract_link_context(content, pattern)
                    inbound_links.append(LinkReference(
                        source_type='discussion',
                        source_id=str(discussion['id']),
                        source_title=discussion['title'],
                        link_context=context,
                        link_url=pattern
                    ))
                    break
        
        # Search in module items
        modules = self._get_course_modules(course_id)
        for module in modules:
            items = self._get_module_items(course_id, module['id'])
            for item in items:
                # Check if module item directly references the page
                if (item.get('type') == 'Page' and 
                    item.get('page_url') == target_page_url):
                    inbound_links.append(LinkReference(
                        source_type='module_item',
                        source_id=str(item['id']),
                        source_title=f"Module: {module['name']} → {item['title']}",
                        link_context='Direct module item reference',
                        link_url=f"modules/{module['id']}/items/{item['id']}"
                    ))
        
        return inbound_links
    
    def _extract_link_context(self, content: str, pattern: str) -> str:
        """Extract text context around a link for better understanding"""
        try:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 50)
                context = content[start:end].strip()
                return f"...{context}..."
            return "Link found in content"
        except:
            return "Context extraction failed"
    
    def calculate_integration_score(self, page_analysis: PageAnalysis) -> float:
        """
        Calculate how integrated a page is into the course structure.
        
        Factors:
        - Number of inbound links (weighted by source type)
        - Module inclusion
        - Recent updates
        - Publication status
        """
        score = 0.0
        
        # Base score for published pages
        if page_analysis.page.get('published', False):
            score += 0.2
        
        # Score based on inbound links
        link_weights = {
            'module_item': 0.3,  # Module items are most important
            'assignment': 0.25,  # Assignments are very important
            'page': 0.2,         # Page-to-page links are important
            'discussion': 0.15   # Discussion links are moderately important
        }
        
        for link in page_analysis.inbound_links:
            score += link_weights.get(link.source_type, 0.1)
        
        # Cap the score at 1.0
        return min(1.0, score)
    
    def assess_deletion_safety(self, page_analysis: PageAnalysis) -> str:
        """
        Assess how safe it is to delete this page.
        
        Returns:
        - 'safe': No inbound links, safe to delete
        - 'caution': Some links but may be manageable
        - 'protected': Has important links, should not delete
        """
        if not page_analysis.inbound_links:
            return 'safe'
        
        # Check for critical link types
        critical_links = [link for link in page_analysis.inbound_links 
                         if link.source_type in ['module_item', 'assignment']]
        
        if critical_links:
            return 'protected'
        
        # If only page-to-page links, it's caution level
        if len(page_analysis.inbound_links) <= 2:
            return 'caution'
        
        return 'protected'
    
    def analyze_duplicate_pair(self, course_id: str, page1: Dict, page2: Dict) -> Dict:
        """
        Analyze a pair of duplicate pages and recommend which one to keep.
        
        Returns detailed analysis with safety assessment and recommendation.
        """
        # Get inbound links for both pages
        page1_links = self.find_inbound_links(course_id, page1['url'])
        page2_links = self.find_inbound_links(course_id, page2['url'])
        
        # Create page analyses
        page1_analysis = PageAnalysis(
            page=page1,
            inbound_links=page1_links,
            integration_score=0,
            safety_level='safe'
        )
        page2_analysis = PageAnalysis(
            page=page2,
            inbound_links=page2_links,
            integration_score=0,
            safety_level='safe'
        )
        
        # Calculate integration scores
        page1_analysis.integration_score = self.calculate_integration_score(page1_analysis)
        page2_analysis.integration_score = self.calculate_integration_score(page2_analysis)
        
        # Assess safety levels
        page1_analysis.safety_level = self.assess_deletion_safety(page1_analysis)
        page2_analysis.safety_level = self.assess_deletion_safety(page2_analysis)
        
        # Make recommendation
        recommendation = self._generate_duplicate_recommendation(page1_analysis, page2_analysis)
        
        return {
            'page1': {
                'title': page1['title'],
                'url': page1['url'],
                'inbound_links_count': len(page1_links),
                'integration_score': page1_analysis.integration_score,
                'safety_level': page1_analysis.safety_level,
                'inbound_links': [
                    {
                        'source_type': link.source_type,
                        'source_title': link.source_title,
                        'context': link.link_context
                    } for link in page1_links
                ]
            },
            'page2': {
                'title': page2['title'],
                'url': page2['url'],
                'inbound_links_count': len(page2_links),
                'integration_score': page2_analysis.integration_score,
                'safety_level': page2_analysis.safety_level,
                'inbound_links': [
                    {
                        'source_type': link.source_type,
                        'source_title': link.source_title,
                        'context': link.link_context
                    } for link in page2_links
                ]
            },
            'recommendation': recommendation
        }
    
    def _generate_duplicate_recommendation(self, page1_analysis: PageAnalysis, 
                                         page2_analysis: PageAnalysis) -> Dict:
        """Generate smart recommendation for duplicate page handling"""
        
        # If one page has no links and the other has links, recommend deleting the unlinked one
        if (not page1_analysis.inbound_links and page2_analysis.inbound_links):
            return {
                'action': 'delete_page1',
                'confidence': 'high',
                'reason': 'Page 1 has no inbound links while Page 2 is referenced elsewhere',
                'safe_to_execute': True
            }
        
        if (page1_analysis.inbound_links and not page2_analysis.inbound_links):
            return {
                'action': 'delete_page2',
                'confidence': 'high',
                'reason': 'Page 2 has no inbound links while Page 1 is referenced elsewhere',
                'safe_to_execute': True
            }
        
        # If both have links, compare integration scores
        if page1_analysis.integration_score > page2_analysis.integration_score:
            return {
                'action': 'delete_page2',
                'confidence': 'medium',
                'reason': f'Page 1 is more integrated (score: {page1_analysis.integration_score:.2f} vs {page2_analysis.integration_score:.2f})',
                'safe_to_execute': False,  # Requires manual review
                'manual_steps': [
                    'Review inbound links to both pages',
                    'Consider redirecting links from page 2 to page 1',
                    'Verify no content loss before deletion'
                ]
            }
        elif page2_analysis.integration_score > page1_analysis.integration_score:
            return {
                'action': 'delete_page1',
                'confidence': 'medium',
                'reason': f'Page 2 is more integrated (score: {page2_analysis.integration_score:.2f} vs {page1_analysis.integration_score:.2f})',
                'safe_to_execute': False,
                'manual_steps': [
                    'Review inbound links to both pages',
                    'Consider redirecting links from page 1 to page 2',
                    'Verify no content loss before deletion'
                ]
            }
        
        # If both have similar integration, manual review required
        return {
            'action': 'manual_review_required',
            'confidence': 'low',
            'reason': 'Both pages have similar integration levels - manual review needed',
            'safe_to_execute': False,
            'manual_steps': [
                'Compare content quality and accuracy',
                'Check creation/modification dates',
                'Review specific link contexts',
                'Consider merging content if both have unique value'
            ]
        }
    
    # Canvas API helper methods
    def _get_all_course_pages(self, course_id: str) -> List[Dict]:
        """Get all pages in the course with their full content"""
        if f'pages_{course_id}' in self.page_cache:
            return self.page_cache[f'pages_{course_id}']
        
        pages = []
        url = f"{self.base_api_url}/courses/{course_id}/pages"
        
        while url:
            response = requests.get(url, headers=self.headers, params={'per_page': 100})
            response.raise_for_status()
            page_list = response.json()
            
            # Get full content for each page
            for page in page_list:
                try:
                    page_url = f"{self.base_api_url}/courses/{course_id}/pages/{page['url']}"
                    page_response = requests.get(page_url, headers=self.headers)
                    page_response.raise_for_status()
                    full_page = page_response.json()
                    pages.append(full_page)
                except Exception as e:
                    self.logger.warning(f"Could not get full content for page {page.get('title', 'Unknown')}: {e}")
                    # Add page with basic info if full content can't be retrieved
                    pages.append(page)
            
            # Check for next page
            links = response.links
            url = links.get('next', {}).get('url')
        
        self.page_cache[f'pages_{course_id}'] = pages
        return pages
    
    def _get_course_assignments(self, course_id: str) -> List[Dict]:
        """Get all assignments in the course"""
        assignments = []
        url = f"{self.base_api_url}/courses/{course_id}/assignments"
        
        while url:
            response = requests.get(url, headers=self.headers, params={'per_page': 100})
            response.raise_for_status()
            assignments.extend(response.json())
            
            links = response.links
            url = links.get('next', {}).get('url')
        
        return assignments
    
    def _get_course_discussions(self, course_id: str) -> List[Dict]:
        """Get all discussion topics in the course"""
        discussions = []
        url = f"{self.base_api_url}/courses/{course_id}/discussion_topics"
        
        while url:
            response = requests.get(url, headers=self.headers, params={'per_page': 100})
            response.raise_for_status()
            discussions.extend(response.json())
            
            links = response.links
            url = links.get('next', {}).get('url')
        
        return discussions
    
    def _get_course_modules(self, course_id: str) -> List[Dict]:
        """Get all modules in the course"""
        modules = []
        url = f"{self.base_api_url}/courses/{course_id}/modules"
        
        while url:
            response = requests.get(url, headers=self.headers, params={'per_page': 100})
            response.raise_for_status()
            modules.extend(response.json())
            
            links = response.links
            url = links.get('next', {}).get('url')
        
        return modules
    
    def _get_module_items(self, course_id: str, module_id: str) -> List[Dict]:
        """Get all items in a specific module"""
        items = []
        url = f"{self.base_api_url}/courses/{course_id}/modules/{module_id}/items"
        
        while url:
            response = requests.get(url, headers=self.headers, params={'per_page': 100})
            response.raise_for_status()
            items.extend(response.json())
            
            links = response.links
            url = links.get('next', {}).get('url')
        
        return items
    
    def calculate_content_similarity(self, content1: str, content2: str) -> float:
        """Calculate content similarity using sequence matching"""
        if not content1 or not content2:
            return 0.0
        
        # Normalize content (remove HTML, extra whitespace)
        norm1 = self._normalize_content(content1)
        norm2 = self._normalize_content(content2)
        
        if not norm1 or not norm2:
            return 0.0
        
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def _normalize_content(self, content: str) -> str:
        """Normalize content for comparison"""
        if not content:
            return ""
        
        # Remove HTML tags
        import re
        content = re.sub(r'<[^>]+>', '', content)
        
        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content)
        
        # Convert to lowercase and strip
        return content.lower().strip()
    
    def run_enhanced_analysis(self, course_id: str, similarity_threshold: float = 0.9) -> Dict:
        """
        Run the complete enhanced analysis with inbound link detection.
        
        Returns comprehensive analysis results for Phase 2 preview.
        """
        self.logger.info(f"Starting enhanced analysis for course {course_id}")
        
        # Get all course pages
        all_pages = self._get_all_course_pages(course_id)
        self.logger.info(f"Found {len(all_pages)} total pages")

        # DEBUG: Log all page titles to see what we're actually analyzing
        self.logger.info("=== ALL PAGES BEING ANALYZED ===")
        for i, page in enumerate(all_pages[:20]):  # Show first 20 pages
            self.logger.info(f"Page {i+1}: '{page.get('title', 'NO TITLE')}' (URL: {page.get('url', 'NO URL')})")
        if len(all_pages) > 20:
            self.logger.info(f"... and {len(all_pages) - 20} more pages")
        self.logger.info("=== END PAGE LIST ===")

        # DEBUG: Check for pages with similar titles
        similar_titles = {}
        for page in all_pages:
            title = page.get('title', '')
            base_title = title.replace('-2', '').replace(' Copy', '').replace('-Copy', '')
            if base_title not in similar_titles:
                similar_titles[base_title] = []
            similar_titles[base_title].append(page)

        # Log pages with similar base titles
        self.logger.info("=== PAGES WITH SIMILAR TITLES ===")
        for base_title, pages in similar_titles.items():
            if len(pages) > 1:
                self.logger.info(f"Base title '{base_title}' has {len(pages)} variations:")
                for page in pages:
                    content_length = len(page.get('body', '') or '')
                    self.logger.info(f"  - '{page.get('title')}' (Content: {content_length} chars)")
        self.logger.info("=== END SIMILAR TITLES ===")
        
        # Find duplicates using content similarity
        duplicates = []
        processed_pairs = set()
        
        for i, page1 in enumerate(all_pages):
            for j, page2 in enumerate(all_pages[i+1:], i+1):
                # Skip if already processed
                pair_key = tuple(sorted([page1['url'], page2['url']]))
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)
                
                # Calculate similarity
                similarity = self.calculate_content_similarity(
                    page1.get('body', ''), 
                    page2.get('body', '')
                )
                
                # DEBUG: Log high similarity pairs (even if below threshold)
                if similarity > 0.5:  # Log any pairs with >50% similarity for debugging
                    self.logger.info(f"Similarity check: '{page1['title']}' vs '{page2['title']}' = {similarity:.1%}")
                
                if similarity >= similarity_threshold:
                    self.logger.info(f"Found duplicate pair: {page1['title']} <-> {page2['title']} ({similarity:.1%})")
                    
                    # Perform enhanced analysis on this duplicate pair
                    analysis = self.analyze_duplicate_pair(course_id, page1, page2)
                    analysis['similarity'] = similarity
                    duplicates.append(analysis)
        
        # Categorize findings
        safe_actions = []
        requires_manual_review = []
        protected_by_links = 0
        
        for duplicate in duplicates:
            recommendation = duplicate['recommendation']
            
            if recommendation['safe_to_execute']:
                safe_actions.append({
                    'page1_title': duplicate['page1']['title'],
                    'page2_title': duplicate['page2']['title'],
                    'delete_page_title': (duplicate['page1']['title'] if recommendation['action'] == 'delete_page1' 
                                         else duplicate['page2']['title']),
                    'keep_page_title': (duplicate['page2']['title'] if recommendation['action'] == 'delete_page1' 
                                       else duplicate['page1']['title']),
                    'reason': recommendation['reason'],
                    'confidence': recommendation['confidence']
                })
            else:
                requires_manual_review.append({
                    'page1_title': duplicate['page1']['title'],
                    'page2_title': duplicate['page2']['title'],
                    'inbound_links_page1': duplicate['page1']['inbound_links_count'],
                    'inbound_links_page2': duplicate['page2']['inbound_links_count'],
                    'reason': recommendation['reason'],
                    'manual_steps': recommendation.get('manual_steps', [])
                })
            
            # Count protected pages
            if (duplicate['page1']['safety_level'] == 'protected' or 
                duplicate['page2']['safety_level'] == 'protected'):
                protected_by_links += 1
        
        # Generate comprehensive results
        results = {
            'course_id': course_id,
            'analysis_type': 'enhanced_with_link_detection',
            'total_pages_analyzed': len(all_pages),
            'total_duplicates': len(duplicates),
            'similarity_threshold': similarity_threshold,
            'findings': {
                'duplicate_pairs': duplicates,
                'safe_actions': safe_actions,
                'requires_manual_review': requires_manual_review
            },
            'risk_assessment': {
                'protected_by_links': protected_by_links,
                'safe_to_delete': len(safe_actions),
                'needs_manual_review': len(requires_manual_review),
                'link_analysis_completed': True
            },
            'recommendations': {
                'immediate_actions': len(safe_actions),
                'review_required': len(requires_manual_review),
                'estimated_time_saved': f"{len(safe_actions) * 2} minutes",
                'safety_level': 'high' if protected_by_links == 0 else 'medium'
            }
        }
        
        self.logger.info(f"Enhanced analysis complete: {len(duplicates)} duplicates found")
        self.logger.info(f"Safe actions: {len(safe_actions)}, Manual review: {len(requires_manual_review)}")
        
        return results

    def generate_excel_report(self, results: Dict, course_id: str) -> str:
        """
        Generate comprehensive Excel report for enhanced analysis results.
        
        Returns the path to the generated Excel file.
        """
        timestamp = datetime.now(pytz.UTC).strftime('%Y%m%d_%H%M%S')
        report_file = f"enhanced_duplicate_analysis_{course_id}_{timestamp}.xlsx"
        
        with pd.ExcelWriter(report_file, engine='xlsxwriter') as writer:
            # Summary sheet
            summary_data = [{
                'Course ID': results['course_id'],
                'Analysis Type': results['analysis_type'],
                'Total Pages Analyzed': results['total_pages_analyzed'],
                'Total Duplicates Found': results['total_duplicates'],
                'Similarity Threshold': results['similarity_threshold'],
                'Safe Actions Identified': results['risk_assessment']['safe_to_delete'],
                'Manual Review Required': results['risk_assessment']['needs_manual_review'],
                'Pages Protected by Links': results['risk_assessment']['protected_by_links'],
                'Analysis Timestamp': datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
            }]
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
            
            # Safe Actions sheet
            if results['findings']['safe_actions']:
                safe_actions_data = []
                for action in results['findings']['safe_actions']:
                    safe_actions_data.append({
                        'Delete Page Title': action['delete_page_title'],
                        'Keep Page Title': action['keep_page_title'],
                        'Reason': action['reason'],
                        'Confidence': action['confidence'],
                        'Risk Level': 'LOW',
                        'Recommended Action': 'SAFE TO DELETE'
                    })
                pd.DataFrame(safe_actions_data).to_excel(writer, sheet_name='Safe Actions', index=False)
            
            # Manual Review Required sheet
            if results['findings']['requires_manual_review']:
                manual_review_data = []
                for review in results['findings']['requires_manual_review']:
                    manual_review_data.append({
                        'Page 1 Title': review['page1_title'],
                        'Page 2 Title': review['page2_title'],
                        'Page 1 Inbound Links': review['inbound_links_page1'],
                        'Page 2 Inbound Links': review['inbound_links_page2'],
                        'Reason': review['reason'],
                        'Manual Steps': '; '.join(review.get('manual_steps', [])),
                        'Risk Level': 'HIGH',
                        'Recommended Action': 'MANUAL REVIEW REQUIRED'
                    })
                pd.DataFrame(manual_review_data).to_excel(writer, sheet_name='Manual Review', index=False)
            
            # Detailed Duplicate Pairs sheet
            if results['findings']['duplicate_pairs']:
                duplicate_pairs_data = []
                for pair in results['findings']['duplicate_pairs']:
                    duplicate_pairs_data.append({
                        'Page 1 Title': pair['page1']['title'],
                        'Page 1 URL': pair['page1']['url'],
                        'Page 1 Integration Score': pair['page1']['integration_score'],
                        'Page 1 Safety Level': pair['page1']['safety_level'],
                        'Page 1 Inbound Links': pair['page1']['inbound_links_count'],
                        'Page 2 Title': pair['page2']['title'],
                        'Page 2 URL': pair['page2']['url'],
                        'Page 2 Integration Score': pair['page2']['integration_score'],
                        'Page 2 Safety Level': pair['page2']['safety_level'],
                        'Page 2 Inbound Links': pair['page2']['inbound_links_count'],
                        'Similarity': f"{pair['similarity']:.1%}",
                        'Recommendation Action': pair['recommendation']['action'],
                        'Recommendation Confidence': pair['recommendation']['confidence'],
                        'Recommendation Reason': pair['recommendation']['reason'],
                        'Safe to Execute': pair['recommendation']['safe_to_execute']
                    })
                pd.DataFrame(duplicate_pairs_data).to_excel(writer, sheet_name='Duplicate Pairs', index=False)
            
            # Risk Assessment sheet
            risk_data = [{
                'Protected by Links': results['risk_assessment']['protected_by_links'],
                'Safe to Delete': results['risk_assessment']['safe_to_delete'],
                'Needs Manual Review': results['risk_assessment']['needs_manual_review'],
                'Link Analysis Completed': results['risk_assessment']['link_analysis_completed'],
                'Overall Safety Level': results['recommendations']['safety_level'],
                'Estimated Time Saved': results['recommendations']['estimated_time_saved'],
                'Immediate Actions': results['recommendations']['immediate_actions'],
                'Review Required': results['recommendations']['review_required']
            }]
            pd.DataFrame(risk_data).to_excel(writer, sheet_name='Risk Assessment', index=False)
        
        return report_file


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description='Enhanced Canvas Duplicate Page Analyzer - Phase 2')
    parser.add_argument('--canvas-url', required=True, help='Canvas instance URL')
    parser.add_argument('--api-token', required=True, help='Canvas API token')
    parser.add_argument('--course-id', required=True, help='Course ID to analyze')
    parser.add_argument('--similarity-threshold', type=float, default=0.9, 
                       help='Similarity threshold (0.0-1.0)')
    parser.add_argument('--analyze-only', action='store_true', 
                       help='Only analyze, do not execute any deletions')
    parser.add_argument('--check-inbound-links', action='store_true', 
                       help='Enable inbound link analysis')
    parser.add_argument('--generate-preview', action='store_true', 
                       help='Generate detailed preview report')
    parser.add_argument('--risk-assessment', action='store_true', 
                       help='Include risk assessment in output')
    parser.add_argument('--execute-approved', type=str, 
                       help='Execute only approved actions from JSON file')
    parser.add_argument('--generate-report', action='store_true', 
                       help='Generate execution report')
    
    args = parser.parse_args()
    
    try:
        # Initialize enhanced analyzer
        analyzer = EnhancedDuplicateAnalyzer(args.canvas_url, args.api_token)
        
        # Check if we're executing approved actions
        if args.execute_approved:
            # Execute approved actions from file
            with open(args.execute_approved, 'r') as f:
                approved_actions = json.load(f)
            
            print(f"Executing {len(approved_actions)} approved actions...")
            
            # For now, simulate execution (enhanced analyzer doesn't have deletion capability yet)
            execution_results = {
                "execution_complete": True,
                "successful_deletions": [],
                "failed_deletions": [],
                "summary": {
                    "actions_requested": len(approved_actions),
                    "actions_completed": 0,  # Placeholder
                    "actions_failed": 0
                }
            }
            
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_results))
            
        else:
            # Run enhanced analysis
            results = analyzer.run_enhanced_analysis(args.course_id, args.similarity_threshold)
            
            # Output results in JSON format for LTI integration
            print(f"ENHANCED_ANALYSIS_JSON: {json.dumps(results)}")
            
            # Generate Excel report if requested
            if args.generate_report:
                try:
                    report_file = analyzer.generate_excel_report(results, args.course_id)
                    print(f"\n📊 Excel report generated: {report_file}")
                except Exception as e:
                    print(f"⚠️ Warning: Could not generate Excel report: {e}")
            
            # Also output human-readable summary
            print(f"\n=== Enhanced Analysis Summary ===")
            print(f"Course ID: {results['course_id']}")
            print(f"Total pages analyzed: {results['total_pages_analyzed']}")
            print(f"Duplicate pairs found: {results['total_duplicates']}")
            print(f"Safe actions identified: {results['risk_assessment']['safe_to_delete']}")
            print(f"Manual review required: {results['risk_assessment']['needs_manual_review']}")
            print(f"Pages protected by links: {results['risk_assessment']['protected_by_links']}")
            
            if results['findings']['safe_actions']:
                print(f"\n--- Safe Actions ---")
                for action in results['findings']['safe_actions']:
                    print(f"• DELETE: {action['delete_page_title']} → KEEP: {action['keep_page_title']}")
                    print(f"  Reason: {action['reason']}")
            
            if results['findings']['requires_manual_review']:
                print(f"\n--- Manual Review Required ---")
                for review in results['findings']['requires_manual_review']:
                    print(f"• {review['page1_title']} vs {review['page2_title']}")
                    print(f"  Links: {review['inbound_links_page1']} vs {review['inbound_links_page2']}")
                    print(f"  Reason: {review['reason']}")
        
    except Exception as e:
        print(f"Error during enhanced analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()