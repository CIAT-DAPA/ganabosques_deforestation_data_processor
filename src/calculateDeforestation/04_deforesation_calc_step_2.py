####################################
########## Brayan Mora A. ########## 
##########  5/02/2025     ##########
####################################

#  Este codigo realiza el calculo de CellID, calculado con el raster base
#  1. Carga los datos que salen del module_spatial_processing
#  2. Calcula el cellID teniendo en cuenta el raster base y los almacena en un bloc de notas 
#  3. Guarda el bloc de notas para cada archivo por año
#  4. Genera un log que se encarga de reportar si hay errores o todo se realizo con exito 

import os
import rasterio
from datetime import datetime

def deforestation_step_2(
    ref_raster_path: str,
    input_folder: str,
    output_folder: str
):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_cellid.txt')
    log_lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_lines.append(f"--- LOG CÁLCULO CELLID ---\nInicio: {timestamp}\n")

    try:
        with rasterio.open(ref_raster_path) as ref:
            ref_width = ref.width
            ref_height = ref.height
    except Exception as e:
        log_lines.append(f"ERROR al abrir raster de referencia: {str(e)}")
        with open(log_path, 'w') as log_file:
            log_file.writelines('\n'.join(log_lines))
        raise

    tif_files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]
    if not tif_files:
        log_lines.append("No se encontraron archivos .tif en la carpeta de entrada.")

    for tif in sorted(tif_files):
        try:
            input_path = os.path.join(input_folder, tif)
            cellid_txt_path = os.path.join(output_folder, f'CellID_{os.path.splitext(tif)[0]}.txt')

            with rasterio.open(input_path) as src:
                if src.width != ref_width or src.height != ref_height:
                    log_lines.append(
                        f"ERROR: Dimensiones incompatibles para {tif} "
                        f"(esperado {ref_height}x{ref_width}, encontrado {src.height}x{src.width})"
                    )
                    continue

                data = src.read(1)
                mask = (data == 2)  # Asumimos que los valores de deforestación ya fueron filtrados como "2"

                rows, cols = mask.nonzero()
                cell_ids = [(r * ref_width) + c + 1 for r, c in zip(rows, cols)]

                with open(cellid_txt_path, 'w') as f:
                    for cid in cell_ids:
                        f.write(f"{cid}\n")

                log_lines.append(f"{tif}: CellIDs calculados y guardados. Total: {len(cell_ids)}")

        except Exception as e:
            log_lines.append(f"❌ ERROR procesando {tif}: {str(e)}")

    log_lines.append(f"\nFin del procesamiento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with open(log_path, 'w') as log_file:
        log_file.writelines('\n'.join(log_lines))

    print("📄 Log de procesamiento guardado en:", log_path)


deforestation_step_2(
    ref_raster_path="D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/Data_ref/raster_ref.tif",
    input_folder='D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/tmp_calculate_deforestation/',
    output_folder='D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/tmp_calculate_deforestation_cell/'
)