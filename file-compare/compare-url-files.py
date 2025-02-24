import re
from urllib.parse import urlparse

# Function to extract and normalize URL from a line
def extract_url(line):
    """Extracts URLs more accurately, handling prefixes."""
    # url_pattern = r'(https?://[^\s\'"<]+)'
    url_pattern = r'https?://[^\s\'"<]+'  # Focus on HTTP/HTTPS URLs
    match = re.search(url_pattern, line)
    if match:
        url = match.group(0).strip()
        # Normalize URL: lowercase, remove trailing slash, ignore query params if desired
        parsed = urlparse(url)
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".lower().rstrip('/')
        return normalized_url
    return None

# Read and process the files
def compare_files(file1_path, file2_path):
    def load_urls(file_path):
        urls = set()
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                url = extract_url(line.strip())
                if url:
                    urls.add(url)
                    # Debug: Print what URL was extracted from each line
                    print(f"Extracted from {file_path}: {url}")
        return urls

    # Load URLs from files
    urls_file1 = load_urls(file1_path)
    urls_file2 = load_urls(file2_path)

    # Compare the sets
    common_urls = urls_file1 & urls_file2  # Intersection
    only_in_file1 = urls_file1 - urls_file2  # In unsorted but not sorted
    only_in_file2 = urls_file2 - urls_file1  # In sorted but not unsorted

    # Print results
    print(f"\nTotal URLs in Unsorted File: {len(urls_file1)}")
    print(f"Total URLs in Sorted File: {len(urls_file2)}")
    print(f"Common URLs: {len(common_urls)}")
    print(f"URLs only in Unsorted File: {len(only_in_file1)}")
    print(f"URLs only in Sorted File: {len(only_in_file2)}")

    # Print differences
    if only_in_file1:
        print("\nURLs only in Unsorted File:")
        for url in sorted(only_in_file1):
            print(url)
    if only_in_file2:
        print("\nURLs only in Sorted File:")
        for url in sorted(only_in_file2):
            print(url)

# Usage
file1_path = "LinksOfInterest.txt"  # Replace with your unsorted file path
file2_path = "LinksOfInterest.md"   # Replace with your sorted file path
compare_files(file1_path, file2_path)
