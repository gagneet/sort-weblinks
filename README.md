# sort-weblinks

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
python sort-weblinks.py -i my-weblinks.txt -o organized_links.md -c config.yaml
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
python weblinks-subhierarchy.py -i weblinks.txt -o organized.md -c config.yaml --debug
```

## Caching and re-use of the URL descriptions:

The `url_cache.json` file is designed to be reused across multiple runs of the script. It caches the titles and timestamps of URLs that have been fetched, which helps:

- Reduce unnecessary network requests
- Speed up subsequent runs
- Avoid hitting rate limits on websites
- Reduce load on the websites being queried
- The cache mechanism is already implemented in the fetch_title method.

The cache duration is controlled by the `cache_duration` setting in your config.yaml file. By default, it's set to 86400 seconds (24 hours). You can modify this in your config file.

## Issues and Error solutions

### 1. IndexError: index 1096 is out of bounds for axis 0 with size 1092

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

### 2. ValueError: max_df corresponds to < documents than min_df

This happens in the TF-IDF vectorization step where you're setting:

min_df=1 (terms must appear in at least 1 document)
max_df=0.9 (terms can appear in at most 90% of documents)

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

min_df=1 means terms must appear in at least 1 document
max_df=0.9 means terms must appear in at most 90% of documents

With a very small number of documents, these constraints can become mathematically impossible to satisfy. For example, with just 2 documents:

90% of 2 = 1.8, rounded down to 1

This means terms can appear in at most 1 document (max_df)
But min_df also requires terms to appear in at least 1 document
This creates a situation where terms must appear in exactly 1 document, which may not be possible given the actual content

The solution adaptively adjusts these parameters based on our dataset size, making our code much more robust.

### 3. There are some links, which do not have a text for the link, describing the website/URI. Also, the links seems to have been sorted randomly

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
