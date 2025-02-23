# Sorting out web-links and arranging them according to category and relevance

## Introduction

I have a lot of links which I have been saving and just putting into a file called my-weblinks.txt
For some of the links, I had created a heading to group and define what the links were about and also added a short description for a majority of the links in the format:

```text
Header:
Short Description: URL/web-link.htm
```

After some time it became difficult (when the file reached 1000+ lines/links), to search and figure out or remember what the links without a header or a description were for or if they were alive or not.
Hence, this attempt to sort and give meaning to eah of the web-links/URL's

## Running the application

```sh
python weblinks_organizer.py -i my-weblinks.txt -o organized_links.md -c config.yaml
```

## Improvements and debugging

Improved the script to:

- Properly handle URL categorization without duplicates
- Respect original categories from your input file
- Implement efficient caching for faster subsequent runs
- Follow proper markdown formatting guidelines
- Better organize your web links

The UTC timestamp provided (2025-02-22 22:21:59) indicates the time, i.e. night UTC time.

The cache system should help us maintain an efficient workflow, especially when running the script multiple times while organizing your links.

For future reference, if we need to make any adjustments to the categorization rules or cache duration, we can easily do so through the config.yaml file.

Also remember, we can always use the --debug flag if we need to troubleshoot any issues:

```sh
python weblinks_organizer.py -i weblinks.txt -o organized.md -c config.yaml --debug
```

Added a log file generation for the categorization.

```bash
python weblinks_organizer.py -i weblinks.txt -o organized.md -c config.yaml --debug [> categorization.log -> this happens by default now]
```

Now we can then analyze `categorization.log` to see why specific links are being categorized incorrectly and adjust the keywords and scoring system in `config.yaml` accordingly.

## Caching and re-use of the URL descriptions

The `url_cache.json` file is designed to be reused across multiple runs of the script. It caches the titles and timestamps of URLs that have been fetched, which helps:

- Reduce unnecessary network requests
- Speed up subsequent runs
- Avoid hitting rate limits on websites
- Reduce load on the websites being queried
- The cache mechanism is already implemented in the fetch_title method.

The cache duration is controlled by the `cache_duration` setting in your config.yaml file. By default, it's set to 86400 seconds (24 hours). You can modify this in your config file.

We can also disable the cache using the --no-cache command line argument:

```sh
python weblinks_organizer.py -i weblinks.txt -o organized.md -c config.yaml --no-cache
```

The script will:

- Read from this cache on startup
- Use cached titles if they haven't expired
- Only fetch new titles for URLs not in the cache or with expired cache entries
- Update the cache with new entries
- Save the updated cache back to disk

### Common cache durations

```yaml
cache_duration: 3600     # 1 hour
cache_duration: 86400    # 1 day (default)
cache_duration: 604800   # 1 week
cache_duration: 2592000  # 30 days
```

## Issues and Error solutions

### IndexError: index 1096 is out of bounds for axis 0 with size 1092

The error we're encountering is happening because there's a mismatch between the number of entries being processed.

Modify the code to handle blank lines and pre-grouped links more effectively

#### Key Fixes

- Group Header Detection: Now detects lines ending with a colon that don't contain URLs as group headers
- Handling Existing Groups: Preserves any existing groupings you already have
- Empty Description Handling: Better handling of entries without descriptions
- TF-IDF Parameters: Adjusted parameters to work with smaller groups of data
- Proper error handling: Makes sure we only process entries that have descriptions

#### Additional improvements

The code now distinguishes between:

- Pre-existing groups you already created
- Auto-detected domain-based groups
- Text similarity-based clusters

It handles blank lines and section headers like Test Management 2.0: as group titles

### ValueError: max_df corresponds to < documents than min_df

This happens in the TF-IDF vectorization step where you're setting:

```python
min_df=1 (terms must appear in at least 1 document)
max_df=0.9 (terms can appear in at most 90% of documents)
```

The error occurs when these constraints conflict - specifically when you have very few documents to cluster. If you have only a small number of remaining entries to cluster, setting max_df=0.9 might result in requiring a term to appear in fewer documents than the min_df=1 requirement.

#### Solution

An edge case. We need to make the vectorizer more robust for small document sets.

#### Key Changes Made

