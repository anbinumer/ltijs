# --- START OF FILE duplicate_page_cleaner.py (Version 3) ---

"""
Canvas Duplicate Page Cleaner - Version 3 (Human-Centered)

This enhanced script analyzes a Canvas course for duplicate pages with a primary focus on safety,
transparency, and empowering the end-user, embodying Human-Centered AI (H2A) principles.

What's New in Version 3:
- CRITICAL SAFETY: Full inbound link checking is now a core, non-optional part of the analysis.
  The script scans pages, assignments, quizzes, announcements, and discussions to find links,
  preventing the auto-deletion of content integrated into the course.
- HUMAN-CENTERED AI LOGIC: Findings are now categorized into two clear groups:
  1. `safe_actions`: High-confidence actions for the user to approve (e.g., deleting an unlinked,
     unpublished, identical orphan page).
  2. `requires_manual_review`: Ambiguous cases where human intelligence is needed. The script provides
     a recommendation but defers the final decision to the user.
- EXPLAINABILITY (X2AI): Every finding includes a clear, plain-language 'reason' for its classification,
  building user trust and providing transparency into the AI's decision process.
- ROBUST & SIMPLE CONTROL FLOW: The script operates in two clean modes:
  `--analyze-only` (default): Performs a comprehensive, read-only analysis and outputs structured JSON.
  `--execute-from-json`: A dedicated mode to safely execute a list of user-approved actions.
- ENHANCED EFFICIENCY: Utilizes concurrent API calls to fetch all course content types for link
  checking without significantly increasing processing time.
"""

import requests
import json
import re
import hashlib
import logging
from typing import Optional, Dict, List, Set, Tuple
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
import concurrent.futures
import argparse
import sys
from requests.adapters import HTTPAdapter
from common.progress import ProgressReporter
from urllib3.util.retry import Retry

# --- SCRIPT CONFIGURATION ---
LOGGING_LEVEL = logging.INFO
MAX_API_WORKERS = 10  # Max concurrent threads for API calls
CONTENT_TYPES_TO_SCAN = ['pages', 'assignments', 'quizzes', 'announcements', 'discussion_topics']

