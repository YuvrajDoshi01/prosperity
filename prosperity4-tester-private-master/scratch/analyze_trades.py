import json

filepath = "/home/mmaliar/prosperity4-tester-private/backtests/295374.log"
with open(filepath) as f:
    content = f.read()

text = content.replace("Sandbox logs:\n", "")
decoder = json.JSONDecoder()
pos = 0
while pos < len(text):
    text_slice = text[pos:].lstrip()
    if not text_slice or "Activities log:" in text_slice[:20]:
        break
    try:
        obj, idx = decoder.raw_decode(text_slice)
        pos += len(text[pos:]) - len(text_slice) + idx
        
        if "lambdaLog" in obj:
            l_log = obj["lambdaLog"]
            if l_log:
                parsed = json.loads(l_log)
                state = parsed[0]
                ts = state[0]
                position = state[6]
                
                # Check trades
                own_trades = state[4]
                if ts <= 1000:
                    print(f"TS: {ts}, Pos: {position}, Trades: {len(own_trades)}, "
                          f"Logs: {parsed[-1][:100].strip()}")
                    for t in own_trades:
                        if t[0] == "INTARIAN_PEPPER_ROOT":
                            print(f"  TRADE: {t}")
                    
    except Exception as e:
        pos += 1
