import json
import os
import shutil
import glob
import re

def slugify(name):
    # Replace spaces with underscore (Wikipedia style)
    slug = re.sub(r'\s+', '_', name.strip())
    # Remove any invalid filename characters
    slug = re.sub(r'[\/\\:\*\?"<>\|]', '', slug)
    return slug

def main():
    print("Generating clean root pages and driver vanity pages...")

    # 1. Copy pages/*.html (except pages/index.html) to root
    copied_pages = 0
    for page_path in glob.glob('pages/*.html'):
        base = os.path.basename(page_path)
        if base == 'index.html':
            continue
        shutil.copy(page_path, base)
        copied_pages += 1
    print(f"Copied {copied_pages} core pages to root.")

    # 2. Read db.json to get all drivers
    with open('data/db.json', 'r', encoding='utf-8') as f:
        db = json.load(f)

    # 3. Read driver.html template
    with open('pages/driver.html', 'r', encoding='utf-8') as f:
        driver_template = f.read()

    drivers = db.get('drivers', {})
    generated_count = 0

    for driver_id, driver_data in drivers.items():
        name = driver_data.get('name', driver_id)
        slug = slugify(name)

        # Inject PRESET_DRIVER_ID so the page loads this driver instantly without query params
        preset_script = f'<script>window.PRESET_DRIVER_ID = "{driver_id}"; window.PRESET_DRIVER_SLUG = "{slug}";</script>'
        page_html = driver_template.replace('<head>', f'<head>\n  {preset_script}')

        target_file = f'{slug}.html'
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(page_html)
        generated_count += 1

    print(f"Generated {generated_count} driver vanity pages.")

if __name__ == '__main__':
    main()
