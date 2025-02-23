import json
from pathlib import Path
import time
from typing import Dict

class CacheManager:
    def __init__(self, cache_file: Path, cache_duration: int = 86400):
        self.cache_file = cache_file
        self.cache_duration = cache_duration
        self.cache = self.load_cache()

    def load_cache(self) -> Dict:
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

    def get_cached_title(self, url: str) -> Optional[str]:
    """async def fetch_title(self, url: str) -> Optional[str]:"""
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

    def update_cache(self, url: str, title: str):
        title = title.strip()
        # Update cache
        self.url[cache_key] = {
            'title': title,
            'timestamp': current_time
        }
        return title