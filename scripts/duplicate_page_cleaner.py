"""
Canvas Duplicate Page Cleaner

Identifies official module pages, finds and auto-deletes exact and orphaned duplicates, flags similar and official duplicates for review, and generates a consolidated traceability report.

Usage: Run per course to clean up rollover and other duplicates.

Features:
- Identifies all pages included in modules as "official pages".
- Finds and auto-deletes orphaned pages (not in modules) that are 100% identical to any official page.
- Finds and auto-deletes duplicate orphaned pages (not matching any official page), keeping the best one based on:
    1. Published status (keep published over unpublished)
    2. If same, keep the most recently created or modified page
- Flags for review any orphaned pages that are highly similar (above threshold) to official pages.
- Flags for review any official pages that are 100% identical to each other (official duplicates).
- Generates a single consolidated Excel report with:
    - Summary
    - Auto-Delete List
    - Review List
    - Official Duplicates
    - Orphaned Duplicates (auto-deleted)
    - Deleted Pages
    - Failed Deletions
    - Preserved Official Pages

See handover notes at the end of the script for more details.
"""

import requests
from typing import Optional, Dict, List, Tuple
import logging
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import pytz
import json
import re
import hashlib
from difflib import SequenceMatcher
import concurrent.futures
import argparse
import sys

