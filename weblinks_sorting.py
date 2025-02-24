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
# Add required imports at the top of your file
import multiprocessing
from logging.handlers import QueueHandler, QueueListener

# Configure logging
"""logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)"""


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
        self.logger = logging.getLogger(__name__)

    async def check_url_validity(self, url: str) -> Tuple[str, bool]:
        """Check if a URL is valid and accessible."""
        result = urlparse(url)
        try:
            # First validate URL format
            if not all([result.scheme, result.netloc]):
                return url, False

            # Define common valid domains that might block HEAD requests
            valid_domains = {
                'github.com', 'www.github.com',
                'gitlab.com', 'www.gitlab.com',
                'bitbucket.org', 'www.bitbucket.org',
                'stackoverflow.com', 'www.stackoverflow.com',
                'docs.google.com',
                'medium.com', 'www.medium.com'
            }

            # If the domain is in our trusted list, consider it valid
            if result.netloc in valid_domains:
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
            self.logger.debug(f"URL validation error for {url}: {str(e)}")
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
        self.logger = logging.getLogger(__name__)
        # First load the configuration
        self.config = self.load_config(config_path)
        # Extract settings and hierarchy from config
        self.settings = self.config.get('settings', {})
        self.hierarchy = self.config.get('categories', {})
        # Initialize validator with more lenient timeout
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
        self.logger.info(f"Validation complete: {len(valid_entries)} valid, {len(invalid_entries)} invalid URLs")
        return valid_entries, invalid_entries

    def calculate_category_score(self, url: str, description: str, category_config: dict) -> Tuple[float, List[str]]:
        """
        Calculate how well a URL and description match a category's keywords.
        Returns a tuple of (score, matching_keywords).
        """
        logger = logging.getLogger(__name__)
        url = url.lower()
        description = description.lower()
        score = 0
        matching_keywords = []

        # Get weights from config
        settings = self.config['settings']['categorization']
        url_weight = settings.get('url_match_weight', 3)
        desc_weight = settings.get('description_match_weight', 2)
        exact_bonus = settings.get('exact_match_bonus', 2)
        partial_weight = settings.get('partial_match_weight', 1)

        logger.debug(f"\nCalculating category score for:")
        logger.debug(f"URL: {url}")
        logger.debug(f"Description: {description}")

        def check_keyword_match(text: str, keyword: str, is_url: bool = False) -> Tuple[bool, bool]:
            """Check if keyword matches text exactly or partially."""
            keyword = keyword.lower()
            exact_match = f" {keyword} " in f" {text} " or text == keyword
            partial_match = keyword in text if not exact_match else False

            if exact_match or partial_match:
                weight = url_weight if is_url else desc_weight
                match_type = "exact" if exact_match else "partial"
                location = "URL" if is_url else "description"
                logger.debug(f"- Matched '{keyword}' ({match_type}) in {location}")

            return exact_match, partial_match

        # Check primary keywords (higher importance)
        primary_keywords = category_config.get('keywords', {}).get('primary', [])
        for keyword in primary_keywords:
            # Check URL
            exact_match, partial_match = check_keyword_match(url, keyword, is_url=True)
            if exact_match:
                score += url_weight * exact_bonus
                matching_keywords.append(f"{keyword}(url,exact)")
            elif partial_match:
                score += url_weight * partial_weight
                matching_keywords.append(f"{keyword}(url,partial)")

            # Check description
            exact_match, partial_match = check_keyword_match(description, keyword)
            if exact_match:
                score += desc_weight * exact_bonus
                matching_keywords.append(f"{keyword}(desc,exact)")
            elif partial_match:
                score += desc_weight * partial_weight
                matching_keywords.append(f"{keyword}(desc,partial)")

        # Check secondary keywords (lower importance)
        secondary_keywords = category_config.get('keywords', {}).get('secondary', [])
        for keyword in secondary_keywords:
            # Check URL
            exact_match, partial_match = check_keyword_match(url, keyword, is_url=True)
            if exact_match:
                score += (url_weight * exact_bonus) / 2
                matching_keywords.append(f"{keyword}(url,exact,secondary)")
            elif partial_match:
                score += (url_weight * partial_weight) / 2
                matching_keywords.append(f"{keyword}(url,partial,secondary)")

            # Check description
            exact_match, partial_match = check_keyword_match(description, keyword)
            if exact_match:
                score += (desc_weight * exact_bonus) / 2
                matching_keywords.append(f"{keyword}(desc,exact,secondary)")
            elif partial_match:
                score += (desc_weight * partial_weight) / 2
                matching_keywords.append(f"{keyword}(desc,partial,secondary)")

        # Check exclude keywords (negative impact)
        exclude_keywords = category_config.get('keywords', {}).get('exclude', [])
        for keyword in exclude_keywords:
            if keyword in url or keyword in description:
                score -= url_weight
                logger.debug(f"- Found exclude keyword '{keyword}' (-{url_weight} points)")

        logger.debug(f"Final score: {score}")
        if matching_keywords:
            logger.debug(f"Matching keywords: {', '.join(matching_keywords)}")

        return score, matching_keywords

    def _categorize_chunk(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """Process a chunk of entries for categorization."""
        logger = logging.getLogger(__name__)

        # Initialize categories including custom ones from entries
        categorized = {main_cat: {} for main_cat in self.hierarchy.keys()}
        custom_categories = {
            entry.group: {"General": []}
            for entry in entries
            if entry.group and entry.group not in self.hierarchy
        }
        categorized.update(custom_categories)
        categorized["Uncategorized"] = {"General": []}

        # Track assigned URLs to prevent duplicates
        assigned_urls = set()

        for entry in entries:
            if entry.url in assigned_urls:
                logger.debug(f"\nSkipping duplicate URL: {entry.url}")
                continue

            desc = (entry.description or '').lower()
            url = entry.url.lower()

            logger.debug(f"\n{'=' * 50}")
            logger.debug(f"Processing URL: {entry.url}")
            logger.debug(f"Description: {entry.description}")
            logger.debug(f"Original group: {entry.group}")

            assigned = False

            # First: Use original group if it exists
            if entry.group:
                group = entry.group
                if group in categorized:
                    if "General" not in categorized[group]:
                        categorized[group]["General"] = []
                    categorized[group]["General"].append(entry)
                    assigned_urls.add(entry.url)
                    assigned = True
                    logger.debug(f"Assigned to original group: {group}")
                    continue

            # Calculate scores for all categories
            category_scores = {}
            logger.debug("\nCategory scoring:")
            for main_cat, config in self.hierarchy.items():
                score, keywords = self.calculate_category_score(url, desc, config)
                if score >= self.config['settings']['categorization']['min_score_threshold']:
                    category_scores[main_cat] = {
                        'score': score,
                        'keywords': keywords
                    }
                    logger.debug(f"- {main_cat}: score={score}, keywords={', '.join(keywords)}")

            if category_scores:
                # Get best category
                best_category = max(category_scores.items(), key=lambda x: x[1]['score'])[0]
                logger.debug(f"\nBest matching category: {best_category}")

                # Find best subcategory
                best_subcat = None
                best_subcat_score = 0

                logger.debug("\nSubcategory scoring:")
                for subcat in self.hierarchy[best_category]['subcategories']:
                    subcat_score, subcat_keywords = self.calculate_category_score(
                        url, desc,
                        {'keywords': {'primary': self.hierarchy[best_category]['subcategories'][subcat]['keywords']}}
                    )

                    logger.debug(f"- {subcat}: score={subcat_score}, keywords={', '.join(subcat_keywords)}")

                    if subcat_score > best_subcat_score:
                        best_subcat_score = subcat_score
                        best_subcat = subcat

                # Assign to category/subcategory
                if best_subcat:
                    if best_subcat not in categorized[best_category]:
                        categorized[best_category][best_subcat] = []
                    categorized[best_category][best_subcat].append(entry)
                    logger.debug(f"\nAssigned to: {best_category}/{best_subcat}")
                else:
                    other_cat = f"Other {best_category}"
                    if other_cat not in categorized[best_category]:
                        categorized[best_category][other_cat] = []
                    categorized[best_category][other_cat].append(entry)
                    logger.debug(f"\nAssigned to: {best_category}/{other_cat}")

                assigned_urls.add(entry.url)
                continue

            # Last resort: Uncategorized
            if not assigned:
                categorized["Uncategorized"]["General"].append(entry)
                assigned_urls.add(entry.url)
                logger.debug("\nNo category found, assigned to: Uncategorized/General")

        return categorized

    @staticmethod
    def default_hierarchy() -> dict:
        """Default category hierarchy."""
        return {
            "Development Resources": {
                "subcategories": {
                    "GitHub Repositories": {
                        "keywords": ["github.com", "repository", "repo", "git"]
                    },
                    "API Documentation": {
                        "keywords": ["api", "swagger", "openapi", "documentation", "docs"]
                    },
                    "Development Tools": {
                        "keywords": ["tool", "ide", "editor", "compiler", "debug"]
                    },
                    "Code Libraries": {
                        "keywords": ["library", "package", "module", "dependency", "npm", "pip"]
                    },
                    "Stack Exchange Resources": {
                        "keywords": ["stackoverflow", "stackexchange", "superuser", "serverfault"]
                    }
                },
                "keywords": {
                    "primary": ["github.com", "gitlab.com", "bitbucket.org", "stackoverflow.com", "docs.github"],
                    "secondary": ["git", "repo", "api", "sdk", "dev", "code", "library", "framework"],
                    "exclude": ["blog", "article"]
                }
            },
            "Web Development": {
                "subcategories": {
                    "Frontend Frameworks": {
                        "keywords": ["react", "vue", "angular", "svelte", "nextjs", "nuxt"]
                    },
                    "CSS Resources": {
                        "keywords": ["css", "sass", "less", "stylesheet", "tailwind", "bootstrap"]
                    },
                    "JavaScript Libraries": {
                        "keywords": ["javascript", "js", "typescript", "npm", "yarn", "jquery"]
                    },
                    "Web Design Tools": {
                        "keywords": ["figma", "sketch", "adobe xd", "webflow"]
                    },
                    "UI/UX Resources": {
                        "keywords": ["ui", "ux", "design", "wireframe", "prototype"]
                    }
                },
                "keywords": {
                    "primary": ["react", "vue", "angular", "nodejs", "webpack"],
                    "secondary": ["css", "html", "javascript", "js", "web", "frontend", "backend"],
                    "exclude": ["article", "tutorial"]
                }
            },
            "DevOps & Infrastructure": {
                "subcategories": {
                    "Cloud Services": {
                        "keywords": ["aws", "azure", "gcp", "cloud", "serverless"]
                    },
                    "Deployment Tools": {
                        "keywords": ["deploy", "jenkins", "circleci", "travis", "gitlab-ci"]
                    },
                    "Monitoring Solutions": {
                        "keywords": ["monitor", "grafana", "prometheus", "nagios", "zabbix"]
                    },
                    "Container Resources": {
                        "keywords": ["docker", "kubernetes", "k8s", "container", "pod"]
                    },
                    "CI/CD Tools": {
                        "keywords": ["ci", "cd", "pipeline", "automation", "github-actions"]
                    }
                },
                "keywords": {
                    "primary": ["cloud", "aws", "azure", "gcp", "docker", "kubernetes"],
                    "secondary": ["devops", "ci/cd", "pipeline", "infrastructure"],
                    "exclude": ["blog"]
                }
            },
            "Learning Resources": {
                "subcategories": {
                    "Tutorials": {
                        "keywords": ["tutorial", "guide", "how-to", "walkthrough"]
                    },
                    "Online Courses": {
                        "keywords": ["course", "class", "lesson", "udemy", "coursera", "edx"]
                    },
                    "Documentation": {
                        "keywords": ["doc", "docs", "documentation", "manual", "reference"]
                    },
                    "Learning Platforms": {
                        "keywords": ["academy", "learning", "platform", "mooc", "education"]
                    }
                },
                "keywords": {
                    "primary": ["course", "learn", "tutorial", "training"],
                    "secondary": ["guide", "handbook", "documentation", "example", "lesson"],
                    "exclude": ["changelog", "release"]
                }
            }
        }

    @staticmethod
    def load_config(config_path: Optional[str]) -> dict:
        """Load configuration from YAML file or use defaults."""
        logger = logging.getLogger(__name__)
        default_config = {
            'settings': {
                'timeout': 5,
                'max_retries': 3,
                'concurrent_requests': 10,
                'cache_duration': 86400,  # 24 hours
                'fetch_titles': True,
                'categorization': {
                    'min_score_threshold': 3,
                    'url_match_weight': 3,
                    'description_match_weight': 2,
                    'exact_match_bonus': 2,
                    'partial_match_weight': 1
                }
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
        logger = logging.getLogger(__name__)
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
        logger = logging.getLogger(__name__)
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.url_cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    async def fetch_title(self, url: str) -> Optional[str]:
        """Fetch page title asynchronously with caching."""
        logger = logging.getLogger(__name__)
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
                else:
                    # Provide generic description based on URL
                    domain = entry.domain or urlparse(entry.url).netloc
                    if 'github.com' in entry.url:
                        parts = entry.url.strip('/').split('/')
                        if len(parts) >= 5:
                            owner, repo = parts[-2], parts[-1]
                            entry.description = f"GitHub: {owner}/{repo}"
                        else:
                            entry.description = "GitHub Repository"
                    else:
                        entry.description = f"Link from {domain}"

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
        logger = logging.getLogger(__name__)
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

    def _finalize_categories(self, categorized: Dict) -> Dict:
        """Helper method to sort and clean up categories."""
        logger = logging.getLogger(__name__)

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
                filtered_subcats = {
                    subcat: entries
                    for subcat, entries in sorted(
                        categorized[main_cat].items(),
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
                    logger.debug(f"\nFinalized category '{main_cat}' with {len(filtered_subcats)} subcategories")

        return filtered_categories

    def categorize_entries(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """
        Categorize entries with following priority:
        1. Try automatic categorization first
        2. If that fails, use original group from input file
        3. If no group exists, put in Uncategorized
        """
        logger = logging.getLogger(__name__)
        logger.debug("\nStarting categorization process...")

        with tqdm(total=len(entries), desc="Categorizing entries", unit="link") as pbar:
            # Initialize categories
            categorized = {main_cat: {} for main_cat in self.hierarchy.keys()}
            categorized["Uncategorized"] = {"General": []}

            for entry in entries:
                logger.debug(f"\n{'=' * 50}")
                logger.debug(f"Processing: {entry.url}")
                logger.debug(f"Description: {entry.description}")
                logger.debug(f"Original group: {entry.group}")

                assigned = False
                desc = (entry.description or '').lower()
                url = entry.url.lower()

                # First attempt: Try automatic categorization
                logger.debug("\nTrying automatic categorization:")
                for main_cat, config in self.hierarchy.items():
                    matching_keywords = []

                    # Check main category keywords
                    for keyword in config['keywords']:
                        if keyword in desc:
                            matching_keywords.append(f"{keyword}(desc)")
                        if keyword in url:
                            matching_keywords.append(f"{keyword}(url)")

                    if matching_keywords:
                        logger.debug(f"Category '{main_cat}' matches with keywords: {', '.join(matching_keywords)}")

                        # Try to find appropriate subcategory
                        best_subcat = None
                        best_subcat_score = 0
                        subcategory_matches = {}

                        for subcat in config['subcategories']:
                            subcat_keywords = []
                            score = 0

                            for keyword in subcat.lower().split():
                                if keyword in desc:
                                    score += 1
                                    subcat_keywords.append(f"{keyword}(desc)")
                                if keyword in url:
                                    score += 2
                                    subcat_keywords.append(f"{keyword}(url)")

                            if score > best_subcat_score:
                                best_subcat_score = score
                                best_subcat = subcat
                                subcategory_matches[subcat] = subcat_keywords

                        if subcategory_matches:
                            logger.debug("Subcategory matches:")
                            for subcat, keywords in subcategory_matches.items():
                                logger.debug(f"- {subcat}: {', '.join(keywords)}")

                        # Assign to the best subcategory or "Other"
                        if best_subcat:
                            if best_subcat not in categorized[main_cat]:
                                categorized[main_cat][best_subcat] = []
                            categorized[main_cat][best_subcat].append(entry)
                            logger.debug(f"Assigned to: {main_cat}/{best_subcat}")
                        else:
                            other_cat = f"Other {main_cat}"
                            if other_cat not in categorized[main_cat]:
                                categorized[main_cat][other_cat] = []
                            categorized[main_cat][other_cat].append(entry)
                            logger.debug(f"No specific subcategory found, assigned to: {main_cat}/{other_cat}")

                        assigned = True
                        break

                # Second attempt: Use original group if automatic categorization failed
                if not assigned and entry.group:
                    logger.debug("\nTrying original group categorization:")
                    group = entry.group
                    logger.debug(f"Original group: {group}")

                    # Check if this group matches any main category
                    for main_cat in self.hierarchy.keys():
                        if main_cat.lower() == group.lower():
                            if "General" not in categorized[main_cat]:
                                categorized[main_cat]["General"] = []
                            categorized[main_cat]["General"].append(entry)
                            assigned = True
                            logger.debug(f"Matched with main category: {main_cat}")
                            break

                    # If not a main category, create it as a new top-level category
                    if not assigned:
                        if group not in categorized:
                            categorized[group] = {}
                        if "General" not in categorized[group]:
                            categorized[group]["General"] = []
                        categorized[group]["General"].append(entry)
                        assigned = True
                        logger.debug(f"Created new category: {group}")

                # Last resort: Uncategorized
                if not assigned:
                    logger.debug("\nNo category found, assigning to Uncategorized")
                    categorized["Uncategorized"]["General"].append(entry)

                pbar.update(1)

            # Sort and clean up categories
            logger.debug("\nFinalizing categories and sorting entries...")
            filtered_categories = self._finalize_categories(categorized)
            logger.debug("Categorization complete!")

            return filtered_categories

    def categorize_entries_parallel(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """Categorize entries using parallel processing if the number of entries is above threshold."""
        logger = logging.getLogger(__name__)
        PARALLEL_THRESHOLD = 50  # Only use parallel processing for 50+ entries

        if len(entries) < PARALLEL_THRESHOLD:
            logger.debug("Using single-threaded processing (entries below threshold)")
            return self.categorize_entries(entries)

        # Determine optimal chunk size
        chunk_size = max(10, len(entries) // (os.cpu_count() or 1))
        chunks = [entries[i:i + chunk_size] for i in range(0, len(entries), chunk_size)]
        logger.debug(f"Split {len(entries)} entries into {len(chunks)} chunks of size ~{chunk_size}")

        # Process chunks in parallel
        logger.debug("Starting parallel processing of chunks")
        with concurrent.futures.ProcessPoolExecutor() as executor:
            chunk_results = list(executor.map(self._categorize_chunk, chunks))

        logger.debug("Merging results from parallel processing")
        # Merge results
        merged = {main_cat: {} for main_cat in self.hierarchy.keys()}
        merged["Uncategorized"] = {"General": []}

        # First, collect all unique categories and subcategories
        all_categories = set()
        all_subcategories = {}

        logger.debug("\nCollecting categories from chunks:")
        for i, result in enumerate(chunk_results):
            logger.debug(f"\nProcessing chunk {i + 1}/{len(chunks)}:")
            for main_cat in result:
                all_categories.add(main_cat)
                if main_cat not in all_subcategories:
                    all_subcategories[main_cat] = set()
                all_subcategories[main_cat].update(result[main_cat].keys())
                logger.debug(f"- Found category '{main_cat}' with subcategories: {', '.join(result[main_cat].keys())}")

        # Initialize the structure with all discovered categories
        logger.debug("\nInitializing category structure:")
        for cat in all_categories:
            if cat not in merged:
                merged[cat] = {}
                logger.debug(f"- Added main category: {cat}")
            for subcat in all_subcategories.get(cat, []):
                if subcat not in merged[cat]:
                    merged[cat][subcat] = []
                    logger.debug(f"  - Added subcategory: {cat}/{subcat}")

        # Merge the entries
        logger.debug("\nMerging entries from all chunks:")
        entry_counts = {cat: {subcat: 0 for subcat in subcats}
                        for cat, subcats in all_subcategories.items()}

        for result in chunk_results:
            for main_cat, subcats in result.items():
                for subcat, entries in subcats.items():
                    merged[main_cat][subcat].extend(entries)
                    entry_counts[main_cat][subcat] += len(entries)

        for main_cat, subcats in entry_counts.items():
            logger.debug(f"\nCategory '{main_cat}' entry counts:")
            for subcat, count in subcats.items():
                logger.debug(f"- {subcat}: {count} entries")

        # Sort entries within each subcategory
        logger.debug("\nSorting entries within categories:")
        for main_cat in merged:
            for subcat in merged[main_cat]:
                before_count = len(merged[main_cat][subcat])
                merged[main_cat][subcat].sort(
                    key=lambda e: (
                        e.description.lower() if e.description else e.url.lower(),
                        e.url.lower()
                    )
                )
                logger.debug(f"- Sorted {before_count} entries in {main_cat}/{subcat}")

        # Create final sorted structure
        logger.debug("\nCreating final sorted structure:")
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
                    logger.debug(f"- Finalized '{main_cat}' with {len(filtered_subcats)} subcategories")

        return filtered_categories

    def write_markdown(self, categories: Dict[str, Dict[str, List[WebLink]]], invalid_links: List[WebLink],
                       output_file: str):
        """Write organized links to markdown file with proper heading hierarchy."""
        with open(output_file, 'w', encoding='utf-8') as f:
            # Write main title and metadata
            f.write("# Organized Web Links\n\n")
            f.write(f"*Generated on {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC*\n")

            total_links = sum(
                len(entries)
                for cat in categories.values()
                for entries in cat.values()
            )
            total_subcats = sum(len(subcats) for subcats in categories.values())
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
                        0 if x == "General" else
                        2 if x.startswith("Other") else
                        1,
                        x.lower()
                    )
                )

                # Only show subcategories in TOC if there's more than just "General"
                if not (len(subcats) == 1 and subcats[0] == "General"):
                    for subcat in subcats:
                        subcat_anchor = f"{main_anchor}-{self.make_anchor(subcat)}"
                        subcat_count = len(categories[main_cat][subcat])
                        f.write(f"  - [{subcat}](#{subcat_anchor}) ({subcat_count} links)\n")

            f.write("\n---\n\n")

            # Write categories and links
            for main_cat in main_categories:
                if not categories[main_cat]:
                    continue

                f.write(f"## {main_cat}\n\n")

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

                # Check if category has only "General" subcategory
                only_general = len(subcats) == 1 and subcats[0] == "General"

                for subcat in subcats:
                    entries = categories[main_cat][subcat]
                    if not entries:
                        continue

                    # Only write subheader if it's not the only "General" subcategory
                    if not (only_general and subcat == "General"):
                        f.write(f"### {subcat}\n\n")

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

            # Add invalid links section at the end
            if invalid_links:
                f.write("## Links Not Working\n\n")
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

    """@staticmethod
    def default_hierarchy() -> dict:
        # Default category hierarchy.
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
        }"""


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


def setup_logging(debug: bool, log_queue: multiprocessing.Queue, log_file: str = "categorization.log"):
    """Setup logging configuration to output to both file and console with multiprocessing support."""
    # Get the root logger
    root_logger = logging.getLogger()

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    log_level = logging.DEBUG if debug else logging.INFO

    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(message)s')  # Simpler format for console

    # Setup queue handler for multiprocessing
    queue_handler = QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)
    root_logger.setLevel(logging.DEBUG)  # Capture all levels

    # Prevent propagation of messages to avoid duplicates
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)

    return root_logger


async def main():
    """Enhanced main function with async support and progress tracking, including URL validation and parallel processing."""
    args = parse_args()

    # Setup multiprocessing logging
    log_queue = multiprocessing.Queue()

    # Create and start the logging listener
    file_handler = logging.FileHandler('categorization.log', mode='w', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    console_handler.setLevel(logging.DEBUG if args.debug else logging.INFO)

    listener = QueueListener(
        log_queue,
        file_handler,
        console_handler,
        respect_handler_level=True
    )
    listener.start()

    # Setup logging
    logger = setup_logging(args.debug, log_queue)

    try:
        # Get current time in UTC
        current_time = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')

        # Log startup information
        logger.info(f"Starting weblinks organizer at {current_time} UTC")
        logger.info(f"User: {os.getlogin()}")

        # Initialize organizer
        logger.info("Initializing WebLinkOrganizer...")
        organizer = WebLinkOrganizer(args.config)

        # Parse input file
        logger.info(f"Parsing links from {args.input}...")
        entries = organizer.parse_links(args.input)
        initial_count = len(entries)
        logger.info(f"Found {initial_count} links")

        # Track unique URLs
        unique_urls = len({entry.url for entry in entries})
        logger.info(f"Found {unique_urls} unique URLs (removed {initial_count - unique_urls} duplicates)")

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
        if len(valid_entries) >= 5000:  # Use parallel processing for larger sets
            logger.info("Using parallel processing for categorization...")
            categories = organizer.categorize_entries_parallel(valid_entries)
        else:
            logger.info("Using single-threaded processing for categorization...")
            categories = organizer.categorize_entries(valid_entries)

        # Count categorized links
        categorized_count = sum(
            len(entries) for cat in categories.values()
            for entries in cat.values()
        )
        logger.info(f"""Link Processing Summary:
        Initial links found: {initial_count}
        Unique URLs: {unique_urls}
        Valid links: {len(valid_entries)}
        Invalid links: {len(invalid_entries)}
        Categorized links: {categorized_count}
        Links in final output: {categorized_count + len(invalid_entries)}
        """)

        # Write output including invalid links section
        logger.info(f"Writing organized links to {args.output}...")
        organizer.write_markdown(categories, invalid_entries, args.output)

        logger.info("Done!")

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        if args.debug:
            logger.exception("Detailed error information:")
        sys.exit(1)

    finally:
        listener.stop()


if __name__ == "__main__":
    # Run async main
    asyncio.run(main())
