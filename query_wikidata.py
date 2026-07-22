import requests
import urllib.parse
import time

players = [
    "Lionel Messi", "Kylian Mbappé", "Vinícius Júnior", "Mohamed Salah",
    "Son Heung-min", "Jude Bellingham", "Florian Wirtz", "Achraf Hakimi",
    "Federico Valverde", "Alexander Isak", "Alphonso Davies", "Joško Gvardiol",
    "Luis Díaz", "Kaoru Mitoma", "Moisés Caicedo", "Edson Álvarez",
    "Andrew Robertson", "Tomáš Souček", "Konrad Laimer", "Ismaël Bennacer",
    "Ellyes Skhiri", "Chris Wood", "Ronwen Williams", "Akram Afif",
    "Chancel Mbemba", "Anel Ahmedhodžić", "Juninho Bacuna"
]

headers = {
    'User-Agent': 'VexpBot/1.0 (Contact: myemail@example.com)',
    'Accept': 'application/sparql-results+json'
}

results = {}

for p in players:
    # Query for the specific player to avoid complex SPARQL syntax errors
    query = f"""
    SELECT ?apiId WHERE {{
      ?item wdt:P9315 ?apiId.
      ?item rdfs:label "{p}"@en.
    }} LIMIT 1
    """
    
    url = "https://query.wikidata.org/sparql"
    try:
        response = requests.get(url, params={'query': query, 'format': 'json'}, headers=headers)
        if response.status_code == 200:
            data = response.json()
            bindings = data.get('results', {}).get('bindings', [])
            if bindings:
                results[p] = bindings[0]['apiId']['value']
            else:
                results[p] = "NOT FOUND"
        else:
            results[p] = f"HTTP {response.status_code}"
    except Exception as e:
        results[p] = str(e)
    
    time.sleep(0.5)

print("PLAYER IDs FOUND:")
for p, id_val in results.items():
    print(f"{p}: {id_val}")
