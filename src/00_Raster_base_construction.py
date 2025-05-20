####################################
########## Brayan Mora A. ########## 
##########  5/01/2025     ##########
####################################

#  Este codigo calcula un raster Base, teniendo en cuenta: 
#  1. Datos de SMBYC de Ideam
#  2. Reproyecion de coordenadas 
#  3. Resample de datos 
#  4. corte por un extent comun 
#  5. finalmente un verificador de extents 

##  Este codigo ha sido probado para todos y cada uno de los rasters de 
##  Deforestacion por lo tanto en el folder output_folder, guardo cada raster 
##  Con el que fue probado (2010_2012 hasta 2023_2024)
##  Pero finalmente solo dejamos uno de estos como el raster de referencia ya 
##  Que todos tienen las mismas caracteristicas. 


import rasterio as rio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.windows import from_bounds
import os
import pandas as pd

# Rutas
input_folder = "D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/def/brutos"
output_folder = 'D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/data/Data_Ref/'
os.makedirs(output_folder, exist_ok=True)

# Archivos tif
files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]

# Bounding box en WGS84
xmin_fixed, ymin_fixed, xmax_fixed, ymax_fixed = -79.22432089079678, -3.4138028100111075, -66.6558405429, 12.580743905

# Resolución deseada
target_res = 0.0002730378942450
dst_crs = 'EPSG:4326'

# Lista para guardar los extents
extents = []

for file in files:
    input_path = os.path.join(input_folder, file)
    output_path = os.path.join(output_folder, file)

    with rio.open(input_path) as src:
        if src.crs.to_string() != dst_crs:
            # Reproyectar
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
            # Si ya está en EPSG:4326, solo copiamos como temporal
            temp_path = output_path + ".tmp.tif"
            with rio.open(temp_path, 'w', **src.meta) as dst:
                for i in range(1, src.count + 1):
                    dst.write(src.read(i), i)

    # Recortar
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

# Verificar extents de los archivos guardados
output_files = [f for f in os.listdir(output_folder) if f.endswith('.tif')]
for file in output_files:
    path = os.path.join(output_folder, file)
    with rio.open(path) as src:
        bounds = src.bounds
        extents.append({
            'filename': file,
            'xmin': bounds.left,
            'ymin': bounds.bottom,
            'xmax': bounds.right,
            'ymax': bounds.top
        })

# Crear dataframe con los extents
df_extent = pd.DataFrame(extents)
print("\nExtents de los archivos reproyectados y recortados:")
print(df_extent)