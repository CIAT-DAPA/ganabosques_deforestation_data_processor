import os
import shutil
import rasterio as rio
from rasterio import features, warp
from rasterio.warp import transform_bounds
from rasterio.transform import from_origin
import numpy as np
import traceback
import logging
from tqdm import tqdm
import re
from pyproj import CRS, Transformer
from tools.log_print import log_print  # Asegúrate de que esta ruta sea válida
from config import config

logger = logging.getLogger(__name__)

def resoluciones_iguales(res1, res2, tol=1e-6):
    return abs(res1[0] - res2[0]) < tol and abs(res1[1] - res2[1]) < tol

def _apply_nad_atd_reclass_block(data):
    """
    Aplica la regla para NAD/ATD:
      - valores > 0 -> 2.0
      - resto -> NaN
    a un bloque (numpy array).
    """
    out = np.full(data.shape, np.nan, dtype="float32")
    mask = data > 0
    out[mask] = 2.0
    return out


def _calculate_common_intersection_bounds(input_folder, dst_crs):
    """
    Calcula el bbox de INTERSECCIÓN de todos los rasters en la carpeta.
    
    Estrategia de dos pasadas:
    - Pasada 1: Lee todos los bounds y calcula la intersección
    - Retorna: (minx, miny, maxx, maxy) del bbox común
    
    Args:
        input_folder: Carpeta con archivos .tif
        
    Returns:
        tuple: (minx, miny, maxx, maxy) en CRS destino
    """
    tif_files = [f for f in os.listdir(input_folder) if f.endswith('.tif')]
    
    if not tif_files:
        raise ValueError(f"No se encontraron archivos .tif en {input_folder}")
    
    minx, miny, maxx, maxy = None, None, None, None
    
    log_print(logger, f"Pasada 1: Calculando bbox de interseccion en {dst_crs} para {len(tif_files)} archivos")
    
    for file in tif_files:
        with rio.open(os.path.join(input_folder, file)) as src:
            if src.crs is None:
                raise ValueError(f"El archivo {file} no tiene CRS definido")

            # Normaliza todos los bounds al CRS destino para evitar mezclar grados/metros.
            left, bottom, right, top = transform_bounds(
                src.crs,
                dst_crs,
                src.bounds.left,
                src.bounds.bottom,
                src.bounds.right,
                src.bounds.top,
                densify_pts=21,
            )
            
            if minx is None:
                # Primer archivo: inicializa los bounds
                minx, miny, maxx, maxy = left, bottom, right, top
                log_print(logger, f"  Archivo 1: {file} -> bounds normalizados")
            else:
                # Siguientes archivos: calcula la intersección
                # Esquina superior izquierda (máximos de min, mínimos de max)
                minx = max(minx, left)
                miny = max(miny, bottom)
                maxx = min(maxx, right)
                maxy = min(maxy, top)
                log_print(logger, f"  Archivo N: {file} -> interseccion actualizada")
    
    # Validar que la intersección es válida
    if minx >= maxx or miny >= maxy:
        raise ValueError(
            f"No hay intersección válida entre los rasters. "
            f"Bounds: ({minx}, {miny}) a ({maxx}, {maxy})"
        )
    
    log_print(logger, f"Bbox de interseccion calculado: ({minx:.2f}, {miny:.2f}) a ({maxx:.2f}, {maxy:.2f})")
    return (minx, miny, maxx, maxy)


def _build_grid(bounds, res_ref):
    """
    Construye un grid destino fijo (transform, width, height) a partir de bounds y resolucion.
    Se usa floor para garantizar que todos los pixeles quedan dentro del bbox comun.
    """
    minx, miny, maxx, maxy = bounds
    resx, resy = res_ref

    width = int(np.floor((maxx - minx) / resx))
    height = int(np.floor((maxy - miny) / resy))

    if width <= 0 or height <= 0:
        raise ValueError(
            f"Grid invalido para bounds={bounds} y resolucion={res_ref}. "
            f"width={width}, height={height}"
        )

    transform = from_origin(minx, maxy, resx, resy)
    return transform, width, height


