import json
with open('version.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
d['version'] = '1.1.3'
d['release_notes'] = 'Version 1.1.3: Support extracting full Customily product-images artwork layers'
with open('version.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2)

with open('core/config.py', 'r', encoding='utf-8') as f:
    text = f.read()

import re
text = re.sub(r'CURRENT_VERSION = ".*?"', 'CURRENT_VERSION = "1.1.3"', text)
with open('core/config.py', 'w', encoding='utf-8') as f:
    f.write(text)
