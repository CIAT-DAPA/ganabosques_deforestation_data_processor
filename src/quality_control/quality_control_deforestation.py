########## Brayan Mora A. ########## 
##########  5/04/2025     ##########
####################################

import os
import shutil
import rasterio
from rasterio.errors import RasterioIOError
import numpy as np
from datetime import datetime
import logging
import re  # <-- Import necesario para trabajar con patrones de nombres
from tools.log_print import log_print  # Asegúrate que esta ruta sea correcta

logger = logging.getLogger(__name__)

def quality_control(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, 'log_quality_control.txt')

    resultados_log = []
    errores = 0
    procesados = 0

    log_print(logger, f"Iniciando control de calidad en: {input_dir}")
    archivos = [f for f in os.listdir(input_dir) if f.lower().endswith(('.tif', '.tiff'))]

    if not archivos:
        mensaje = "No se encontraron archivos .tif o .tiff en el directorio."
        resultados_log.append(mensaje)
        log_print(logger, mensaje, level='warning')
    else:
        for archivo in archivos:
            raster_path = os.path.join(input_dir, archivo)
            resultados_log.append(f"--- Archivo: {archivo} ---")
            log_print(logger, f"Procesando archivo: {archivo}")

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
                    mensaje = "Archivo válido con valores distintos de 0 y nodata."
                    resultados_log.append(mensaje)
                    log_print(logger, mensaje)

                    # ================= LÓGICA DE RENOMBRADO =================
                    # Queremos que:
                    #   smbyc_2010-2012.tif  -> smbyc_2010-01-01-2012-01-01.tif
                    #   smbyc_2012-2013.tif  -> smbyc_2012-01-01-2013-01-01.tif
                    # Y si ya viene como smbyc_2010-01-01-2012-01-01.tif, lo dejamos igual.

                    nombre_base, extension = os.path.splitext(archivo)

                    # Caso 1: ya tiene el formato completo YYYY-MM-DD-YYYY-MM-DD => lo dejamos igual
                    patron_completo = r".+_\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}"
                    if re.fullmatch(patron_completo, nombre_base):
                        nuevo_nombre = archivo  # sin cambios
                    else:
                        # Caso 2: formato corto tipo smbyc_2010-2012
                        patron_corto = r"(.+?)_(\d{4})-(\d{4})"
                        m = re.fullmatch(patron_corto, nombre_base)
                        if m:
                            prefijo = m.group(1)   # smbyc
                            anio_ini = m.group(2)  # 2010
                            anio_fin = m.group(3)  # 2012

                            nuevo_nombre_base = f"{prefijo}_{anio_ini}-01-01-{anio_fin}-01-01"
                            nuevo_nombre = nuevo_nombre_base + extension
                        else:
                            # Si no cumple ningún patrón, dejamos el nombre original
                            nuevo_nombre = archivo

                    nombre_salida = os.path.join(output_dir, nuevo_nombre)
                    # ========================================================

                    shutil.copy(raster_path, nombre_salida)
                    procesados += 1
                else:
                    mensaje = "Archivo sin valores válidos (solo contiene 0 o nodata)."
                    resultados_log.append(mensaje)
                    log_print(logger, mensaje, level='warning')
                    errores += 1

            except RasterioIOError as e:
                mensaje = f"Error al abrir el archivo: {e}"
                resultados_log.append(mensaje)
                log_print(logger, mensaje, level='error')
                errores += 1
            except Exception as e:
                mensaje = f"Error inesperado: {e}"
                resultados_log.append(mensaje)
                log_print(logger, mensaje, level='error')
                errores += 1

            resultados_log.append("")  # Línea vacía para separar archivos

    resumen = [
        f"Total procesados correctamente: {procesados}",
        f"Total con errores o vacíos: {errores}"
    ]

    for linea in resumen:
        log_print(logger, linea)

    # Guardar el log local
    with open(log_path, 'w', encoding='utf-8') as log_file:
        log_file.write(f"LOG DE REVISIÓN DE RASTERS - {datetime.now()}\n\n")
        log_file.write("\n".join(resultados_log))
        log_file.write("\nResumen:\n")
        log_file.write("\n".join(resumen))

    return True if procesados > 0 else False