- Dynamic Vectorizer Configuration:
I've added code to dynamically adjust the TF-IDF vectorizer parameters based on the corpus size
For small document sets (5 or fewer), the code now uses min_df=1 and max_df=1.0 to prevent the conflict

- Error Handling:
Added a try-except block around the vectorization and clustering steps
If clustering fails, it will fall back to grouping remaining entries as "Miscellaneous" instead of crashing

- DBSCAN Parameter Adjustment:
Added dynamic adjustment of the min_samples parameter based on document count
For very small datasets (3 or fewer), it now uses min_samples=1

#### Explanation of the Error

This error occurs because:

```python
min_df=1 means terms must appear in at least 1 document
max_df=0.9 means terms must appear in at most 90% of documents
```

With a very small number of documents, these constraints can become mathematically impossible to satisfy. For example, with just 2 documents:

```sh
90% of 2 = 1.8, rounded down to 1
```

This means terms can appear in at most 1 document (max_df)
But min_df also requires terms to appear in at least 1 document
This creates a situation where terms must appear in exactly 1 document, which may not be possible given the actual content

The solution adaptively adjusts these parameters based on our dataset size, making our code much more robust.

### There are some links, which do not have a text for the link, describing the website/URI. Also, the links seems to have been sorted randomly

#### a. Missing Link Descriptions

The updated code now:

- Handles GitHub repositories better by extracting the owner/repo name when no title is available
- Recognizes when a link description is just the URL itself and tries to fetch a better title
- Applies more intelligent fallbacks based on the URL type

#### b. Better Categorization

I've improved the categorization with:

- Topic-based grouping for common link types (GitHub repos, API tools, web design resources, etc.)
- Expanded keyword recognition to identify link purposes
- More aggressive domain-based grouping to reduce the "Miscellaneous" category
- Special handling for Stack Exchange sites (Stack Overflow, Super User)

##### Categorization Logic

The categorization is done in this order:

- First tries to use original group from input file
- Then attempts automatic categorization based on keywords
- Falls back to "Uncategorized" if no match

#### c. Link Sorting & Organization

The output is now much more organized:

- Links within each category are sorted alphabetically by description
- Categories themselves are sorted alphabetically (with "Miscellaneous" at the end)
- Added a table of contents with link counts
- Added statistics about total links and categories

#### d. Enhanced Link Format Recognition

The parser now handles more formats:

- Traditional "Description: URL" format
- Bullet points (- or *)
- "Description - URL" format with dash separator
- URL-only entries

### ERROR - An error occurred: 'WebLinkOrganizer' object has no attribute 'settings'

The error occurs because there's a mismatch in the configuration initialization.
The issue is in the load_config method where the default configuration structure doesn't match what's being used in the rest of the code.

The error occurred because the default configuration in the original code didn't have the correct structure with 'settings' and 'categories' as top-level keys. The updated version ensures that:

- The configuration always has both 'settings' and 'categories' sections
- If a config file is provided but missing these sections, they're added with default values
- If no config file is provided, a properly structured default configuration is used

## Updates and key changes

### v0.5

- Added only_general check to identify categories with just a "General" subcategory
- Skip writing "### General" when it's the only subcategory
- Skip showing subcategories in TOC when there's only "General"
- Restore generic descriptions for URLs
- Show exactly where links are being filtered out
- Provide detailed categorization logging
- Help identify why links might be miscategorized

Logging enhancements, adding a 'setup_logging' function:

- It handles both file and console output
- It provides more control over log formatting
- It allows different log levels for file and console
- It creates a new log file for each run
- It properly handles Unicode characters in the log

Output:

- Show subcategories only when there are multiple subcategories
- Skip `### General` when it's the only subcategory in a category
- Remove duplicate headings
- Keep the hierarchy clean and simple

### v0.4

- Prevent duplicate entries by tracking assigned URLs
- Improve categorization accuracy using a scoring system
- Respect manual categorization from the input file
- Use proper markdown heading hierarchy (H1 -> H2 -> H3)
- Better organize the output with consistent structure
- Add relevance thresholds to prevent incorrect categorization

The scoring system now:

- Weighs URL matches more heavily than description matches
- Requires a minimum score to categorize automatically
- Better handles subcategory matching
- Respects original categories from the input file

