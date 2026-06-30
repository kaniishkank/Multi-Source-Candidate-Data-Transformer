import sys
import argparse
import json
import csv
import os
from pipeline import CandidateTransformer
from parser import extract_unstructured_data

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Source Candidate Data Transformer CLI."
    )
    parser.add_argument("--csv", help="Path to recruiter CSV file")
    parser.add_argument("--notes", help="Path to unstructured candidate notes file")
    parser.add_argument("--config", required=True, help="Path to projection configuration JSON file")
    
    args = parser.parse_args()
    
    transformer = CandidateTransformer()
    
    # Process structured CSV if provided
    if args.csv:
        if not os.path.exists(args.csv):
            print(f"Error: CSV file not found at '{args.csv}'", file=sys.stderr)
            sys.exit(1)
        try:
            with open(args.csv, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if not rows:
                    print(f"Warning: CSV file '{args.csv}' is empty.", file=sys.stderr)
                for row in rows:
                    transformer.ingest_csv_row(row)
        except Exception as e:
            print(f"Error parsing CSV file '{args.csv}': {e}", file=sys.stderr)
            sys.exit(1)
            
    # Process unstructured notes if provided
    if args.notes:
        if not os.path.exists(args.notes):
            print(f"Error: Notes file not found at '{args.notes}'", file=sys.stderr)
            sys.exit(1)
        try:
            with open(args.notes, mode='r', encoding='utf-8') as f:
                raw_text = f.read()
            
            # Extract unstructured data using Gemini
            try:
                parsed_data = extract_unstructured_data(raw_text)
                transformer.ingest_parsed_json(parsed_data)
            except ValueError as ve:
                print(f"Warning: LLM data extraction skipped: {ve}", file=sys.stderr)
                print("Proceeding with merge and projection using other available sources.", file=sys.stderr)
            except Exception as e:
                print(f"Warning: LLM data extraction failed: {e}", file=sys.stderr)
                print("Proceeding with merge and projection using other available sources.", file=sys.stderr)
        except Exception as e:
            print(f"Error reading notes file '{args.notes}': {e}", file=sys.stderr)
            sys.exit(1)

    # Read projection configuration
    if not os.path.exists(args.config):
        print(f"Error: Configuration file not found at '{args.config}'", file=sys.stderr)
        sys.exit(1)
        
    try:
        with open(args.config, mode='r', encoding='utf-8') as f:
            config_json = f.read()
            # Basic validation of config
            json.loads(config_json)
    except json.JSONDecodeError as je:
        print(f"Error: Configuration file is not valid JSON: {je}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading configuration file '{args.config}': {e}", file=sys.stderr)
        sys.exit(1)
        
    # Project and output the result
    try:
        output = transformer.project_output(config_json)
        print(json.dumps(output, indent=2))
    except ValueError as ve:
        print(f"Error during projection: {ve}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error during candidate data projection: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
