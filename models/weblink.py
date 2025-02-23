from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

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