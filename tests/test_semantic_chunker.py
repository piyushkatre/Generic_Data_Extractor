import pytest
from bs4 import BeautifulSoup
from modules.semantic_chunker.chunker import chunk_html
from modules.semantic_chunker.models import ChunkingResult
from modules.preprocessor import estimate_tokens, detect_page_type

def test_chunker_small_page():
    html = "<html><head><title>Test Title</title></head><body><h1>Heading</h1><p>This is a small page content.</p></body></html>"
    res = chunk_html(html, safe_token_limit=100)
    assert isinstance(res, ChunkingResult)
    assert res.total_chunks == 1
    assert "Test Title" in res.chunks[0].page_title

def test_chunker_large_page_split():
    list_items = "".join(f"<li>Item number {i} with some descriptive text</li>" for i in range(50))
    html = f"<html><body><div id='content'><ul>{list_items}</ul></div></body></html>"
    
    res = chunk_html(html, safe_token_limit=20)
    assert res.total_chunks > 1
    assert "ul" in res.chunks[0].html
    assert res.chunks[0].parent_section == "content"

def test_chunker_table_split():
    rows = "".join(f"<tr><td>Cell A {i}</td><td>Cell B {i}</td></tr>" for i in range(40))
    html = f"<html><body><table>{rows}</table></body></html>"
    
    res = chunk_html(html, safe_token_limit=15)
    assert res.total_chunks > 1
    for chunk in res.chunks:
        assert "table" in chunk.html
        assert "tr" in chunk.html

def test_chunker_fallback_sliding_window():
    text = "Word " * 1000
    html = f"<html><body><p>{text}</p></body></html>"
    
    res = chunk_html(html, safe_token_limit=50)
    assert res.total_chunks > 1

def test_token_estimator():
    # Estimating clean HTML and visible text
    html = "<html><body>" + "<p>Some text</p>" * 100 + "</body></html>"
    tokens = estimate_tokens(html)
    # len(html) is around 13 * 100 + 25 = 1325. html_tokens = 1325 // 4 = 331
    # text is "Some text " * 100. len(text) = 1000. text_tokens = 1000 // 3 = 333
    # estimate_tokens should be max(331, 333) = 333
    assert tokens >= 330

def test_page_understanding_faq():
    faq_html = """
    <html><body>
      <div class="faq-section">
        <details><summary>What is this?</summary><p>It is a test.</p></details>
        <details><summary>Who are you?</summary><p>I am an assistant.</p></details>
        <details><summary>Why simplify?</summary><p>To make it clean.</p></details>
      </div>
    </body></html>
    """
    res = detect_page_type(faq_html)
    assert res["page_type"] == "FAQ"
    assert res["confidence"] > 0.4

def test_page_understanding_documentation():
    doc_html = """
    <html><body>
      <h1>API Guide</h1>
      <pre><code>import sys; print(sys.version)</code></pre>
      <h2>Section 1</h2>
      <pre><code>x = 5</code></pre>
      <h2>Section 2</h2>
      <h3>Subset A</h3>
      <h2>Section 3</h2>
      <h2>Section 4</h2>
      <h2>Section 5</h2>
      <h2>Section 6</h2>
      <h2>Section 7</h2>
    </body></html>
    """
    res = detect_page_type(doc_html)
    assert res["page_type"] == "Documentation"

def test_smarter_chunking_faq():
    faq_html = """
    <html><body>
      <div id="faq-container">
        <details><summary>Q1</summary><p>A1</p></details>
        <details><summary>Q2</summary><p>A2</p></details>
        <details><summary>Q3</summary><p>A3</p></details>
      </div>
    </body></html>
    """
    # Force split by specifying low limit
    res = chunk_html(faq_html, safe_token_limit=10, page_type_guess="FAQ")
    assert res.total_chunks >= 3
    # Check that individual chunks are details tags
    for chunk in res.chunks[:3]:
        assert "details" in chunk.html
