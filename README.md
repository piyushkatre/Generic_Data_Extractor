# Generic Schema-Driven Franchise Data Extractor 🚀

A highly optimized, generic, and adapter-driven hybrid information extraction pipeline designed to extract structured franchise data from any supported web page and store them accurately into schema-compliant Excel spreadsheets.

---

## 🛠️ Key Architectural Components

The pipeline separates structured data extraction into two distinct, high-performance phases:

```
                  URL
                   │
         [Playwright Rendering]
         - Tab-clicking & Merging
                   │
           [DOM Preprocessor]
         - Clean structure & attributes
                   │
       ┌───────────┴───────────┐
       ▼                       ▼
  [Deterministic]           [Gemini]
  - BS4 & Regex             - complementary
  - 24+ structured fields   - reasoning & NLP
       └───────────┬───────────┘
                   ▼
           [Record Validator]
         - Sanitize, Clean & Validate
                   │
            [Schema Mapper]
         - Column & alias resolver
                   │
           [Dataset Builder]
         - franchise_dataset.xlsx
```

### 1. Robust Tab Collection & DOM Processing
* **Playwright Render Engine (`modules/browser.py`)**: Sequentially scrolls pages, clicks franchise-specific tabs (`Profile`, `Business Summary`, `FAQ`, `Gallery`, `Reviews`), and merges loaded tab panes into a single unified HTML document.
* **DOM Preprocessor (`modules/preprocessor.py`)**: Sanitizes structure, keeping only safe layout tags and routing-relevant attributes (`class`, `id`, `role`, etc.).

### 2. Hybrid Extraction Layer
* **Deterministic Extractor (`modules/dataset_builder/deterministic_extractor.py`)**: Parses structured key-value tables and details lists directly from the DOM using BeautifulSoup and regex. Resolves 24+ fields (including contact info, social links, logo URLs, and document assets) instantly without using LLM tokens.
* **Complementary LLM Extractor (`modules/gemini.py`)**: Uses Gemini 2.5 Flash to extract descriptive fields requiring natural language understanding (e.g. *About*, *Business Model*, *Products / Services*, *Ideal Franchisee*, *Marketing Support*). Gemini never overwrites deterministic DOM values.

### 3. Record Validator (`modules/dataset_builder/record_validator.py`)
A dedicated validation layer between extraction and schema mapping that enforces strict quality checks:
* **Franchise Name**: Rejects generic placeholders (like `"Franchise Opportunity"`).
* **Established Year**: Parses and extracts only clean 4-digit years (e.g. `2016`).
* **Agreement Duration**: Rejects simple `"Yes"` or `"No"` placeholders.
* **Phone / Email**: Matches values against strict formatting regexes to filter out junk or area ranges.
* **Financial / Area Indicators**: Rejects values missing currency symbols (for investment) or square footage indicators (for area).

### 4. Schema Mapper & Dataset Builder (`modules/dataset_builder/schema_mapper.py` & `builder.py`)
* Maps canonical records to target Excel columns using exact, alias, and alphanumeric canonical matching.
* Ensures known schema fields are **never** placed in the `Additional Information` column.
* Restricts `Additional Information` strictly to unmapped, custom fields (maintaining `< 5%` footprint).

---

## 🌟 Phase 2 Feature Enhancements

We have recently upgraded the extraction pipeline with several key features to boost quality, diagnostics, and robustness:

### 1. Adapter-Driven DOM Cleaning & Pruning
* **Dynamic Keywords Preservation**: The preprocessor dynamically builds preservation lists based on columns, aliases, and extraction fields from the adapter's schema, instead of using hardcoded keywords.
* **Two-Level DOM Filtering**: Introduced `CRITICAL` vs `NORMAL` priority filtering level inside the Relevant DOM Builder. Critical fields, contacts, and location blocks are guaranteed to never be removed during structuring.

