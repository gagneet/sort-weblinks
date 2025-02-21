# sort-weblinks

## Introduction

I have a lot of links which I have been saving and just putting into a file called my-weblinks.txt
For some of the links, I had created a heading to define what the links were about and also added a short description for a majority of the links in the format:

<header>
<description>: <URL/web-link>

After some time it became difficult (when the file reached 1000+ lines/links), to search and figure out or remember what the links without a header or a description were for or if they were alive or not.
Hence, this attempt to sort and give meaning to eah of the web-links/URL's

## Issues and Error solutions

### 1. ValueError: max_df corresponds to < documents than min_df

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
