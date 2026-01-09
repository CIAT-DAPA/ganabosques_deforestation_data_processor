import os
import rasterio as rio
from rasterio.warp import reproject, Resampling, calculate_default_transform
import numpy as np
import traceback
import logging
from tqdm import tqdm
import re
from tools.log_print import log_print  # Asegúrate de que esta ruta sea válida
from config import config

logger = logging.getLogger(__name__)

def resoluciones_iguales(res1, res2, tol=1e-6):
    return abs(res1[0] - res2[0]) < tol and abs(res1[1] - res2[1]) < tol

def mdl_spatial_processing(input_folder, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_procesamiento.txt')

    try:
        log_print(logger, f"Iniciando procesamiento espacial en: {input_folder}")

        # Parámetros de recorte y referencia
        xmin_fixed = config["SPATIAL_PARAMETERS"]["xmin_ref"]
        ymin_fixed = config["SPATIAL_PARAMETERS"]["ymin_ref"]
        xmax_fixed = config["SPATIAL_PARAMETERS"]["xmax_ref"]
        ymax_fixed = config["SPATIAL_PARAMETERS"]["ymax_ref"]
        res_ref = config["SPATIAL_PARAMETERS"]["res_ref"]
        dst_crs = config["SPATIAL_PARAMETERS"]["dst_crs_ref"]

        tif_files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]
        tif_files.sort()

        if not tif_files:
            log_print(logger, "No se encontraron archivos .tif para procesar.", level='warning')
            return False

        for file in tqdm(tif_files, desc="Procesando archivos", unit="archivo"):
            log_print(logger, f"Procesando archivo: {file}")
            input_path = os.path.join(input_folder, file)

            # ================= LÓGICA DE NOMBRE (SOLO AÑOS, SIN CONVERTIR) =================
            # A partir de ahora NO se convierte a YYYY-MM-DD-YYYY-MM-DD.
            # Si el nombre es prefijo_YYYY-YYYY.tif, se deja igual.
            # Si tiene otro formato, también se respeta el nombre original.

            nombre_base, extension = os.path.splitext(file)

            patron_corto = r"(.+?)_(\d{4})-(\d{4})"
            if re.fullmatch(patron_corto, nombre_base):
                nuevo_nombre = file  # ya está en formato corto, no cambiamos
            else:
                nuevo_nombre = file  # cualquier otro formato, no cambiamos

            output_path = os.path.join(output_folder, nuevo_nombre)
            # ============================================================================

            with rio.open(input_path) as src:
                src_crs = src.crs
                res_src = src.res

                # Calcular transformación y dimensiones del raster recortado/reproyectado
                out_transform, out_width, out_height = calculate_default_transform(
                    src_crs, dst_crs,
                    src.width, src.height,
                    xmin_fixed, ymin_fixed, xmax_fixed, ymax_fixed,
                    resolution=(res_ref[0] + res_ref[1]) / 2
                )

                kwargs = src.meta.copy()
                kwargs.update({
                    'crs': dst_crs,
                    'transform': out_transform,
                    'width': out_width,
                    'height': out_height,
                    'compress': 'lzw'
                })

                with rio.open(output_path, 'w', **kwargs) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rio.band(src, i),
                            destination=rio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src_crs,
                            dst_transform=out_transform,
                            dst_crs=dst_crs,
                            resampling=Resampling.nearest,
                            num_threads=2
                        )

            log_print(logger, f"Archivo procesado correctamente: {nuevo_nombre}")

        # Escribir log final
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write("El código ha corrido perfectamente.\n")
            log_file.write(f"{len(tif_files)} archivos procesados correctamente.\n")

        log_print(logger, f"{len(tif_files)} archivos procesados correctamente.")
        return True

    except Exception:
        error_msg = traceback.format_exc()
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write("Ha ocurrido un error durante el procesamiento:\n")
            log_file.write(error_msg)

        log_print(logger, "Ha ocurrido un error durante el procesamiento. Revisa el log.", level='error')
        logger.error(error_msg)
        return False
