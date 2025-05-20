####################################
########## Brayan Mora A. ########## 
##########  5/02/2025     ##########
####################################

#  Este codigo realiza el calculo de deforestacion, se alimenta de los datos que salen del modulo_spatial_processing 
#  1. Carga los datos que salen del module_spatial_processing
#  2. Solo deja los pixeles de deforestacion con el nivel == 2 si es SMBYC, pero la funcion tiene la opcion de incluir otra base de datos 
#     se debe de especificar que capa es la que representa deforestacion. Estos parametros mencionados, son secundarios, funciona or defecto con SMBYC 
#  3. Guarda los rasters en un temporal
#  4. Genera un log que se encarga de reportar si hay errores o todo se realizo con exito 

import os
import rasterio
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
    tif_files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]

    for tif in sorted(tif_files):
        input_path = os.path.join(input_folder, tif)
        output_path = os.path.join(output_folder, tif)

        try:
            with rasterio.open(input_path) as src:
                data = src.read(1)
                nodata = src.nodata if src.nodata is not None else -9999

                # Convertir NA a 0
                data_clean = np.where(data == nodata, 0, data)

                # Máscara y filtro por valor de deforestación
                mask = (data_clean == value_to_filter)
                filtered = np.where(mask, value_to_filter, 0)

                # Guardar raster filtrado sin NA
                meta = src.meta.copy()
                meta.update(dtype=rasterio.int32, compress='lzw', nodata=0)
                with rasterio.open(output_path, 'w', **meta) as dst:
                    dst.write(filtered.astype(np.int32), 1)

                log_lines.append(f"{tif} procesado correctamente.")

        except Exception as e:
            log_lines.append(f"ERROR procesando {tif}: {str(e)}")

    log_lines.append(f"\nFin del procesamiento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with open(log_path, 'w') as log_file:
        log_file.writelines('\n'.join(log_lines))

    print("📄 Log guardado en:", log_path)

deforestation_step_1(
    input_folder='D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/tmp_spatial_processing/',
    output_folder='D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/tmp_calculate_deforestation/',
    source='SMBYC'  # o 'OTRA', si usas otro origen
    # deforestation_value=9  # Solo si source no es SMBYC
)