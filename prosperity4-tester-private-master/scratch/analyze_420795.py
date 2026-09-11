import json

log_path = "/home/mmaliar/prosperity4-tester-private/imc_logs/420795.json"
try:
    with open(log_path) as f:
        data = json.load(f)
    print("Type of data:", type(data))
    if isinstance(data, dict):
        print("Keys:", data.keys())
    elif isinstance(data, list):
        print("List of length:", len(data))
        if len(data) > 0:
            item = data[0]
            print("Type of item[0]:", type(item))
            if isinstance(item, dict):
                print("Keys of item[0]:", item.keys())
except Exception as e:
    print("Error:", e)
