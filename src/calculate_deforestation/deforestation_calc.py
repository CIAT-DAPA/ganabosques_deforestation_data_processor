import os
import re
import rasterio
import numpy as np
from datetime import datetime
import logging
from tqdm import tqdm
from tools.log_print import log_print
from ganabosques_orm.enums.deforestationsource import DeforestationSource

logger = logging.getLogger(__name__)

def extract_years_from_filename(filename):
    """
    Extrae uno o dos años de un nombre de archivo.
    Si hay dos, devuelve ambos. Si hay uno, repite el mismo.
    """
    matches = re.findall(r'20\d{2}', filename)
    if len(matches) == 2:
        return int(matches[0]), int(matches[1])
    elif len(matches) == 1:
        y = int(matches[0])
        return y, y + 1
    else:
        raise ValueError(f"No se encontraron años válidos en el nombre del archivo: {filename}")


def deforestation_calc(input_folder, output_folder, source, deforestation_value=None):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_parte1.txt')
    log_lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines.append(f"--- LOG PARTE 1: CARGA Y FILTRADO ---\nInicio: {timestamp}\n")

    log_print(logger, "Iniciando cálculo de deforestación...")

    # Validación de parámetros
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
    output_years = []

    if not tif_files:
        msg = "No se encontraron archivos .tif en el directorio de entrada."
        log_print(logger, msg, level='warning')
        log_lines.append(msg)

    # PROCESAMIENTO ANUAL
    for tif in tqdm(tif_files, desc="Procesando deforestación anual", unit="archivo"):
        input_path = os.path.join(input_folder, tif)

        try:
            year_start, year_end = extract_years_from_filename(tif)
            output_years.append(year_end)

            output_filename = f"{source.lower()}_deforestation_annual_{year_start}-{year_end}.tif"
            output_path = os.path.join(output_folder, f"{source.lower()}_deforestation_annual", output_filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with rasterio.open(input_path) as src:
                profile = src.profile.copy()
                profile.update({
                    'dtype': 'float32',
                    'nodata': None,  # usamos NaN en datos
                    'compress': 'lzw'
                })

                with rasterio.open(output_path, 'w', **profile) as dst:
                    for ji, window in src.block_windows(1):
                        data = src.read(1, window=window)

                        # Crear matriz con NaN
                        filtered = np.full(data.shape, np.nan, dtype='float32')

                        # Mantener solo píxeles de deforestación
                        mask = (data == value_to_filter)
                        filtered[mask] = 2

                        dst.write(filtered, 1, window=window)

            processed_layers.append(output_path)
            msg = f"{tif} procesado correctamente como {output_filename}."
            log_lines.append(msg)
            log_print(logger, msg)

        except Exception as e:
            msg = f"ERROR procesando {tif}: {str(e)}"
            log_lines.append(msg)
            log_print(logger, msg, level='error')

    # ACUMULADO PROGRESIVO
    if processed_layers:
        try:
            sorted_layers = sorted(zip(output_years, processed_layers))

            for idx, (year, layer_path) in enumerate(tqdm(sorted_layers, desc="Generando acumulado", unit="año")):
                with rasterio.open(layer_path) as src:
                    profile = src.profile
                    profile.update(dtype='float32', nodata=None, compress='lzw')

                    cumulative_folder = os.path.join(output_folder, f"{source.lower()}_deforestation_cumulative")
                    os.makedirs(cumulative_folder, exist_ok=True)

                    # Nuevo nombre: deforestation_cumulative_2010-(year-1)
                    start_year = 2010
                    end_year = year - 1
                    cum_filename = f"deforestation_cumulative_{start_year}-{end_year}.tif"
                    cum_path = os.path.join(cumulative_folder, cum_filename)

                    if idx == 0:
                        # Primer año → copiar tal cual (pero normalizado a 2 y NaN)
                        with rasterio.open(cum_path, 'w', **profile) as dst:
                            for ji, window in src.block_windows(1):
                                data = src.read(1, window=window).astype('float32')
                                data = np.where(data == 2, 2, np.nan)
                                dst.write(data, 1, window=window)
                    else:
                        prev_year = sorted_layers[idx - 1][0]
                        prev_cum_filename = f"deforestation_cumulative_{start_year}-{prev_year - 1}.tif"
                        prev_cum_path = os.path.join(cumulative_folder, prev_cum_filename)

                        with rasterio.open(prev_cum_path) as prev, rasterio.open(cum_path, 'w', **profile) as dst:
                            for ji, window in src.block_windows(1):
                                current_data = src.read(1, window=window).astype('float32')
                                prev_data = prev.read(1, window=window).astype('float32')

                                # Reemplazar NaN por 0 para la suma
                                current_masked = np.where(np.isnan(current_data), 0, current_data)
                                prev_masked = np.where(np.isnan(prev_data), 0, prev_data)

                                sum_data = current_masked + prev_masked

                                # Forzar todos los valores > 2 a 2
                                sum_data = np.where(sum_data > 2, 2, sum_data)

                                # Convertir ceros de vuelta a NaN
                                sum_data = np.where(sum_data == 0, np.nan, sum_data)

                                dst.write(sum_data, 1, window=window)

                    msg = f"Raster acumulado hasta {end_year} guardado como {cum_filename}."
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
