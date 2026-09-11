import json

filepath = "/home/mmaliar/prosperity4-tester-private/backtests/295374.log"
with open(filepath) as f:
    text = f.read()

# Remove Sandbox logs:
text = text.replace("Sandbox logs:\n", "")

# We can parse the text by taking {} blocks
import re
decoder = json.JSONDecoder()
pos = 0

while pos < len(text):
    text_slice = text[pos:].lstrip()
    if not text_slice:
        break
    try:
        obj, idx = decoder.raw_decode(text_slice)
        pos += len(text[pos:]) - len(text_slice) + idx
        
        if "lambdaLog" in obj:
            l_log = obj["lambdaLog"]
            if l_log:
                parsed = json.loads(l_log)
                logs = parsed[-1]
                if logs:
                    state_ts = parsed[0][0]
                    print(f"[{state_ts}] {logs.strip()}")
                
    except json.JSONDecodeError as e:
        print("Error at pos", pos, e)
        break
