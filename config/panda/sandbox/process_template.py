import os
import re
import glob

# loop over all template files
sandbox_dir = os.path.abspath(os.path.dirname(__file__))
for name in glob.glob(os.path.join(sandbox_dir, '*.template')):
    new_filename = re.sub('\.template$', '', name)
    # skip already exists
    if os.path.exists(new_filename):
        continue
    # patch
    with open(name) as f:
        template = f.read()
        # replace placeholders with env vars
        items = re.findall(r'\$\{(\w+)\}', template)
        done_list = set()
        for item in items:
            if item in done_list:
                continue
            done_list.add(item)
            if item in os.environ:
                template = template.replace('${'+item+'}', os.environ[item])
    # dump
    with open(new_filename, 'w') as f:
        f.write(template)
