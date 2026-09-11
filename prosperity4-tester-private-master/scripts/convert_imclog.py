import json
import csv
import sys
import os

def convert(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    activities_csv = data.get('activitiesLog', '')
    if not activities_csv:
        print("No activitiesLog found in the input JSON.")
        return

    # Find timestamps from the CSV
    lines = [line for line in activities_csv.strip().split('\n') if line.strip()]
    if not lines:
        print("Empty activitiesLog")
        return
        
    reader = csv.DictReader(lines, delimiter=';')
    timestamps = set()
    products = set()
    for row in reader:
        ts_str = row.get('timestamp')
        if ts_str is not None and ts_str.isdigit():
            timestamps.add(int(ts_str))
        product = row.get('product')
        if product:
            products.add(product)
            
    sorted_timestamps = sorted(list(timestamps))
    
    # Create the listings array for the dummy data
    dummy_listings = [[p, p, 1] for p in sorted(list(products))]
    
    with open(output_path, 'w', encoding='utf-8') as out:
        # Standard backtest format has "Sandbox logs:" at the start
        out.write("Sandbox logs:\n")
        
        # Output dummy sandbox/lambda log structures per timestamp
        for ts in sorted_timestamps:
            # The visualizer REQUIRES a valid compressed state array in lambdaLog 
            # for at least one row. We also must include the listings array so it 
            # knows which products exist to draw tabs/charts for.
            dummy_data = [
                [
                    ts, "", dummy_listings, {}, [], [], {}, [{}, {}]
                ],
                [], 0, "", ""
            ]
            compressed_json = json.dumps(dummy_data, separators=(',', ':'))
            
            log_item = {
                "sandboxLog": "",
                "lambdaLog": compressed_json,
                "timestamp": ts
            }
            out.write(json.dumps(log_item, indent=2))
            out.write('\n')
            
        # Activities log requires exactly 3 newlines before it
        out.write('\n\n\nActivities log:\n')
        out.write(activities_csv)
        if not activities_csv.endswith('\n'):
            out.write('\n')
            
        # Trade History requires exactly 5 newlines before it
        out.write('\n\n\n\n\nTrade History:\n')
        out.write('[\n]\n')

    print(f"Successfully converted {input_path} to {output_path}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python convert_imclog.py <input.json> <output.log>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
