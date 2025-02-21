import re
import nltk
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

# Parse the file
with open('my-weblinks.txt', 'r') as f:
    lines = f.readlines()

# Extract descriptions and URLs
entries = []
for line in lines:
    match = re.match(r'(.*?):\s*(https?://\S+)', line.strip())
    if match:
        description, url = match.groups()
        entries.append({'description': description, 'url': url})

# Extract features from descriptions
descriptions = [entry['description'] for entry in entries]
vectorizer = TfidfVectorizer(stop_words='english')
X = vectorizer.fit_transform(descriptions)

# Cluster into topics (adjust num_clusters based on your needs)
num_clusters = 10
kmeans = KMeans(n_clusters=num_clusters)
kmeans.fit(X)

# Group by cluster
clusters = {}
for i, entry in enumerate(entries):
    cluster_id = kmeans.labels_[i]
    if cluster_id not in clusters:
        clusters[cluster_id] = []
    clusters[cluster_id].append(entry)

# Generate output with headings
for cluster_id, cluster_entries in clusters.items():
    # Extract common words to form heading
    cluster_texts = [entry['description'] for entry in cluster_entries]
    # Generate heading logic here...
    print(f"## Topic {cluster_id}")
    for entry in cluster_entries:
        print(f"{entry['description']}: {entry['url']}")
    print()