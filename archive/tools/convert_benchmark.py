import argparse
import json
import os
import re
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description="Convert Excel datasets to JSON benchmark files.")
    parser.add_argument("--input", required=True, help="Path to the input Excel file.")
    parser.add_argument("--output", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--source", required=True, help="Source name (e.g. FranchiseBazar, FranchiseMart).")
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' does not exist.")
        return
        
    # Extract prefix for IDs (e.g., "FranchiseBazar" -> "FB")
    # Take uppercase characters from source name
    prefix = "".join([c for c in args.source if c.isupper()])
    if not prefix:
        prefix = args.source[:2].upper()
        
    print(f"Reading {args.input}...")
    
    # Read Excel using pandas
    try:
        df = pd.read_excel(args.input)
    except Exception as e:
        print(f"Failed to read Excel using pandas: {e}. Trying openpyxl fallback...")
        try:
            import openpyxl
            wb = openpyxl.load_workbook(args.input, data_only=True)
            sheet = wb.active
            data = []
            headers = [cell.value for cell in sheet[1]]
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if all(val is None for val in row):
                    continue
                row_dict = {}
                for h, val in zip(headers, row):
                    if h is not None:
                        row_dict[str(h)] = val
                data.append(row_dict)
            df = pd.DataFrame(data)
        except Exception as ex:
            print(f"Error reading Excel file: {ex}")
            return

    records = []
    idx = 1
    skipped_empty_rows = 0
    
    for row_num, (_, row) in enumerate(df.iterrows(), start=2):
        row_dict = row.to_dict()
        
        # Clean null/NaN values and skip completely empty columns
        clean_row = {}
        row_has_data = False
        for k, v in row_dict.items():
            if pd.isna(v) or v is None or str(v).strip() == "" or v == "NaT" or str(v).strip().lower() == "nan":
                continue
            clean_row[str(k).strip()] = v
            row_has_data = True
            
        if not row_has_data:
            skipped_empty_rows += 1
            continue
            
        # Assign unique benchmark ID
        benchmark_id = f"{prefix}{idx:04d}"
        idx += 1
        
        # Build record with metadata fields at the beginning
        record = {
            "benchmark_id": benchmark_id,
            "benchmark_version": "1.0",
            "source": args.source,
            "verified": False
        }
        
        # Merge clean row attributes
        record.update(clean_row)
        records.append(record)
        
    # Ensure directory of output exists
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        
    print(f"Conversion Summary:")
    print(f"  Source:             {args.source} ({prefix})")
    print(f"  Total converted:    {len(records)} records")
    print(f"  Skipped empty rows: {skipped_empty_rows}")
    print(f"  Saved JSON to:      {args.output}")

if __name__ == "__main__":
    main()
