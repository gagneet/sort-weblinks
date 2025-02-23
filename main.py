import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Tuple
from argparse import ArgumentParser

from .services.organizer import WebLinkOrganizer

logger = logging.getLogger(__name__)

def parse_args():
    """Parse command line arguments."""
    parser = ArgumentParser(
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
        initial_count = len(entries)
        logger.info(f"Found {initial_count} links")
        
        # Track unique URLs
        unique_urls = len({entry.url for entry in entries})
        logger.info(f"Found {unique_urls} unique URLs (removed {initial_count - unique_urls} duplicates)")
        
        # Rest of your existing main function code...
        
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        if args.debug:
            logger.exception("Detailed error information:")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())