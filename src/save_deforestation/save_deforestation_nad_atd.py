# save_deforestation.py
# =====================================================================
# Publicar/actualizar mosaicos NAD / ATD en GeoServer
# USANDO indexer.properties y timeregex.properties EXTERNOS
# ubicados en:
#     src/tools/utils/properties/
# + Guardar registros en MongoDB (colección 'deforestation')
# =====================================================================

import os
import sys
import glob
import re
import shutil
import logging
from zipfile import ZipFile
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

from geoserver.catalog import Catalog
from geoserver.resource import Coverage
from geoserver.support import DimensionInfo

# ---------------------------------------------------------------------
# log_print + config
# ---------------------------------------------------------------------
try:
    from tools.log_print import log_print
except Exception:
    def log_print(logger, msg, level="info"):
        if level == "error":
            logger.error(msg)
        elif level == "warning":
            logger.warning(msg)
        else:
            logger.info(msg)
        print(msg)

try:
    from config import config
except Exception:
    class _Cfg:
        def get(self, key, default=None):
            return os.getenv(key, default)
    config = _Cfg()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# =====================================================================
# Helpers GENERALES
# =====================================================================

def _ensure_rest_url(url_geo: str) -> str:
    if not url_geo:
        return ""
    u = url_geo.strip().rstrip("/")
    if u.endswith("/geoserver/rest"):
        return u + "/"
    if u.endswith("/geoserver"):
        return u + "/rest/"
    if u.endswith("/rest"):
        return u + "/"
    return u + "/rest/"


def _create_dirs(*paths: str):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def _list_tifs(src_folder: str):
    if not os.path.isdir(src_folder):
        return []
    return sorted(glob.glob(os.path.join(src_folder, "*.tif")))


def _check_external_properties(props_dir: str):
    idx = os.path.join(props_dir, "indexer.properties")
    trg = os.path.join(props_dir, "timeregex.properties")

    if not os.path.isfile(idx):
        raise FileNotFoundError(f"indexer.properties no encontrado en {props_dir}")

    if not os.path.isfile(trg):
        raise FileNotFoundError(f"timeregex.properties no encontrado en {props_dir}")

    return idx, trg


# =====================================================================
# Helpers MONGO (conexión QUEMADA) — SIN ORM
# =====================================================================

from pymongo import MongoClient  # usamos PyMongo directo

MONGO_URI = "mongodb://localhost:27017"
MONGO_DB_NAME = "ganabosques"


def _connect_mongo():
    """
    Conexión quemada a MongoDB local (PyMongo, sin ORM).
    Devuelve el objeto de base de datos.
    """
    log_print(logger, f"[Mongo] Conectando a {MONGO_URI} / DB={MONGO_DB_NAME}")
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB_NAME]


def _parse_period_from_filename(filename: str):
    """
    Extrae period_start y period_end desde un nombre tipo:
      nad_2017-01-01-2017-03-30.tif
      atd_2017-01-01-2017-03-30.tif
    Devuelve (datetime_inicio, datetime_fin).
    """
    base = os.path.basename(filename)
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})", base)
    if not m:
        raise ValueError(f"No se pudo extraer rango de fechas desde '{base}'")

    start_str, end_str = m.group(1), m.group(2)
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    return start_dt, end_dt


def _build_wcs_base_url(geo_base_url: str, workspace: str, store_name: str) -> str:
    """
    Construye una URL base WCS GetCoverage SIN subset de tiempo, por ejemplo:
      http://localhost:8600/geoserver/deforestation/ows?service=WCS&version=2.0.1&request=GetCoverage&coverageId=nad&format=image/geotiff
    """
    geo = (geo_base_url or "").rstrip("/")
    ws = (workspace or "").strip("/")
    return (
        f"{geo}/{ws}/ows?"
        "service=WCS&version=2.0.1&request=GetCoverage"
        f"&coverageId={store_name}&format=image/geotiff"
    )


