####################################
########## Brayan Mora A. ##########
##########    5/02/2025    ##########
####################################

import os
import rasterio
from rasterio.windows import Window
from rasterio.enums import Resampling
import numpy as np
from datetime import datetime
import logging
from tqdm import tqdm  
from tools.log_print import log_print  # Asegúrate que esta ruta esté bien
from ganabosques_orm.enums.deforestationsource import DeforestationSource

logger = logging.getLogger(__name__)

def deforestation_calc(input_folder, output_folder, source, deforestation_value=None):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_parte1.txt')
    log_lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines.append(f"--- LOG PARTE 1: CARGA Y FILTRADO ---\nInicio: {timestamp}\n")

    log_print(logger, "Iniciando cálculo de deforestación...")

    if source != DeforestationSource.SMBYC.value and deforestation_value is None:
        error_msg = f"ERROR: Si la fuente no es '{DeforestationSource.SMBYC.value}', debes especificar 'deforestation_value'."
        log_lines.append(error_msg)
        log_print(logger, error_msg, level='error')
        with open(log_path, 'w') as log_file:
            log_file.writelines('\n'.join(log_lines))
        raise ValueError(error_msg)

    value_to_filter = 2 if source == DeforestationSource.SMBYC.value else deforestation_value
    tif_files = sorted([f for f in os.listdir(input_folder) if f.endswith('.tif')])
    processed_layers = []
    years = []

    if not tif_files:
        msg = "No se encontraron archivos .tif en el directorio de entrada."
        log_print(logger, msg, level='warning')
        log_lines.append(msg)

    # PROCESAMIENTO ANUAL CON BARRA DE PROGRESO
    for tif in tqdm(tif_files, desc="Procesando deforestación anual", unit="archivo"):
        input_path = os.path.join(input_folder, tif)
        year_str = ''.join(filter(str.isdigit, tif))
        year = int(year_str)
        output_filename = f"{source.lower()}_deforestation_annual_{year}-{year + 1}.tif"
        output_path = os.path.join(output_folder, f"{source.lower()}_deforestation_annual", output_filename)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

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
                years.append(year)
                msg = f"{tif} procesado correctamente como {output_filename}."
                log_lines.append(msg)
                log_print(logger, msg)

        except Exception as e:
            msg = f"ERROR procesando {tif}: {str(e)}"
            log_lines.append(msg)
            log_print(logger, msg, level='error')

    # ACUMULADO PROGRESIVO CON BARRA DE PROGRESO
    if processed_layers:
        try:
            sorted_years_layers = sorted(zip(years, processed_layers))
            cumulative_sum = None

            for idx, (year, layer_path) in enumerate(tqdm(sorted_years_layers, desc="Generando acumulado", unit="año")):
                with rasterio.open(layer_path) as src:
                    profile = src.profile
                    profile.update(dtype='int32', nodata=-99999, compress='lzw')
                    data = src.read(1)

                    if cumulative_sum is None:
                        cumulative_sum = np.zeros_like(data, dtype='int32')

                    cumulative_sum += data

                    if idx >= 1:
                        cum_filename = f"{source.lower()}_deforestation_cumulative_{year}.tif"
                        cum_path = os.path.join(output_folder, f"{source.lower()}_deforestation_cumulative", cum_filename)
                        os.makedirs(os.path.dirname(cum_path), exist_ok=True)

                        with rasterio.open(cum_path, 'w', **profile) as dst:
                            dst.write(cumulative_sum, 1)

                        msg = f"Raster acumulado hasta {year} guardado como {cum_filename}."
                        log_lines.append(msg)
                        log_print(logger, msg)

        except Exception as e:
            msg = f"ERROR generando acumulado: {str(e)}"
            log_lines.append(msg)
            log_print(logger, msg, level='error')
    else:
        msg = "No se generó acumulado porque no se procesaron capas correctamente."
        log_lines.append(msg)
        log_print(logger, msg, level='warning')

    log_lines.append(f"\nFin del procesamiento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with open(log_path, 'w') as log_file:
        log_file.writelines('\n'.join(log_lines))

    log_print(logger, f"Log guardado en: {log_path}")

