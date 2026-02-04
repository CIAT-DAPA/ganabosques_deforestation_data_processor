import os
import math
import tempfile
import zipfile
import subprocess
import shutil
import numpy as np
import rasterio as rio
from rasterio import features, warp
from rasterio.transform import from_origin
from rasterio.crs import CRS as RioCRS
import fiona
from fiona.errors import DriverError
from shapely.geometry import shape
from pyproj import CRS, Transformer
import traceback

from config import config


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

BASE_RESULTS = r"D:\OneDrive - CGIAR\Desktop\ganabosques\ganabosques_results\01_etl_deforestation"
BRUTOS_DIR = os.path.join(BASE_RESULTS, "atd_nad_brutos")
ATD_IN_DIR = os.path.join(BRUTOS_DIR, "atd")
NAD_IN_DIR = os.path.join(BRUTOS_DIR, "nad")
ATD_OUT_DIR = os.path.join(BASE_RESULTS, "atd")
NAD_OUT_DIR = os.path.join(BASE_RESULTS, "nad")

YEARS = list(range(2016, 2026))
QUARTERS = {
    1: ("01-01", "03-30"),
    2: ("04-01", "06-30"),
    3: ("07-01", "09-30"),
    4: ("10-01", "12-31"),
}

DST_CRS = None
TRANSFORM_REF = None
WIDTH_REF = None
HEIGHT_REF = None


# ============================================================
# UTILIDADES
# ============================================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def init_reference():
    """
    Define la grilla de referencia NAD/ATD a partir de config['SPATIAL_PARAMETERS'].
    xmin_ref/ymin_ref/xmax_ref/ymax_ref en EPSG:4326 (lon/lat).
    dst_crs_ref en metros (por ej. 'EPSG:3116').
    res_ref en metros (por ej. [30, 30]).
    """
    global DST_CRS, TRANSFORM_REF, WIDTH_REF, HEIGHT_REF

    sp = config["SPATIAL_PARAMETERS"]
    xmin_lon, ymin_lat = sp["xmin_ref"], sp["ymin_ref"]
    xmax_lon, ymax_lat = sp["xmax_ref"], sp["ymax_ref"]
    resx, resy = sp["res_ref"]
    dst_crs_str = sp["dst_crs_ref"]

    DST_CRS = RioCRS.from_string(dst_crs_str)

    src_crs = CRS.from_epsg(4326)
    transformer = Transformer.from_crs(src_crs, DST_CRS, always_xy=True)

    xmin_m, ymin_m = transformer.transform(xmin_lon, ymin_lat)
    xmax_m, ymax_m = transformer.transform(xmax_lon, ymax_lat)

    xmin_m, xmax_m = sorted((xmin_m, xmax_m))
    ymin_m, ymax_m = sorted((ymin_m, ymax_m))

    WIDTH_REF = int(np.ceil((xmax_m - xmin_m) / resx))
    HEIGHT_REF = int(np.ceil((ymax_m - ymin_m) / resy))

    if WIDTH_REF <= 0 or HEIGHT_REF <= 0:
        raise ValueError(f"Grid inválida: {WIDTH_REF} x {HEIGHT_REF}")

    TRANSFORM_REF = from_origin(xmin_m, ymax_m, resx, resy)

    print(f"[INIT] Grilla de referencia: {WIDTH_REF}x{HEIGHT_REF}, {DST_CRS}")


# ============================================================
# FUNCIONES COMUNES: RECLASIFICAR + REPROYECTAR A GRILLA REF
# ============================================================

def _apply_nad_reclass_block(data):
    """
    Aplica la regla:
      - valores > 0 -> 2
      - resto -> NaN
    a un bloque (numpy array).
    """
    out = np.full(data.shape, np.nan, dtype="float32")
    mask = data > 0
    out[mask] = 2.0
    return out