def _save_mosaic_records_to_mongo(rasters_dir: str, store_name: str):
    """
    Recorre los TIF de rasters_dir y crea/actualiza documentos en la colección 'deforestation'
    usando PyMongo directamente.

    Guardamos:
      - deforestation_source: "smbyc"  (lowercase)
      - deforestation_type: "nad" o "atd" (string), según el store_name
      - name: nombre del archivo TIF SIN extensión (ej. 'nad_2017-01-01-2017-03-30')
      - path: URL base WCS (sin subset de tiempo)
      - period_start / period_end: extraídos del nombre
      - log: { enable: true, created, updated }
    """
    if not os.path.isdir(rasters_dir):
        log_print(logger, f"[Mongo] Carpeta no encontrada, se omite: {rasters_dir}", level="warning")
        return

    db = _connect_mongo()
    coll = db["deforestation"]

    geo_base_url = config.get("URL_GEO", "http://localhost:8600/geoserver")
    workspace = config.get("GEO_WORKSPACE", "deforestation")

    # deforestation_source fijo (string, lowercase)
    deforestation_source_value = "smbyc"

    # deforestation_type como STRING según el store ("nad" / "atd")
    store_lower = store_name.lower()
    if store_lower in ("nad", "atd"):
        deforestation_type_value = store_lower
    else:
        deforestation_type_value = store_lower
        log_print(
            logger,
            f"[Mongo] ⚠ Store '{store_name}' no es 'nad' ni 'atd'; se guardará tal cual en deforestation_type='{deforestation_type_value}'",
            level="warning"
        )

    wcs_path = _build_wcs_base_url(geo_base_url, workspace, store_name)
    log_print(logger, f"[Mongo] WCS base URL para '{store_name}': {wcs_path}")

    tifs = _list_tifs(rasters_dir)
    if not tifs:
        log_print(logger, f"[Mongo] ⚠ No se encontraron TIF en {rasters_dir}", level="warning")
        return

    now = datetime.utcnow()

    for tif_path in tifs:
        fname = os.path.basename(tif_path)              # ej: "nad_2017-01-01-2017-03-30.tif"
        name_no_ext, _ = os.path.splitext(fname)        # ej: "nad_2017-01-01-2017-03-30"

        try:
            period_start, period_end = _parse_period_from_filename(fname)
        except Exception as e:
            log_print(logger, f"[Mongo] ❌ No se pudo parsear fechas para '{fname}': {e}", level="error")
            continue

        # Filtro para identificar unívocamente el registro
        filter_doc = {
            "deforestation_source": deforestation_source_value,
            "deforestation_type": deforestation_type_value,
            "name": name_no_ext,
        }

        # Campos que siempre se actualizan
        update_doc_set = {
            "deforestation_source": deforestation_source_value,
            "deforestation_type": deforestation_type_value,  # "nad" o "atd"
            "name": name_no_ext,
            "period_start": period_start,
            "period_end": period_end,
            "path": wcs_path,
            "log.enable": True,
            "log.updated": now,
        }

        # Campos que solo se setean al crear (insert)
        update_doc_on_insert = {
            "log.created": now,
        }

        try:
            result = coll.update_one(
                filter_doc,
                {
                    "$set": update_doc_set,
                    "$setOnInsert": update_doc_on_insert,
                },
                upsert=True,
            )

            if result.upserted_id is not None:
                log_print(logger, f"[Mongo] Registro creado: {name_no_ext}")
            else:
                log_print(logger, f"[Mongo] Registro actualizado: {name_no_ext}")

        except Exception as e:
            log_print(logger, f"[Mongo] ❌ Error guardando '{name_no_ext}': {e}", level="error")


# =====================================================================
# ZIP con TIF + PROPERTIES
# =====================================================================

def _zip_tifs_and_props(src_folder: str, props_dir: str,
                        tmp_dir: str, zip_dir: str, zip_name: str):

    print("\n===== DEBUG ZIP TIF + PROPERTIES =====")
    print("SRC_FOLDER:", src_folder)
    print("PROPS_DIR:", props_dir)
    print("TMP_DIR:", tmp_dir)
    print("ZIP_DIR:", zip_dir)

    tifs = _list_tifs(src_folder)
    print("TIFs encontrados:", tifs)

    if not tifs:
        log_print(logger, f"❌ No hay .tif en {src_folder}", level="error")
        return None

    idx_path, trg_path = _check_external_properties(props_dir)

    print("indexer.properties path:", idx_path)
    print("timeregex.properties path:", trg_path)

    print("\n--- indexer.properties ---")
    with open(idx_path, "r", encoding="utf-8") as f:
        print(f.read())

    print("\n--- timeregex.properties ---")
    with open(trg_path, "r", encoding="utf-8") as f:
        print(f.read())
    print("--------------------------\n")

    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)

    # copiar tif
    for t in tifs:
        dst = os.path.join(tmp_dir, os.path.basename(t))
        shutil.copyfile(t, dst)
        print("Copiado TIF:", dst)

    # copiar properties externas
    idx_tmp = os.path.join(tmp_dir, "indexer.properties")
    trg_tmp = os.path.join(tmp_dir, "timeregex.properties")
    shutil.copyfile(idx_path, idx_tmp)
    shutil.copyfile(trg_path, trg_tmp)
    print("Copiado PROP:", idx_tmp)
    print("Copiado PROP:", trg_tmp)

    zip_fullpath = os.path.join(zip_dir, zip_name)
    print("\nArchivos que van al ZIP:")
    with ZipFile(zip_fullpath, "w") as z:
        for f in glob.glob(os.path.join(tmp_dir, "*")):
            print("  +", os.path.basename(f))
            z.write(f, os.path.basename(f))

    print("ZIP creado en:", zip_fullpath)
    print("===== FIN DEBUG ZIP =====\n")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    log_print(logger, f"ZIP TIF+PROPS: {zip_fullpath}")
    return zip_fullpath


