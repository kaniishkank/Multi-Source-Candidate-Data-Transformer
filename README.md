# Multi-Source Candidate Data Transformer

A production-grade Python utility that ingests candidate profile data from multiple structured (CSV) and unstructured (notes, resumes) sources, merges them deterministically using a prioritized precedence conflict policy, logs provenance changes, and reshapes candidate profiles according to client-defined layouts.

## Features

- **LLM Data Extraction Layer (`parser.py`)**: Uses the modern Gemini API (`gemini-2.5-flash` with a fallback to `gemini-1.5-flash`) to parse unstructured notes/resumes into valid JSON profiles with strict validations (ISO-3166-1 alpha-2 countries, E.164 phones, YYYY-MM dates).
- **Deterministic Merge Engine (`pipeline.py`)**: Manages candidate profile states and deduplication. Ranks sources hierarchically (`recruiter_csv` > `unstructured_note`) to resolve value conflicts.
- **Provenance Log**: Keeps a historical trail of every commit or update with source names, methods, and timestamps.
- **Flexible Projection Layer**: Supports reshaping and slicing data based on JSON specifications using dot-bracketed paths (e.g. `emails[0]`, `locations[0].city`). Handles `on_missing` behavior flags (`null`, `omit`, or `error`).
- **CLI Interface Wrapper (`main.py`)**: Coordinates inputs (`--csv`, `--notes`, `--config`) and degrades gracefully on API network failures or parsing issues instead of crashing.

---

## Codebase Structure

- `parser.py`: Gemini client integration logic.
- `pipeline.py`: The `CandidateTransformer` logic, data mapping helper, and layout projector.
- `main.py`: Command-line interface orchestration.
- `test_pipeline.py`: Standard unit testing framework.
- `run_validation.py`: Programmatic helper script to write mock files and execute tests.
- `data/`: Directory storing test candidates and unstructured notes.
- `config.json`: The layout specification file.
- `.gitignore`: Standard git rules for ignoring Python cache files and logs.

---

## Installation & Setup

1. **Install python dependency**:
   ```bash
   pip install google-genai
   ```

2. **Configure API Credentials**:
   To enable LLM extraction, export your Gemini key to your environment variables:
   ```bash
   # Windows (PowerShell)
   $env:GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

   # Linux/macOS
   export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
   ```

---

## How to Run

### 1. Run Verification & Mock Generation
To quickly create sample data, write configuration layout specifications, and verify unit tests, execute:
```bash
python run_validation.py
```

### 2. Run CLI Command
To transform candidate files and print the restructured profile directly to stdout:
```bash
python main.py --csv data/recruiter.csv --notes data/notes.txt --config config.json
```

If the `GEMINI_API_KEY` is not present, `main.py` will print a warning message to `stderr` and fallback to using the CSV source data only rather than crashing.

### 3. Run Unit Tests
To execute the suite verifying conflict policies and projection parameters:
```bash
python -m unittest test_pipeline.py
```

---

## Merge Policies & Priority Rankings

| Source Type | Priority Rank | Behavior on Value Conflict |
|---|---|---|
| `recruiter_csv` | 2 (Highest) | Overwrites scalar fields. Sorting lists puts CSV values at the top of the queue. |
| `unstructured_note` | 1 (Lowest) | Ingested first or appended/deduplicated if CSV is already present. |
