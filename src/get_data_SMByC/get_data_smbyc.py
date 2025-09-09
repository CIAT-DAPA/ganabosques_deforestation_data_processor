## Copia seguridad SMBYC
import requests
import logging
import os
from tools.log_print import log_print  # Asegúrate que la ruta sea correcta


# Configuración del logger del módulo
logger = logging.getLogger("get data")

def get_data(years, output_path, geo, workspace, mosaic):
    # Crear carpeta si no existe
    os.makedirs(output_path, exist_ok=True)

    for year in years:
        start = f"{year}-01-01T00:00:00.000Z"
        end = f"{year + 1}-12-31T23:59:59.000Z"
        url = (
            f"{geo}/{workspace}/ows?"
            f"service=WCS&version=2.0.1&request=GetCoverage"
            f"&coverageId={mosaic}"
            f"&format=image/geotiff"
            f'&subset=Time("{start}","{end}")'
        )

        log_print(logger, f"Enviando solicitud GET para el rango {year}-{year+1} a:\n{url}")

        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                if year == 2010:
                    output_file = os.path.join(output_path, f"{mosaic}_{year}-{year + 2}.tif")
                else:
                    output_file = os.path.join(output_path, f"{mosaic}_{year}-{year + 1}.tif")
                with open(output_file, "wb") as f:
                    f.write(response.content)
                log_print(logger, f"✅ Archivo guardado exitosamente: {output_file}")
            else:
                log_print(
                    logger,
                    f"❌ Error en la respuesta para {year}-{year+1}: {response.status_code} - {response.text}",
                    level="error"
                )
        except requests.exceptions.Timeout:
            log_print(logger, f"⏰ Timeout para el año {year}-{year+1}.", level="error")
        except requests.exceptions.RequestException as e:
            log_print(logger, f"❗ Error en la solicitud para {year}-{year+1}: {e}", level="error")
