import requests
import logging
import os
from tools.log_print import log_print  # Asegúrate que la ruta sea correcta
from ganabosques_orm.enums.ugg import UGG

# Configuración del logger del módulo
logger = logging.getLogger("get data")

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

        log_print(logger, f"Enviando solicitud GET para el año {year} a:\n{url}")

        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                output_file = os.path.join(output_path, f"{mosaic}_{year}.tif")
                with open(output_file, "wb") as f:
                    f.write(response.content)
                log_print(logger, f"Archivo guardado exitosamente: {output_file}")
            else:
                log_print(
                    logger,
                    f"Error en la respuesta para {year}: {response.status_code} - {response.text}",
                    level="error"
                )
        except requests.exceptions.Timeout:
            log_print(logger, f"Timeout para el año {year}.", level="error")
        except requests.exceptions.RequestException as e:
            log_print(logger, f"Error en la solicitud para {year}: {e}", level="error")
