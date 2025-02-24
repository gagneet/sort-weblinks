import re
from urllib.parse import urlparse
from collections import defaultdict


def extract_url(line):
    """Extracts URLs more accurately, handling prefixes."""
    url_pattern = r'https?://[^\s\'"<]+'
    match = re.search(url_pattern, line)
    if match:
        url = match.group(0).strip()
        parsed = urlparse(url)
        # Include query parameters but ignore fragments
        normalized_url = (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            f"{parsed.query and '?' + parsed.query or ''}"
        ).lower().rstrip('/')
        return normalized_url
    return None


def find_duplicates(file_path):
    """Find duplicate URLs and their line numbers in a file."""
    url_locations = defaultdict(list)
    original_lines = []

    with open(file_path, 'r', encoding='utf-8') as file:
        original_lines = file.readlines()
        for line_num, line in enumerate(original_lines, 1):
            url = extract_url(line.strip())
            if url:
                url_locations[url].append((line_num, line.strip()))

    # Filter only URLs that appear more than once
    duplicates = {url: lines for url, lines in url_locations.items() if len(lines) > 1}
    return duplicates, original_lines


def write_files_without_duplicates(file_path, original_lines, duplicates):
    """Write files separating unique and duplicate content."""
    base_name = file_path.rsplit('.', 1)[0]

    # Create set of line numbers that contain duplicates, excluding first occurrence
    duplicate_line_nums = {line_num for url_data in duplicates.values()
                           for line_num, _ in url_data[1:]}  # Only remove subsequent occurrences

    # Write file without duplicates (keeping first occurrence)
    with open(f"{base_name}_unique.md", 'w', encoding='utf-8') as unique_file:
        for i, line in enumerate(original_lines, 1):
            if i not in duplicate_line_nums:
                unique_file.write(line)

    # Write duplicates to separate file
    with open(f"{base_name}_duplicates.md", 'w', encoding='utf-8') as dup_file:
        for url, occurrences in duplicates.items():
            dup_file.write(f"\n--- Duplicate URL: {url} ---\n")
            dup_file.write(f"Kept Line {occurrences[0][0]}: {occurrences[0][1]}\n")  # Show which line was kept
            dup_file.write("Removed duplicates:\n")
            for line_num, line in occurrences[1:]:  # Show which lines were removed
                dup_file.write(f"Line {line_num}: {line}\n")


def compare_files(file1_path, file2_path):
    # Find duplicates in both files
    duplicates_file1, lines_file1 = find_duplicates(file1_path)
    duplicates_file2, lines_file2 = find_duplicates(file2_path)

    # Calculate duplicate statistics
    total_duplicates_file1 = sum(len(lines) - 1 for lines in duplicates_file1.values())
    total_duplicates_file2 = sum(len(lines) - 1 for lines in duplicates_file2.values())

    # Write files without duplicates
    write_files_without_duplicates(file1_path, lines_file1, duplicates_file1)
    write_files_without_duplicates(file2_path, lines_file2, duplicates_file2)

    # Load URLs for comparison
    def load_urls(file_path):
        urls = set()
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                url = extract_url(line.strip())
                if url:
                    urls.add(url)
        return urls

    urls_file1 = load_urls(file1_path)
    urls_file2 = load_urls(file2_path)

    # Compare the sets
    common_urls = urls_file1 & urls_file2
    only_in_file1 = urls_file1 - urls_file2
    only_in_file2 = urls_file2 - urls_file1

    # Print results
    print("\n=== File Statistics ===")
    print(f"Total URLs in Unsorted File: {len(urls_file1)}")
    print(f"Total URLs in Sorted File: {len(urls_file2)}")
    print(f"Common URLs: {len(common_urls)}")
    print(f"URLs only in Unsorted File: {len(only_in_file1)}")
    print(f"URLs only in Sorted File: {len(only_in_file2)}")

    print("\n=== Duplicate Statistics ===")
    print(f"Number of duplicate URLs in Unsorted File: {len(duplicates_file1)}")
    print(f"Total duplicate lines in Unsorted File: {total_duplicates_file1}")
    print(f"Number of duplicate URLs in Sorted File: {len(duplicates_file2)}")
    print(f"Total duplicate lines in Sorted File: {total_duplicates_file2}")

    # Print duplicate details
    if duplicates_file1:
        print("\nDuplicate URLs in Unsorted File:")
        for url, lines in duplicates_file1.items():
            print(f"\nURL: {url}")
            print(f"Found on lines: {', '.join(str(line_num) for line_num, _ in lines)}")

    if duplicates_file2:
        print("\nDuplicate URLs in Sorted File:")
        for url, lines in duplicates_file2.items():
            print(f"\nURL: {url}")
            print(f"Found on lines: {', '.join(str(line_num) for line_num, _ in lines)}")

    print("\n=== New Files Created ===")
    print(f"1. {file1_path.rsplit('.', 1)[0]}_unique.md - Original file without duplicates")
    print(f"2. {file1_path.rsplit('.', 1)[0]}_duplicates.md - Contains all duplicates")
    print(f"3. {file2_path.rsplit('.', 1)[0]}_unique.md - Original file without duplicates")
    print(f"4. {file2_path.rsplit('.', 1)[0]}_duplicates.md - Contains all duplicates")


# Usage
file1_path = "LinksOfInterest.txt"
file2_path = "LinksOfInterest.md"
compare_files(file1_path, file2_path)