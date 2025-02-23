from typing import Dict, List
from datetime import datetime, UTC
import re
from ..models.weblink import WebLink

class MarkdownWriter:
    @staticmethod
    def make_anchor(text: str) -> str:
        return re.sub(r'[^a-z0-9-]', '', text.lower().replace(' ', '-'))

    def write_markdown(self, categories: Dict[str, Dict[str, List[WebLink]]], invalid_links: List[WebLink], output_file: str):
        """Write organized links to markdown file with proper heading hierarchy."""
        with open(output_file, 'w', encoding='utf-8') as f:
            # Write main title and metadata
            f.write("# Organized Web Links\n\n")
            f.write(f"*Generated on {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC*\n")
            
            total_links = sum(
                len(entries) 
                for cat in categories.values() 
                for entries in cat.values()
            )
            total_subcats = sum(len(subcats) for subcats in categories.values())
            f.write(f"*Total Links: {total_links} in {total_subcats} subcategories*\n\n")
            
            # Table of Contents
            f.write("## Table of Contents\n\n")
            
            # Sort main categories (keeping Uncategorized last)
            main_categories = sorted(
                [cat for cat in categories.keys() if cat != "Uncategorized"]
            )
            if "Uncategorized" in categories:
                main_categories.append("Uncategorized")

            for main_cat in main_categories:
                if not categories[main_cat]:
                    continue
                
                main_anchor = self.make_anchor(main_cat)
                cat_count = sum(len(entries) for entries in categories[main_cat].values())
                f.write(f"- [**{main_cat}**](#{main_anchor}) ({cat_count} links)\n")
                
                # Sort subcategories
                subcats = sorted(
                    categories[main_cat].keys(),
                    key=lambda x: (
                        0 if x == "General" else 
                        2 if x.startswith("Other") else 
                        1,
                        x.lower()
                    )
                )
                
                # Only show subcategories in TOC if there's more than just "General"
                if not (len(subcats) == 1 and subcats[0] == "General"):
                    for subcat in subcats:
                        subcat_anchor = f"{main_anchor}-{self.make_anchor(subcat)}"
                        subcat_count = len(categories[main_cat][subcat])
                        f.write(f"  - [{subcat}](#{subcat_anchor}) ({subcat_count} links)\n")
            
            f.write("\n---\n\n")
            
            # Write categories and links
            for main_cat in main_categories:
                if not categories[main_cat]:
                    continue
                
                f.write(f"## {main_cat}\n\n")
                
                # Sort subcategories
                subcats = sorted(
                    categories[main_cat].keys(),
                    key=lambda x: (
                        0 if x == "General" else 
                        2 if x.startswith("Other") else 
                        1,
                        x.lower()
                    )
                )
                
                # Check if category has only "General" subcategory
                only_general = len(subcats) == 1 and subcats[0] == "General"
                
                for subcat in subcats:
                    entries = categories[main_cat][subcat]
                    if not entries:
                        continue
                    
                    # Only write subheader if it's not the only "General" subcategory
                    if not (only_general and subcat == "General"):
                        f.write(f"### {subcat}\n\n")
                    
                    # Sort entries
                    sorted_entries = sorted(
                        entries,
                        key=lambda e: (
                            (e.description or '').lower() or e.url.lower(),
                            e.url.lower()
                        )
                    )

                    for entry in sorted_entries:
                        if entry.description and entry.description != entry.url:
                            f.write(f"- {entry.description}: {entry.url}\n")
                        else:
                            f.write(f"- {entry.url}\n")
                    
                    f.write("\n")

            # Add invalid links section at the end
            if invalid_links:
                f.write("## Links Not Working\n\n")
                for entry in sorted(invalid_links, key=lambda e: (e.description or '').lower() or e.url.lower()):
                    if entry.description and entry.description != entry.url:
                        f.write(f"- {entry.description}: {entry.url}\n")
                    else:
                        f.write(f"- {entry.url}\n")
                    f.write("\n")