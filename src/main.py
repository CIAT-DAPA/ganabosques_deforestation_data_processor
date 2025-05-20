import requests

url = 'https://raw.githubusercontent.com/CIAT-DAPA/ganabosques_deforestation_data_processor/main/funciones.py'
response = requests.get(url)

with open('funciones.py', 'w', encoding='utf-8') as f:
    f.write(response.text)