def _fixed_bounds_to_dst_crs(xmin_fixed, ymin_fixed, xmax_fixed, ymax_fixed, dst_crs):
    """Transforma los bounds de referencia (en EPSG:4326) al CRS destino."""
    transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_string(dst_crs), always_xy=True)
    xmin_m, ymin_m = transformer.transform(xmin_fixed, ymin_fixed)
    xmax_m, ymax_m = transformer.transform(xmax_fixed, ymax_fixed)
    xmin_m, xmax_m = sorted((xmin_m, xmax_m))
    ymin_m, ymax_m = sorted((ymin_m, ymax_m))
    return xmin_m, ymin_m, xmax_m, ymax_m


def _intersect_bounds(a, b):
    """Interseccion de dos bounds (minx, miny, maxx, maxy)."""
    minx = max(a[0], b[0])
    miny = max(a[1], b[1])
    maxx = min(a[2], b[2])
    maxy = min(a[3], b[3])
    if minx >= maxx or miny >= maxy:
        raise ValueError(f"Interseccion invalida entre bounds {a} y {b}")
    return minx, miny, maxx, maxy

def mdl_spatial_processing(input_folder, output_folder, source=None, deforestation_type=None):
    """
    Procesamiento espacial de rasters.
    Procesa subcarpetas según el tipo: smbyc/, nad/, atd/
    Si deforestation_type es None, procesa todas las subcarpetas disponibles.
    
    Args:
        input_folder: Carpeta base de entrada
        output_folder: Carpeta base de salida
        source: Fuente de datos (legacy, se mantiene por compatibilidad)
        deforestation_type: Tipo de deforestación (annual, cumulative, nad, atd)
    """
    os.makedirs(output_folder, exist_ok=True)
    
    # Determinar qué subcarpetas procesar
    if deforestation_type:
        if deforestation_type.lower() in ["annual", "cumulative"]:
            folders_to_process = {"smbyc": False}  # False = no es NAD/ATD
        else:
            folders_to_process = {deforestation_type.lower(): True}  # True = es NAD/ATD
    else:
        # Buscar todas las subcarpetas disponibles
        folders_to_process = {}
        for folder in ["smbyc", "nad", "atd"]:
            if os.path.isdir(os.path.join(input_folder, folder)):
                is_nad_atd = folder in ["nad", "atd"]
                folders_to_process[folder] = is_nad_atd
    
    if not folders_to_process:
        log_print(logger, "No se encontraron carpetas para procesar.", level='warning')
        return False
    
    log_print(logger, f"Procesando carpetas: {list(folders_to_process.keys())}")
    
    all_success = True
    for folder_name, is_nad_atd in folders_to_process.items():
        input_subfolder = os.path.join(input_folder, folder_name)
        output_subfolder = os.path.join(output_folder, folder_name)
        
        if not os.path.isdir(input_subfolder):
            log_print(logger, f"Carpeta no encontrada: {input_subfolder}", level="warning")
            continue
        
        os.makedirs(output_subfolder, exist_ok=True)
        success = _process_spatial_folder(input_subfolder, output_subfolder, folder_name, is_nad_atd)
        if not success:
            all_success = False
    
    return all_success