def reproject_raster_to_ref(src_path: str, out_path: str):
    """
    Reproyecta un raster (NAD o ATD intermedio) a la grilla de referencia
    (TRANSFORM_REF, DST_CRS) **sin crear un array gigante en memoria**.

    1) Reproyecta directamente del src al archivo destino (en disco).
    2) Luego recorre el raster por bloques (windows) y aplica >0 -> 2, resto NaN.
    """
    if WIDTH_REF is None or HEIGHT_REF is None or WIDTH_REF <= 0 or HEIGHT_REF <= 0:
        raise RuntimeError(
            "La grilla de referencia no es válida. ¿Llamaste a init_reference()?"
        )

    try:
        with rio.open(src_path) as src:
            dst_meta = src.meta.copy()
            dst_meta.update({
                "crs": DST_CRS,
                "transform": TRANSFORM_REF,
                "width": WIDTH_REF,
                "height": HEIGHT_REF,
                "compress": "lzw",
                "dtype": "float32",
                "nodata": np.nan,
            })

            # 1) Reproyección directa a disco (sin dst_arr grande)
            with rio.open(out_path, "w", **dst_meta) as dst:
                warp.reproject(
                    source=rio.band(src, 1),
                    destination=rio.band(dst, 1),
                    src_crs=src.crs,
                    src_transform=src.transform,
                    dst_crs=DST_CRS,
                    dst_transform=TRANSFORM_REF,
                    resampling=warp.Resampling.nearest,
                    num_threads=4,     # ajusta según tus núcleos
                    warp_mem_limit=512 # MB usados internamente por GDAL
                )

        # 2) Reclasificación por bloques: >0 -> 2, resto NaN
        with rio.open(out_path, "r+") as dst:
            for _, window in dst.block_windows(1):
                data = dst.read(1, window=window)
                out_block = _apply_nad_reclass_block(data)
                dst.write(out_block, 1, window=window)

    except Exception as e:
        print(f"[ERROR] Falló la reproyección de {os.path.basename(src_path)}: {e}")
        traceback.print_exc()


# ============================================================
# ATD: SHP → RASTER EPSG:4326 → GRILLA REF (EPSG:3116)
# ============================================================

def meters_to_deg_lat(m):
    return m / 111_320.0


def meters_to_deg_lon(m, lat_deg):
    lat_rad = math.radians(lat_deg)
    return m / (111_320.0 * math.cos(lat_rad))


def rasterize_atd_to_lonlat(vector_path: str, out_raster: str, res_m: float = 30.0):
    """
    Rasteriza shapefile ATD a un raster intermedio en EPSG:4326 (0/2).
    Este raster será luego reproyectado a la grilla de referencia con
    reproject_raster_to_ref.
    """
    lonlat_crs = RioCRS.from_epsg(4326)

    try:
        with fiona.open(vector_path, "r") as src:
            src_crs = src.crs_wkt if src.crs_wkt else src.crs
            if not src_crs:
                raise ValueError(
                    f"El shapefile {os.path.basename(vector_path)} no tiene CRS definido."
                )

            geoms_ll = []
            min_lon = math.inf
            min_lat = math.inf
            max_lon = -math.inf
            max_lat = -math.inf

            for feat in src:
                geom = feat["geometry"]
                if geom is None:
                    continue

                geom_ll = warp.transform_geom(
                    src_crs,
                    lonlat_crs.to_string(),
                    geom,
                    precision=9
                )
                geoms_ll.append(geom_ll)

                g_shp = shape(geom_ll)
                bminx, bminy, bmaxx, bmaxy = g_shp.bounds

                min_lon = min(min_lon, bminx)
                min_lat = min(min_lat, bminy)
                max_lon = max(max_lon, bmaxx)
                max_lat = max(max_lat, bmaxy)

            if not geoms_ll:
                print(f"[ATD] WARN: No hay geometrías válidas en {os.path.basename(vector_path)}")
                return

        lat_center = (min_lat + max_lat) / 2.0
        res_lat_deg = meters_to_deg_lat(res_m)
        res_lon_deg = meters_to_deg_lon(res_m, lat_center)

        width = int(math.ceil((max_lon - min_lon) / res_lon_deg))
        height = int(math.ceil((max_lat - min_lat) / res_lat_deg))

        if width <= 0 or height <= 0:
            raise ValueError(
                f"Dimensiones inválidas para {os.path.basename(vector_path)}: {width} x {height}"
            )

        transform = from_origin(min_lon, max_lat, res_lon_deg, res_lat_deg)

        shapes_list = [(g, 2) for g in geoms_ll]

        raster_arr = features.rasterize(
            shapes=shapes_list,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            all_touched=True,
            dtype="uint8"
        )

        meta = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": 1,
            "dtype": "uint8",
            "crs": lonlat_crs,
            "transform": transform,
            "compress": "lzw",
            "nodata": 0,
        }

        out_dir = os.path.dirname(out_raster)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        with rio.open(out_raster, "w", **meta) as dst:
            dst.write(raster_arr, 1)

    except Exception as e:
        print(f"[ERROR] Falló la rasterización ATD (lon/lat) de {os.path.basename(vector_path)}: {e}")
        traceback.print_exc()


