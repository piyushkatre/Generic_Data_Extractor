from __future__ import annotations

import time
from typing import List, Optional
from bs4 import BeautifulSoup, Tag

from modules.semantic_chunker.models import ChunkingResult, SemanticChunk
from utils.logger import get_logger

logger = get_logger(__name__)

def _get_heading_path(element: Tag) -> List[str]:
    """
    Traverse parents of the element to find preceding heading texts.
    """
    headings = []
    # Simple strategy: find sibling headings before the current element or parent elements
    # But to keep it simple, we search for previous sibling headings or parent tag headings
    curr = element
    while curr:
        # Find previous siblings that are headings
        sib = curr.previous_sibling
        while sib:
            if getattr(sib, "name", None) in ("h1", "h2", "h3", "h4", "h5", "h6"):
                headings.append(sib.get_text().strip())
                break
            sib = sib.previous_sibling
        curr = curr.parent
    return list(reversed(headings))

def chunk_html(
    html_content: str,
    safe_token_limit: int = 60000,
    page_title: str = "",
    page_type_guess: str = "Unknown"
) -> ChunkingResult:
    """
    Simple iterative semantic chunker that splits large HTML pages into semantic blocks.
    It guarantees that each chunk fits inside safe_token_limit (estimated heuristic).
    """
    start_time = time.perf_counter()
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Extract title if not provided
    if not page_title:
        if soup.title and soup.title.string:
            page_title = soup.title.string.strip()
        else:
            h1 = soup.find("h1")
            if h1:
                page_title = h1.get_text().strip()
            else:
                page_title = "Untitled Page"
                
    # Check if the entire HTML fits within safe_token_limit
    from modules.preprocessor import estimate_tokens
    est_total_tokens = estimate_tokens(html_content)
    if est_total_tokens <= safe_token_limit:
        return ChunkingResult(
            chunks=[
                SemanticChunk(
                    chunk_id=1,
                    page_title=page_title,
                    page_type_guess=page_type_guess,
                    parent_section="body",
                    heading_path=[],
                    estimated_tokens=est_total_tokens,
                    char_count=len(html_content),
                    html=html_content
                )
            ],
            total_chunks=1,
            strategy_used="DIRECT",
            total_chars=len(html_content),
            average_chunk_chars=len(html_content),
            largest_chunk_chars=len(html_content),
            smallest_chunk_chars=len(html_content),
            recursive_split_count=0,
            chunking_time_ms=int((time.perf_counter() - start_time) * 1000),
            oversized_chunks=0
        )

    # Start with top-level child elements of body (or soup if no body)
    body = soup.find("body") or soup

    elements = [el for el in body.children if getattr(el, "name", None) is not None]
    
    chunks: List[SemanticChunk] = []
    chunk_id_seq = 1
    
    # Iterative stack for traversal: tuple of (element, parent_section)
    todo = [(el, "body") for el in elements]
    
    while todo:
        current, parent_sec = todo.pop(0)
        current_html = str(current)
        est_tokens = estimate_tokens(current_html)
        
        # If the element fits, or is very small, make it a chunk
        if est_tokens <= safe_token_limit or len(current_html) <= 50:
            chunks.append(
                SemanticChunk(
                    chunk_id=chunk_id_seq,
                    page_title=page_title,
                    page_type_guess=page_type_guess,
                    parent_section=parent_sec,
                    heading_path=_get_heading_path(current),
                    estimated_tokens=est_tokens,
                    char_count=len(current_html),
                    html=current_html
                )
            )
            chunk_id_seq += 1
        else:
            # Oversized element! Split by page type custom rules.
            tag_name = current.name
            
            # 1. FAQ splitting:
            if page_type_guess == "FAQ":
                details_tags = current.find_all("details", recursive=False)
                if details_tags:
                    todo = [(d, parent_sec) for d in details_tags] + todo
                    continue
                children = [c for c in current.children if getattr(c, "name", None) is not None]
                if children:
                    todo = [(c, parent_sec) for c in children] + todo
                    continue
                    
            # 2. Product Listing / Franchise Listing:
            if page_type_guess in ("Product Listing", "Franchise Listing"):
                cards = []
                for child in current.children:
                    if getattr(child, "name", None) is not None:
                        c_id = str(child.get("id", "")).lower()
                        c_class = " ".join(child.get("class", [])).lower() if child.get("class") else ""
                        if any(k in c_id or k in c_class for k in ("product", "card", "item", "listing", "row", "col")):
                            cards.append(child)
                if cards:
                    todo = [(c, parent_sec) for c in cards] + todo
                    continue
            
            # 3. Documentation splitting:
            if page_type_guess == "Documentation":
                parts = []
                current_part = []
                for child in current.children:
                    if getattr(child, "name", None) is not None:
                        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                            if current_part:
                                part_html = "".join(str(x) for x in current_part)
                                if part_html.strip():
                                    parts.append(BeautifulSoup(part_html, "html.parser"))
                            current_part = [child]
                        else:
                            current_part.append(child)
                if current_part:
                    part_html = "".join(str(x) for x in current_part)
                    if part_html.strip():
                        parts.append(BeautifulSoup(part_html, "html.parser"))
                if len(parts) > 1:
                    todo = [(p, parent_sec) for p in parts] + todo
                    continue

            # 4. Table-heavy pages (or if the tag itself is a table):
            if tag_name == "table" or page_type_guess == "Table-heavy":
                rows = current.find_all("tr")
                if len(rows) > 1:
                    half = len(rows) // 2
                    table_1 = f"<table>{''.join(str(r) for r in rows[:half])}</table>"
                    table_2 = f"<table>{''.join(str(r) for r in rows[half:])}</table>"
                    
                    soup_t1 = BeautifulSoup(table_1, "html.parser").table
                    soup_t2 = BeautifulSoup(table_2, "html.parser").table
                    if soup_t1 and soup_t2:
                        todo = [(soup_t1, parent_sec), (soup_t2, parent_sec)] + todo
                        continue

            # 5. Blog / News Article (or default Layout tags):
            if tag_name in ("section", "article", "main", "div", "body", "header", "footer"):
                children = [c for c in current.children if getattr(c, "name", None) is not None]
                if children:
                    child_sec = current.get("id") or current.get("class") or parent_sec
                    if isinstance(child_sec, list):
                        child_sec = "-".join(child_sec)
                    todo = [(c, str(child_sec)) for c in children] + todo
                    continue

            # 6. Default lists split by items
            if tag_name in ("ul", "ol"):
                items = current.find_all("li")
                if len(items) > 1:
                    half = len(items) // 2
                    list_1 = f"<{tag_name}>{''.join(str(it) for it in items[:half])}</{tag_name}>"
                    list_2 = f"<{tag_name}>{''.join(str(it) for it in items[half:])}</{tag_name}>"
                    
                    soup_l1 = BeautifulSoup(list_1, "html.parser").find(tag_name)
                    soup_l2 = BeautifulSoup(list_2, "html.parser").find(tag_name)
                    if soup_l1 and soup_l2:
                        todo = [(soup_l1, parent_sec), (soup_l2, parent_sec)] + todo
                        continue

            # Fallback: Fixed character window
            text_content = current_html
            window_size = safe_token_limit * 3
            if window_size < 1000:
                window_size = 1000
                
            for i in range(0, len(text_content), window_size):
                chunk_slice = text_content[i:i+window_size]
                chunks.append(
                    SemanticChunk(
                        chunk_id=chunk_id_seq,
                        page_title=page_title,
                        page_type_guess=page_type_guess,
                        parent_section=parent_sec,
                        heading_path=_get_heading_path(current),
                        estimated_tokens=estimate_tokens(chunk_slice),
                        char_count=len(chunk_slice),
                        html=chunk_slice
                    )
                )
                chunk_id_seq += 1

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    
    char_counts = [c.char_count for c in chunks] or [0]
    return ChunkingResult(
        chunks=chunks,
        total_chunks=len(chunks),
        strategy_used="HIERARCHICAL_CHUNKING",
        total_chars=sum(char_counts),
        average_chunk_chars=int(sum(char_counts) / len(chunks)) if chunks else 0,
        largest_chunk_chars=max(char_counts),
        smallest_chunk_chars=min(char_counts),
        recursive_split_count=0,
        chunking_time_ms=elapsed_ms,
        oversized_chunks=0
    )