def _process_spatial_folder(input_folder, output_folder, folder_name, is_nad_atd):
    """
    Procesa rasters con alineamiento garantizado.
    
    Estrategia de dos pasadas:
    1. Pasada 1: Calcula el bbox de intersección de TODOS los rasters
    2. Pasada 2: Reproyecta cada raster y lo recorta al bbox común
    
    Esto garantiza que todos los outputs:
    - Tengan las mismas dimensiones (width, height)
    - Estén perfectamente alineados (mismo transform)
    """
    os.makedirs(output_folder, exist_ok=True)
    log_path = os.path.join(output_folder, 'log_procesamiento.txt')

    try:
        log_print(logger, f"Iniciando procesamiento espacial ALINEADO en: {input_folder}")

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

        # ========== PASADA 1: Calcular bbox comun en CRS destino ==========
        try:
            common_bounds_data = _calculate_common_intersection_bounds(input_folder, dst_crs)

            # Intersecta con el bbox fijo de referencia para garantizar area objetivo.
            fixed_bounds = _fixed_bounds_to_dst_crs(
                xmin_fixed,
                ymin_fixed,
                xmax_fixed,
                ymax_fixed,
                dst_crs,
            )
            common_bounds = _intersect_bounds(common_bounds_data, fixed_bounds)

            # Grid unico para TODOS los rasters de esta carpeta.
            common_transform, common_width, common_height = _build_grid(common_bounds, res_ref)
        except ValueError as e:
            log_print(logger, f"Error calculando bbox común: {e}", level='error')
            return False

        # ========== PASADA 2: Procesar cada archivo con el bbox común ==========
        log_print(logger, f"Pasada 2: Reproyectando y alineando {len(tif_files)} archivos en un grid comun")

        for file in tqdm(tif_files, desc="Procesando archivos", unit="archivo"):
            log_print(logger, f"Procesando archivo: {file}")
            input_path = os.path.join(input_folder, file)

            # Mantener nombre original
            nombre_base, extension = os.path.splitext(file)
            nuevo_nombre = file

            output_path = os.path.join(output_folder, nuevo_nombre)

            with rio.open(input_path) as src:
                src_crs = src.crs
                if src_crs is None:
                    log_print(logger, f"Archivo sin CRS, se omite: {file}", level='warning')
                    continue

                # Siempre usamos el mismo grid para todos los rasters.
                out_transform = common_transform
                out_width = common_width
                out_height = common_height

                kwargs = src.meta.copy()
                kwargs.update({
                    'crs': dst_crs,
                    'transform': out_transform,
                    'width': out_width,
                    'height': out_height,
                    'compress': 'lzw'
                })
                
                # Para NAD/ATD: configurar dtype y nodata correctamente para float32
                if is_nad_atd:
                    kwargs.update({
                        'dtype': 'float32',
                        'nodata': np.nan
                    })
                else:
                    kwargs.update({
                        'nodata': 0
                    })

                with rio.open(output_path, 'w', **kwargs) as dst:
                    for i in range(1, src.count + 1):
                        warp.reproject(
                            source=rio.band(src, i),
                            destination=rio.band(dst, i),
                            src_crs=src.crs,
                            src_transform=src.transform,
                            dst_crs=dst_crs,
                            dst_transform=out_transform,
                            resampling=warp.Resampling.nearest,
                            num_threads=4 if is_nad_atd else 2,
                            warp_mem_limit=512
                        )

            # Reclasificación para NAD/ATD: valores > 0 -> 2.0, resto -> NaN
            if is_nad_atd:
                log_print(logger, f"Aplicando reclasificación NAD/ATD a: {nuevo_nombre}")
                with rio.open(output_path, "r+") as dst:
                    for _, window in dst.block_windows(1):
                        data = dst.read(1, window=window)
                        out_block = _apply_nad_atd_reclass_block(data)
                        dst.write(out_block, 1, window=window)

            log_print(logger, f"Archivo procesado correctamente: {nuevo_nombre} ({common_width}x{common_height})")

        # Escribir log final
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write("El código ha corrido perfectamente (con alineamiento garantizado).\n")
            log_file.write(f"{len(tif_files)} archivos procesados correctamente.\n")
            log_file.write(f"Bbox común: {common_bounds}\n")

        log_print(logger, f"{len(tif_files)} archivos procesados correctamente y alineados.")
        return True

    except Exception:
        error_msg = traceback.format_exc()
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write("Ha ocurrido un error durante el procesamiento:\n")
            log_file.write(error_msg)

        log_print(logger, "Ha ocurrido un error durante el procesamiento. Revisa el log.", level='error')
        logger.error(error_msg)
        return False
