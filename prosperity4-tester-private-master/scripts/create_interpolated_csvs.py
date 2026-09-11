import csv

# Source directory containing the backtesting resource CSVs
base_path = 'venv/lib/python3.14/site-packages/prosperity4bt/resources/round2/'

# Mapping of original files to day 6, 7, 8
mapping = {
    'prices_round_2_day_-1.csv': ('prices_round_2_day_6.csv', 6),
    'prices_round_2_day_0.csv': ('prices_round_2_day_7.csv', 7),
    'prices_round_2_day_1.csv': ('prices_round_2_day_8.csv', 8)
}

def get_new_level(levels, is_bid):
    if not levels: return None
    total_v = sum(v for p, v in levels)
    # Using round half-up for 25% logic
    v_new = int(total_v * 0.25 + 0.5) 
    if v_new <= 0: return None
    
    vwap = sum(p * v for p, v in levels) / total_v
    occupied = set(p for p, v in levels)
    
    # Pre-sorted, levels[0] is best (highest bid, lowest ask)
    best_p = levels[0][0] 
    min_p, max_p = min(occupied), max(occupied)
    
    p_best = None
    min_dist = float('inf')
    
    # Search around the current prices to fit the distribution perfectly
    for p in range(min_p - 15, max_p + 16):
        if p in occupied: continue
        # Must not cross the actual best price or be better than it
        # This keeps the spread and mid_price identical!
        if is_bid and p > best_p: continue
        if not is_bid and p < best_p: continue
        
        dist = abs(p - vwap)
        if dist < min_dist:
            min_dist = dist
            p_best = p
        elif dist == min_dist:
            # Tie breaker: try to put it closer to the best price
            if is_bid and p > p_best: p_best = p
            elif not is_bid and p < p_best: p_best = p
            
    if p_best is None: # fallback
        if is_bid: p_best = min_p - 1
        else: p_best = max_p + 1
        
    return (p_best, v_new)

def generate_interpolated_csvs():
    for in_name, (out_name, new_day) in mapping.items():
        in_file = base_path + in_name
        out_file = base_path + out_name
        
        with open(in_file, 'r', newline='') as f_in, open(out_file, 'w', newline='') as f_out:
            reader = csv.DictReader(f_in, delimiter=';')
            fieldnames = reader.fieldnames
            writer = csv.DictWriter(f_out, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            
            for row in reader:
                # Group current bids and asks
                bids = []
                asks = []
                for i in range(1, 4):
                    bp = row.get(f'bid_price_{i}')
                    bv = row.get(f'bid_volume_{i}')
                    if bp and bv: bids.append((int(bp), int(bv)))
                    
                    ap = row.get(f'ask_price_{i}')
                    av = row.get(f'ask_volume_{i}')
                    if ap and av: asks.append((int(ap), int(av)))
                
                # Sort best first
                bids.sort(key=lambda x: x[0], reverse=True)
                asks.sort(key=lambda x: x[0])
                
                # Interpolate the new expected price level
                new_bid = get_new_level(bids, is_bid=True)
                new_ask = get_new_level(asks, is_bid=False)
                
                if new_bid: bids.append(new_bid)
                if new_ask: asks.append(new_ask)
                
                # Re-sort to insert it in place
                bids.sort(key=lambda x: x[0], reverse=True)
                asks.sort(key=lambda x: x[0])
                
                # Truncate to top 3 to ensure it fits in CSV structure
                bids = bids[:3]
                asks = asks[:3]
                
                # Clear existing columns prior to reinjection
                for i in range(1, 4):
                    row[f'bid_price_{i}'] = ''
                    row[f'bid_volume_{i}'] = ''
                    row[f'ask_price_{i}'] = ''
                    row[f'ask_volume_{i}'] = ''
                
                # Repopulate CSV cells with best newly injected 3 levels
                for i, (p, v) in enumerate(bids):
                    row[f'bid_price_{i+1}'] = str(p)
                    row[f'bid_volume_{i+1}'] = str(v)
                    
                for i, (p, v) in enumerate(asks):
                    row[f'ask_price_{i+1}'] = str(p)
                    row[f'ask_volume_{i+1}'] = str(v)
                
                # Update day identifier
                row['day'] = str(new_day)
                writer.writerow(row)
                
        print(f"Processed {in_file} -> {out_file}")

if __name__ == "__main__":
    generate_interpolated_csvs()