class CanvasDuplicateCleaner:
    def __init__(self, base_url: str, api_token: str):
        """Initialize Canvas Duplicate Cleaner."""
        self.base_url = f"https://{base_url}".rstrip('/')
        self.api_url = f"{self.base_url}/api/v1"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        # Analysis results
        self.official_pages = []
        self.orphaned_pages = []
        self.exact_duplicates = []
        self.similar_pages = []
        self.deleted_pages = []

    def make_request(self, endpoint: str, params: Optional[Dict] = None) -> any:
        """Make Canvas API request with pagination."""
        if params is None:
            params = {}
        
        params['per_page'] = 100
        url = f"{self.api_url}/{endpoint}"
        
        try:
            results = []
            while url:
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                
                data = response.json()
                if isinstance(data, list):
                    results.extend(data)
                else:
                    return data
                
                url = response.links.get('next', {}).get('url')
                params = {}
            
            return results
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed: {str(e)}")
            raise

    def get_official_pages(self, course_id: str) -> List[Dict]:
        """Get all pages that are organized in modules (official pages)."""
        self.logger.info("Identifying official module pages...")
        
        modules = self.make_request(f"courses/{course_id}/modules")
        official_page_urls = set()
        
        for module in modules:
            try:
                items = self.make_request(f"courses/{course_id}/modules/{module['id']}/items")
                for item in items:
                    if item['type'] == 'Page' and 'page_url' in item:
                        official_page_urls.add(item['page_url'])
            except Exception as e:
                self.logger.warning(f"Could not get items for module {module['name']}: {str(e)}")
        
        # Get full page details for official pages
        official_pages = []
        for page_url in official_page_urls:
            try:
                page = self.make_request(f"courses/{course_id}/pages/{page_url}")
                page['is_official'] = True
                official_pages.append(page)
            except Exception as e:
                self.logger.warning(f"Could not get details for page {page_url}: {str(e)}")
        
        self.logger.info(f"Found {len(official_pages)} official module pages")
        return official_pages

    def get_all_pages(self, course_id: str) -> List[Dict]:
        """Get all pages in the course, fetching details in parallel for speed."""
        self.logger.info("Fetching all course pages...")
        pages = self.make_request(f"courses/{course_id}/pages")

        detailed_pages = []
        errors = []
        
        def fetch_detail(page):
            try:
                return self.make_request(f"courses/{course_id}/pages/{page['url']}")
            except Exception as e:
                self.logger.warning(f"Could not get details for page {page['url']}: {str(e)}")
                errors.append(page['url'])
                return None

        # Use ThreadPoolExecutor for parallel fetching (max 5 threads)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(fetch_detail, pages))
        detailed_pages = [r for r in results if r]
        if errors:
            self.logger.warning(f"Failed to fetch details for {len(errors)} pages.")
        return detailed_pages

    def normalize_content(self, content: str) -> str:
        """Normalize content for comparison by removing HTML and whitespace."""
        if not content:
            return ""
        
        soup = BeautifulSoup(content, 'html.parser')
        text = soup.get_text()
        # Remove extra whitespace and normalize
        normalized = re.sub(r'\s+', ' ', text).strip().lower()
        return normalized

    def calculate_content_hash(self, content: str) -> str:
        """Generate hash for exact content comparison."""
        normalized = self.normalize_content(content)
        return hashlib.md5(normalized.encode()).hexdigest()

    def calculate_similarity(self, content1: str, content2: str) -> float:
        """Calculate similarity percentage between two content pieces."""
        norm1 = self.normalize_content(content1)
        norm2 = self.normalize_content(content2)
        
        if not norm1 or not norm2:
            return 0.0
        
        return SequenceMatcher(None, norm1, norm2).ratio()

    def find_duplicates(self, official_pages: List[Dict], all_pages: List[Dict], 
                       similarity_threshold: float = 0.7) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
        """Find exact duplicates (100% by hash or similarity), similar pages, official duplicates, and orphaned duplicates."""
        self.logger.info("Analyzing duplicates...")
        
        official_urls = {page['url'] for page in official_pages}
        orphaned_pages = [page for page in all_pages if page['url'] not in official_urls]
        
        # Create content hashes for official pages
        official_hashes = {}
        for page in official_pages:
            content_hash = self.calculate_content_hash(page.get('body', ''))
            if content_hash not in official_hashes:
                official_hashes[content_hash] = []
            official_hashes[content_hash].append(page)
        
        exact_duplicates = []
        similar_pages = []
        official_duplicates = []
        orphaned_duplicates = []
        
        # Detect official duplicates (same content, different URLs, both in modules)
        seen_official = set()
        for hash_val, pages in official_hashes.items():
            if len(pages) > 1:
                for i in range(len(pages)):
                    for j in range(i+1, len(pages)):
                        pair = tuple(sorted([pages[i]['url'], pages[j]['url']]))
                        if pair not in seen_official:
                            official_duplicates.append({
                                'official_page_1': pages[i],
                                'official_page_2': pages[j],
                                'similarity': 1.0
                            })
                            seen_official.add(pair)
        # Track orphaned pages by content hash
        orphan_hashes = {}
        for page in orphaned_pages:
            content_hash = self.calculate_content_hash(page.get('body', ''))
            if content_hash not in orphan_hashes:
                orphan_hashes[content_hash] = []
            orphan_hashes[content_hash].append(page)
        # Detect orphaned duplicates (not matching any official page)
        for hash_val, pages in orphan_hashes.items():
            if len(pages) > 1:
                # More than one orphaned page with same content
                # Decide which to keep and which to delete
                # 1. Prefer published over unpublished
                # 2. If same, keep most recently created/modified
                # Mark all but one for deletion
                # Sort: published first, then by most recent created/updated
                def page_sort_key(p):
                    published = p.get('published', False)
                    created = p.get('created_at', '')
                    updated = p.get('updated_at', '')
                    # Use updated_at if available, else created_at
                    sort_time = updated or created
                    return (published, sort_time)
                sorted_pages = sorted(pages, key=page_sort_key, reverse=True)
                # Keep the first one, delete the rest
                to_keep = sorted_pages[0]
                for to_delete in sorted_pages[1:]:
                    orphaned_duplicates.append({
                        'delete_page': to_delete,
                        'keep_page': to_keep,
                        'reason': 'Duplicate orphaned page (auto-deleted)'
                    })
        # Now, process orphaned pages as before
        for orphan in orphaned_pages:
            orphan_hash = self.calculate_content_hash(orphan.get('body', ''))
            orphan_content = orphan.get('body', '')
            found_exact = False
            # Check for exact match by hash
            if orphan_hash in official_hashes:
                for official_page in official_hashes[orphan_hash]:
                    exact_duplicates.append({
                        'duplicate_page': orphan,
                        'official_page': official_page,
                        'similarity': 1.0
                    })
                found_exact = True
            else:
                # Check for 100% similarity (treat as exact duplicate)
                for official_page in official_pages:
                    similarity = self.calculate_similarity(orphan_content, official_page.get('body', ''))
                    if similarity == 1.0:
                        exact_duplicates.append({
                            'duplicate_page': orphan,
                            'official_page': official_page,
                            'similarity': 1.0
                        })
                        found_exact = True
                        break
            if found_exact:
                continue
            # Check for similarity (less than 100% but above threshold)
            best_match = None
            best_similarity = 0.0
            for official_page in official_pages:
                similarity = self.calculate_similarity(orphan_content, official_page.get('body', ''))
                if similarity > best_similarity and similarity >= similarity_threshold:
                    best_similarity = similarity
                    best_match = official_page
            if best_match:
                similar_pages.append({
                    'similar_page': orphan,
                    'official_page': best_match,
                    'similarity': best_similarity
                })
        # Note: Now, any 100% similarity match is treated as an exact duplicate, regardless of hash.
        # Official duplicates are flagged for review in the report, not auto-deleted by default.
        # Orphaned duplicates (not matching official) are auto-deleted except for the best one.
        return exact_duplicates, similar_pages, official_duplicates, orphaned_duplicates

    def delete_page(self, course_id: str, page_url: str) -> bool:
        """Delete a page from Canvas. Logs detailed error info if deletion fails."""
        try:
            url = f"{self.api_url}/courses/{course_id}/pages/{page_url}"
            response = requests.delete(url, headers=self.headers)
            if response.status_code == 200:
                return True
            else:
                # Log detailed error info for failed deletion
                self.logger.error(
                    f"Failed to delete page {page_url}: Status {response.status_code} - {response.text}"
                )
                return False
        except Exception as e:
            self.logger.error(f"Exception during deletion of page {page_url}: {str(e)}")
            return False

    def process_course(self, course_id: str, similarity_threshold: float = 0.7, 
                      auto_delete: bool = False) -> Dict:
        """Process a course for duplicate cleanup. Handles deletion and logs results. Uses parallel deletion."""
        self.logger.info(f"Processing course {course_id}")
        
        # Get course info
        course_info = self.make_request(f"courses/{course_id}")
        course_name = course_info.get('name', 'Unknown')
        
        # Get pages
        official_pages = self.get_official_pages(course_id)
        all_pages = self.get_all_pages(course_id)
        
        # Find duplicates
        exact_duplicates, similar_pages, official_duplicates, orphaned_duplicates = self.find_duplicates(
            official_pages, all_pages, similarity_threshold
        )
        
        # Store results
        self.official_pages = official_pages
        self.exact_duplicates = exact_duplicates
        self.similar_pages = similar_pages
        self.official_duplicates = official_duplicates # Store official duplicates
        self.orphaned_duplicates = orphaned_duplicates # Store orphaned duplicates
        
        # Auto-delete exact duplicates if requested (parallel)
        deleted_count = 0
        failed_deletions = []  # Track failed deletions for reporting
        if auto_delete and exact_duplicates:
            self.logger.info(f"Auto-deleting {len(exact_duplicates)} exact duplicates (parallel, max 5 threads)...")
            def delete_dup(dup):
                page_url = dup['duplicate_page']['url']
                if self.delete_page(course_id, page_url):
                    self.logger.info(f"Deleted: {dup['duplicate_page']['title']}")
                    return dup
                else:
                    failed_deletions.append(dup['duplicate_page'])
                    self.logger.error(f"Could not delete: {dup['duplicate_page']['title']} (URL: {page_url})")
                    return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(delete_dup, exact_duplicates))
            self.deleted_pages = [r for r in results if r]
            deleted_count = len(self.deleted_pages)
            if failed_deletions:
                self.logger.error(f"Failed to delete {len(failed_deletions)} pages. See logs for details.")
        # Auto-delete orphaned duplicates (not matching official)
        orphaned_deleted = []
        if auto_delete and orphaned_duplicates:
            self.logger.info(f"Auto-deleting {len(orphaned_duplicates)} orphaned duplicates (parallel, max 5 threads)...")
            def delete_orphan_dup(dup):
                page_url = dup['delete_page']['url']
                if self.delete_page(course_id, page_url):
                    self.logger.info(f"Deleted orphaned duplicate: {dup['delete_page']['title']}")
                    return dup
                else:
                    failed_deletions.append(dup['delete_page'])
                    self.logger.error(f"Could not delete orphaned duplicate: {dup['delete_page']['title']} (URL: {page_url})")
                    return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(delete_orphan_dup, orphaned_duplicates))
            orphaned_deleted = [r for r in results if r]
            deleted_count += len(orphaned_deleted)
        
        return {
            'course_id': course_id,
            'course_name': course_name,
            'total_pages': len(all_pages),
            'official_pages': len(official_pages),
            'exact_duplicates': len(exact_duplicates),
            'similar_pages': len(similar_pages),
            'official_duplicates': len(official_duplicates), # Add to result for traceability
            'orphaned_duplicates': len(orphaned_duplicates), # Add to result for traceability
            'deleted_count': deleted_count,
            'failed_deletions': failed_deletions,  # Add to result for traceability
            'analysis_timestamp': datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
        }

    def generate_preview_report(self, course_id: str, similarity_threshold: float = 0.7) -> str:
        """Generate preview report before deletion."""
        # Run analysis without deletion
        result = self.process_course(course_id, similarity_threshold, auto_delete=False)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        preview_file = f'canvas_duplicate_preview_{course_id}_{timestamp}.xlsx'
        
        with pd.ExcelWriter(preview_file, engine='xlsxwriter') as writer:
            # Summary sheet
            summary_data = [{
                'Course ID': result['course_id'],
                'Course Name': result['course_name'],
                'Total Pages': result['total_pages'],
                'Official Module Pages': result['official_pages'],
                'Exact Duplicates (Auto-delete)': result['exact_duplicates'],
                'Similar Pages (Review)': result['similar_pages'],
                'Official Duplicates (Review)': result['official_duplicates'], # Add to summary
                'Analysis Date': result['analysis_timestamp']
            }]
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
            
            # Exact duplicates for auto-deletion
            if self.exact_duplicates:
                auto_delete_data = []
                for dup in self.exact_duplicates:
                    auto_delete_data.append({
                        'Page Title': dup['duplicate_page']['title'],
                        'Page URL': dup['duplicate_page']['url'],
                        'Official Version': dup['official_page']['title'],
                        'Created Date': dup['duplicate_page'].get('created_at', 'N/A'),
                        'Last Updated': dup['duplicate_page'].get('updated_at', 'N/A'),
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{dup['duplicate_page']['url']}",
                        'Action': 'AUTO-DELETE'
                    })
                pd.DataFrame(auto_delete_data).to_excel(writer, sheet_name='Auto-Delete List', index=False)
            
            # Similar pages for review
            if self.similar_pages:
                review_data = []
                for sim in self.similar_pages:
                    review_data.append({
                        'Page Title': sim['similar_page']['title'],
                        'Page URL': sim['similar_page']['url'],
                        'Similarity %': f"{sim['similarity']:.1%}",
                        'Official Version': sim['official_page']['title'],
                        'Created Date': sim['similar_page'].get('created_at', 'N/A'),
                        'Last Updated': sim['similar_page'].get('updated_at', 'N/A'),
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{sim['similar_page']['url']}",
                        'Action': 'REVIEW REQUIRED'
                    })
                pd.DataFrame(review_data).to_excel(writer, sheet_name='Review List', index=False)

            # Official duplicates for review
            if self.official_duplicates:
                official_dup_data = []
                for dup in self.official_duplicates:
                    official_dup_data.append({
                        'Official Page 1 Title': dup['official_page_1']['title'],
                        'Official Page 1 URL': dup['official_page_1']['url'],
                        'Official Page 2 Title': dup['official_page_2']['title'],
                        'Official Page 2 URL': dup['official_page_2']['url'],
                        'Similarity %': f"{dup['similarity']:.1%}",
                        'Created 1': dup['official_page_1'].get('created_at', 'N/A'),
                        'Created 2': dup['official_page_2'].get('created_at', 'N/A'),
                        'Canvas Link 1': f"{self.base_url}/courses/{course_id}/pages/{dup['official_page_1']['url']}",
                        'Canvas Link 2': f"{self.base_url}/courses/{course_id}/pages/{dup['official_page_2']['url']}"
                    })
                pd.DataFrame(official_dup_data).to_excel(writer, sheet_name='Official Duplicates', index=False)
        
        self.logger.info(f"Preview report generated: {preview_file}")
        return preview_file

    def generate_traceability_report(self, course_id: str) -> str:
        """Generate final traceability report after actions."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        trace_file = f'canvas_cleanup_traceability_{course_id}_{timestamp}.xlsx'
        
        with pd.ExcelWriter(trace_file, engine='xlsxwriter') as writer:
            # Actions taken
            if self.deleted_pages:
                deleted_data = []
                for dup in self.deleted_pages:
                    deleted_data.append({
                        'Deleted Page Title': dup['duplicate_page']['title'],
                        'Deleted Page URL': dup['duplicate_page']['url'],
                        'Official Version Kept': dup['official_page']['title'],
                        'Official Page URL': dup['official_page']['url'],
                        'Deletion Timestamp': datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'Reason': 'Exact duplicate (100% match)'
                    })
                pd.DataFrame(deleted_data).to_excel(writer, sheet_name='Deleted Pages', index=False)
            
            # Flagged for review
            if self.similar_pages:
                flagged_data = []
                for sim in self.similar_pages:
                    flagged_data.append({
                        'Page Title': sim['similar_page']['title'],
                        'Page URL': sim['similar_page']['url'],
                        'Similarity %': f"{sim['similarity']:.1%}",
                        'Official Version': sim['official_page']['title'],
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{sim['similar_page']['url']}",
                        'Status': 'Requires Manual Review',
                        'Next Action': 'Educator decision needed'
                    })
                pd.DataFrame(flagged_data).to_excel(writer, sheet_name='Flagged for Review', index=False)
            
            # Preserved official pages
            if self.official_pages:
                preserved_data = []
                for page in self.official_pages:
                    preserved_data.append({
                        'Page Title': page['title'],
                        'Page URL': page['url'],
                        'Module Status': 'Official (Preserved)',
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{page['url']}"
                    })
                pd.DataFrame(preserved_data).to_excel(writer, sheet_name='Preserved Pages', index=False)
        
        self.logger.info(f"Traceability report generated: {trace_file}")
        return trace_file

    def generate_consolidated_report(self, course_id: str, similarity_threshold: float = 0.7, auto_delete: bool = False) -> str:
        """Generate a single consolidated report for preview, deletion, review, failed deletions, preserved pages, official duplicates, and orphaned duplicates."""
        # Run analysis and (optionally) deletion
        result = self.process_course(course_id, similarity_threshold, auto_delete=auto_delete)
        # Find official and orphaned duplicates for reporting
        _, _, official_duplicates, orphaned_duplicates = self.find_duplicates(self.official_pages, self.official_pages, similarity_threshold)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = f'canvas_duplicate_cleanup_{course_id}_{timestamp}.xlsx'
        with pd.ExcelWriter(report_file, engine='xlsxwriter') as writer:
            # Summary sheet
            summary_data = [{
                'Course ID': result['course_id'],
                'Course Name': result['course_name'],
                'Total Pages': result['total_pages'],
                'Official Module Pages': result['official_pages'],
                'Exact Duplicates (Auto-delete)': result['exact_duplicates'],
                'Similar Pages (Review)': result['similar_pages'],
                'Official Duplicates (Review)': result['official_duplicates'], # Add to summary
                'Orphaned Duplicates (Auto-delete)': result['orphaned_duplicates'], # Add to summary
                'Deleted Count': result['deleted_count'],
                'Failed Deletions': len(result['failed_deletions']),
                'Analysis Date': result['analysis_timestamp']
            }]
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)

            # Exact duplicates for auto-deletion
            if self.exact_duplicates:
                auto_delete_data = []
                for dup in self.exact_duplicates:
                    auto_delete_data.append({
                        'Page Title': dup['duplicate_page']['title'],
                        'Page URL': dup['duplicate_page']['url'],
                        'Official Version': dup['official_page']['title'],
                        'Created Date': dup['duplicate_page'].get('created_at', 'N/A'),
                        'Last Updated': dup['duplicate_page'].get('updated_at', 'N/A'),
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{dup['duplicate_page']['url']}",
                        'Action': 'AUTO-DELETE',
                        'Deleted': any(
                            d['duplicate_page']['url'] == dup['duplicate_page']['url'] for d in self.deleted_pages
                        )
                    })
                pd.DataFrame(auto_delete_data).to_excel(writer, sheet_name='Auto-Delete List', index=False)

            # Similar pages for review
            if self.similar_pages:
                review_data = []
                for sim in self.similar_pages:
                    review_data.append({
                        'Page Title': sim['similar_page']['title'],
                        'Page URL': sim['similar_page']['url'],
                        'Similarity %': f"{sim['similarity']:.1%}",
                        'Official Version': sim['official_page']['title'],
                        'Created Date': sim['similar_page'].get('created_at', 'N/A'),
                        'Last Updated': sim['similar_page'].get('updated_at', 'N/A'),
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{sim['similar_page']['url']}",
                        'Action': 'REVIEW REQUIRED'
                    })
                pd.DataFrame(review_data).to_excel(writer, sheet_name='Review List', index=False)

            # Official duplicates (flagged for review)
            if official_duplicates:
                official_dup_data = []
                for dup in official_duplicates:
                    official_dup_data.append({
                        'Official Page 1 Title': dup['official_page_1']['title'],
                        'Official Page 1 URL': dup['official_page_1']['url'],
                        'Official Page 2 Title': dup['official_page_2']['title'],
                        'Official Page 2 URL': dup['official_page_2']['url'],
                        'Similarity %': f"{dup['similarity']:.1%}",
                        'Created 1': dup['official_page_1'].get('created_at', 'N/A'),
                        'Created 2': dup['official_page_2'].get('created_at', 'N/A'),
                        'Canvas Link 1': f"{self.base_url}/courses/{course_id}/pages/{dup['official_page_1']['url']}",
                        'Canvas Link 2': f"{self.base_url}/courses/{course_id}/pages/{dup['official_page_2']['url']}"
                    })
                pd.DataFrame(official_dup_data).to_excel(writer, sheet_name='Official Duplicates', index=False)

            # Orphaned duplicates (auto-deleted)
            if self.orphaned_duplicates:
                orphaned_dup_data = []
                for dup in self.orphaned_duplicates:
                    orphaned_dup_data.append({
                        'Deleted Orphaned Page Title': dup['delete_page']['title'],
                        'Deleted Orphaned Page URL': dup['delete_page']['url'],
                        'Kept Orphaned Page Title': dup['keep_page']['title'],
                        'Kept Orphaned Page URL': dup['keep_page']['url'],
                        'Reason': dup['reason'],
                        'Created Deleted': dup['delete_page'].get('created_at', 'N/A'),
                        'Created Kept': dup['keep_page'].get('created_at', 'N/A'),
                        'Published Deleted': dup['delete_page'].get('published', 'N/A'),
                        'Published Kept': dup['keep_page'].get('published', 'N/A'),
                        'Canvas Link Deleted': f"{self.base_url}/courses/{course_id}/pages/{dup['delete_page']['url']}",
                        'Canvas Link Kept': f"{self.base_url}/courses/{course_id}/pages/{dup['keep_page']['url']}"
                    })
                pd.DataFrame(orphaned_dup_data).to_excel(writer, sheet_name='Orphaned Duplicates', index=False)

            # Deleted pages
            if self.deleted_pages:
                deleted_data = []
                for dup in self.deleted_pages:
                    deleted_data.append({
                        'Deleted Page Title': dup['duplicate_page']['title'],
                        'Deleted Page URL': dup['duplicate_page']['url'],
                        'Official Version Kept': dup['official_page']['title'],
                        'Official Page URL': dup['official_page']['url'],
                        'Deletion Timestamp': datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'Reason': 'Exact duplicate (100% match)'
                    })
                pd.DataFrame(deleted_data).to_excel(writer, sheet_name='Deleted Pages', index=False)

            # Failed deletions
            if result['failed_deletions']:
                failed_data = []
                for page in result['failed_deletions']:
                    failed_data.append({
                        'Failed Page Title': page.get('title', 'N/A'),
                        'Failed Page URL': page.get('url', 'N/A'),
                        'Reason': 'API deletion failed (see logs)'
                    })
                pd.DataFrame(failed_data).to_excel(writer, sheet_name='Failed Deletions', index=False)

            # Preserved official pages
            if self.official_pages:
                preserved_data = []
                for page in self.official_pages:
                    preserved_data.append({
                        'Page Title': page['title'],
                        'Page URL': page['url'],
                        'Module Status': 'Official (Preserved)',
                        'Canvas Link': f"{self.base_url}/courses/{course_id}/pages/{page['url']}"
                    })
                pd.DataFrame(preserved_data).to_excel(writer, sheet_name='Preserved Pages', index=False)
        self.logger.info(f"Consolidated report generated: {report_file}")
        return report_file

def main():
    parser = argparse.ArgumentParser(description='Canvas Duplicate Page Cleaner')
    parser.add_argument('--canvas-url', required=True)
    parser.add_argument('--api-token', required=True)
    parser.add_argument('--course-id', required=True)
    parser.add_argument('--similarity-threshold', type=float, default=0.7)
    parser.add_argument('--auto-delete', choices=['true', 'false'], default='false')
    
    args = parser.parse_args()
    
    # Initialize your existing cleaner
    cleaner = CanvasDuplicateCleaner(args.canvas_url, args.api_token)
    
    auto_delete = args.auto_delete.lower() == 'true'
    
    print(f"Analyzing course {args.course_id}...")
    report_file = cleaner.generate_consolidated_report(
        args.course_id, 
        args.similarity_threshold, 
        auto_delete=auto_delete
    )
    
    print(f"✅ Consolidated report generated: {report_file}")
    print(f"Exact duplicates: {len(cleaner.exact_duplicates)}")
    if auto_delete:
        print(f"Deleted: {len(cleaner.deleted_pages)} exact duplicates")
# --- HANDOVER NOTE ---
# - The script identifies official pages (in modules) and orphaned pages (not in modules).
# - Orphaned pages that are 100% identical to any official page are auto-deleted.
# - Duplicate orphaned pages (not matching any official page) are auto-deleted, keeping the best one based on published status and recency (see 'Orphaned Duplicates' sheet in the report).
# - Official duplicates (identical official pages) are flagged for review, not auto-deleted.
# - Orphaned pages highly similar (above threshold) to official pages are flagged for review.
# - All actions and findings are reported in a single consolidated Excel file.
# - Adjust max_workers in ThreadPoolExecutor if API rate limits are encountered.
# - For further customization, see the find_duplicates and process_course methods.
# ----------------------

if __name__ == "__main__":
    main()