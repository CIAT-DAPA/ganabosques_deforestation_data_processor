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
import re
from tools.log_print import log_print  # Asegúrate que esta ruta sea correcta

logger = logging.getLogger(__name__)

def quality_control(input_dir, output_dir, deforestation_type=None):
    """
    Control de calidad para archivos raster.
    Procesa subcarpetas según el tipo: smbyc/, nad/, atd/
    Si deforestation_type es None, procesa todas las subcarpetas disponibles.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Determinar qué subcarpetas procesar
    if deforestation_type:
        if deforestation_type.lower() in ["annual", "cumulative"]:
            folders_to_process = ["smbyc"]
        else:
            folders_to_process = [deforestation_type.lower()]
    else:
        # Buscar todas las subcarpetas disponibles
        folders_to_process = []
        for folder in ["smbyc", "nad", "atd"]:
            if os.path.isdir(os.path.join(input_dir, folder)):
                folders_to_process.append(folder)
    
    if not folders_to_process:
        log_print(logger, "No se encontraron carpetas para procesar.", level="warning")
        return False
    
    log_print(logger, f"Procesando carpetas: {folders_to_process}")
    
    all_success = True
    for folder_name in folders_to_process:
        input_subfolder = os.path.join(input_dir, folder_name)
        output_subfolder = os.path.join(output_dir, folder_name)
        
        if not os.path.isdir(input_subfolder):
            log_print(logger, f"Carpeta no encontrada: {input_subfolder}", level="warning")
            continue
        
        os.makedirs(output_subfolder, exist_ok=True)
        success = _process_folder(input_subfolder, output_subfolder, folder_name)
        if not success:
            all_success = False
    
    return all_success


def _process_folder(input_dir, output_dir, folder_name):
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
                    crs = src.crs  # (si quieres luego validar CRS, aquí ya está)

                # Validación de contenido
                if nodata is not None:
                    valores_validos = array[(array != nodata) & (array != 0)]
                else:
                    valores_validos = array[array != 0]

                if valores_validos.size > 0:
                    mensaje = "Archivo válido con valores distintos de 0 y nodata."
                    resultados_log.append(mensaje)
                    log_print(logger, mensaje)

                    # ================= LÓGICA DE RENOMBRADO (SOLO AÑOS) =================
                    # Solo aceptamos/normalizamos nombres tipo:
                    #   smbyc_2010-2012.tif
                    # Si NO coincide con ese patrón, lo copiamos con el nombre original.

                    nombre_base, extension = os.path.splitext(archivo)

                    patron_corto = r"(.+?)_(\d{4})-(\d{4})"
                    m_corto = re.fullmatch(patron_corto, nombre_base)

                    if m_corto:
                        # Ya está en formato corto -> no cambiamos
                        nuevo_nombre = archivo
                    else:
                        # No intentamos convertir otros formatos (incluye el completo)
                        nuevo_nombre = archivo

                    nombre_salida = os.path.join(output_dir, nuevo_nombre)
                    # ===================================================================

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