def _infer_quarter_from_name(year: int, shp_path: str) -> int | None:
    base = os.path.basename(shp_path).lower()
    parent = os.path.basename(os.path.dirname(shp_path)).lower()
    s = f"{parent}_{base}"

    q = None
    if "iii_trim" in s or "_iii_" in s:
        q = 3
    elif "iv_trim" in s or "_iv_" in s:
        q = 4
    elif "ii_trim" in s or "_ii_" in s:
        q = 2
    elif "i_trim" in s or "_i_" in s:
        q = 1

    if q is None:
        for cand in range(1, 5):
            patt1 = f"_{cand:02}_trim"
            patt2 = f"_{cand}_trim"
            if patt1 in s or patt2 in s:
                q = cand
                break

    return q


def process_atd():
    """
    Flujo ATD:

    - Busca shapefiles en atd_nad_brutos/atd/<AÑO>/.../*.shp
    - Para cada shapefile:
        * Inferir trimestre (q)
        * Rasterizar a EPSG:4326 (0/2) -> archivo temporal
        * Reproyectar a grilla ref (EPSG:3116) con reproject_raster_to_ref
        * Guardar en:
            ATD_OUT_DIR/atd_AAAA-MM-DD-AAAA-MM-DD.tif
    """
    print("[ATD] Iniciando flujo ATD...")
    ensure_dir(ATD_OUT_DIR)

    for year in YEARS:
        year_in_dir = os.path.join(ATD_IN_DIR, str(year))
        if not os.path.isdir(year_in_dir):
            continue

        print(f"[ATD] Año {year}")

        for root, dirs, files in os.walk(year_in_dir):
            for fname in files:
                if not fname.lower().endswith(".shp"):
                    continue

                shp_path = os.path.join(root, fname)

                q = _infer_quarter_from_name(year, shp_path)
                if q is None or q not in QUARTERS:
                    continue

                start_mmdd, end_mmdd = QUARTERS[q]
                start_date = f"{year}-{start_mmdd}"
                end_date = f"{year}-{end_mmdd}"

                out_final = os.path.join(
                    ATD_OUT_DIR,
                    f"atd_{start_date}-{end_date}.tif"
                )

                if os.path.exists(out_final):
                    continue

                tmp_raster = os.path.join(
                    ATD_OUT_DIR,
                    f"_tmp_atd_{year}_{q:02}_trim_4326.tif"
                )

                rasterize_atd_to_lonlat(shp_path, tmp_raster)

                if os.path.exists(tmp_raster):
                    try:
                        reproject_raster_to_ref(tmp_raster, out_final)
                    finally:
                        try:
                            os.remove(tmp_raster)
                        except OSError:
                            pass

    print("[ATD] Flujo ATD finalizado.")


# ============================================================
# NAD: RASTERS .TIF PRIORITARIO, SI NO KMZ/KML
# ============================================================

def _find_quarter_file(year_in_dir: str, year: int, q: int, ext: str):
    candidates = [f"alertas_tempranas_{year}_{q:02}_trim.{ext}"]
    if q == 4:
        candidates.append(f"alertas_temprenas_{year}_iv_trim.{ext}")
    for name in candidates:
        path = os.path.join(year_in_dir, name)
        if os.path.exists(path):
            return path
    return None


