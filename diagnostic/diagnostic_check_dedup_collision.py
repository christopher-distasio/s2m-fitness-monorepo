import json
import csv

gap_ids = ['1253375', '2157602', '2400613', '1507377']

# Load clean set: map normalized description -> fdc_id that survived dedup
with open('data/processed/branded_clean.json') as f:
    clean = json.load(f)
clean_desc_to_id = {}
for food in clean:
    key = food['description'].lower().strip()
    clean_desc_to_id[key] = food['fdc_id']

# Get descriptions for the gap fdc_ids from food.csv
gap_descriptions = {}
with open('data/raw/FoodData_Central_branded_food_csv_2026-04-30/food.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['fdc_id'] in gap_ids:
            gap_descriptions[row['fdc_id']] = row['description'].strip()

print('Checking dedup collision hypothesis:')
for fid in gap_ids:
    desc = gap_descriptions.get(fid, '(not found in food.csv)')
    key = desc.lower().strip()
    winner = clean_desc_to_id.get(key)
    if winner:
        print(f"  fdc_id={fid} desc={desc!r}")
        print(f"    -> COLLISION: same description as fdc_id={winner}, which won dedup instead")
    else:
        print(f"  fdc_id={fid} desc={desc!r}")
        print(f"    -> no collision found - description not in clean set at all, different cause")
