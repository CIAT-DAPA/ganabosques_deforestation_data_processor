## Get Data SMBYC 
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
        # Rango temporal para la solicitud WCS (esto lo dejamos igual)
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
        logger.propagate = False

        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                # ---- AQUÍ ESTÁ EL CAMBIO EN EL NOMBRE DEL ARCHIVO ----
                # Definimos los años de inicio y fin según tu lógica previa
                if year == 2010:
                    start_year = year          # 2010
                    end_year = year + 2        # 2012  -> smbyc_2010-01-01-2012-01-01.tif
                else:
                    start_year = year          # p.ej. 2012
                    end_year = year + 1        # 2013  -> smbyc_2012-01-01-2013-01-01.tif

                # Ahora construimos las fechas completas para el nombre del archivo
                start_date_str = f"{start_year}0101"
                end_date_str = f"{end_year}0101"

                # Nombre final del archivo .tif
                output_file = os.path.join(
                    output_path,
                    f"{mosaic}_{start_date_str}-{end_date_str}.tif"
                )
                # -------------------------------------------------------

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
