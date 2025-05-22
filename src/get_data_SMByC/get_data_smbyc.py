import requests
import logging
import os

# Configuración del log
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_data(years, output_path, geo, workspace, mosaic):
    # Crear carpeta si no existe
    os.makedirs(output_path, exist_ok=True)

    for year in years:
        url = (
            f"{geo}/{workspace}/ows?"
            f"service=WCS&version=2.0.1&request=GetCoverage"
            f"&coverageId={mosaic}"
            f"&format=image/geotiff"
            f'&subset=Time("{year}-01-01T00:00:00.000Z")'
        )

        logging.info(f"Enviando solicitud GET para el año {year} a: {url}")

        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                output_file = os.path.join(output_path, f"smbyc_{year}.tif")  # Aquí el cambio solicitado
                with open(output_file, "wb") as f:
                    f.write(response.content)
                logging.info(f"Archivo guardado exitosamente: {output_file}")
            else:
                logging.error(f"Error en la respuesta para {year}: {response.status_code} - {response.text}")
        except requests.exceptions.Timeout:
            logging.error(f"Timeout para el año {year}.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error en la solicitud para {year}: {e}")
