import os
import rasterio as rio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.windows import from_bounds
import numpy as np
import traceback

def resoluciones_iguales(res1, res2, tol=1e-6):
    return abs(res1[0] - res2[0]) < tol and abs(res1[1] - res2[1]) < tol

def mdl_spatial_processing(input_folder, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_procesamiento.txt')

    try:
        # Raster de referencia
        xmin_fixed = -79.22432089079678
        ymin_fixed = -3.413815939872096
        xmax_fixed = -66.65584054291094
        ymax_fixed = 12.580743905000004
        res_ref = (0.000273037894245, 0.000273037894245)
        dst_crs = 'EPSG:4326'

        tif_files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]
        tif_files.sort()

        for file in tif_files:
            input_path = os.path.join(input_folder, file)
            output_path = os.path.join(output_folder, file)

            with rio.open(input_path) as src:
                src_crs = src.crs.to_string()
                res_src = src.res

                # Crear raster temporal reproyectado y/o resampleado
                if src_crs != dst_crs or not resoluciones_iguales(res_src, res_ref):
                    transform, width, height = calculate_default_transform(
                        src.crs, dst_crs,
                        src.width, src.height,
                        *src.bounds,
                        resolution=(res_ref[0] + res_ref[1]) / 2
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
                                resampling=Resampling.bilinear
                            )
                else:
                    # Copiar directamente si CRS y resolución son iguales
                    temp_path = output_path + ".tmp.tif"
                    kwargs = src.meta.copy()
                    kwargs.update({'compress': 'lzw'})
                    with rio.open(temp_path, 'w', **kwargs) as dst:
                        for i in range(1, src.count + 1):
                            dst.write(src.read(i), i)

            # Recorte con window y guardar archivo final comprimido
            with rio.open(temp_path) as src:
                window = from_bounds(xmin_fixed, ymin_fixed, xmax_fixed, ymax_fixed, src.transform)
                data = src.read(1, window=window)
                transform_crop = src.window_transform(window)

                meta = src.meta.copy()
                meta.update({
                    "height": data.shape[0],
                    "width": data.shape[1],
                    "transform": transform_crop,
                    "compress": "lzw"
                })

                with rio.open(output_path, 'w', **meta) as dst:
                    dst.write(data, 1)

            os.remove(temp_path)
            print(f"Procesado: {file}")

        with open(log_path, 'w') as log_file:
            log_file.write("El código ha corrido perfectamente.\n")
            log_file.write(f"{len(tif_files)} archivos procesados correctamente.\n")

    except Exception:
        error_msg = traceback.format_exc()
        with open(log_path, 'w') as log_file:
            log_file.write("Ha ocurrido un error durante el procesamiento:\n")
            log_file.write(error_msg)
        print("Error durante el procesamiento. Revisa el log.")

# Ejecutar la función
mdl_spatial_processing(input_folder= r"D:\OneDrive - CGIAR\Desktop\ganabosques\deforestacion\outputs\tmp_quality_control",
                         output_folder= r"D:\OneDrive - CGIAR\Desktop\ganabosques\deforestacion\outputs\tmp_spatial_procesing")