#### datetime.now(UTC)

- Returns a timezone-aware datetime object
- Explicitly shows the intent to use UTC
- More consistent with modern datetime handling practices

### v0.3

- Properly implement chunk processing
- Respect original categories from the input file
- Use parallel processing only when beneficial (50+ entries)
- Maintain proper sorting and hierarchy
- Keep custom categories from the input file
- Keep both methods but fix their implementation
- Use parallel processing for large link sets
- Add a threshold to automatically decide when to use parallel processing
- Better respect existing categories from the input file
- Handle category headers in different formats (with or without '#', with or without ':')
- Create new top-level categories for groups that don't match existing categories
- Only attempt automatic categorization for links without explicit groups
- Move truly uncategorized links to the "Uncategorized" section at the end

The code will now:

- First use the original categories from your `my-weblinks.txt` file
- Only attempt automatic categorization for links without categories
- Process in parallel for better performance with large sets
- Maintain all header information from the input file
- Removes unused code that could confuse future maintainers
- Reduces the complexity of the codebase
- Makes the execution flow clearer
- Eliminates potential bugs that could arise from maintaining parallel code paths

### v0.2

These changes make the URL validation more robust by:

- First attempt automatic categorization for all URLs based on their content and URL
- If automatic categorization fails, use the original header from the input file
- If no categorization is possible, move to Uncategorized
- Sort at multiple levels:
  - Main categories (alphabetically, with Uncategorized last)
  - Subcategories (with "General" first, "Other" last, rest alphabetically)
  - Links within each category (by description/URL)
- Maintain consistent sorting in both the Table of Contents and the main content
- Adding a list of common trusted domains that are considered valid by default
- Trying both HEAD and GET requests
- Attempting HTTP if HTTPS fails
- Being more lenient with timeouts (increased to 10 seconds)
- Considering URLs with valid format as potentially valid even if we can't connect
- Better error handling and logging
- Reordered the initialization sequence in __init__ to ensure dependencies are properly initialized
- Improved the configuration loading with proper default values
- Added better error handling and logging
- Ensured the configuration structure is complete with all required settings

The links should now be properly categorized instead of being marked as invalid.
We can also add more domains to the `VALID_DOMAINS` set if we have specific websites that we know are valid but might not respond well to validation checks.

### v0.1

- Load configuration from the specified YAML file (or use defaults)
- Show progress bars during long operations
- Provide detailed feedback about the process
- Handle errors gracefully
- Support customization via command-line arguments

#### The enhancements include

Configuration File Support

- Moved category hierarchy to external YAML config
- Added settings for timeouts, retries, etc.
- Fallback to default configuration if file is missing

Progress Indicators:

- Added tqdm progress bars for:
- Fetching titles
- Categorizing entries
- Clear logging of each stage

CLI Options:

- Input file path (-i/--input)
- Output file path (-o/--output)
- Config file path (-c/--config)
- Cache control (--no-cache)
- Debug logging (--debug)

Better Error Handling:

- Proper logging configuration
- Graceful fallbacks for missing config
- Detailed error reporting in debug mode

#### Create a config file (optional)

```bash
cp config.yaml ~/.config/weblinks_organizer/config.yaml
```

```bash
# Basic usage
python weblinks_organizer.py

# With custom files
python weblinks_organizer.py -i my_links.txt -o organized.md

# With custom config
python weblinks_organizer.py -c my_config.yaml

# Disable cache
python weblinks_organizer.py --no-cache

# Debug mode
python weblinks_organizer.py --debug
```

### Previous un-charted changes

Code Structure Improvements:

- There's duplicate functionality between write_hierarchical_markdown() and the markdown writing section in main(). We should consolidate this.
- The categorize_with_hierarchy() function is quite long and could be split into smaller, more focused functions.

Error Handling & Robustness:

- Add better error handling for file operations
- Implement retry logic for web requests
- Validate URLs before processing

Performance Optimizations:

- Implement concurrent title fetching using asyncio or threading
- Cache web request results
- Optimize the text clustering algorithm for larger datasets

Feature Enhancements:

- Add support for custom category mapping via configuration file
- Implement URL validation and cleanup
- Add support for relative dates in output
- Add sorting options for links within categories