# ------------------------ ZIP solo PROPERTIES ------------------------

def _zip_props_only(props_dir: str, tmp_dir: str, zip_dir: str, zip_name: str):

    idx_path, trg_path = _check_external_properties(props_dir)

    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)

    shutil.copyfile(idx_path, os.path.join(tmp_dir, "indexer.properties"))
    shutil.copyfile(trg_path, os.path.join(tmp_dir, "timeregex.properties"))

    zip_fullpath = os.path.join(zip_dir, zip_name)
    with ZipFile(zip_fullpath, "w") as z:
        z.write(os.path.join(tmp_dir, "indexer.properties"), "indexer.properties")
        z.write(os.path.join(tmp_dir, "timeregex.properties"), "timeregex.properties")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    log_print(logger, f"ZIP SOLO PROPS: {zip_fullpath}")
    return zip_fullpath


# =====================================================================
# Cliente GeoServer
# =====================================================================

class GeoserverClient:

    def __init__(self, url: str, user: str, pwd: str):
        self.url = _ensure_rest_url(url)
        self.user = user
        self.pwd = pwd
        self.catalog = None
        self.workspace = None
        self.workspace_name = ""

        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(user, pwd)

    def connect(self):
        try:
            self.catalog = Catalog(self.url, username=self.user, password=self.pwd)
            log_print(logger, "✅ Conectado a GeoServer")
        except Exception as e:
            log_print(logger, f"❌ Error conectando a GeoServer: {e}", level="error")
            sys.exit(1)

    def get_workspace(self, name: str):
        self.workspace = self.catalog.get_workspace(name)
        self.workspace_name = name
        if not self.workspace:
            log_print(logger, f"❌ Workspace no encontrado: {name}", level="error")
            sys.exit(1)
        log_print(logger, f"Workspace OK: {name}")

    # subir zip por REST
    def _rest_post_zip(self, endpoint: str, zip_path: str):
        with open(zip_path, "rb") as f:
            r = self.session.post(
                endpoint, data=f,
                headers={"Content-Type": "application/zip"},
                timeout=600
            )
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"REST ZIP error {r.status_code}: {r.text[:500]}")
        return r

    # habilitar dimensión TIME
    def _enable_time_dimension(self, store_name: str):
        """
        Habilita la dimensión 'time' en el coverage asociado al store.
        Compatible con la firma actual de DimensionInfo.
        """
        try:
            coverage = self.catalog.get_resource(store_name, workspace=self.workspace)
            if not coverage:
                log_print(logger, f"⚠ Coverage no encontrado para {store_name}", level="warning")
                return

            # DimensionInfo(name, enabled, presentation, resolution, units, unit_symbol)
            tinfo = DimensionInfo(
                "time",      # name
                True,        # enabled
                "LIST",      # presentation
                None,        # resolution
                "ISO8601",   # units
                None         # unit_symbol
            )

            md = coverage.metadata or {}
            md["time"] = tinfo
            coverage.metadata = md
            self.catalog.save(coverage)

            log_print(logger, f"🕒 Dimensión TIME habilitada en {store_name}")

        except Exception as e:
            log_print(logger, f"⚠ No se pudo habilitar TIME: {e}", level="warning")

    # ---------------------- CREAR / ACTUALIZAR MOSAICO ----------------------

    def create_or_update_mosaic(self, store_name: str, src_folder: str,
                                props_dir: str, tmp_root: str, zip_root: str):

        log_print(logger, f"== Procesando mosaic '{store_name}' ==")

        if not os.path.isdir(src_folder):
            log_print(logger, f"⚠ Carpeta no encontrada: {src_folder}", level="warning")
            return

        try:
            existing = self.catalog.get_store(store_name, workspace=self.workspace)
        except Exception:
            existing = None

        # ---- SI NO EXISTE: crear mosaico con TIF + PROPERTIES
        if existing is None:
            tif_zip = _zip_tifs_and_props(
                src_folder, props_dir,
                os.path.join(tmp_root, f"{store_name}_tmp"),
                os.path.join(zip_root, f"{store_name}_zip"),
                "mosaic.zip"
            )
            if not tif_zip:
                return

            try:
                self.catalog.create_imagemosaic(store_name, tif_zip, workspace=self.workspace)
                log_print(logger, f"🧱 Mosaico creado: {store_name}")
            except Exception as e:
                log_print(logger, f"GeoServer create_imagemosaic falló, usando REST: {e}", level="warning")
                endpoint = (
                    f"{self.url}workspaces/{self.workspace_name}/coveragestores/{store_name}"
                    f"/file.imagemosaic?configure=first&coverageName={store_name}"
                )
                self._rest_post_zip(endpoint, tif_zip)
                log_print(logger, f"🧱 Mosaico creado vía REST: {store_name}")

        else:
            # ---- SI EXISTE: actualizar solo las PROPERTIES
            props_zip = _zip_props_only(
                props_dir,
                os.path.join(tmp_root, f"{store_name}_props_tmp"),
                os.path.join(zip_root, f"{store_name}_props_zip"),
                "props.zip"
            )
            endpoint = (
                f"{self.url}workspaces/{self.workspace_name}/coveragestores/{store_name}/file.imagemosaic?configure=none"
            )
            self._rest_post_zip(endpoint, props_zip)
            log_print(logger, f"📦 PROPERTIES actualizadas para '{store_name}'")

        log_print(logger, "ℹ HARVEST automático omitido (reindexar manual si agregas nuevos TIF).")
        self._enable_time_dimension(store_name)