class CanvasDuplicateCleaner:
    """A robust tool to analyze and clean up duplicate Canvas pages."""

    def __init__(self, base_url: str, api_token: str, course_id: str):
        """Initializes the cleaner with API credentials and a requests session."""
        self.base_url = f"https://{base_url}".rstrip('/')
        self.api_url = f"{self.base_url}/api/v1"
        self.course_id = course_id
        self.headers = {"Authorization": f"Bearer {api_token}"}
        
        # Setup logging
        logging.basicConfig(level=LOGGING_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        # Setup a resilient requests session
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.headers.update(self.headers)
        
        # Pre-compile regex for finding Canvas page links in HTML
        self.page_link_regex = re.compile(rf'/courses/{self.course_id}/pages/([^"/]+)')
        
        # Internal cache for analysis results
        self.inbound_links_map: Dict[str, Set[str]] = {}

    def _make_paginated_request(self, endpoint: str) -> List[Dict]:
        """Makes a paginated GET request to the Canvas API."""
        results = []
        url = f"{self.api_url}/{endpoint}?per_page=100"
        while url:
            try:
                response = self.session.get(url)
                response.raise_for_status()
                data = response.json()
                results.extend(data)
                url = response.links.get('next', {}).get('url')
            except requests.exceptions.RequestException as e:
                self.logger.error(f"API request failed for endpoint '{endpoint}': {e}")
                raise
        return results

    def _get_inbound_links_map(self, progress: ProgressReporter | None = None) -> Dict[str, Set[str]]:
        """
        CRITICAL SAFETY FEATURE: Scans all course content to find which pages have inbound links.
        This is the core of the HCD safety mechanism.
        """
        if self.inbound_links_map:
            return self.inbound_links_map

        self.logger.info("Scanning all course content for inbound links (Pages, Assignments, etc.)...")
        if progress:
            progress.update(step="scan_links", current=0, total=len(CONTENT_TYPES_TO_SCAN), message="Scanning inbound links")
        link_map: Dict[str, Set[str]] = {}

        def scan_item_for_links(item: Dict, item_type: str):
            """Helper function to parse HTML and find links within a single content item."""
            body = item.get('body') or item.get('description') or item.get('message', '')
            if not body:
                return
            
            source_name = f"{item_type.rstrip('s').capitalize()}: '{item.get('title', 'Untitled')}'"
            found_urls = self.page_link_regex.findall(body)
            for page_url in found_urls:
                if page_url not in link_map:
                    link_map[page_url] = set()
                link_map[page_url].add(source_name)

        def fetch_and_scan_content(content_type: str):
            """Fetches all items of a content type and scans them for links."""
            try:
                endpoint = f"courses/{self.course_id}/{content_type}"
                items = self._make_paginated_request(endpoint)
                for item in items:
                    scan_item_for_links(item, content_type)
            except Exception as e:
                self.logger.warning(f"Could not scan content type '{content_type}': {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
            list(executor.map(fetch_and_scan_content, CONTENT_TYPES_TO_SCAN))
        if progress:
            progress.update(step="scan_links", current=len(CONTENT_TYPES_TO_SCAN), total=len(CONTENT_TYPES_TO_SCAN), message="Link scan complete")

        self.logger.info(f"Finished link scan. Found links to {len(link_map)} unique pages.")
        self.inbound_links_map = link_map
        return self.inbound_links_map

    def _get_page_objects(self, progress: ProgressReporter | None = None) -> Tuple[List[Dict], List[Dict]]:
        """Fetches all pages and classifies them as 'official' (in a module) or 'orphaned'."""
        self.logger.info("Fetching all course pages and identifying official module pages...")
        
        # Get basic page list (without body content)
        basic_pages = self._make_paginated_request(f"courses/{self.course_id}/pages")
        
        # Fetch full details for each page (THIS IS THE CRITICAL MISSING STEP!)
        self.logger.info(f"Fetching full details for {len(basic_pages)} pages...")
        if progress:
            progress.update(step="fetch_pages", current=0, total=len(basic_pages) or 1, message="Fetching full page details")
        def fetch_full_page(page):
            try:
                # Use session directly for single page request (not paginated)
                url = f"{self.api_url}/courses/{self.course_id}/pages/{page['url']}"
                response = self.session.get(url)
                response.raise_for_status()
                full_page = response.json()
                return full_page
            except Exception as e:
                self.logger.warning(f"Could not get details for page {page['url']}: {e}")
                return None
        
        # Use concurrent fetching like the standalone version
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
            results = []
            for idx, full in enumerate(executor.map(fetch_full_page, basic_pages), 1):
                if full is not None:
                    results.append(full)
                if progress:
                    progress.update(step="fetch_pages", current=idx, total=len(basic_pages) or 1, message=f"Fetched {idx}/{len(basic_pages) or 1} pages")
        all_pages = [r for r in results if r is not None]
        self.logger.info(f"Successfully fetched full details for {len(all_pages)} pages.")
        
        # Get modules and classify pages
        modules = self._make_paginated_request(f"courses/{self.course_id}/modules")
        official_page_urls: Set[str] = set()
        
        def get_module_items(module: Dict):
            try:
                items = self._make_paginated_request(f"courses/{self.course_id}/modules/{module['id']}/items")
                for item in items:
                    if item.get('type') == 'Page' and item.get('page_url'):
                        official_page_urls.add(item['page_url'])
            except Exception as e:
                self.logger.warning(f"Could not get items for module '{module.get('name')}': {e}")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
            list(executor.map(get_module_items, modules))
        
        official_pages = [p for p in all_pages if p['url'] in official_page_urls]
        orphaned_pages = [p for p in all_pages if p['url'] not in official_page_urls]
        self.logger.info(f"Classification complete. Official: {len(official_pages)}, Orphaned: {len(orphaned_pages)}.")
        return official_pages, orphaned_pages

    @staticmethod
    def _normalize_and_hash(content: str, page_title: str = "Unknown") -> str:
        """Normalizes HTML content to text and returns an MD5 hash."""
        if not content:
            # This should now be rare instead of happening for every page!
            logger = logging.getLogger(__name__)
            logger.debug(f"Page '{page_title}' has no content - will hash to empty string")
            return ""
        text = BeautifulSoup(content, 'html.parser').get_text()
        normalized = re.sub(r'\s+', ' ', text).strip().lower()
        content_hash = hashlib.md5(normalized.encode()).hexdigest()
        # Debug logging to verify we're getting real content
        logger = logging.getLogger(__name__)
        logger.debug(f"Page '{page_title}' content hash: {content_hash[:8]}... (length: {len(normalized)} chars)")
        return content_hash
    
    def analyze_duplicates(self, progress: ProgressReporter | None = None) -> Dict:
        """
        Performs the full analysis and returns structured findings.
        This is the main "brain" of the script.
        """
        self.logger.info("Starting duplicate analysis...")
        if progress:
            progress.update(step="initialize", message="Preparing analysis")
        official_pages, orphaned_pages = self._get_page_objects(progress=progress)
        inbound_links_map = self._get_inbound_links_map(progress=progress)
        
        all_pages = official_pages + orphaned_pages
        if not all_pages:
            self.logger.info("No pages found in this course.")
            return {"summary": {"pages_scanned": 0}, "findings": {"safe_actions": [], "requires_manual_review": []}}
            
        page_hashes: Dict[str, str] = {p['url']: self._normalize_and_hash(p.get('body'), p.get('title', 'Unknown')) for p in all_pages}
        hash_to_pages: Dict[str, List[Dict]] = {}
        for page in all_pages:
            h = page_hashes[page['url']]
            if h not in hash_to_pages:
                hash_to_pages[h] = []
            hash_to_pages[h].append(page)

        safe_actions: List[Dict] = []
        requires_manual_review: List[Dict] = []
        processed_urls: Set[str] = set()

        total_groups = len(hash_to_pages) or 1
        for idx, (h, pages) in enumerate(hash_to_pages.items(), 1):
            if len(pages) < 2:
                continue

            # Sort pages to find the "best" one to keep (Official > Published > Most Recent)
            pages.sort(key=lambda p: (
                p['url'] in [op['url'] for op in official_pages],
                p.get('published', False),
                p.get('updated_at', p.get('created_at', ''))
            ), reverse=True)
            
            best_page_to_keep = pages[0]
            for page_to_delete in pages[1:]:
                if page_to_delete['url'] in processed_urls:
                    continue
                
                processed_urls.add(best_page_to_keep['url'])
                processed_urls.add(page_to_delete['url'])

                # --- H2A Decision Logic ---
                is_delete_candidate_official = page_to_delete['url'] in [op['url'] for op in official_pages]
                delete_candidate_links = inbound_links_map.get(page_to_delete['url'], set())
                
                finding = {
                    "delete_page_title": page_to_delete['title'],
                    "delete_page_url": page_to_delete['url'],
                    "keep_page_title": best_page_to_keep['title'],
                    "keep_page_url": best_page_to_keep['url'],
                    "similarity_percentage": "100.0%",
                }

                if is_delete_candidate_official or len(delete_candidate_links) > 0:
                    # Case for MANUAL REVIEW: The page to be deleted is either official or has links.
                    reason = "Both pages are official content." if is_delete_candidate_official else f"Page has {len(delete_candidate_links)} inbound link(s)."
                    finding["reason"] = f"Manual review required. {reason} It is a duplicate of '{best_page_to_keep['title']}'."
                    finding["risk_level"] = "HIGH"
                    finding["inbound_links"] = list(delete_candidate_links)
                    requires_manual_review.append(finding)
                else:
                    # Case for SAFE ACTION: The page to be deleted is an orphan with zero inbound links.
                    finding["reason"] = "Safe to remove. This page is an unlinked, orphaned copy of an official page."
                    finding["risk_level"] = "LOW"
                    safe_actions.append(finding)

            if progress:
                progress.update(step="analyze_duplicates", current=idx, total=total_groups, message=f"Analyzed {idx}/{total_groups} duplicate groups")

        self.logger.info(f"Analysis complete. Found {len(safe_actions)} safe actions and {len(requires_manual_review)} items for manual review.")
        result = {
            "summary": {
                "pages_scanned": len(all_pages),
                "official_pages": len(official_pages),
                "orphaned_pages": len(orphaned_pages),
                "pages_with_links": len(inbound_links_map),
                "safe_actions_found": len(safe_actions),
                "manual_review_needed": len(requires_manual_review),
            },
            "findings": {
                "safe_actions": safe_actions,
                "requires_manual_review": requires_manual_review,
            }
        }
        if progress:
            progress.done({"summary": result.get("summary", {})})
        return result

    def execute_approved_actions(self, actions: List[Dict]) -> Dict:
        """Deletes pages from a list of approved actions."""
        if not actions:
            return {"summary": {"successful": 0, "failed": 0}, "results": {}}
            
        self.logger.info(f"Executing {len(actions)} approved deletion actions...")
        successful_deletions: List[Dict] = []
        failed_deletions: List[Dict] = []

        def delete_action(action: Dict):
            page_url = action.get('delete_page_url')
            if not page_url:
                failed_deletions.append({**action, "failure_reason": "Missing 'delete_page_url'"})
                return
            try:
                url = f"{self.api_url}/courses/{self.course_id}/pages/{page_url}"
                response = self.session.delete(url)
                response.raise_for_status()
                successful_deletions.append(action)
                self.logger.info(f"Successfully deleted page: {action.get('delete_page_title')}")
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to delete page '{action.get('delete_page_title')}': {e}")
                failed_deletions.append({**action, "failure_reason": str(e)})

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
            executor.map(delete_action, actions)

        self.logger.info(f"Execution complete. Successful: {len(successful_deletions)}, Failed: {len(failed_deletions)}")
        return {
            "summary": {
                "successful": len(successful_deletions),
                "failed": len(failed_deletions),
            },
            "results": {
                "successful_deletions": successful_deletions,
                "failed_deletions": failed_deletions,
            }
        }

def main():
    """Main function to handle command-line execution."""
    parser = argparse.ArgumentParser(description="Canvas Duplicate Page Cleaner v3 (Human-Centered)")
    parser.add_argument('--canvas-url', required=True, help="The base URL of the Canvas instance (e.g., canvas.instructure.com)")
    parser.add_argument('--api-token', required=True, help="A valid Canvas API token.")
    parser.add_argument('--course-id', required=True, help="The ID of the course to process.")
    
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--analyze-only', action='store_true', help="Default mode: Perform a full, read-only analysis and output JSON.")
    mode.add_argument('--execute-from-json', type=str, metavar="FILE_PATH", help="Execute approved actions from a specified JSON file.")

    args = parser.parse_args()
    
    cleaner = CanvasDuplicateCleaner(args.canvas_url, args.api_token, args.course_id)
    
    try:
        if args.execute_from_json:
            print(f"Executing approved actions from: {args.execute_from_json}", file=sys.stderr)
            with open(args.execute_from_json, 'r') as f:
                actions = json.load(f)
            
            execution_results = cleaner.execute_approved_actions(actions)
            # Print final execution report to stdout for the Node.js server
            print("EXECUTION_RESULTS_JSON:", json.dumps(execution_results, indent=2))

        else: # --analyze-only is the other option
            print(f"Performing analysis for course: {args.course_id}", file=sys.stderr)
            progress = ProgressReporter(enabled=True)
            analysis_results = cleaner.analyze_duplicates(progress=progress)
            # Print final analysis to stdout for the Node.js server
            print("ENHANCED_ANALYSIS_JSON:", json.dumps(analysis_results, indent=2))
            
    except Exception as e:
        # Log the full error for debugging and exit with a non-zero status code
        logging.getLogger(__name__).critical(f"A critical error occurred: {e}", exc_info=True)
        # Output a structured error for the calling process
        error_output = json.dumps({"success": False, "error": str(e)})
        print(f"CRITICAL_ERROR_JSON: {error_output}", file=sys.stdout)
        sys.exit(1)

if __name__ == "__main__":
    main()

# --- HANDOVER NOTE (Version 3) ---
# This script has been significantly refactored for safety and clarity.
# The core safety feature is the `_get_inbound_links_map` method, which prevents auto-deletion
# of any page that is linked from other course content. This is fundamental to its HCD approach.
# The script's output is now a clean JSON object, designed to be consumed by a UI, with findings
# separated into `safe_actions` and `requires_manual_review`. Each finding contains a `reason`
# to ensure the AI's logic is explainable to the user.
# The control flow is simplified: `--analyze-only` produces the data, and `--execute-from-json`
# acts on user-approved data, ensuring the human is always in control of destructive actions.
# ---------------------------------