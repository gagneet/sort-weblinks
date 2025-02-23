import re
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN
from collections import Counter
from urllib.parse import urlparse, urljoin
import yaml
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import json
import concurrent.futures
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
import requests
import time
import argparse
from tqdm import tqdm
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class WebLink:
    url: str
    description: Optional[str] = None
    group: Optional[str] = None
    format: str = 'raw_url'
    title: Optional[str] = None
    fetch_date: Optional[datetime] = None
    domain: Optional[str] = None

    def __post_init__(self):
        self.domain = urlparse(self.url).netloc if self.url else None

class WebLinkOrganizer:
    def __init__(self, config_path: Optional[str] = None):
        self.config = self.load_config(config_path)
        self.session = self.create_session()
        self.cache_file = Path('url_cache.json')
        self.url_cache = self.load_cache()
        self.hierarchy = self.config.get('categories', self.default_hierarchy())
        self.settings = self.config.get('settings', {})

    @staticmethod
    def load_config(config_path: Optional[str]) -> dict:
        """Load configuration from YAML file or use defaults."""
        default_config = {
            'timeout': 5,
            'max_retries': 3,
            'concurrent_requests': 10,
            'cache_duration': 86400,  # 24 hours
            'custom_categories': {}
        }
        
        if config_path:
            try:
                config_path = Path(config_path)
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                        if not config:
                            raise ValueError("Empty configuration file")
                        return config
                else:
                    logger.warning(f"Config file not found: {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config file: {e}")
        
        logger.info("Using default configuration")
        return {
            'settings': {
                'timeout': 5,
                'max_retries': 3,
                'concurrent_requests': 10,
                'cache_duration': 86400,  # 24 hours
                'fetch_titles': True,
                'min_cluster_size': 2,
                'clustering_threshold': 0.7
            },
            'categories': WebLinkOrganizer.default_hierarchy()
        }

    def create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retries = Retry(
            total=self.settings.get('max_retries', 3),
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return session

    def load_cache(self) -> dict:
        """Load URL cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    # Clean expired entries
                    current_time = time.time()
                    cache_duration = self.settings.get('cache_duration', 86400)
                    return {
                        k: v for k, v in cache_data.items()
                        if current_time - v.get('timestamp', 0) < cache_duration
                    }
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
        return {}

    def save_cache(self):
        """Save URL cache to file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.url_cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    async def fetch_title(self, url: str) -> Optional[str]:
        """Fetch page title asynchronously with caching."""
        cache_key = url
        current_time = time.time()
        
        # Check cache
        if cache_key in self.url_cache:
            cached_data = self.url_cache[cache_key]
            if current_time - cached_data['timestamp'] < self.settings.get('cache_duration', 86400):
                return cached_data['title']
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.settings.get('timeout', 5))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        title = soup.title.string if soup.title else None
                        
                        if title:
                            title = title.strip()
                            # Update cache
                            self.url_cache[cache_key] = {
                                'title': title,
                                'timestamp': current_time
                            }
                            return title
        except Exception as e:
            logger.debug(f"Failed to fetch title for {url}: {e}")
        return None

    async def fetch_missing_titles(self, entries: List[WebLink]) -> List[WebLink]:
        """Fetch missing titles concurrently with progress bar."""
        if not self.settings.get('fetch_titles', True):
            return entries

        entries_needing_titles = [
            entry for entry in entries
            if not entry.description or entry.description == entry.url
        ]
        
        if not entries_needing_titles:
            return entries

        with tqdm(total=len(entries_needing_titles), 
                 desc="Fetching titles", 
                 unit="link") as pbar:
            
            async def process_entry(entry: WebLink):
                title = await self.fetch_title(entry.url)
                if title:
                    entry.description = title
                elif 'github.com' in entry.url:
                    parts = entry.url.strip('/').split('/')
                    if len(parts) >= 5:
                        owner, repo = parts[-2], parts[-1]
                        entry.description = f"GitHub: {owner}/{repo}"
                    else:
                        entry.description = "GitHub Repository"
                else:
                    entry.description = f"Link from {entry.domain}"
                
                entry.fetch_date = datetime.now()
                pbar.update(1)
                return entry

            # Process in batches to avoid overwhelming the system
            batch_size = self.settings.get('concurrent_requests', 10)
            processed_entries = []
            
            for i in range(0, len(entries_needing_titles), batch_size):
                batch = entries_needing_titles[i:i + batch_size]
                batch_results = await asyncio.gather(*[process_entry(entry) for entry in batch])
                processed_entries.extend(batch_results)
                await asyncio.sleep(0.1)  # Small delay between batches
            
            # Update cache
            self.save_cache()
            
            # Replace original entries with processed ones
            entry_map = {id(entry): entry for entry in processed_entries}
            return [entry_map.get(id(e), e) for e in entries]

    def parse_links(self, file_path: str) -> List[WebLink]:
        """Parse links from file with improved error handling."""
        entries = []
        current_group = None
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Failed to read input file: {e}")
            return entries

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for group header
            if line.endswith(':') and 'http' not in line:
                current_group = line[:-1]
                continue

            # Handle bullet points
            if line.startswith(('-', '*')):
                line = line[1:].strip()

            # Parse different link formats
            patterns = [
                (r'(.*?):\s*(https?://\S+)', 'with_description'),
                (r'(.*?)\s+[-]\s+(https?://\S+)', 'with_description'),
                (r'(https?://\S+)', 'raw_url')
            ]

            for pattern, format_type in patterns:
                match = re.match(pattern, line)
                if match:
                    if format_type == 'with_description':
                        description, url = match.groups()
                        entries.append(WebLink(
                            url=url.strip(),
                            description=description.strip(),
                            group=current_group,
                            format=format_type
                        ))
                    else:
                        url = match.group(1)
                        entries.append(WebLink(
                            url=url.strip(),
                            group=current_group,
                            format=format_type
                        ))
                    break

        return entries

    def categorize_entries(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """Categorize entries using hierarchical structure with progress tracking."""
        with tqdm(total=len(entries), desc="Categorizing entries", unit="link") as pbar:
            # Initialize categories
            categorized = {main_cat: {} for main_cat in self.hierarchy.keys()}
            categorized["Miscellaneous"] = {"Uncategorized": []}

            # First pass: respect existing groups
            remaining_entries = []
            for entry in entries:
                if entry.group:
                    assigned = False
                    group_lower = entry.group.lower()
                    for main_cat, config in self.hierarchy.items():
                        if any(keyword in group_lower for keyword in config['keywords']):
                            if entry.group not in categorized[main_cat]:
                                categorized[main_cat][entry.group] = []
                            categorized[main_cat][entry.group].append(entry)
                            assigned = True
                            break
                    
                    if not assigned:
                        remaining_entries.append(entry)
                else:
                    remaining_entries.append(entry)
                pbar.update(1)

            # Second pass: categorize remaining entries
            for entry in remaining_entries:
                assigned = False
                desc = (entry.description or '').lower()
                url = entry.url.lower()

                # Try to match with main categories first
                for main_cat, config in self.hierarchy.items():
                    if any(keyword in desc or keyword in url for keyword in config['keywords']):
                        # Try to find appropriate subcategory
                        for subcat in config['subcategories']:
                            if any(keyword in desc or keyword in url 
                                  for keyword in subcat.lower().split()):
                                if subcat not in categorized[main_cat]:
                                    categorized[main_cat][subcat] = []
                                categorized[main_cat][subcat].append(entry)
                                assigned = True
                                break
                        
                        if not assigned:
                            # Put in "Other" subcategory
                            other_cat = f"Other {main_cat}"
                            if other_cat not in categorized[main_cat]:
                                categorized[main_cat][other_cat] = []
                            categorized[main_cat][other_cat].append(entry)
                            assigned = True
                        break

                if not assigned:
                    categorized["Miscellaneous"]["Uncategorized"].append(entry)

        # Clean up empty categories
        return {
            main_cat: subcats for main_cat, subcats in categorized.items()
            if any(entries for entries in subcats.values())
        }

    def write_markdown(self, categories: Dict[str, Dict[str, List[WebLink]]], output_file: str):
        """Write organized links to markdown file."""
        with open(output_file, 'w', encoding='utf-8') as f:
            # Write header with metadata
            total_links = sum(
                len(entries) 
                for cat in categories.values() 
                for entries in cat.values()
            )
            total_subcats = sum(len(subcats) for subcats in categories.values())
            
            f.write("# Organized Web Links\n\n")
            f.write(f"*Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*\n")
            f.write(f"*Total Links: {total_links} in {total_subcats} subcategories*\n\n")
            
            # Table of Contents
            f.write("## Table of Contents\n\n")
            for main_cat in sorted(categories.keys()):
                if not categories[main_cat]:
                    continue
                
                main_anchor = self.make_anchor(main_cat)
                cat_count = sum(len(entries) for entries in categories[main_cat].values())
                f.write(f"- [**{main_cat}**](#{main_anchor}) ({cat_count} links)\n")
                
                for subcat in sorted(categories[main_cat].keys()):
                    subcat_anchor = f"{main_anchor}-{self.make_anchor(subcat)}"
                    subcat_count = len(categories[main_cat][subcat])
                    f.write(f"  - [{subcat}](#{subcat_anchor}) ({subcat_count} links)\n")
            
            f.write("\n---\n\n")
            
            # Write categories and links
            for main_cat in sorted(categories.keys()):
                if not categories[main_cat]:
                    continue
                
                f.write(f"# {main_cat}\n\n")
                
                for subcat in sorted(categories[main_cat].keys()):
                    entries = categories[main_cat][subcat]
                    if not entries:
                        continue
                    
                    f.write(f"## {subcat}\n\n")
                    
                    # Sort entries
                    sorted_entries = sorted(
                        entries,
                        key=lambda e: (e.description or '').lower() or e.url.lower()
                    )
                    
                    for entry in sorted_entries:
                        if entry.description and entry.description != entry.url:
                            f.write(f"- {entry.description}: {entry.url}\n")
                        else:
                            f.write(f"- {entry.url}\n")
                    
                    f.write("\n")

    @staticmethod
    def make_anchor(text: str) -> str:
        """Create valid markdown anchor from text."""
        return re.sub(r'[^a-z0-9-]', '', text.lower().replace(' ', '-'))

    @staticmethod
    def default_hierarchy() -> dict:
        """Default category hierarchy."""
        return {
            "Development Resources": {
                "subcategories": [
                    "GitHub Repositories",
                    "API Documentation",
                    "Development Tools",
                    "Code Libraries",
                    "Stack Exchange Resources"
                ],
                "keywords": [
                    "github", "api", "code", "dev", "sdk", "library",
                    "framework", "stack", "overflow", "git", "repo"
                ]
            },
            "Web Development": {
                "subcategories": [
                    "Frontend Frameworks",
                    "CSS Resources",
                    "JavaScript Libraries",
                    "Web Design Tools",
                    "UI/UX Resources"
                ],
                "keywords": [
                    "css", "html", "javascript", "js", "web", "frontend",
                    "react", "vue", "angular", "design", "ui", "ux"
                ]
            },
            "DevOps & Infrastructure": {
                "subcategories": [
                    "Cloud Services",
                    "Deployment Tools",
                    "Monitoring Solutions",
                    "Container Resources",
                    "CI/CD Tools"
                ],
                "keywords": [
                    "cloud", "aws", "azure", "gcp", "docker", "kubernetes",
                    "devops", "ci/cd", "pipeline", "infrastructure"
                ]
            },
            "Learning Resources": {
                "subcategories": [
                    "Tutorials",
                    "Online Courses",
                    "Documentation",
                    "Learning Platforms",
                    "Educational Resources"
                ],
                "keywords": [
                    "learn", "tutorial", "course", "education", "training",
                    "doc", "guide", "how-to", "lesson"
                ]
            }
        }

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Organize web links into a hierarchical markdown structure.'
    )
    parser.add_argument(
        '-i', '--input',
        type=str,
        default='weblinks.txt',
        help='Input file containing web links (default: weblinks.txt)'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='organized_links.md',
        help='Output markdown file (default: organized_links.md)'
    )
    parser.add_argument(
        '-c', '--config',
        type=str,
        help='Path to YAML configuration file'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable URL cache'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    return parser.parse_args()

async def main():
    """Main function with async support and progress tracking."""
    args = parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Initialize organizer
        logger.info("Initializing WebLinkOrganizer...")
        organizer = WebLinkOrganizer(args.config)
        
        # Parse input file
        logger.info(f"Parsing links from {args.input}...")
        entries = organizer.parse_links(args.input)
        logger.info(f"Found {len(entries)} links")
        
        # Fetch missing titles
        if not args.no_cache:
            logger.info("Fetching missing titles...")
            entries = await organizer.fetch_missing_titles(entries)
        
        # Categorize entries
        logger.info("Categorizing entries...")
        categories = organizer.categorize_entries(entries)
        
        # Write output
        logger.info(f"Writing organized links to {args.output}...")
        organizer.write_markdown(categories, args.output)
        
        logger.info("Done!")
        
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        if args.debug:
            logger.exception("Detailed error information:")
        sys.exit(1)

if __name__ == "__main__":
    # Run async main
    asyncio.run(main())