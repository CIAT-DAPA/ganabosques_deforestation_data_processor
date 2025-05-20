####################################
########## Brayan Mora A. ########## 
##########  5/02/2025     ##########
####################################

#  Este codigo realiza el calculo deforestacion acumulada 
#  1. Carga los datos que salen del module_spatial_deforestation_calc_step 1 
#  2. Calcula la deforestacion acumulada teniendo en cuenta los NA,s  
#  3. Guarda el archivo 
#  4. Genera un log que se encarga de reportar si hay errores o todo se realizo con exito

import os
import numpy as np
import rasterio
from rasterio.errors import RasterioIOError
from datetime import datetime

def deforestacion_cum(
    input_folder: str,
    output_tif_path: str
):
    log_path = os.path.join(os.path.dirname(output_tif_path), 'log_acumulado.txt')
    log_lines = []
    log_lines.append(f"--- LOG ACUMULADO DE DEFORESTACIÓN ---\nInicio: {datetime.now()}\n")

    tif_files = sorted([f for f in os.listdir(input_folder) if f.endswith('.tif')])
    if not tif_files:
        log_lines.append("⚠️ No se encontraron archivos .tif en la carpeta de entrada.")
        with open(log_path, 'w') as f:
            f.writelines('\n'.join(log_lines))
        return

    first_tif_path = os.path.join(input_folder, tif_files[0])
    try:
        with rasterio.open(first_tif_path) as src:
            meta = src.meta.copy()
            shape_base = src.read(1).shape
            acumulado = np.zeros(shape_base, dtype='float32')
            log_lines.append(f"📌 Tamaño base: {shape_base[0]} filas x {shape_base[1]} columnas (desde {tif_files[0]})")
    except Exception as e:
        log_lines.append(f"❌ ERROR al abrir el primer raster: {str(e)}")
        with open(log_path, 'w') as f:
            f.writelines('\n'.join(log_lines))
        raise

    for tif in tif_files:
        try:
            file_path = os.path.join(input_folder, tif)
            with rasterio.open(file_path) as src:
                data = src.read(1)
                data = np.where(np.isnan(data), 0, data)
                data = np.where(data == src.nodata, 0, data)
                shape = data.shape

                log_lines.append(f"🗂️ {tif}: {shape[0]} filas x {shape[1]} columnas")

                if shape != shape_base:
                    data_alineado = np.full(shape_base, np.nan, dtype='float32')
                    min_rows = min(shape_base[0], shape[0])
                    min_cols = min(shape_base[1], shape[1])
                    data_alineado[:min_rows, :min_cols] = data[:min_rows, :min_cols]
                    data = data_alineado
                    log_lines.append(f"⚠️ {tif} tenía dimensiones distintas. Rellenado con NA para ajustar.")
                else:
                    log_lines.append(f"✅ {tif} incluido en el acumulado.")

                acumulado += np.nan_to_num(data)

        except RasterioIOError as e:
            log_lines.append(f"❌ ERROR al leer {tif}: {str(e)}")
        except Exception as e:
            log_lines.append(f"❌ ERROR inesperado en {tif}: {str(e)}")

    # Convertir valores > 0 a 2, el resto a 0
    acumulado = np.where(acumulado > 0, 2, 0).astype('uint8')

    # Guardar raster binarizado
    try:
        meta.update(dtype='uint8', count=1, nodata=0)

        with rasterio.open(output_tif_path, 'w', **meta) as dst:
            dst.write(acumulado, 1)

        log_lines.append(f"✅ Raster acumulado binarizado guardado correctamente: {output_tif_path}")

    except Exception as e:
        log_lines.append(f"❌ ERROR al guardar el raster acumulado: {str(e)}")

    log_lines.append(f"\nFin del procesamiento: {datetime.now()}")
    with open(log_path, 'w') as f:
        f.writelines('\n'.join(log_lines))

    print("📄 Log actualizado guardado en:", log_path)

    deforestacion_cum(
      input_folder='/home/bmora/ganabosques_project/Data/def/tmp_calculate_deforestation/',
    output_tif_path='/home/bmora/ganabosques_project/Data/def/tmp_calculate_deforestation/deforestation_accumulated.tif'
)