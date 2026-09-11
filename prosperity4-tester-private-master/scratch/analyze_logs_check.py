import json

filepath = "/home/mmaliar/prosperity4-tester-private/backtests/295374.log"
with open(filepath) as f:
    content = f.read()

text = content.replace("Sandbox logs:\n", "")
decoder = json.JSONDecoder()
pos = 0
found_logs = 0

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
                logs = parsed[-1]
                if logs.strip():
                    found_logs += 1
                    if found_logs <= 5:
                        print(f"TS {parsed[0][0]} logs:", logs[:200])
                    
    except Exception as e:
        pos += 1
