# Generic Schema-Driven Data Extractor 🚀

A generic, schema-driven hybrid information extraction pipeline: point it at a URL plus a **Website Configuration** and an **Extraction Schema**, and it renders the page, prunes irrelevant DOM, extracts fields deterministically where possible, fills the rest with an LLM, validates, and writes a schema-compliant spreadsheet row. It ships with franchise-listing templates (FranchiseBazar, FranchiseIndia, IndiaMART, ...), but the extraction engine itself has no franchise-specific assumptions baked in — see `docs/ARCHITECTURE_REDESIGN.md` for the architecture rationale and `docs/PROJECT_STRUCTURE.md` for a fuller module-by-module reference.

---

## 🛠️ Key Architectural Components

The pipeline separates structured data extraction into two distinct, high-performance phases:

```
                  URL
                   │
         [Playwright Rendering]
         - Tab-clicking & Merging (per WebsiteConfig)
                   │
           [DOM Preprocessor]
         - Clean structure & attributes
                   │
       ┌───────────┴───────────┐
       ▼                       ▼
  [Deterministic]           [LLM Provider]
  - BS4 & Regex             - complementary
  - schema-alias driven     - reasoning & NLP
       └───────────┬───────────┘
                   ▼
        [Field-Ownership Merge]
      - OwnershipResolver decides
        deterministic vs LLM per field
                   │
           [Record Validator]
         - Sanitize, Clean & Validate
                   │
            [Schema Mapper]
         - Column & alias resolver
                   │
           [Dataset Builder]
         - schema-defined .xlsx output
```

### 1. Robust Tab Collection & DOM Processing
* **Playwright Render Engine (`modules/browser.py`)**: Sequentially scrolls pages, clicks the tabs named in the active `WebsiteConfig` (e.g. `Profile`, `Business Summary`, `FAQ`, `Gallery`, `Reviews` for the franchise-listing templates), and merges loaded tab panes into a single unified HTML document.
* **DOM Preprocessor (`modules/preprocessor.py`)**: Sanitizes structure, keeping only safe layout tags and routing-relevant attributes (`class`, `id`, `role`, etc.), and runs a lightweight page-type detector purely for informational display (it never selects a schema).

### 2. Hybrid Extraction Layer
* **Deterministic Extractor (`modules/dataset_builder/deterministic_extractor.py`)**: Parses structured key-value tables and details lists directly from the DOM using BeautifulSoup and regex, resolving whichever fields the active `ExtractionSchema` declares aliases for — instantly, without using LLM tokens.
* **LLM Extractor (`modules/gemini.py` + `modules/llm/`)**: Calls the configured provider (Gemini or Ollama) to fill in fields requiring natural language understanding, validated against a dynamic model built purely from the active schema (no inherited fields from other verticals).
* **Field-Ownership Merge (`core/ownership.py`)**: For each schema field, `OwnershipResolver` decides whether the deterministic value or the LLM value wins, based on the field's own declared ownership (if set) or a generic type-based default.

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

### 1. Config/Schema-Driven DOM Cleaning & Pruning
* **Dynamic Keywords Preservation**: The preprocessor dynamically builds preservation lists based on the active `ExtractionSchema`'s columns, aliases, and extraction fields, instead of using hardcoded keywords.
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
│   ├── app.py                   # Streamlit layout and extraction grid UI
│   └── main.py                  # FastAPI endpoint - same ExtractionPipeline as the UI
├── core/
│   ├── pipeline.py              # ExtractionPipeline - the single orchestration path
│   ├── runtime_adapter.py       # RuntimeAdapter - built from a WebsiteConfig + ExtractionSchema
│   ├── ownership.py             # OwnershipResolver - deterministic-vs-LLM field merge
│   ├── pipeline_context.py      # PipelineContext - runtime state carrier for one run
│   └── job_executor.py          # execute_job() - runs an ExtractionJob's URLs through the pipeline
├── config/
│   ├── website_config.py        # WebsiteConfig
│   ├── extraction_schema.py     # ExtractionField / ExtractionSchema
│   └── extraction_job.py        # ExtractionJob
├── modules/
│   ├── browser.py               # Playwright tab clicker and page loader
│   ├── preprocessor.py          # HTML cleaner, attribute whitelist, page-type detector
│   ├── gemini.py                # Thin LLM-provider-call wrapper (no orchestration)
│   ├── validation/
│   │   └── formatters.py        # Currency/area/hours/phone normalizers
│   ├── dataset_builder/
│   │   ├── builder.py           # Excel spreadsheet writer
│   │   ├── deterministic_extractor.py # Local BS4/Regex table & list parser
│   │   ├── record_validator.py  # Data cleansing, validation & normalization
│   │   ├── schema_mapper.py     # Schema matching tier resolver
│   │   ├── schema_loader.py     # build_model(): schema -> dynamic Pydantic model
│   │   └── generic_record.py    # GenericExtractionRecord - the minimal universal core
│   ├── merger/                  # Legacy, unused (abandoned chunking strategy)
│   └── semantic_chunker/        # Legacy, unused (abandoned chunking strategy)
├── templates/                   # WebsiteConfig + ExtractionSchema pairs, one folder per site
│   ├── default/
│   ├── franchise_bazar/
│   └── ...
├── schemas/
│   ├── franchise_schema.json    # Legacy page-type schema (optional fallback only)
│   └── schema_aliases.json      # Column headers alias directory
├── tests/
│   ├── test_deterministic_extractor.py
│   ├── test_record_validator.py
│   ├── test_schema_mapper.py
│   ├── test_schema_field_omission.py  # Verifies undeclared schema fields never surface end-to-end
│   ├── test_pipeline_integration.py
│   └── ...                      # 140+ comprehensive test suites
├── docs/
│   ├── PROJECT_STRUCTURE.md     # Fuller module-by-module reference
│   └── ARCHITECTURE_REDESIGN.md # Forward-looking blueprint (Profiles, versioning, stores, UI)
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
