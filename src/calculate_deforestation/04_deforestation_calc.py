####################################
########## Brayan Mora A. ########## 
##########  5/02/2025     ##########
####################################

import os
import rasterio
from rasterio.windows import Window
from rasterio.enums import Resampling
import numpy as np
from datetime import datetime

def deforestation_step_1(input_folder, output_folder, source='SMBYC', deforestation_value=None):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_parte1.txt')
    log_lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines.append(f"--- LOG PARTE 1: CARGA Y FILTRADO ---\nInicio: {timestamp}\n")

    if source != 'SMBYC' and deforestation_value is None:
        error_msg = "ERROR: Si la fuente no es 'SMBYC', debes especificar 'deforestation_value'."
        log_lines.append(error_msg)
        with open(log_path, 'w') as log_file:
            log_file.writelines('\n'.join(log_lines))
        raise ValueError(error_msg)

    value_to_filter = 2 if source == 'SMBYC' else deforestation_value
    tif_files = sorted([f for f in os.listdir(input_folder) if f.endswith('.tif')])
    processed_layers = []
    years = []

    for tif in tif_files:
        input_path = os.path.join(input_folder, tif)
        year = ''.join(filter(str.isdigit, tif))
        output_filename = f"{source.lower()}_{year}.tif"
        output_path = os.path.join(output_folder, output_filename)

        try:
            with rasterio.open(input_path) as src:
                profile = src.profile
                profile.update({
                    'dtype': 'int32',
                    'nodata': -99999,
                    'compress': 'lzw'
                })

                with rasterio.open(output_path, 'w', **profile) as dst:
                    for ji, window in src.block_windows(1):
                        data = src.read(1, window=window)
                        data_clean = np.where((data == src.nodata) | (data == 0), 0, data)
                        filtered = np.where(data_clean == value_to_filter, value_to_filter, 0)
                        dst.write(filtered.astype('int32'), 1, window=window)

                processed_layers.append(output_path)
                years.append(int(year))
                log_lines.append(f"{tif} procesado correctamente como {output_filename}.")

        except Exception as e:
            log_lines.append(f"ERROR procesando {tif}: {str(e)}")

    # Acumulado
    if len(processed_layers) >= 1:
        try:
            with rasterio.open(processed_layers[0]) as ref:
                profile = ref.profile
                profile.update(dtype='int32', nodata=-99999, compress='lzw')
                cum_filename = f"deforestation_cum_{min(years)}_{max(years)}.tif"
                cum_path = os.path.join(output_folder, cum_filename)

                with rasterio.open(cum_path, 'w', **profile) as dst:
                    for ji, window in ref.block_windows(1):
                        cumulative = np.zeros(window.height * window.width, dtype='int32').reshape((window.height, window.width))

                        for layer_path in processed_layers:
                            with rasterio.open(layer_path) as lyr:
                                data = lyr.read(1, window=window)
                                cumulative += data

                        dst.write(cumulative, 1, window=window)

                log_lines.append(f"Raster acumulado guardado como {cum_filename}.")
        except Exception as e:
            log_lines.append(f"ERROR generando acumulado: {str(e)}")
    else:
        log_lines.append("No se generó acumulado porque no se procesaron capas correctamente.")

    log_lines.append(f"\nFin del procesamiento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with open(log_path, 'w') as log_file:
        log_file.writelines('\n'.join(log_lines))

    print("📄 Log guardado en:", log_path)

    
deforestation_step_1(
    input_folder= r"D:\OneDrive - CGIAR\Desktop\ganabosques\deforestacion\outputs\tmp_spatial_procesing",
    output_folder=r"D:\OneDrive - CGIAR\Desktop\ganabosques\deforestacion\outputs\tmp_calc_deforestation",
    source='SMBYC'  # o 'OTRA', si usas otro origen
    # deforestation_value=9  # Solo si source no es SMBYC
)