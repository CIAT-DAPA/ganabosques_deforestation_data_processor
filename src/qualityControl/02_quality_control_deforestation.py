########## Brayan Mora A. ########## 
##########  5/04/2025     ##########
####################################

import os
import shutil
import rasterio
from rasterio.errors import RasterioIOError
import numpy as np
from datetime import datetime

def quality_control(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, 'log_quality_control.txt')

    resultados_log = []
    errores = 0
    procesados = 0

    archivos = [f for f in os.listdir(input_dir) if f.lower().endswith(('.tif', '.tiff'))]

    if not archivos:
        resultados_log.append("No se encontraron archivos .tif o .tiff en el directorio.")
    else:
        for archivo in archivos:
            raster_path = os.path.join(input_dir, archivo)
            resultados_log.append(f"--- Archivo: {archivo} ---")
            try:
                with rasterio.open(raster_path) as src:
                    array = src.read(1)
                    nodata = src.nodata
                    crs = src.crs

                # Validación de contenido
                if nodata is not None:
                    valores_validos = array[(array != nodata) & (array != 0)]
                else:
                    valores_validos = array[array != 0]

                if valores_validos.size > 0:
                    resultados_log.append("✔ Archivo válido con valores distintos de 0 y nodata.")
                    nombre_salida = os.path.join(output_dir, archivo)
                    shutil.copy(raster_path, nombre_salida)
                    procesados += 1
                else:
                    resultados_log.append("✖ Archivo sin valores válidos (solo contiene 0 o nodata).")
                    errores += 1

            except RasterioIOError as e:
                resultados_log.append(f"✖ Error al abrir el archivo: {e}")
                errores += 1
            except Exception as e:
                resultados_log.append(f"✖ Error inesperado: {e}")
                errores += 1

            resultados_log.append("")  # Línea vacía para separar archivos

    # Guardar el log
    with open(log_path, 'w', encoding='utf-8') as log_file:
        log_file.write(f"LOG DE REVISIÓN DE RASTERS - {datetime.now()}\n\n")
        log_file.write("\n".join(resultados_log))
        log_file.write("\nResumen:\n")
        log_file.write(f"Total procesados correctamente: {procesados}\n")
        log_file.write(f"Total con errores o vacíos: {errores}\n")


quality_control(input_dir=  r"D:\OneDrive - CGIAR\Desktop\ganabosques\deforestacion\outputs\tmp_get_data_deforestation",
                output_dir=  r"D:\OneDrive - CGIAR\Desktop\ganabosques\deforestacion\outputs\tmp_quality_control")