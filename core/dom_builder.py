from bs4 import BeautifulSoup, Tag
from typing import List, Dict, Any

class DOMBlockBuilder:
    """
    Parses HTML and converts it into a list of structured semantic blocks
    to represent structural elements in a token-efficient JSON format for Gemini.
    """
    def __init__(self, html_content: str):
        self.soup = BeautifulSoup(html_content, "html.parser")

    def build_blocks(self) -> List[Dict[str, Any]]:
        blocks = []
        body = self.soup.find("body") or self.soup
        self._parse_node(body, blocks)
        return blocks

    def _parse_node(self, node: Any, blocks: List[Dict[str, Any]]):
        if not node:
            return
            
        current_inline_group = []
        
        def flush_inline_group():
            if current_inline_group:
                text_parts = []
                for item in current_inline_group:
                    if isinstance(item, Tag):
                        text_parts.append(item.get_text(" ", strip=True))
                    else:
                        text_parts.append(str(item).strip())
                text = " ".join(p for p in text_parts if p).strip()
                if text:
                    blocks.append({
                        "type": "paragraph",
                        "text": text
                    })
                current_inline_group.clear()

        block_tag_names = {"div", "section", "article", "main", "body", "p", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "dl"}

        for child in node.children:
            is_tag = isinstance(child, Tag)
            
            if is_tag and (child.name in block_tag_names or child.name in ("img", "input")):
                flush_inline_group()
                
                # Headings
                if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    level = int(child.name[1])
                    text = child.get_text(" ", strip=True)
                    if text:
                        blocks.append({
                            "type": "heading",
                            "level": level,
                            "text": text
                        })
                # Paragraphs
                elif child.name == "p":
                    text = child.get_text(" ", strip=True)
                    if text:
                        blocks.append({
                            "type": "paragraph",
                            "text": text
                        })
                # Bullet/Ordered Lists
                elif child.name in ("ul", "ol"):
                    items = []
                    for li in child.find_all("li", recursive=False):
                        text = li.get_text(" ", strip=True)
                        if text:
                            items.append(text)
                    if items:
                        blocks.append({
                            "type": "list",
                            "list_type": "ordered" if child.name == "ol" else "unordered",
                            "items": items
                        })
                # Definition Lists
                elif child.name == "dl":
                    items = []
                    dt = None
                    for sub in child.children:
                        if not isinstance(sub, Tag):
                            continue
                        if sub.name == "dt":
                            dt = sub.get_text(" ", strip=True)
                        elif sub.name == "dd" and dt:
                            dd = sub.get_text(" ", strip=True)
                            items.append({"key": dt, "value": dd})
                            dt = None
                    if items:
                        blocks.append({
                            "type": "definition_list",
                            "items": items
                        })
                # Tables
                elif child.name == "table":
                    rows = []
                    for tr in child.find_all("tr"):
                        row_data = []
                        for cell in tr.find_all(["td", "th"]):
                            row_data.append(cell.get_text(" ", strip=True))
                        if any(row_data):
                            rows.append(row_data)
                    if rows:
                        blocks.append({
                            "type": "table",
                            "rows": rows
                        })
                # Images
                elif child.name == "img":
                    src = child.get("src", "")
                    alt = child.get("alt", "") or child.get("title", "")
                    if src or alt:
                        blocks.append({
                            "type": "image",
                            "src": src,
                            "alt": alt
                        })
                # Input Fields
                elif child.name == "input":
                    placeholder = child.get("placeholder", "")
                    val = child.get("value", "")
                    if placeholder or val:
                        blocks.append({
                            "type": "input",
                            "placeholder": placeholder,
                            "value": val
                        })
                # Generic wrappers
                elif child.name in ("div", "section", "article", "main", "body"):
                    self._parse_node(child, blocks)
            else:
                if is_tag:
                    current_inline_group.append(child)
                else:
                    text_val = str(child).strip()
                    if text_val:
                        current_inline_group.append(child)
                        
        flush_inline_group()
