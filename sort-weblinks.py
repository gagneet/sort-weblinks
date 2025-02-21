import re
import requests
from bs4 import BeautifulSoup
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN
import time
from collections import Counter
from urllib.parse import urlparse

def get_page_title(url, timeout=3):
    """Attempt to fetch the title of a webpage"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string if soup.title else None
            return title.strip() if title else None
    except Exception as e:
        pass
    return None

def extract_domain(url):
    """Extract the domain from a URL"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        return domain
    except:
        return None

def parse_links(file_path):
    """Parse links from file, handling multiple formats"""
    entries = []
    current_group = None
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if this is a group header (ends with colon but doesn't contain URL)
        if line.endswith(':') and 'http' not in line:
            current_group = line[:-1]  # Remove the trailing colon
            continue
        
        # Handle bullet points format with description: url
        if line.startswith('-') or line.startswith('*'):
            line = line[1:].strip()
            
        # Pattern 1: Description: URL
        pattern1 = re.match(r'(.*?):\s*(https?://\S+)', line)
        # Pattern 2: Raw URL
        pattern2 = re.match(r'(https?://\S+)', line)
        # Pattern 3: Description - URL (using dash instead of colon)
        pattern3 = re.match(r'(.*?)\s+[-–]\s+(https?://\S+)', line)
        
        if pattern1:
            description, url = pattern1.groups()
            entries.append({
                'description': description.strip(),
                'url': url.strip(),
                'format': 'with_description',
                'group': current_group
            })
        elif pattern3:
            description, url = pattern3.groups()
            entries.append({
                'description': description.strip(),
                'url': url.strip(),
                'format': 'with_description',
                'group': current_group
            })
        elif pattern2:
            url = pattern2.group(1)
            entries.append({
                'description': None,
                'url': url.strip(),
                'format': 'raw_url',
                'group': current_group
            })
            
    return entries

def fetch_missing_titles(entries, max_fetch=50):
    """Fetch titles for entries without descriptions (limit to prevent too many requests)"""
    count = 0
    for entry in entries:
        # Handle both raw URLs and entries with descriptions but need enhancing
        if (entry['format'] == 'raw_url' and not entry['description']) or \
           (entry['description'] and entry['description'].strip() == entry['url'].strip()):
            print(f"Fetching title for {entry['url']}...")
            title = get_page_title(entry['url'])
            if title:
                entry['description'] = title
            else:
                # Extract repo name for GitHub links
                if 'github.com' in entry['url']:
                    # Extract the repository name and owner from github URLs
                    parts = entry['url'].strip('/').split('/')
                    if len(parts) >= 5:  # https://github.com/owner/repo
                        owner = parts[-2]
                        repo = parts[-1]
                        entry['description'] = f"GitHub: {owner}/{repo}"
                    else:
                        entry['description'] = "GitHub Repository"
                else:
                    # Use domain as fallback description
                    domain = extract_domain(entry['url'])
                    if domain:
                        entry['description'] = f"Link from {domain}"
                    else:
                        entry['description'] = "Unnamed resource"
            count += 1
            time.sleep(0.5)  # Be nice to servers
    
    return entries

def get_keywords_for_cluster(descriptions, vectorizer, num_keywords=5):
    """Extract keywords that represent a cluster"""
    if not descriptions:
        return "Miscellaneous"
        
    # Get the TF-IDF matrix for these descriptions
    X = vectorizer.transform(descriptions)
    
    # Sum up the TF-IDF values for each term across all documents
    feature_names = vectorizer.get_feature_names_out()
    tfidf_sums = X.sum(axis=0).A1
    
    # Get the indices of the top terms
    top_indices = tfidf_sums.argsort()[-num_keywords:][::-1]
    
    # Get the actual terms
    top_terms = [feature_names[i] for i in top_indices]
    
    # Create a readable name
    if top_terms:
        return f"{', '.join(top_terms[:3]).title()}"
    else:
        return "Miscellaneous"

def extract_common_topics(entries):
    """Use domain and common words to identify topics"""
    # First, respect existing groups
    existing_groups = {}
    for entry in entries:
        if entry['group']:
            if entry['group'] not in existing_groups:
                existing_groups[entry['group']] = []
            existing_groups[entry['group']].append(entry)
    
    # Get entries without groups
    ungrouped = [e for e in entries if not e['group']]
    
    # SPECIAL CASES HANDLING
    # Group github repos together
    github_entries = [e for e in ungrouped if 'github.com' in e['url']]
    api_entries = [e for e in ungrouped if any(kw in e['description'].lower() 
                 for kw in ['api', 'swagger', 'openapi', 'rest', 'graphql', 'endpoint'])]
    css_entries = [e for e in ungrouped if any(kw in e['description'].lower() 
                 for kw in ['css', 'style', 'font', 'design', 'icon'])]
    cloud_entries = [e for e in ungrouped if any(kw in e['description'].lower() 
                   for kw in ['aws', 'ec2', 'cloud', 'azure', 'instance'])]
    learning_entries = [e for e in ungrouped if any(kw in e['description'].lower() 
                      for kw in ['learn', 'tutorial', 'course', 'education'])]
    
    # Create special groups
    special_topics = {}
    if github_entries:
        special_topics["GitHub Repositories"] = github_entries
    if api_entries:
        special_topics["API Tools & Resources"] = api_entries
    if css_entries:
        special_topics["Web Design & CSS Resources"] = css_entries
    if cloud_entries:
        special_topics["Cloud & Infrastructure"] = cloud_entries
    if learning_entries:
        special_topics["Learning Resources"] = learning_entries
    
    # Remove entries that were added to special topics
    special_entries_urls = set()
    for entries_list in special_topics.values():
        special_entries_urls.update([e['url'] for e in entries_list])
    
    ungrouped = [e for e in ungrouped if e['url'] not in special_entries_urls]
    
    # Extract domains for remaining ungrouped entries
    domains = [extract_domain(entry['url']) for entry in ungrouped if entry['url']]
    domain_counter = Counter([d for d in domains if d])
    
    # Find the most common domains (more aggressive grouping)
    common_domains = [domain for domain, count in domain_counter.most_common(10) if count > 1]
    
    # Dictionary to store domain groupings
    domain_topics = {}
    
    # Group by common domains
    for domain in common_domains:
        if 'github.com' in domain:
            topic_name = "Additional GitHub Resources"
        elif 'stackoverflow.com' in domain or 'superuser.com' in domain:
            topic_name = "Stack Exchange Q&A Resources"
        else:
            topic_name = f"Resources from {domain}"
            
        domain_topics[topic_name] = [
            entry for entry in ungrouped 
            if extract_domain(entry['url']) == domain
        ]
    
    # Collect entries not yet categorized
    remaining_entries = [
        entry for entry in ungrouped 
        if extract_domain(entry['url']) not in common_domains
    ]
    
    # Combine existing groups with special topics and domain-based groups
    all_groups = {**existing_groups, **special_topics, **domain_topics}
    
    return all_groups, remaining_entries

def main():
    file_path = 'weblinks.txt'
    
    # 1. Parse the links
    print("Parsing links...")
    entries = parse_links(file_path)
    print(f"Found {len(entries)} links ({sum(1 for e in entries if e['format'] == 'raw_url')} raw URLs)")
    
    # 2. Fetch titles for raw URLs
    print("Fetching titles for raw URLs...")
    entries = fetch_missing_titles(entries)
    
    # 3. First respect existing groups and then group by common domains
    print("Grouping by existing categories and common domains...")
    domain_topics, remaining_entries = extract_common_topics(entries)
    
    # 4. Use text clustering for the remaining entries
    print("Clustering remaining entries...")
    # Filter out entries without descriptions
    remaining_with_desc = [e for e in remaining_entries if e['description']]
    
    if remaining_with_desc:
        descriptions = [entry['description'] for entry in remaining_with_desc]
        
        # FIX: Check number of documents before configuring vectorizer params
        num_docs = len(descriptions)
        
        # Dynamically adjust min_df and max_df based on corpus size
        if num_docs <= 5:
            # For very small corpus, use absolute counts and avoid max_df
            vectorizer = TfidfVectorizer(
                stop_words='english',
                min_df=1,  # At least 1 document
                max_df=1.0,  # No upper bound
                ngram_range=(1, 2)
            )
        else:
            # For larger corpus, use the original parameters
            vectorizer = TfidfVectorizer(
                stop_words='english',
                min_df=1,
                max_df=0.9,
                ngram_range=(1, 2)
            )
            
        try:
            X = vectorizer.fit_transform(descriptions)
            
            # Adjust DBSCAN parameters for small datasets
            min_samples = 2 if num_docs > 3 else 1
            eps = 0.7  # Cosine distance threshold
            
            # Use DBSCAN for clustering
            clustering = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')
            clusters = clustering.fit_predict(X)
            
            # Group entries by cluster
            text_topics = {}
            unclustered = []
            
            for i, entry in enumerate(remaining_with_desc):
                cluster_id = clusters[i]
                if cluster_id == -1:
                    # DBSCAN marks outliers as -1
                    unclustered.append(entry)
                else:
                    if cluster_id not in text_topics:
                        text_topics[cluster_id] = []
                    text_topics[cluster_id].append(entry)
            
            # Generate topics names for each cluster
            named_topics = {}
            for cluster_id, cluster_entries in text_topics.items():
                cluster_descriptions = [entry['description'] for entry in cluster_entries]
                topic_name = get_keywords_for_cluster(cluster_descriptions, vectorizer)
                named_topics[topic_name] = cluster_entries
                
        except ValueError as e:
            # Handle vectorization errors by putting all entries in unclustered
            print(f"Warning: Clustering failed ({str(e)}). Grouping remaining entries as Miscellaneous.")
            named_topics = {}
            unclustered = remaining_with_desc
            
        # Add entries without descriptions to unclustered
        unclustered.extend([e for e in remaining_entries if not e['description']])
        
        # Combine all topics
        all_topics = {**domain_topics, **named_topics}
        
        # Add unclustered as "Miscellaneous"
        if unclustered:
            all_topics["Miscellaneous"] = unclustered
    else:
        all_topics = domain_topics
        if remaining_entries:
            all_topics["Miscellaneous"] = remaining_entries
    
    # 5. Sort entries within each topic for consistent ordering
    for topic, topic_entries in all_topics.items():
        # Sort by description (if available) then by URL
        all_topics[topic] = sorted(
            topic_entries,
            key=lambda e: (e['description'] or '').lower() or e['url'].lower()
        )
    
    # Sort topics by name, but keep "Miscellaneous" at the end
    sorted_topics = {}
    misc_entries = all_topics.pop("Miscellaneous", [])
    
    # Sort topics alphabetically
    for topic in sorted(all_topics.keys()):
        sorted_topics[topic] = all_topics[topic]
    
    # Add miscellaneous at the end if it exists
    if misc_entries:
        sorted_topics["Miscellaneous"] = misc_entries
    
    # 6. Output the results with statistics
    with open('organized_links.md', 'w', encoding='utf-8') as f:
        f.write("# Organized Web Links\n\n")
        f.write(f"*Total Links: {len(entries)} in {len(sorted_topics)} categories*\n\n")
        f.write("## Table of Contents\n\n")
        
        # Create a table of contents
        for topic in sorted_topics.keys():
            cleaned_topic = topic.replace('#', '').replace('*', '').replace('`', '')
            topic_anchor = cleaned_topic.lower().replace(' ', '-').replace(',', '')
            f.write(f"- [{cleaned_topic}](#{topic_anchor}) ({len(sorted_topics[topic])} links)\n")
        
        f.write("\n---\n\n")
        
        # Write each topic with its entries
        for topic, topic_entries in sorted_topics.items():
            f.write(f"## {topic}\n\n")
            for entry in topic_entries:
                if entry['description'] and entry['description'] != entry['url']:
                    f.write(f"- {entry['description']}: {entry['url']}\n")
                else:
                    f.write(f"- {entry['url']}\n")
            f.write("\n")
    
    print(f"Done! Organized {len(entries)} links into {len(all_topics)} topics.")
    print(f"Results saved to 'organized_links.md'")

if __name__ == "__main__":
    main()