### 2. Multi-Format Parsers & Advanced Normalization
* **Advanced Deterministic Extractors**: Added Sentence Key-Value parser, Heading-to-Paragraph parser, Maps links/coordinates extractor, and social link recognition.
* **Dynamic Equivalence Matching**: Implemented equivalence checks inside the evaluation framework:
  * **Phone**: Formats are compared by matching the suffix digits (e.g. `+91 9876543210` == `9876543210`).
  * **URL**: Checks domains and paths by stripping protocol and subdomain (e.g. `https://abc.com/` == `http://abc.com`).
  * **Address**: Normalizes punctuation and extra whitespace to evaluate matching words.
  * **Duration**: Converts duration/time values to a unified month unit (e.g. `6 Months` == `0.5 year` == `180 days`).
* **Normalized Range Validations**: Skipped/disabled offline validation warnings for normalized currency, percentage, and measurement ranges if they represent clean numeric entries.
* **Smart Currency Standardization**: Normalizes target spreadsheet cells to the uniform `₹20 Lakhs` (or Crore/K/₹) format for Indian Rupees while preserving foreign currencies (e.g. `$60,000` USD) without conversion.

### 3. Execution Diagnostics & Snapping
* **Timestamped Debug Snapshots**: When `DEBUG=True` or `DEVELOPER_MODE` is enabled, the pipeline automatically writes execution snapshots to run-specific subdirectories under `debug/run_YYYYMMDD_HHMMSS/` (e.g., HTML structure, prompt, gemini extraction, validated records, mapping paths, and mapped spreadsheet rows).
* **Detailed Mapping Trace**: Documents exact mapping paths for each spreadsheet column (e.g., `Mapped Column -> Mapping Source -> Alias Used -> Normalizer Used`) inside `MappingResult`.
* **Browser Tab Classification**: Categorizes crawled tabs into Static, Dynamic, Duplicate, or Ignored with tab navigation logging.
* **Rich Streamlit Diagnostics Dashboard**:
  * Displays **Overall Extraction Quality Score** metric (`Mapped Fields / Total Expected Fields * 100`).
  * Renders a **🔌 Adapter Health Report** dashboard table summarizing Adapter details, Quality, DOM Retention %, Deterministic/Gemini counts, normalizations, and warnings.
  * Provides expandable diagnostic blocks tracing DOM Statistics, Deterministic Fields, Gemini Fields, Validator Changes, and Mapping Summary paths.

---

## 📂 Project Structure

```
/
├── app/
│   └── app.py                   # Streamlit layout and extraction grid UI
├── modules/
│   ├── browser.py               # Playwright tab clicker and page loader
│   ├── preprocessor.py          # HTML cleaner and attribute whitelist
│   ├── gemini.py                # Pydantic schemas, Gemini API caller & result merger
│   ├── dataset_builder/
│   │   ├── builder.py           # Excel spreadsheet writer
│   │   ├── deterministic_extractor.py # Local BS4/Regex table & list parser
│   │   ├── record_validator.py  # Data cleansing, validation & normalization
│   │   └── schema_mapper.py     # Schema matching tier resolver
│   ├── evaluation/
│   │   ├── dom_checker.py       # Anti-hallucination DOM verification
│   │   └── quality_evaluator.py # Extraction coverage reporter
│   └── semantic_chunker/
│       └── chunker.py           # Text layout segmenter
├── schemas/
│   ├── franchise_schema.json    # Excel columns list blueprint
│   └── schema_aliases.json      # Column headers alias directory
├── tests/
│   ├── test_deterministic_extractor.py
│   ├── test_record_validator.py
│   ├── test_schema_mapper.py
│   └── ...                      # 83+ comprehensive test suites
├── requirements.txt             # Dependency requirements
└── README.md                    # Core project blueprints
```

---

## ⚡ Setup & Run

### 1. Virtual Environment Setup
```bash
# Initialize and activate env
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Download Playwright chromium binaries
playwright install chromium
```

### 2. Configuration
Copy `.env.example` to `.env` and fill in your Google AI Gemini API Key:
```bash
cp .env.example .env
# Edit .env: GEMINI_API_KEY=your_api_key_here
```

### 3. Run Streamlit UI Dashboard
```bash
streamlit run app/app.py
```

### 4. Run Test Suite
```bash
pytest
```
