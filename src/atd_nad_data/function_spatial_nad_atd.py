import os
import math
import tempfile
import zipfile
import subprocess
import traceback
import shutil

import numpy as np
import rasterio as rio
from rasterio import features, warp
from rasterio.transform import from_origin
from rasterio.crs import CRS as RioCRS
import fiona
from shapely.geometry import shape
from shapely.ops import transform as shp_transform
from pyproj import CRS, Transformer


def spatial_info(path_input: str, output_folder: str):
    """
    FUNCIÓN INDEPENDIENTE:
    - Resolución final: 2000 m
    - CRS final: EPSG:3116
    - Extent final: inferido de ATD+NAD (solo bboxes finitos). Si falla, usa fallback.
    - Quemado final (ATD y NAD): >0 => 2, else => NaN (float32)

    Requiere ogr2ogr SOLO si hay KML/KMZ. Si no está, los salta con warning.
    """

    # =========================
    # Parámetros fijos
    # =========================
    RES_M = 2000.0
    DST_CRS = RioCRS.from_epsg(3116)

    # Fallback extent (aprox Colombia) en EPSG:3116
    FALLBACK_BOUNDS_3116 = (-200000.0, -200000.0, 1400000.0, 2200000.0)

    # ¿Existe ogr2ogr?
    OGR2OGR = shutil.which("ogr2ogr")  # devuelve ruta completa o None

    # =========================
    # Helpers
    # =========================
    def log(msg: str):
        print(msg, flush=True)

    def ensure_dir(p: str):
        os.makedirs(p, exist_ok=True)

    def is_finite_bbox(b):
        return b is not None and len(b) == 4 and all(math.isfinite(v) for v in b)

    def _collect_files(root: str, exts: tuple[str, ...]) -> list[str]:
        out = []
        for r, _, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(exts):
                    out.append(os.path.join(r, fn))
        return sorted(out)

    def _find_any_in_dir(root: str) -> dict:
        found = {"shp": None, "kml": None, "kmz": None}
        for r, _, files in os.walk(root):
            for fn in files:
                low = fn.lower()
                p = os.path.join(r, fn)
                if low.endswith(".shp") and found["shp"] is None:
                    found["shp"] = p
                elif low.endswith(".kml") and found["kml"] is None:
                    found["kml"] = p
                elif low.endswith(".kmz") and found["kmz"] is None:
                    found["kmz"] = p
        return found

    def _extract_kmz_to_kml(kmz_path: str, tmpdir: str) -> str:
        with zipfile.ZipFile(kmz_path, "r") as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError(f"No encontré .kml dentro de {kmz_path}")
            chosen = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
            z.extract(chosen, tmpdir)
            return os.path.join(tmpdir, chosen)

    def _ogr2ogr_to_geojson(src_vector: str, out_geojson: str):
        if OGR2OGR is None:
            raise FileNotFoundError(
                "No encontré 'ogr2ogr' en PATH. Instala GDAL o agrega ogr2ogr al PATH."
            )

        cmd = [OGR2OGR, "-f", "GeoJSON", out_geojson, src_vector]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(
                f"ogr2ogr falló.\nCMD: {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}"
            )

        if (not os.path.exists(out_geojson)) or os.path.getsize(out_geojson) < 20:
            raise RuntimeError(f"GeoJSON vacío al convertir: {src_vector}")

    def _apply_burn_reclass_block(data: np.ndarray) -> np.ndarray:
        out = np.full(data.shape, np.nan, dtype="float32")
        out[data > 0] = 2.0
        return out

    def _update_global_bounds(bounds_m, bbox, src_label=""):
        if not is_finite_bbox(bbox):
            log(f"[SCAN] Ignorado bbox no-finito: {src_label} -> {bbox}")
            return bounds_m

        xmin, ymin, xmax, ymax = bbox
        if bounds_m is None:
            return [xmin, ymin, xmax, ymax]

        bounds_m[0] = min(bounds_m[0], xmin)
        bounds_m[1] = min(bounds_m[1], ymin)
        bounds_m[2] = max(bounds_m[2], xmax)
        bounds_m[3] = max(bounds_m[3], ymax)
        return bounds_m

    # =========================
    # Bounds: Raster -> DST
    # =========================
    def _bounds_of_raster_in_dst(tif_path: str):
        with rio.open(tif_path) as src:
            if src.crs is None:
                raise ValueError(f"Raster sin CRS: {tif_path}")

            b = src.bounds
            tr = Transformer.from_crs(
                CRS.from_user_input(src.crs.to_string()),
                CRS.from_user_input(DST_CRS.to_string()),
                always_xy=True
            )

            xs = [b.left, b.left, b.right, b.right]
            ys = [b.bottom, b.top, b.bottom, b.top]
            X, Y = tr.transform(xs, ys)

            bbox = (min(X), min(Y), max(X), max(Y))
            if not is_finite_bbox(bbox):
                raise ValueError(f"BBox no finito raster: {tif_path} -> {bbox}")
            return bbox

    # =========================
    # Bounds: Vector -> DST
    # =========================
    def _bounds_of_vector_in_dst(vector_path: str):
        with fiona.open(vector_path, "r") as src:
            src_crs = src.crs_wkt if src.crs_wkt else src.crs
            if not src_crs:
                raise ValueError(f"Vector sin CRS: {vector_path}")

            tr = Transformer.from_crs(
                CRS.from_user_input(src_crs),
                CRS.from_user_input(DST_CRS.to_string()),
                always_xy=True
            )

            minx = math.inf
            miny = math.inf
            maxx = -math.inf
            maxy = -math.inf

            any_geom = False
            for feat in src:
                geom = feat.get("geometry")
                if geom is None:
                    continue
                g = shape(geom)
                if g.is_empty:
                    continue
                any_geom = True
                bminx, bminy, bmaxx, bmaxy = g.bounds

                xs = [bminx, bminx, bmaxx, bmaxx]
                ys = [bminy, bmaxy, bminy, bmaxy]
                X, Y = tr.transform(xs, ys)

                minx = min(minx, min(X))
                miny = min(miny, min(Y))
                maxx = max(maxx, max(X))
                maxy = max(maxy, max(Y))

            bbox = (minx, miny, maxx, maxy)
            if (not any_geom) or (not is_finite_bbox(bbox)):
                raise ValueError(f"No hay geometrías válidas en: {vector_path}")
            return bbox

    # =========================
    # 0) Validar estructura
    # =========================
    atd_root = os.path.join(path_input, "atd")
    nad_root = os.path.join(path_input, "nad")

    if not os.path.isdir(atd_root) and not os.path.isdir(nad_root):
        raise FileNotFoundError(f"No encuentro subcarpetas 'atd' o 'nad' en: {path_input}")

    if OGR2OGR is None:
        log("[WARN] No encontré ogr2ogr en PATH. Los KML/KMZ se van a saltar. "
            "Solución: conda install -c conda-forge gdal, o agrega GDAL al PATH.")
    else:
        log(f"[OK] ogr2ogr encontrado: {OGR2OGR}")

    # =========================
    # 1) Scan extent global
    # =========================
    global_bounds = None

    # ATD
    if os.path.isdir(atd_root):
        for year_name in sorted(os.listdir(atd_root)):
            year_dir = os.path.join(atd_root, year_name)
            if not os.path.isdir(year_dir):
                continue
            for q_folder in sorted(os.listdir(year_dir)):
                q_dir = os.path.join(year_dir, q_folder)
                if not os.path.isdir(q_dir):
                    continue

                found = _find_any_in_dir(q_dir)

                if found["shp"]:
                    try:
                        bbox = _bounds_of_vector_in_dst(found["shp"])
                        global_bounds = _update_global_bounds(global_bounds, bbox, found["shp"])
                    except Exception as e:
                        log(f"[SCAN] ATD SHP ignorado ({q_dir}): {e}")

                elif found["kml"] or found["kmz"]:
                    if OGR2OGR is None:
                        log(f"[SCAN] ATD KML/KMZ saltado (sin ogr2ogr): {q_dir}")
                        continue
                    try:
                        with tempfile.TemporaryDirectory() as tmpdir:
                            if found["kmz"]:
                                src_kml = _extract_kmz_to_kml(found["kmz"], tmpdir)
                            else:
                                src_kml = found["kml"]

                            gj = os.path.join(tmpdir, "tmp.geojson")
                            _ogr2ogr_to_geojson(src_kml, gj)

                            bbox = _bounds_of_vector_in_dst(gj)
                            global_bounds = _update_global_bounds(global_bounds, bbox, src_kml)
                    except Exception as e:
                        log(f"[SCAN] ATD KML/KMZ ignorado ({q_dir}): {e}")

    # NAD
    if os.path.isdir(nad_root):
        for year_name in sorted(os.listdir(nad_root)):
            year_dir = os.path.join(nad_root, year_name)
            if not os.path.isdir(year_dir):
                continue
            for q_folder in sorted(os.listdir(year_dir)):
                q_dir = os.path.join(year_dir, q_folder)
                if not os.path.isdir(q_dir):
                    continue

                for tif in _collect_files(q_dir, (".tif", ".tiff")):
                    try:
                        bbox = _bounds_of_raster_in_dst(tif)
                        global_bounds = _update_global_bounds(global_bounds, bbox, tif)
                    except Exception as e:
                        log(f"[SCAN] NAD TIF ignorado ({tif}): {e}")

    # =========================
    # 2) Construir grilla 2km
    # =========================
    if global_bounds is None or not is_finite_bbox(global_bounds):
        log(f"[INIT] Extent no inferible. Uso fallback EPSG:3116: {FALLBACK_BOUNDS_3116}")
        xmin, ymin, xmax, ymax = FALLBACK_BOUNDS_3116
    else:
        xmin, ymin, xmax, ymax = global_bounds

    def _snap_floor(v): return math.floor(v / RES_M) * RES_M
    def _snap_ceil(v): return math.ceil(v / RES_M) * RES_M

    xmin = _snap_floor(xmin)
    ymin = _snap_floor(ymin)
    xmax = _snap_ceil(xmax)
    ymax = _snap_ceil(ymax)

    width = int(round((xmax - xmin) / RES_M))
    height = int(round((ymax - ymin) / RES_M))
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Grilla inválida: {width}x{height} | bounds=({xmin},{ymin},{xmax},{ymax})")

    TRANSFORM_REF = from_origin(xmin, ymax, RES_M, RES_M)
    log(f"[INIT] Grilla 2km: {width}x{height} | {DST_CRS} | bounds=({xmin},{ymin},{xmax},{ymax})")

    # =========================
    # 3) Rasterizar vector -> grilla ref (por bloques)
    # =========================
    def _rasterize_vector_to_ref(vector_path: str, out_path: str):
        ensure_dir(os.path.dirname(out_path))

        meta = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": 1,
            "dtype": "float32",
            "crs": DST_CRS,
            "transform": TRANSFORM_REF,
            "compress": "lzw",
            "nodata": np.nan,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }

        with fiona.open(vector_path, "r") as src:
            src_crs = src.crs_wkt if src.crs_wkt else src.crs
            if not src_crs:
                raise ValueError(f"Vector sin CRS: {vector_path}")

            tr = Transformer.from_crs(
                CRS.from_user_input(src_crs),
                CRS.from_user_input(DST_CRS.to_string()),
                always_xy=True
            )

            def _tx_coords(x, y, z=None):
                X, Y = tr.transform(x, y)
                return (X, Y) if z is None else (X, Y, z)

            geoms = []
            for feat in src:
                geom = feat.get("geometry")
                if geom is None:
                    continue
                g = shape(geom)
                if g.is_empty:
                    continue
                try:
                    g2 = shp_transform(_tx_coords, g)
                    if not g2.is_empty:
                        geoms.append(g2)
                except Exception:
                    continue

        if not geoms:
            raise ValueError(f"No hay geometrías válidas para rasterizar: {vector_path}")

        with rio.open(out_path, "w", **meta) as dst:
            # Inicializar NaN por bloques
            for _, window in dst.block_windows(1):
                dst.write(np.full((window.height, window.width), np.nan, dtype="float32"), 1, window=window)

            # Rasterizar por bloque con filtro bbox
            for _, window in dst.block_windows(1):
                minx_w, miny_w, maxx_w, maxy_w = rio.windows.bounds(window, TRANSFORM_REF)

                candidates = []
                for g in geoms:
                    gb = g.bounds
                    if (gb[2] < minx_w) or (gb[0] > maxx_w) or (gb[3] < miny_w) or (gb[1] > maxy_w):
                        continue
                    candidates.append(g)

                if not candidates:
                    continue

                out_block = np.full((window.height, window.width), np.nan, dtype="float32")
                features.rasterize(
                    shapes=[(g, 2.0) for g in candidates],
                    out=out_block,
                    transform=rio.windows.transform(window, TRANSFORM_REF),
                    fill=np.nan,
                    all_touched=True,
                    dtype="float32",
                )
                dst.write(out_block, 1, window=window)

    # =========================
    # 4) Reproyectar raster -> grilla ref + quemado
    # =========================
    def _reproject_raster_to_ref(src_path: str, out_path: str):
        ensure_dir(os.path.dirname(out_path))

        with rio.open(src_path) as src:
            if src.crs is None:
                raise ValueError(f"Raster sin CRS: {src_path}")

            dst_meta = src.meta.copy()
            dst_meta.update({
                "driver": "GTiff",
                "crs": DST_CRS,
                "transform": TRANSFORM_REF,
                "width": width,
                "height": height,
                "compress": "lzw",
                "dtype": "float32",
                "nodata": np.nan,
                "count": 1,
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
            })

            with rio.open(out_path, "w", **dst_meta) as dst:
                warp.reproject(
                    source=rio.band(src, 1),
                    destination=rio.band(dst, 1),
                    src_crs=src.crs,
                    src_transform=src.transform,
                    dst_crs=DST_CRS,
                    dst_transform=TRANSFORM_REF,
                    resampling=warp.Resampling.nearest,
                    num_threads=4,
                    warp_mem_limit=512,
                )

        with rio.open(out_path, "r+") as dst:
            for _, window in dst.block_windows(1):
                data = dst.read(1, window=window)
                dst.write(_apply_burn_reclass_block(data), 1, window=window)

    # =========================
    # 5) Ejecutar ATD
    # =========================
    if os.path.isdir(atd_root):
        for year_name in sorted(os.listdir(atd_root)):
            year_dir = os.path.join(atd_root, year_name)
            if not os.path.isdir(year_dir):
                continue

            out_year_dir = os.path.join(output_folder, "atd", year_name)
            ensure_dir(out_year_dir)

            for q_folder in sorted(os.listdir(year_dir)):
                q_dir = os.path.join(year_dir, q_folder)
                if not os.path.isdir(q_dir):
                    continue

                out_final = os.path.join(out_year_dir, f"{q_folder}.tif")
                if os.path.exists(out_final):
                    continue

                try:
                    found = _find_any_in_dir(q_dir)

                    if found["shp"]:
                        _rasterize_vector_to_ref(found["shp"], out_final)
                        log(f"[ATD] OK  SHP {year_name}/{q_folder} -> {out_final}")
                        continue

                    if found["kml"] or found["kmz"]:
                        if OGR2OGR is None:
                            log(f"[ATD] WARN: KML/KMZ encontrado pero sin ogr2ogr. Saltado: {q_dir}")
                            continue

                        with tempfile.TemporaryDirectory() as tmpdir:
                            if found["kmz"]:
                                src_kml = _extract_kmz_to_kml(found["kmz"], tmpdir)
                            else:
                                src_kml = found["kml"]

                            geojson = os.path.join(tmpdir, "tmp.geojson")
                            _ogr2ogr_to_geojson(src_kml, geojson)

                            _rasterize_vector_to_ref(geojson, out_final)
                            log(f"[ATD] OK  KML/KMZ {year_name}/{q_folder} -> {out_final}")
                            continue

                    log(f"[ATD] WARN: no encontré .shp/.kml/.kmz en {q_dir}")

                except Exception as e:
                    log(f"[ATD] ERROR en {year_name}/{q_folder}: {e}")
                    traceback.print_exc()

    # =========================
    # 6) Ejecutar NAD
    # =========================
    if os.path.isdir(nad_root):
        for year_name in sorted(os.listdir(nad_root)):
            year_dir = os.path.join(nad_root, year_name)
            if not os.path.isdir(year_dir):
                continue

            out_year_dir = os.path.join(output_folder, "nad", year_name)
            ensure_dir(out_year_dir)

            for q_folder in sorted(os.listdir(year_dir)):
                q_dir = os.path.join(year_dir, q_folder)
                if not os.path.isdir(q_dir):
                    continue

                tifs = _collect_files(q_dir, (".tif", ".tiff"))
                if not tifs:
                    log(f"[NAD] WARN: no encontré .tif en {q_dir}")
                    continue

                for src_tif in tifs:
                    out_final = os.path.join(out_year_dir, os.path.basename(src_tif))
                    if os.path.exists(out_final):
                        continue

                    try:
                        _reproject_raster_to_ref(src_tif, out_final)
                        log(f"[NAD] OK  {year_name}/{q_folder} -> {out_final}")
                    except Exception as e:
                        log(f"[NAD] ERROR con {src_tif}: {e}")
                        traceback.print_exc()


if __name__ == "__main__":
    path_input = r"D:\OneDrive - CGIAR\Desktop\ganabosques\ganabosques_results\01_etl_deforestation\atd_nad_brutos"
    output_folder = r"D:\OneDrive - CGIAR\Desktop\ganabosques\ganabosques_results\01_etl_deforestation\rasters_atd_nad_brutos"
    spatial_info(path_input, output_folder)
