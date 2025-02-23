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
    """Parse links from file, handling multiple formats and subheaders."""
    entries = []
    current_group = None
    current_subheader = None  # Add for subheaders

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.endswith(':') and 'http' not in line:  # Group/Header
            current_group = line[:-1].strip()
            current_subheader = None  # Reset subheader when a new group starts
            continue

        # Check for subheader (starts with '##' or '###')
        subheader_match = re.match(r'^(##+)\s+(.+?):$', line) # Improved regex for subheaders
        if subheader_match:
            level = len(subheader_match.group(1)) # Get the level of subheader
            current_subheader = {"name": subheader_match.group(2).strip(), "level": level}
            continue

        # Handle bullet points format with description: url (or URL)
        if line.startswith('-') or line.startswith('*'):
            line = line[1:].strip()

        # Regular expression matching (combined for efficiency)
        match = re.match(r'(?P<description>.*?):\s*(?P<url>https?://\S+)|(?P<url2>https?://\S+)|(?P<desc2>.*)\s+[-–—]\s+(?P<url3>https?://\S+)', line)
        if match:
            match_dict = match.groupdict()
            url = match_dict.get('url') or match_dict.get('url2') or match_dict.get('url3')
            description = (match_dict.get('description') or match_dict.get('desc2') or None).strip() if match_dict.get('description') or match_dict.get('desc2') else None

            entries.append({
                'description': description,
                'url': url.strip(),
                'group': current_group,
                'subheader': current_subheader,  # Add subheader to the entry
            })

    return entries


def fetch_missing_titles(entries, max_fetch=50):
    """Fetch titles for entries without descriptions (limit to prevent too many requests)"""
    count = 0
    with requests.Session() as session:  # Use a session for connection reuse
        for entry in entries:
            if entry['description'] is None or entry['description'].strip() == entry['url'].strip(): # Simplified condition
                if count >= max_fetch:  # Rate limiting
                    print("Reached maximum title fetch limit. Skipping remaining.")
                    break
                print(f"Fetching title for {entry['url']}...")
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    response = session.get(entry['url'], headers=headers, timeout=3)
                    response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    soup = BeautifulSoup(response.text, 'html.parser')
                    title = soup.title.string if soup.title else None
                    entry['description'] = title.strip() if title else None
                except requests.exceptions.RequestException as e:
                    print(f"Error fetching title for {entry['url']}: {e}")
                    # Handle GitHub links even if title fetch fails
                    if 'github.com' in entry['url']:
                        parts = entry['url'].strip('/').split('/')
                        if len(parts) >= 5:
                            owner = parts[-2]
                            repo = parts[-1]
                            entry['description'] = f"GitHub: {owner}/{repo}"
                        else:
                            entry['description'] = "GitHub Repository"
                    else:
                        domain = extract_domain(entry['url'])
                        entry['description'] = f"Link from {domain}" if domain else "Unnamed resource"

                count += 1
                time.sleep(0.2)  # Reduced delay

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
    return {}, [] # Return empty as this logic is now in categorize_with_hierarchy
	
def define_category_hierarchy():
    """Define a hierarchical category structure with main categories and subcategories"""
    return {
        "Development Resources": {
            "subcategories": [
                "GitHub Repositories", 
                "API Tools & Resources",
                "Development Libraries",
                "Code Snippets",
                "Stack Exchange Q&A Resources"
            ],
            "keywords": ["code", "develop", "programming", "github", "api", "sdk", "library", 
                        "framework", "stack", "overflow", "git", "repo", "developer"]
        },
        "Web Design & Frontend": {
            "subcategories": [
                "Web Design & CSS Resources",
                "UI/UX Resources",
                "Frontend Frameworks",
                "Design Inspiration"
            ],
            "keywords": ["css", "html", "design", "ui", "ux", "frontend", "web", "style", 
                        "font", "color", "responsive", "layout", "react", "vue", "angular"]
        },
        "Infrastructure & DevOps": {
            "subcategories": [
                "Cloud & Infrastructure",
                "Deployment Tools",
                "Monitoring Solutions",
                "Container Resources"
            ],
            "keywords": ["cloud", "aws", "azure", "gcp", "server", "docker", "kubernetes", 
                        "devops", "ci/cd", "pipeline", "infrastructure", "monitor", "deploy"]
        },
        "Learning & Education": {
            "subcategories": [
                "Learning Resources",
                "Tutorials",
                "Documentation",
                "Courses"
            ],
            "keywords": ["learn", "tutorial", "education", "course", "training", "documentation", 
                        "guide", "howto", "lesson", "educational", "academy", "study"]
        }
    }