def rasterize_vector_to_lonlat(vector_path: str, out_raster: str, res_m: float = 30.0):
    """
    Rasteriza un vector (por ejemplo KML de NAD) a EPSG:4326 en una grilla
    ajustada al extent del vector. Luego se reproyecta con reproject_raster_to_ref.
    """
    lonlat_crs = RioCRS.from_epsg(4326)

    with fiona.open(vector_path, "r") as src:
        src_crs = src.crs_wkt if src.crs_wkt else src.crs
        if not src_crs:
            raise ValueError("El vector no tiene CRS definido.")

        geoms_ll = []
        min_lon = math.inf
        min_lat = math.inf
        max_lon = -math.inf
        max_lat = -math.inf

        for feat in src:
            geom = feat["geometry"]
            if geom is None:
                continue

            geom_ll = warp.transform_geom(
                src_crs,
                lonlat_crs.to_string(),
                geom,
                precision=9
            )
            geoms_ll.append(geom_ll)

            g_shp = shape(geom_ll)
            bminx, bminy, bmaxx, bmaxy = g_shp.bounds

            min_lon = min(min_lon, bminx)
            min_lat = min(min_lat, bminy)
            max_lon = max(max_lon, bmaxx)
            max_lat = max(max_lat, bmaxy)

        if not geoms_ll:
            print(f"[NAD] WARN: No hay geometrías válidas en {os.path.basename(vector_path)}")
            return

    lat_center = (min_lat + max_lat) / 2.0
    res_lat_deg = meters_to_deg_lat(res_m)
    res_lon_deg = meters_to_deg_lon(res_m, lat_center)

    width = int(math.ceil((max_lon - min_lon) / res_lon_deg))
    height = int(math.ceil((max_lat - min_lat) / res_lat_deg))

    if width <= 0 or height <= 0:
        raise ValueError(
            f"Dimensiones inválidas para {os.path.basename(vector_path)}: {width} x {height}"
        )

    transform = from_origin(min_lon, max_lat, res_lon_deg, res_lat_deg)
    shapes_list = [(g, 1) for g in geoms_ll]

    raster_arr = features.rasterize(
        shapes=shapes_list,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8"
    )

    meta = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "uint8",
        "crs": lonlat_crs,
        "transform": transform,
        "compress": "lzw",
        "nodata": 0,
    }

    with rio.open(out_raster, "w", **meta) as dst:
        dst.write(raster_arr, 1)


def process_nad():
    print("[NAD] Iniciando flujo NAD...")
    ensure_dir(NAD_OUT_DIR)

    for year in YEARS:
        print(f"[NAD] Año {year}")
        year_in_dir = os.path.join(NAD_IN_DIR, str(year))
        if not os.path.isdir(year_in_dir):
            continue

        for q in range(1, 5):
            start_mmdd, end_mmdd = QUARTERS[q]
            start_date = f"{year}-{start_mmdd}"
            end_date = f"{year}-{end_mmdd}"

            out_raster = os.path.join(
                NAD_OUT_DIR,
                f"nad_{start_date}-{end_date}.tif"
            )

            if os.path.exists(out_raster):
                continue

            tif_path = _find_quarter_file(year_in_dir, year, q, "tif")

            if tif_path:
                reproject_raster_to_ref(tif_path, out_raster)
                continue

            kmz_path = _find_quarter_file(year_in_dir, year, q, "kmz")

            if kmz_path:
                print(f"[NAD] KMZ encontrado {os.path.basename(kmz_path)} -> rasterizando")
                try:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        with zipfile.ZipFile(kmz_path, "r") as z:
                            z.extract("doc.kml", tmpdir)
                        kml_path = os.path.join(tmpdir, "doc.kml")

                        tmp_raster = os.path.join(
                            NAD_OUT_DIR,
                            f"_tmp_nad_{year}_{q:02}_4326.tif"
                        )
                        rasterize_vector_to_lonlat(kml_path, tmp_raster)

                        if os.path.exists(tmp_raster):
                            try:
                                reproject_raster_to_ref(tmp_raster, out_raster)
                            finally:
                                try:
                                    os.remove(tmp_raster)
                                except OSError:
                                    pass
                except Exception as e:
                    print(f"[ERROR] Falló el procesamiento de {os.path.basename(kmz_path)}: {e}")
                    traceback.print_exc()

    print("[NAD] Flujo NAD finalizado.")


# ============================================================
# MAIN
# ============================================================

def main():
    init_reference()
    print("Seleccione flujo a ejecutar")
    print("    1) ATD (vector -> raster EPSG:4326 -> grilla ref EPSG:3116)")
    print("    2) NAD (rasters .tif prioritario, si no KMZ/KML)")
    opcion = input("Opción (1/2): ").strip()

    if opcion == "1":
        process_atd()
    elif opcion == "2":
        process_nad()
    else:
        print("Opción no válida")


if __name__ == "__main__":
    main()
