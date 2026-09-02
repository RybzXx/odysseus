import os
js_path = os.path.join('static', 'js', 'projects.js')
with open(js_path, 'r', encoding='utf-8') as f:
    code = f.read()
code = code.replace("??? All Projects", "All Projects")
with open(js_path, 'w', encoding='utf-8') as f:
    f.write(code)
print("fixed")
