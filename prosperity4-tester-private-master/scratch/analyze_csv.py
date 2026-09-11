import csv
from io import StringIO
import re

filepath = "/home/mmaliar/prosperity4-tester-private/backtests/295374.log"
with open(filepath) as f:
    content = f.read()

# We need everything after "Activities log:"
parts = content.split("Activities log:")
if len(parts) > 1:
    activities = parts[1].strip()
    # It might have "Trade History" or just be the CSV
    lines = activities.split('\n')
    
    csv_lines = []
    trade_lines = []
    
    mode = "activities"
    for line in lines:
        if line.strip() == "Trade History:":
            mode = "trades"
            continue
        if mode == "activities":
            if ";" in line:
                csv_lines.append(line)
        else:
            if ";" in line: # actually trades is a json or csv? Trade history is JSON
                trade_lines.append(line)

    print(f"Found {len(csv_lines)} activity rows")
    # Let's read it
    data = []
    reader = csv.reader(csv_lines, delimiter=";")
    next(reader, None) # skip header if any
    
    ash_pnl = 0
    pepper_pnl = 0
    
    for row in reader:
        try:
            day, timestamp, product, bid1, bvol1, bid2, bvol2, bid3, bvol3, ask1, avol1, ask2, avol2, ask3, avol3, mid, pnl = row
            if timestamp == "1000":
                print(f"Timestamp {timestamp}: ASH PNL = {ash_pnl}, PEPPER PNL = {pepper_pnl}")
            
            pnl_val = float(pnl) if pnl != "" else 0.0
            if product == "ASH_COATED_OSMIUM":
                ash_pnl = pnl_val
            elif product == "INTARIAN_PEPPER_ROOT":
                pepper_pnl = pnl_val
                
            if int(timestamp) in [1000, 2000, 3000, 4000, 5000]:
                 print(f"TS {timestamp} {product} PNL: {pnl_val}")
                 
        except Exception as e:
            pass
            
    print(f"Final PNL: ASH = {ash_pnl}, PEPPER = {pepper_pnl}")
    
    if mode == "trades":
        print(f"Trade lines starts with: {trade_lines[0][:100]}")
        try:
            import json
            trades = json.loads("".join(trade_lines))
            print("Trades parsed!")
            
            # Print first few trades
            for t in trades[:10]:
                print(t)
        except Exception as e:
            print("Failed to parse trades:", e)
