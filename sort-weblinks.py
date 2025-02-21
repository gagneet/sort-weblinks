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
    """Parse links from file, handling both formats"""
    entries = []
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Pattern 1: Description: URL
        pattern1 = re.match(r'(.*?):\s*(https?://\S+)', line)
        # Pattern 2: Raw URL
        pattern2 = re.match(r'(https?://\S+)', line)
        
        if pattern1:
            description, url = pattern1.groups()
            entries.append({
                'description': description.strip(),
                'url': url.strip(),
                'format': 'with_description'
            })
        elif pattern2:
            url = pattern2.group(1)
            entries.append({
                'description': None,
                'url': url.strip(),
                'format': 'raw_url'
            })
            
    return entries

def fetch_missing_titles(entries, max_fetch=50):
    """Fetch titles for entries without descriptions (limit to prevent too many requests)"""
    count = 0
    for entry in entries:
        if entry['format'] == 'raw_url' and count < max_fetch:
            print(f"Fetching title for {entry['url']}...")
            title = get_page_title(entry['url'])
            if title:
                entry['description'] = title
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
    # Extract domains
    domains = [extract_domain(entry['url']) for entry in entries if entry['url']]
    domain_counter = Counter([d for d in domains if d])
    
    # Find the most common domains
    common_domains = [domain for domain, count in domain_counter.most_common(5) if count > 1]
    
    # Dictionary to store topic groupings
    topics = {}
    
    # First, group by common domains
    for domain in common_domains:
        topics[f"Resources from {domain}"] = [
            entry for entry in entries 
            if extract_domain(entry['url']) == domain
        ]
    
    # Collect entries not yet categorized
    remaining_entries = [
        entry for entry in entries 
        if extract_domain(entry['url']) not in common_domains
    ]
    
    return topics, remaining_entries

def main():
    file_path = 'weblinks.txt'
    
    # 1. Parse the links
    print("Parsing links...")
    entries = parse_links(file_path)
    print(f"Found {len(entries)} links ({sum(1 for e in entries if e['format'] == 'raw_url')} raw URLs)")
    
    # 2. Fetch titles for raw URLs
    print("Fetching titles for raw URLs...")
    entries = fetch_missing_titles(entries)
    
    # 3. First group by common domains
    print("Grouping by common domains...")
    domain_topics, remaining_entries = extract_common_topics(entries)
    
    # 4. Use text clustering for the remaining entries
    print("Clustering remaining entries...")
    descriptions = [entry['description'] for entry in remaining_entries if entry['description']]
    
    if descriptions:
        # Create TF-IDF features
        vectorizer = TfidfVectorizer(
            stop_words='english',
            min_df=2,
            max_df=0.8,
            ngram_range=(1, 2)
        )
        X = vectorizer.fit_transform(descriptions)
        
        # Use DBSCAN for clustering (automatically determines number of clusters)
        clustering = DBSCAN(eps=0.7, min_samples=2, metric='cosine')
        clusters = clustering.fit_predict(X)
        
        # Group entries by cluster
        text_topics = {}
        unclustered = []
        
        for i, entry in enumerate(remaining_entries):
            if not entry['description']:
                unclustered.append(entry)
                continue
                
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
        
        # Combine domain-based and text-based topics
        all_topics = {**domain_topics, **named_topics}
        
        # Add unclustered as "Miscellaneous"
        if unclustered:
            all_topics["Miscellaneous"] = unclustered
    else:
        all_topics = domain_topics
        if remaining_entries:
            all_topics["Miscellaneous"] = remaining_entries
    
    # 5. Output the results
    with open('organized_links.md', 'w', encoding='utf-8') as f:
        f.write("# Organized Web Links\n\n")
        
        for topic, topic_entries in all_topics.items():
            f.write(f"## {topic}\n\n")
            for entry in topic_entries:
                if entry['description']:
                    f.write(f"- {entry['description']}: {entry['url']}\n")
                else:
                    f.write(f"- {entry['url']}\n")
            f.write("\n")
    
    print(f"Done! Organized {len(entries)} links into {len(all_topics)} topics.")
    print(f"Results saved to 'organized_links.md'")

if __name__ == "__main__":
    main()