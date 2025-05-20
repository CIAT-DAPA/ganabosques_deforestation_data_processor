####################################
########## Brayan Mora A. ########## 
##########  5/02/2025     ##########
####################################

#  Este codigo realiza un pre - proceso de datos espaciales
#  1. Carga un raster base el cual sirve para tener patrones de: Sistema de coordenadas, resolucion, Extent
#  2. Reproyecta sistema de coordenadas si es necesario 
#  3. Corta y realiza mascara con extent  
#  5. Hace un resample si es necesario 
#  6. Guarda los rasters en un temporal
#  7. Genera un log que se encarga de reportar si hay errores o todo se realizo con exito 


import os
import rasterio as rio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.windows import from_bounds
import numpy as np
import traceback

def mdl_spatial_processing(ref_path, input_folder, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_procesamiento.txt')
    
    try:
        # Leer raster de referencia
        with rio.open(ref_path) as ref:
            bounds = ref.bounds
            xmin_fixed, ymin_fixed, xmax_fixed, ymax_fixed = bounds.left, bounds.bottom, bounds.right, bounds.top
            res_x, res_y = ref.res
            target_res = (res_x + res_y) / 2
            dst_crs = ref.crs.to_string()

        # Archivos a procesar
        tif_files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]
        tif_files.sort()

        for file in tif_files:
            input_path = os.path.join(input_folder, file)
            output_path = os.path.join(output_folder, file)

            with rio.open(input_path) as src:
                # Verificar si se requiere reproyección
                if src.crs.to_string() != dst_crs:
                    transform, width, height = calculate_default_transform(
                        src.crs, dst_crs,
                        src.width, src.height,
                        *src.bounds,
                        resolution=target_res
                    )

                    kwargs = src.meta.copy()
                    kwargs.update({
                        'crs': dst_crs,
                        'transform': transform,
                        'width': width,
                        'height': height,
                        'compress': 'lzw'
                    })

                    temp_path = output_path + ".tmp.tif"
                    with rio.open(temp_path, 'w', **kwargs) as dst:
                        for i in range(1, src.count + 1):
                            reproject(
                                source=rio.band(src, i),
                                destination=rio.band(dst, i),
                                src_transform=src.transform,
                                src_crs=src.crs,
                                dst_transform=transform,
                                dst_crs=dst_crs,
                                resampling=Resampling.nearest
                            )
                else:
                    # Si ya está en el CRS correcto, solo copiar
                    temp_path = output_path + ".tmp.tif"
                    with rio.open(temp_path, 'w', **src.meta) as dst:
                        for i in range(1, src.count + 1):
                            dst.write(src.read(i), i)

            # Recorte con window
            with rio.open(temp_path) as src:
                window = from_bounds(xmin_fixed, ymin_fixed, xmax_fixed, ymax_fixed, src.transform)
                data = src.read(1, window=window)
                transform_crop = src.window_transform(window)

                meta = src.meta.copy()
                meta.update({
                    "height": data.shape[0],
                    "width": data.shape[1],
                    "transform": transform_crop
                })

                with rio.open(output_path, 'w', **meta) as dst:
                    dst.write(data, 1)

            os.remove(temp_path)
            print(f"Procesado: {file}")

        # Escribir log de éxito
        with open(log_path, 'w') as log_file:
            log_file.write("El código ha corrido perfectamente.\n")
            log_file.write(f"{len(tif_files)} archivos procesados correctamente.\n")

    except Exception as e:
        error_msg = traceback.format_exc()
        with open(log_path, 'w') as log_file:
            log_file.write("Ha ocurrido un error durante el procesamiento:\n")
            log_file.write(error_msg)
        print("Error durante el procesamiento. Revisa el log.")




# Importa la función si está en otro archivo (opcional)
# from tu_modulo import mdl_spatial_processing

# Definir rutas
ref_path = "D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/Data_ref/raster_ref.tif"
input_folder = "D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/brutos/content/"
output_folder = 'D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/tmp_spatial_processing/'

# Ejecutar la función
mdl_spatial_processing(ref_path, input_folder, output_folder)