import csv
with open('venv/lib/python3.14/site-packages/prosperity4bt/resources/round2/prices_round_2_day_7.csv') as f:
    reader = csv.DictReader(f, delimiter=';')
    print(next(reader))
