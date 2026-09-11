import json

dummy_data = [
    [
        0,
        "",
        [],
        {},
        [],
        [],
        {},
        [{}, {}]
    ],
    [],
    0,
    "",
    ""
]

# We need the string field to be "lambdaLog": "<compressed_json_string>"
# So it's double serialized.
compressed_json = json.dumps(dummy_data, separators=(',', ':'))

# Let's see what the line looks like:
line = f'  "lambdaLog": {json.dumps(compressed_json)},'
print(line)

# Simulate js parser
start = line.index('[[')
end = line.rindex(']') + 1
substring = line[start:end]

# In JS: JSON.parse('"' + substring + '"') -> unescapes the \" inside substring
js_string = '"' + substring + '"'
print("Extracted JS string literal:", js_string)
import ast
try:
    # Python equivalent of JSON.parse for a string:
    parsed_string = json.loads(js_string)
    print("Parsed string:", parsed_string)
    parsed_obj = json.loads(parsed_string)
    print("Parsed obj length:", len(parsed_obj))
except Exception as e:
    print("Failed!", e)
