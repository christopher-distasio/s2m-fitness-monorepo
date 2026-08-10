import csv

ids_to_check = ['1448141', '1253375', '2157602', '2400613', '1507377']

print('Checking market_country + presence in branded_food.csv:')
with open('data/raw/FoodData_Central_branded_food_csv_2026-04-30/branded_food.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['fdc_id'] in ids_to_check:
            print(f"  fdc_id={row['fdc_id']} market_country={row.get('market_country')!r}")

print()
print('Checking presence + calorie value in food_nutrient.csv (nutrient_id 1008 = calories):')
found_calories = {}
with open('data/raw/FoodData_Central_branded_food_csv_2026-04-30/food_nutrient.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['fdc_id'] in ids_to_check and row['nutrient_id'] == '1008':
            found_calories[row['fdc_id']] = row['amount']

for fid in ids_to_check:
    print(f"  fdc_id={fid} calories={found_calories.get(fid, 'NOT FOUND')}")