# =====================================================================
#   FUNCIÓN PRINCIPAL — USADA POR main.py step 5
# =====================================================================

def process_geoserver_mosaics(output_path_deforestation: str, source: str):

    # ------------------ leer config ------------------
    gs_url = config.get("URL_GEO", "")
    username = config.get("GEO_USER")
    password = config.get("GEO_PWD")
    ws_name = config.get("GEO_WORKSPACE")

    if not all([gs_url, username, password, ws_name]):
        log_print(logger, "❌ Faltan variables GeoServer en config/.env", level="error")
        return

    # ------------------ carpetas NAD/ATD ------------------
    nad_dir = os.path.join(output_path_deforestation, "nad")
    atd_dir = os.path.join(output_path_deforestation, "atd")

    # ------------------ properties externas ------------------
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    props_dir = os.path.join(BASE_DIR)

    log_print(logger, f"[GeoServer] PROPERTIES_DIR = {props_dir}")

    # ------------------ carpetas temporales ------------------
    tmp_root = os.path.join(output_path_deforestation, "tmp_mosaic")
    zip_root = os.path.join(output_path_deforestation, "zip_mosaic")
    _create_dirs(tmp_root, zip_root)

    # ------------------ conexión ------------------
    geo = GeoserverClient(gs_url, username, password)
    geo.connect()
    geo.get_workspace(ws_name)

    # ------------------ publicar NAD ------------------
    if os.path.isdir(nad_dir):
        geo.create_or_update_mosaic("nad", nad_dir, props_dir, tmp_root, zip_root)
        # 👉 Guardar/actualizar en Mongo
        _save_mosaic_records_to_mongo(nad_dir, "nad")
    else:
        log_print(logger, f"⚠ Carpeta NAD no encontrada: {nad_dir}", level="warning")

    # ------------------ publicar ATD ------------------
    if os.path.isdir(atd_dir):
        geo.create_or_update_mosaic("atd", atd_dir, props_dir, tmp_root, zip_root)
        # 👉 Guardar/actualizar en Mongo
        _save_mosaic_records_to_mongo(atd_dir, "atd")
    else:
        log_print(logger, f"⚠ Carpeta ATD no encontrada: {atd_dir}", level="warning")

    log_print(logger, "✔ Flujo de mosaicos NAD/ATD + Mongo finalizado.")
