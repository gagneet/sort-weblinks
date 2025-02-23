import asyncio
import aiohttp
from typing import Tuple, Set
from urllib.parse import urlparse
from tqdm import tqdm
import logging

logger = logging.getLogger(__name__)

class URLValidator:
    def __init__(self, timeout: int = 10, max_workers: int = 10):
        self.timeout = timeout
        self.max_workers = max_workers
        self.valid_domains = {
            'github.com', 'www.github.com',
            'gitlab.com', 'www.gitlab.com',
            'bitbucket.org', 'www.bitbucket.org',
            'stackoverflow.com', 'www.stackoverflow.com',
            'docs.google.com',
            'medium.com', 'www.medium.com'
        }

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