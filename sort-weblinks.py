import re
import sys
import os
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
from typing import List, Tuple, Set
from urllib.parse import urlparse
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
import requests
import time
from datetime import datetime, UTC  # Add UTC import at the top of the file
import argparse
from tqdm import tqdm


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

class URLValidator:
    def __init__(self, timeout: int = 10, max_workers: int = 10):
        self.timeout = timeout
        self.max_workers = max_workers
        
    async def check_url_validity(self, url: str) -> Tuple[str, bool]:
        """Check if a URL is valid and accessible."""
        try:
            # First validate URL format
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                return url, False

            # Define common valid domains that might block HEAD requests
            VALID_DOMAINS = {
                'github.com', 'www.github.com',
                'gitlab.com', 'www.gitlab.com',
                'bitbucket.org', 'www.bitbucket.org',
                'stackoverflow.com', 'www.stackoverflow.com',
                'docs.google.com',
                'medium.com', 'www.medium.com'
            }

            # If the domain is in our trusted list, consider it valid
            if result.netloc in VALID_DOMAINS:
                return url, True

            # Then check if URL is accessible
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    # Try HEAD request first
                    async with session.head(url, allow_redirects=True) as response:
                        return url, 200 <= response.status < 400
                except:
                    # If HEAD fails, try GET
                    try:
                        async with session.get(url, allow_redirects=True) as response:
                            return url, 200 <= response.status < 400
                    except:
                        # For HTTPS URLs that fail, try HTTP
                        if url.startswith('https://'):
                            http_url = 'http://' + url[8:]
                            try:
                                async with session.get(http_url, allow_redirects=True) as response:
                                    return url, 200 <= response.status < 400
                            except:
                                pass
                        return url, False
        except Exception as e:
            logger.debug(f"URL validation error for {url}: {str(e)}")
            # Consider URLs with valid format as potentially valid even if we can't connect
            if all([result.scheme, result.netloc]):
                return url, True
            return url, False

    async def validate_urls_batch(self, urls: Set[str], pbar: Optional[tqdm] = None) -> dict:
        """Validate a batch of URLs concurrently."""
        tasks = [self.check_url_validity(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update progress bar if provided
        if pbar is not None:
            pbar.update(len(urls))
            
        return {
            url: valid for url,
			valid in results 
            if not isinstance(valid, Exception)
        }

class WebLinkOrganizer:
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the WebLinkOrganizer with configuration."""
        # First load the configuration
        self.config = self.load_config(config_path)
        # Extract settings and hierarchy from config
        self.settings = self.config.get('settings', {})
        self.hierarchy = self.config.get('categories', self.default_hierarchy())
        # Initialize validator with more lenient timeout, cache and session
        self.url_validator = URLValidator(timeout=10)  # Increased timeout
        self.invalid_links = []  # Store invalid links
        self.cache_file = Path('url_cache.json')
        self.url_cache = self.load_cache()
        self.session = self.create_session()

    async def validate_all_links(self, entries: List[WebLink]) -> Tuple[List[WebLink], List[WebLink]]:
        """Validate all URLs and separate valid from invalid links."""
        unique_urls = {entry.url for entry in entries}
        total_urls = len(unique_urls)
        
        # Create progress bar for URL validation
        with tqdm(total=total_urls, 
                 desc="Validating URLs", 
                 unit="url",
                 bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} URLs [{elapsed}<{remaining}]') as pbar:
            
            # Process URLs in batches
            batch_size = 50
            url_batches = [list(unique_urls)[i:i + batch_size] 
                          for i in range(0, len(unique_urls), batch_size)]
            
            validity_map = {}
            for batch in url_batches:
                batch_results = await self.url_validator.validate_urls_batch(set(batch), pbar)
                validity_map.update(batch_results)
            
            # Create secondary progress bar for processing entries
            with tqdm(total=len(entries), 
                     desc="Processing entries", 
                     unit="entry",
                     leave=False) as entry_pbar:
                
                valid_entries = []
                invalid_entries = []
                
                for entry in entries:
                    if validity_map.get(entry.url, False):
                        valid_entries.append(entry)
                    else:
                        invalid_entries.append(entry)
                    entry_pbar.update(1)
        
        # Print summary
        logger.info(f"Validation complete: {len(valid_entries)} valid, {len(invalid_entries)} invalid URLs")
        return valid_entries, invalid_entries

    def _categorize_chunk(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """Process a chunk of entries for categorization."""
        # Initialize categories including custom ones from entries
        categorized = {main_cat: {} for main_cat in self.hierarchy.keys()}
        custom_categories = {
            entry.group: {"General": []} 
            for entry in entries 
            if entry.group and entry.group not in self.hierarchy
        }
        categorized.update(custom_categories)
        categorized["Uncategorized"] = {"General": []}

        for entry in entries:
            assigned = False
            desc = (entry.description or '').lower()
            url = entry.url.lower()

            # First: Use original group if it exists
            if entry.group:
                group = entry.group
                if group in categorized:
                    if "General" not in categorized[group]:
                        categorized[group]["General"] = []
                    categorized[group]["General"].append(entry)
                    assigned = True

            # Second: Try automatic categorization if not assigned
            if not assigned:
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

            # Last resort: Uncategorized
            if not assigned:
                categorized["Uncategorized"]["General"].append(entry)

        return categorized

    @staticmethod
    def load_config(config_path: Optional[str]) -> dict:
        """Load configuration from YAML file or use defaults."""
        default_config = {
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
        
        if config_path:
            try:
                config_path = Path(config_path)
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        loaded_config = yaml.safe_load(f)
                        if not loaded_config:
                            logger.warning("Empty configuration file, using defaults")
                            return default_config
                        
                        # Merge with defaults to ensure all required settings exist
                        merged_config = {
                            'settings': {**default_config['settings'], **loaded_config.get('settings', {})},
                            'categories': loaded_config.get('categories', default_config['categories'])
                        }
                        return merged_config
                else:
                    logger.warning(f"Config file not found: {config_path}")
                    return default_config
            except Exception as e:
                logger.warning(f"Failed to load config file: {e}")
                return default_config
        
        logger.info("Using default configuration")
        return default_config

    def create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        max_retries = self.settings.get('max_retries', 3)
        retries = Retry(
            total=max_retries,
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
            # Check for group header (now handles more formats)
            if (line.endswith(':') or line.startswith('#')) and 'http' not in line:
                # Clean up the group name
                current_group = line.strip('# :').strip()
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
        """
        Categorize entries with following priority:
        1. Try automatic categorization first
        2. If that fails, use original group from input file
        3. If no group exists, put in Uncategorized
        """
        with tqdm(total=len(entries), desc="Categorizing entries", unit="link") as pbar:
            # Initialize categories
            categorized = {main_cat: {} for main_cat in self.hierarchy.keys()}
            categorized["Uncategorized"] = {"General": []}

            for entry in entries:
                assigned = False
                desc = (entry.description or '').lower()
                url = entry.url.lower()

                # First attempt: Try automatic categorization
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

                # Second attempt: Use original group if automatic categorization failed
                if not assigned and entry.group:
                    group = entry.group
                    # Check if this group matches any main category
                    for main_cat in self.hierarchy.keys():
                        if main_cat.lower() == group.lower():
                            if "General" not in categorized[main_cat]:
                                categorized[main_cat]["General"] = []
                            categorized[main_cat]["General"].append(entry)
                            assigned = True
                            break

                    # If not a main category, create it as a new top-level category
                    if not assigned:
                        if group not in categorized:
                            categorized[group] = {}
                        if "General" not in categorized[group]:
                            categorized[group]["General"] = []
                        categorized[group]["General"].append(entry)
                        assigned = True

                # Last resort: Uncategorized
                if not assigned:
                    categorized["Uncategorized"]["General"].append(entry)

                pbar.update(1)

            # Sort entries within each subcategory
            for main_cat in categorized:
                for subcat in categorized[main_cat]:
                    categorized[main_cat][subcat].sort(
                        key=lambda e: (
                            e.description.lower() if e.description else e.url.lower(),
                            e.url.lower()
                        )
                    )

            # Clean up and sort categories
            filtered_categories = {}
            # Sort main categories alphabetically (keeping Uncategorized for last)
            main_cats = sorted(
                [cat for cat in categorized.keys() if cat != "Uncategorized"]
            )
            if "Uncategorized" in categorized:
                main_cats.append("Uncategorized")

            # Create final sorted structure
            for main_cat in main_cats:
                if any(entries for entries in categorized[main_cat].values()):
                    # Sort subcategories
                    filtered_subcats = {
                        subcat: entries 
                        for subcat, entries in sorted(
                            categorized[main_cat].items(),
                            key=lambda x: (
                                # Sort "General" first, "Other" last, rest alphabetically
                                0 if x[0] == "General" else 
                                2 if x[0].startswith("Other") else 
                                1,
                                x[0].lower()
                            )
                        )
                        if entries
                    }
                    if filtered_subcats:
                        filtered_categories[main_cat] = filtered_subcats

            return filtered_categories

    def categorize_entries_parallel(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """Categorize entries using parallel processing if the number of entries is above threshold."""
        PARALLEL_THRESHOLD = 50  # Only use parallel processing for 50+ entries
        
        if len(entries) < PARALLEL_THRESHOLD:
            return self.categorize_entries(entries)
        
        # Determine optimal chunk size
        chunk_size = max(10, len(entries) // (os.cpu_count() or 1))
        chunks = [entries[i:i + chunk_size] for i in range(0, len(entries), chunk_size)]
        
        # Process chunks in parallel
        with concurrent.futures.ProcessPoolExecutor() as executor:
            chunk_results = list(executor.map(self._categorize_chunk, chunks))
        
        # Merge results
        merged = {main_cat: {} for main_cat in self.hierarchy.keys()}
        merged["Uncategorized"] = {"General": []}
        
        # First, collect all unique categories and subcategories
        all_categories = set()
        all_subcategories = {}
        
        for result in chunk_results:
            for main_cat in result:
                all_categories.add(main_cat)
                if main_cat not in all_subcategories:
                    all_subcategories[main_cat] = set()
                all_subcategories[main_cat].update(result[main_cat].keys())
        
        # Initialize the structure with all discovered categories
        for cat in all_categories:
            if cat not in merged:
                merged[cat] = {}
            for subcat in all_subcategories.get(cat, []):
                if subcat not in merged[cat]:
                    merged[cat][subcat] = []
        
        # Merge the entries
        for result in chunk_results:
            for main_cat, subcats in result.items():
                for subcat, entries in subcats.items():
                    merged[main_cat][subcat].extend(entries)
        
        # Sort entries within each subcategory
        for main_cat in merged:
            for subcat in merged[main_cat]:
                merged[main_cat][subcat].sort(
                    key=lambda e: (
                        e.description.lower() if e.description else e.url.lower(),
                        e.url.lower()
                    )
                )
        
        # Create final sorted structure
        filtered_categories = {}
        main_cats = sorted(
            [cat for cat in merged.keys() if cat != "Uncategorized"]
        )
        if "Uncategorized" in merged:
            main_cats.append("Uncategorized")
        
        for main_cat in main_cats:
            if any(entries for entries in merged[main_cat].values()):
                filtered_subcats = {
                    subcat: entries 
                    for subcat, entries in sorted(
                        merged[main_cat].items(),
                        key=lambda x: (
                            0 if x[0] == "General" else 
                            2 if x[0].startswith("Other") else 
                            1,
                            x[0].lower()
                        )
                    )
                    if entries
                }
                if filtered_subcats:
                    filtered_categories[main_cat] = filtered_subcats
        
        return filtered_categories

    def write_markdown(self, categories: Dict[str, Dict[str, List[WebLink]]], invalid_links: List[WebLink], output_file: str):
        """Write organized links to markdown file with sorted categories and entries, including invalid links section."""
        with open(output_file, 'w', encoding='utf-8') as f:
            # Write header with metadata
            total_links = sum(
                len(entries) 
                for cat in categories.values() 
                for entries in cat.values()
            )
            total_subcats = sum(len(subcats) for subcats in categories.values())
            
            f.write("# Organized Web Links\n\n")
            f.write(f"*Generated on {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC*\n")
            f.write(f"*Total Links: {total_links} in {total_subcats} subcategories*\n\n")
            
            # Table of Contents
            f.write("## Table of Contents\n\n")
            
            # Sort main categories (keeping Uncategorized last)
            main_categories = sorted(
                [cat for cat in categories.keys() if cat != "Uncategorized"]
            )
            if "Uncategorized" in categories:
                main_categories.append("Uncategorized")

            for main_cat in main_categories:
                if not categories[main_cat]:
                    continue
                
                main_anchor = self.make_anchor(main_cat)
                cat_count = sum(len(entries) for entries in categories[main_cat].values())
                f.write(f"- [**{main_cat}**](#{main_anchor}) ({cat_count} links)\n")
                
                # Sort subcategories
                subcats = sorted(
                    categories[main_cat].keys(),
                    key=lambda x: (
                        # Sort "General" first, "Other" last, rest alphabetically
                        0 if x == "General" else 
                        2 if x.startswith("Other") else 
                        1,
                        x.lower()
                    )
                )
                
                for subcat in subcats:
                    subcat_anchor = f"{main_anchor}-{self.make_anchor(subcat)}"
                    subcat_count = len(categories[main_cat][subcat])
                    f.write(f"  - [{subcat}](#{subcat_anchor}) ({subcat_count} links)\n")
            
            f.write("\n---\n\n")
            
            # Write categories and links
            for main_cat in main_categories:
                if not categories[main_cat]:
                    continue
                
                f.write(f"# {main_cat}\n\n")
                
                # Sort subcategories
                subcats = sorted(
                    categories[main_cat].keys(),
                    key=lambda x: (
                        0 if x == "General" else 
                        2 if x.startswith("Other") else 
                        1,
                        x.lower()
                    )
                )
                
                for subcat in subcats:
                    entries = categories[main_cat][subcat]
                    if not entries:
                        continue
                    
                    f.write(f"## {subcat}\n\n")
                    
                    # Sort entries
                    sorted_entries = sorted(
                        entries,
                        key=lambda e: (
                            (e.description or '').lower() or e.url.lower(),
                            e.url.lower()
                        )
                    )

                    for entry in sorted_entries:
                        if entry.description and entry.description != entry.url:
                            f.write(f"- {entry.description}: {entry.url}\n")
                        else:
                            f.write(f"- {entry.url}\n")
                    
                    f.write("\n")

            # Add invalid links section at the end if there are any
            if invalid_links:
                f.write("\n# Links Not Working\n\n")
                for entry in sorted(invalid_links, key=lambda e: (e.description or '').lower() or e.url.lower()):
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
    """Enhanced main function with async support and progress tracking, including URL validation and parallel processing."""
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
        
        # Validate URLs
        logger.info("Validating URLs...")
        valid_entries, invalid_entries = await organizer.validate_all_links(entries)
        logger.info(f"Found {len(valid_entries)} valid and {len(invalid_entries)} invalid links")
        
        # Fetch missing titles for valid links
        if not args.no_cache:
            logger.info("Fetching missing titles...")
            valid_entries = await organizer.fetch_missing_titles(valid_entries)
        
        # Categorize entries
        logger.info("Categorizing entries...")
        if len(valid_entries) >= 1000:  # Use parallel processing for larger sets
            logger.info("Using parallel processing for categorization...")
            categories = organizer.categorize_entries_parallel(valid_entries)
        else:
            logger.info("Using single-threaded processing for categorization...")
            categories = organizer.categorize_entries(valid_entries)
        
        # Write output including invalid links section
        logger.info(f"Writing organized links to {args.output}...")
        organizer.write_markdown(categories, invalid_entries, args.output)
        
        logger.info("Done!")
        
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        if args.debug:
            logger.exception("Detailed error information:")
        sys.exit(1)

if __name__ == "__main__":
    # Run async main
    asyncio.run(main())