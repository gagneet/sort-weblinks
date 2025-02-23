from typing import Dict, List, Tuple
from ..models.weblink import WebLink
import logging

logger = logging.getLogger(__name__)

class Categorizer:
    def __init__(self, config: dict):
        self.config = config
        self.hierarchy = config.get('categories', {})

    def calculate_category_score(self, url: str, desc: str, category_config: dict) -> Tuple[float, List[str]]:
        # Your existing calculate_category_score code...

    def categorize_entries(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """
        Categorize entries with following priority:
        1. Try automatic categorization first
        2. If that fails, use original group from input file
        3. If no group exists, put in Uncategorized
        """
        with tqdm(total=len(entries), desc="Categorizing entries", unit="link") as pbar:
            # Initialize categories
            categorized = {main_cat: {} for main_cat in self.hierarchy.keys()}
            categorized["Uncategorized"] = {"General": []}

            for entry in entries:
                assigned = False
                desc = (entry.description or '').lower()
                url = entry.url.lower()

                # First attempt: Try automatic categorization
                for main_cat, config in self.hierarchy.items():
                    if any(keyword in desc or keyword in url for keyword in config['keywords']):
                        # Try to find appropriate subcategory
                        for subcat in config['subcategories']:
                            if any(keyword in desc or keyword in url 
                                  for keyword in subcat.lower().split()):
                                if subcat not in categorized[main_cat]:
                                    categorized[main_cat][subcat] = []
                                categorized[main_cat][subcat].append(entry)
                                assigned = True
                                break
                        
                        if not assigned:
                            # Put in "Other" subcategory
                            other_cat = f"Other {main_cat}"
                            if other_cat not in categorized[main_cat]:
                                categorized[main_cat][other_cat] = []
                            categorized[main_cat][other_cat].append(entry)
                            assigned = True
                        break

                # Second attempt: Use original group if automatic categorization failed
                if not assigned and entry.group:
                    group = entry.group
                    # Check if this group matches any main category
                    for main_cat in self.hierarchy.keys():
                        if main_cat.lower() == group.lower():
                            if "General" not in categorized[main_cat]:
                                categorized[main_cat]["General"] = []
                            categorized[main_cat]["General"].append(entry)
                            assigned = True
                            break

                    # If not a main category, create it as a new top-level category
                    if not assigned:
                        if group not in categorized:
                            categorized[group] = {}
                        if "General" not in categorized[group]:
                            categorized[group]["General"] = []
                        categorized[group]["General"].append(entry)
                        assigned = True

                # Last resort: Uncategorized
                if not assigned:
                    categorized["Uncategorized"]["General"].append(entry)

                pbar.update(1)

            # Sort entries within each subcategory
            for main_cat in categorized:
                for subcat in categorized[main_cat]:
                    categorized[main_cat][subcat].sort(
                        key=lambda e: (
                            e.description.lower() if e.description else e.url.lower(),
                            e.url.lower()
                        )
                    )

            # Clean up and sort categories
            filtered_categories = {}
            # Sort main categories alphabetically (keeping Uncategorized for last)
            main_cats = sorted(
                [cat for cat in categorized.keys() if cat != "Uncategorized"]
            )
            if "Uncategorized" in categorized:
                main_cats.append("Uncategorized")

            # Create final sorted structure
            for main_cat in main_cats:
                if any(entries for entries in categorized[main_cat].values()):
                    # Sort subcategories
                    filtered_subcats = {
                        subcat: entries 
                        for subcat, entries in sorted(
                            categorized[main_cat].items(),
                            key=lambda x: (
                                # Sort "General" first, "Other" last, rest alphabetically
                                0 if x[0] == "General" else 
                                2 if x[0].startswith("Other") else 
                                1,
                                x[0].lower()
                            )
                        )
                        if entries
                    }
                    if filtered_subcats:
                        filtered_categories[main_cat] = filtered_subcats

            return filtered_categories

    def categorize_entries_parallel(self, entries: List[WebLink]) -> Dict[str, Dict[str, List[WebLink]]]:
        """Categorize entries using parallel processing if the number of entries is above threshold."""
        PARALLEL_THRESHOLD = 50  # Only use parallel processing for 50+ entries
        
        if len(entries) < PARALLEL_THRESHOLD:
            return self.categorize_entries(entries)
        
        # Determine optimal chunk size
        chunk_size = max(10, len(entries) // (os.cpu_count() or 1))
        chunks = [entries[i:i + chunk_size] for i in range(0, len(entries), chunk_size)]
        
        # Process chunks in parallel
        with concurrent.futures.ProcessPoolExecutor() as executor:
            chunk_results = list(executor.map(self._categorize_chunk, chunks))
        
        # Merge results
        merged = {main_cat: {} for main_cat in self.hierarchy.keys()}
        merged["Uncategorized"] = {"General": []}
        
        # First, collect all unique categories and subcategories
        all_categories = set()
        all_subcategories = {}
        
        for result in chunk_results:
            for main_cat in result:
                all_categories.add(main_cat)
                if main_cat not in all_subcategories:
                    all_subcategories[main_cat] = set()
                all_subcategories[main_cat].update(result[main_cat].keys())
        
        # Initialize the structure with all discovered categories
        for cat in all_categories:
            if cat not in merged:
                merged[cat] = {}
            for subcat in all_subcategories.get(cat, []):
                if subcat not in merged[cat]:
                    merged[cat][subcat] = []
        
        # Merge the entries
        for result in chunk_results:
            for main_cat, subcats in result.items():
                for subcat, entries in subcats.items():
                    merged[main_cat][subcat].extend(entries)
        
        # Sort entries within each subcategory
        for main_cat in merged:
            for subcat in merged[main_cat]:
                merged[main_cat][subcat].sort(
                    key=lambda e: (
                        e.description.lower() if e.description else e.url.lower(),
                        e.url.lower()
                    )
                )
        
        # Create final sorted structure
        filtered_categories = {}
        main_cats = sorted(
            [cat for cat in merged.keys() if cat != "Uncategorized"]
        )
        if "Uncategorized" in merged:
            main_cats.append("Uncategorized")
        
        for main_cat in main_cats:
            if any(entries for entries in merged[main_cat].values()):
                filtered_subcats = {
                    subcat: entries 
                    for subcat, entries in sorted(
                        merged[main_cat].items(),
                        key=lambda x: (
                            0 if x[0] == "General" else 
                            2 if x[0].startswith("Other") else 
                            1,
                            x[0].lower()
                        )
                    )
                    if entries
                }
                if filtered_subcats:
                    filtered_categories[main_cat] = filtered_subcats
        
        return filtered_categories