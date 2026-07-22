"""
Shared pytest fixtures for the DOM Intelligence test suite.

All HTML snippets are minimal, self-contained, and do not require network
access.  They are designed to trigger specific heuristic branches in each
analyser module.
"""

import pytest


# ---------------------------------------------------------------------------
# Minimal / empty HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_html() -> str:
    return ""


@pytest.fixture
def minimal_html() -> str:
    """A single-paragraph page with no structural complexity."""
    return "<html><body><p>Hello, world!</p></body></html>"


# ---------------------------------------------------------------------------
# E-commerce / product catalog HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def product_html() -> str:
    """
    Simulates a product listing page with price signals, add-to-cart buttons,
    images with alt text, and a footer — triggers Product Catalog scoring.
    """
    return """
    <html>
    <head><title>Shop — Best Deals</title></head>
    <body>
      <nav><a href="/">Home</a> <a href="/shop">Shop</a></nav>
      <main>
        <div class="product-card">
          <img src="/img/phone.jpg" alt="Smartphone XL">
          <h2>Smartphone XL</h2>
          <span class="price">$299.99</span>
          <button>Add to Cart</button>
        </div>
        <div class="product-card">
          <img src="/img/laptop.jpg" alt="Laptop Pro">
          <h2>Laptop Pro</h2>
          <span class="price">$899.00</span>
          <button>Add to Cart</button>
        </div>
        <div class="product-card">
          <img src="/img/tablet.jpg" alt="Tablet Mini">
          <h2>Tablet Mini</h2>
          <span class="price">$199.50</span>
          <button>Add to Cart</button>
        </div>
      </main>
      <footer><p>© 2024 Shop Inc.</p></footer>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Blog / multi-article HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def blog_html() -> str:
    """
    Simulates a blog index page with multiple article elements and time tags —
    triggers Blog scoring.
    """
    return """
    <html>
    <head><title>My Tech Blog</title></head>
    <body>
      <nav><a href="/">Home</a> <a href="/blog">Blog</a></nav>
      <main>
        <article>
          <h2>Post One</h2>
          <time datetime="2024-01-10">January 10, 2024</time>
          <p>Author: Jane Doe</p>
          <p>Lorem ipsum dolor sit amet.</p>
        </article>
        <article>
          <h2>Post Two</h2>
          <time datetime="2024-01-15">January 15, 2024</time>
          <p>By John Smith</p>
          <p>Consectetur adipiscing elit.</p>
        </article>
        <article>
          <h2>Post Three</h2>
          <time datetime="2024-01-20">January 20, 2024</time>
          <p>Posted by Alice</p>
          <p>Sed do eiusmod tempor.</p>
        </article>
      </main>
      <footer><p>All rights reserved.</p></footer>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Documentation HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def docs_html() -> str:
    """
    Simulates a documentation page with code blocks and dense headings —
    triggers Documentation scoring.
    """
    return """
    <html>
    <head><title>API Reference</title></head>
    <body>
      <aside class="sidebar toc">
        <ul>
          <li><a href="#intro">Introduction</a></li>
          <li><a href="#auth">Authentication</a></li>
        </ul>
      </aside>
      <main>
        <h1>API Reference</h1>
        <h2 id="intro">Introduction</h2>
        <p>Welcome to the API docs.</p>
        <h2 id="auth">Authentication</h2>
        <p>Use Bearer tokens.</p>
        <pre><code>curl -H "Authorization: Bearer TOKEN" https://api.example.com</code></pre>
        <h3>Request</h3>
        <pre><code>GET /v1/users HTTP/1.1</code></pre>
        <h3>Response</h3>
        <pre><code>{"users": []}</code></pre>
        <h2>Endpoints</h2>
        <h3>Users</h3>
        <pre><code>POST /v1/users</code></pre>
        <h3>Posts</h3>
        <pre><code>GET /v1/posts</code></pre>
      </main>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Single article HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def article_html() -> str:
    """
    Simulates a single news/blog article — triggers Article scoring.
    """
    return """
    <html>
    <head><title>Breaking News Article</title></head>
    <body>
      <nav><a href="/">Home</a></nav>
      <article>
        <h1>Major Discovery Announced</h1>
        <time datetime="2024-03-01">March 1, 2024</time>
        <p>By Jane Reporter</p>
        <p>Scientists have announced a breakthrough in renewable energy.</p>
        <p>The discovery was made at MIT and will be published next month.</p>
      </article>
      <footer><p>© News Corp</p></footer>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Dashboard / data table HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def dashboard_html() -> str:
    """
    Simulates a data dashboard with multiple tables and form inputs —
    triggers Dashboard scoring.
    """
    return """
    <html>
    <head><title>Analytics Dashboard</title></head>
    <body>
      <form>
        <input type="text" placeholder="Search...">
        <select><option>Last 7 days</option><option>Last 30 days</option></select>
        <input type="date">
        <input type="submit" value="Apply">
      </form>
      <table>
        <thead><tr><th>Metric</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>Sessions</td><td>12,340</td></tr>
          <tr><td>Bounce Rate</td><td>42%</td></tr>
        </tbody>
      </table>
      <table>
        <thead><tr><th>Page</th><th>Views</th></tr></thead>
        <tbody>
          <tr><td>/home</td><td>5,000</td></tr>
          <tr><td>/products</td><td>3,200</td></tr>
        </tbody>
      </table>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Feature-rich HTML (all structural features present)
# ---------------------------------------------------------------------------

@pytest.fixture
def feature_rich_html() -> str:
    """
    HTML that contains every structural feature the PageProfiler can detect:
    table, form, nav, footer, aside, pagination, expandable section, lazy img,
    and repeated cards.
    """
    return """
    <html>
    <head><title>Feature Rich Page</title></head>
    <body>
      <nav role="navigation"><a href="/">Home</a></nav>
      <aside role="complementary"><p>Sidebar content</p></aside>
      <main>
        <table><tr><td>Data</td></tr></table>
        <form><input type="text"><button>Submit</button></form>
        <div class="cards">
          <div class="card"><p>Card 1</p></div>
          <div class="card"><p>Card 2</p></div>
          <div class="card"><p>Card 3</p></div>
        </div>
        <details><summary>FAQ</summary><p>Answer here.</p></details>
        <img src="placeholder.jpg" loading="lazy" alt="lazy image">
        <nav aria-label="pagination">
          <a href="?page=1">1</a>
          <a href="?page=2" rel="next">Next</a>
        </nav>
      </main>
      <footer><p>Footer text</p></footer>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Complex HTML (for complexity scoring tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def complex_html() -> str:
    """
    A deeply nested, table-heavy, form-rich HTML page that should score
    HIGH or EXTREME complexity.
    """
    # Build a deeply nested structure programmatically
    deep = "<div>" * 25 + "<p>deep content</p>" + "</div>" * 25
    tables = "\n".join(
        f"<table><tr><td>Cell {i}</td></tr></table>" for i in range(10)
    )
    forms = "\n".join(
        f"<form><input type='text' placeholder='Field {i}'></form>" for i in range(5)
    )
    # Pad HTML to exceed 200KB
    filler = "<p>" + ("x" * 100) + "</p>\n"
    padding = filler * 2100  # ~210KB of filler content
    return f"<html><body>{deep}{tables}{forms}{padding}</body></html>"


# ---------------------------------------------------------------------------
# Listing HTML
# ---------------------------------------------------------------------------

@pytest.fixture
def listing_html() -> str:
    """
    HTML with long ordered/unordered lists — triggers Listing scoring.
    """
    items = "\n".join(f"<li>Item {i}</li>" for i in range(1, 11))
    return f"""
    <html>
    <head><title>Directory</title></head>
    <body>
      <h1>All Items</h1>
      <ul>
        {items}
      </ul>
      <ol>
        {items}
      </ol>
    </body>
    </html>
    """