def categorize_with_hierarchy(entries):
    hierarchy = define_category_hierarchy()
    hierarchical_results = {main_cat: {} for main_cat in hierarchy.keys()}
    unassigned = []

    for entry in entries:
        assigned = False
        desc = entry['description'].lower() if entry['description'] else ""
        url = entry['url'].lower()
        group = entry.get('group') # Use get to avoid errors if key does not exist
        subheader = entry.get('subheader')
        
        # 1. Handle existing groups and subheaders first
        if group:
            main_cat = None
            for cat, config in hierarchy.items():
                if group.lower() in config['subcategories'] or group.lower() in cat.lower() or any(keyword in group.lower() for keyword in config['keywords']):
                    main_cat = cat
                    break
            if not main_cat:
                main_cat = "Custom Categories" # Create a custom category for existing group

            if subheader:
                if main_cat not in hierarchical_results:
                    hierarchical_results[main_cat] = {}
                if subheader['name'] not in hierarchical_results[main_cat]:
                    hierarchical_results[main_cat][subheader['name']] = []
                hierarchical_results[main_cat][subheader['name']].append(entry)
            else:
                if main_cat not in hierarchical_results:
                    hierarchical_results[main_cat] = {}
                if group not in hierarchical_results[main_cat]:
                    hierarchical_results[main_cat][group] = []
                hierarchical_results[main_cat][group].append(entry)
            continue
        
        # 2. Categorize based on keywords in description or URL
        for main_cat, config in hierarchy.items():
            if any(keyword in desc or keyword in url for keyword in config['keywords']):
                # Find the best subcategory
                best_subcategory = None
                for subcat in config['subcategories']:
                    if any(keyword in desc or keyword in url for keyword in subcat.lower().split()):
                        best_subcategory = subcat
                        break

                if best_subcategory:
                    if main_cat not in hierarchical_results:
                        hierarchical_results[main_cat] = {}
                    if best_subcategory not in hierarchical_results[main_cat]:
                        hierarchical_results[main_cat][best_subcategory] = []
                    hierarchical_results[main_cat][best_subcategory].append(entry)
                else:  # No specific subcategory, use "Other"
                    other_cat = f"Other {main_cat}"
                    if main_cat not in hierarchical_results:
                        hierarchical_results[main_cat] = {}
                    if other_cat not in hierarchical_results[main_cat]:
                        hierarchical_results[main_cat][other_cat] = []
                    hierarchical_results[main_cat][other_cat].append(entry)

                assigned = True
                break

        if not assigned:
            unassigned.append(entry)

    if unassigned:
        if "Other Categories" not in hierarchical_results:
            hierarchical_results["Other Categories"] = {}
        hierarchical_results["Other Categories"]["Miscellaneous"] = unassigned

    return hierarchical_results


def write_hierarchical_markdown(hierarchical_categories, output_file="hierarchical_links1.md"):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Hierarchical Web Link Organization\n\n")

        total_links = 0
        for main_cat, subcats in hierarchical_categories.items():
            for entries in subcats.values():
                total_links += len(entries)

        f.write(f"*Total Links: {total_links} in {sum(len(subcats) for subcats in hierarchical_categories.values())} subcategories*\n\n")

        # Table of Contents (Improved for subheaders)
        f.write("## Table of Contents\n\n")
        for main_cat, subcats in sorted(hierarchical_categories.items()):
            if not subcats:
                continue

            main_cat_anchor = main_cat.lower().replace(' ', '-').replace('&', '').replace(',', '')
            f.write(f"- [**{main_cat}**](#{main_cat_anchor})\n")

            for subcat, entries in sorted(subcats.items()):
                subcat_anchor = f"{main_cat_anchor}-{subcat.lower().replace(' ', '-').replace('&', '').replace(',', '')}"
                f.write(f"  - [{subcat}](#{subcat_anchor}) ({len(entries)} links)\n") # Added indentation

        f.write("\n---\n\n")

        # Write each main category and its subcategories (Improved for subheaders)
        for main_cat, subcats in sorted(hierarchical_categories.items()):
            if not subcats:
                continue

            main_cat_anchor = main_cat.lower().replace(' ', '-').replace('&', '').replace(',', '')
            f.write(f"# {main_cat}\n\n")

            for subcat, entries in sorted(subcats.items()):
                subcat_anchor = f"{main_cat_anchor}-{subcat.lower().replace(' ', '-').replace('&', '').replace(',', '')}"
                f.write(f"## {subcat}\n\n")

                sorted_entries = sorted(entries, key=lambda e: (e['description'] or '').lower() or e['url'].lower())
                for entry in sorted_entries:
                    link_text = f"- "
                    if entry['description'] and entry['description'] != entry['url']:
                        link_text += f"{entry['description']}: "
                    link_text += f"{entry['url']}\n"
                    f.write(link_text) # Simplified link writing

                f.write("\n")

    print(f"Hierarchical organization complete! Result saved to {output_file}")


def main():
    file_path = 'weblinks.txt'
    
    # 1. Parse the links
    print("Parsing links...")
    entries = parse_links(file_path)
    print(f"Found {len(entries)} links")
    
    # 2. Fetch titles for raw URLs
    print("Fetching titles for entries...")
    entries = fetch_missing_titles(entries)
    
	# 3. Use hierarchical categorization - sub-groups within the main categories
    print("Applying hierarchical categorization...")
    hierarchical_categories = categorize_with_hierarchy(entries)
  
	# 7. Write the results to markdown
    write_hierarchical_markdown(hierarchical_categories)
    
    print("Done! Links have been organized hierarchically.")
    print(f"Results saved to 'hierarchical_links1.md'")  # Corrected filename

if __name__ == "__main__":
    main()