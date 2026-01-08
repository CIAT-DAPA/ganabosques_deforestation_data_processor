# save_deforestation.py
# =====================================================================
# Publicar/actualizar mosaicos SMBYC (annual + cumulative) en GeoServer
# USANDO indexer.properties y timeregex.properties EXTERNOS
#
# Estructura esperada de salida (Paso 4):
#   output_path_deforestation/
#     smbyc_deforestation_annual/*.tif
#     smbyc_deforestation_cumulative/*.tif
#
# Properties externas esperadas:
#   src/tools/utils/properties/
#     indexer.properties
#     timeregex.properties
#
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

from pymongo import MongoClient

from geoserver.catalog import Catalog
from geoserver.support import DimensionInfo

from tools.log_print import log_print
from config import config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers generales
# ──────────────────────────────────────────────────────────────────────────────
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


def _list_tifs(folder: str):
    if not os.path.isdir(folder):
        return []
    return sorted(glob.glob(os.path.join(folder, "*.tif")))


def _check_external_properties(props_dir: str):
    idx = os.path.join(props_dir, "indexer.properties")
    trg = os.path.join(props_dir, "timeregex.properties")
    if not os.path.isfile(idx):
        raise FileNotFoundError(f"indexer.properties no encontrado en: {props_dir}")
    if not os.path.isfile(trg):
        raise FileNotFoundError(f"timeregex.properties no encontrado en: {props_dir}")
    return idx, trg


def _zip_tifs_and_props(src_folder: str, props_dir: str, tmp_dir: str, zip_dir: str, zip_name: str):
    """
    ZIP con: todos los .tif + indexer.properties + timeregex.properties
    (para crear el mosaico con time indexado desde filename)
    """
    tifs = _list_tifs(src_folder)
    if not tifs:
        log_print(logger, f"❌ No hay .tif en {src_folder}", level="error")
        return None

    idx_path, trg_path = _check_external_properties(props_dir)

    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)

    # copiar tifs
    for t in tifs:
        shutil.copyfile(t, os.path.join(tmp_dir, os.path.basename(t)))

    # copiar properties
    shutil.copyfile(idx_path, os.path.join(tmp_dir, "indexer.properties"))
    shutil.copyfile(trg_path, os.path.join(tmp_dir, "timeregex.properties"))

    zip_fullpath = os.path.join(zip_dir, zip_name)
    with ZipFile(zip_fullpath, "w") as z:
        for f in glob.glob(os.path.join(tmp_dir, "*")):
            z.write(f, os.path.basename(f))

    shutil.rmtree(tmp_dir, ignore_errors=True)
    log_print(logger, f"📦 ZIP TIF+PROPS generado: {zip_fullpath}")
    return zip_fullpath


def _zip_tifs_only(src_folder: str, tmp_dir: str, zip_dir: str, zip_name: str):
    """
    ZIP solo con TIFs (para harvest_uploadgranule).
    """
    tifs = _list_tifs(src_folder)
    if not tifs:
        log_print(logger, f"❌ No hay .tif en {src_folder}", level="error")
        return None

    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs(zip_dir, exist_ok=True)

    for t in tifs:
        shutil.copyfile(t, os.path.join(tmp_dir, os.path.basename(t)))

    zip_fullpath = os.path.join(zip_dir, zip_name)
    with ZipFile(zip_fullpath, "w") as z:
        for f in glob.glob(os.path.join(tmp_dir, "*.tif")):
            z.write(f, os.path.basename(f))

    shutil.rmtree(tmp_dir, ignore_errors=True)
    log_print(logger, f"📦 ZIP solo TIF generado: {zip_fullpath}")
    return zip_fullpath


# ──────────────────────────────────────────────────────────────────────────────
# Mongo helpers (ADICIÓN)
# ──────────────────────────────────────────────────────────────────────────────
def _connect_mongo():
    mongo_uri = config.get("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = config.get("MONGO_DB_NAME", "ganabosques")
    log_print(logger, f"[Mongo] Conectando a {mongo_uri} / DB={mongo_db}")
    client = MongoClient(mongo_uri)
    return client[mongo_db]


def _parse_period_from_filename(filename: str):
    """
    Extrae period_start y period_end desde un nombre tipo:
      smbyc_deforestation_annual_2010-01-01-2012-01-01.tif
      smbyc_deforestation_cumulative_2010-01-01-2013-01-01.tif

    Devuelve (datetime_inicio, datetime_fin).
    """
    base = os.path.basename(filename)
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})", base)
    if not m:
        raise ValueError(f"No se pudo extraer rango de fechas desde '{base}'")

    start_dt = datetime.strptime(m.group(1), "%Y-%m-%d")
    end_dt = datetime.strptime(m.group(2), "%Y-%m-%d")
    return start_dt, end_dt


def _build_wcs_base_url(geo_base_url: str, workspace: str, store_name: str) -> str:
    """
    URL base WCS (sin subset de tiempo)
    """
    geo = (geo_base_url or "").rstrip("/")
    ws = (workspace or "").strip("/")
    return (
        f"{geo}/{ws}/ows?"
        "service=WCS&version=2.0.1&request=GetCoverage"
        f"&coverageId={store_name}&format=image/geotiff"
    )


def _save_mosaic_records_to_mongo(rasters_dir: str, store_name: str, source_value: str):
    """
    Recorre los TIF de rasters_dir y hace upsert en colección 'deforestation'.

    Guarda:
      - deforestation_source: source_value (ej: "smbyc")
      - deforestation_type: store_name (ej: "smbyc_deforestation_annual")
      - name: tif sin extensión
      - period_start / period_end: desde el nombre
      - path: URL base WCS
      - log.enable / log.created / log.updated
    """
    if not os.path.isdir(rasters_dir):
        log_print(logger, f"[Mongo] Carpeta no encontrada, se omite: {rasters_dir}", level="warning")
        return

    db = _connect_mongo()
    coll = db["deforestation"]

    geo_base_url = config.get("URL_GEO", "http://localhost:8600/geoserver")
    workspace = config.get("GEO_WORKSPACE", "deforestation")
    wcs_path = _build_wcs_base_url(geo_base_url, workspace, store_name)

    tifs = _list_tifs(rasters_dir)
    if not tifs:
        log_print(logger, f"[Mongo] ⚠ No se encontraron TIF en {rasters_dir}", level="warning")
        return

    now = datetime.utcnow()
    store_lower = (store_name or "").lower()

    for tif_path in tifs:
        fname = os.path.basename(tif_path)
        name_no_ext, _ = os.path.splitext(fname)

        try:
            period_start, period_end = _parse_period_from_filename(fname)
        except Exception as e:
            log_print(logger, f"[Mongo] ❌ No se pudo parsear fechas para '{fname}': {e}", level="error")
            continue

        filter_doc = {
            "deforestation_source": source_value,
            "deforestation_type": store_lower,
            "name": name_no_ext,
        }

        update_doc_set = {
            "deforestation_source": source_value,
            "deforestation_type": store_lower,
            "name": name_no_ext,
            "period_start": period_start,
            "period_end": period_end,
            "path": wcs_path,
            "log.enable": True,
            "log.updated": now,
        }

        update_doc_on_insert = {
            "log.created": now,
        }

        try:
            result = coll.update_one(
                filter_doc,
                {"$set": update_doc_set, "$setOnInsert": update_doc_on_insert},
                upsert=True,
            )
            if result.upserted_id is not None:
                log_print(logger, f"[Mongo] Registro creado: {name_no_ext}")
            else:
                log_print(logger, f"[Mongo] Registro actualizado: {name_no_ext}")
        except Exception as e:
            log_print(logger, f"[Mongo] ❌ Error guardando '{name_no_ext}': {e}", level="error")

    log_print(logger, f"[Mongo] ✅ Registros guardados para store={store_name}")


# ──────────────────────────────────────────────────────────────────────────────
# Cliente GeoServer
# ──────────────────────────────────────────────────────────────────────────────
class GeoserverClient:
    def __init__(self, url: str, user: str, pwd: str):
        self.url = url
        self.user = user
        self.pwd = pwd
        self.catalog = None
        self.workspace = None
        self.workspace_name = ""

    def connect(self):
        try:
            self.catalog = Catalog(self.url, username=self.user, password=self.pwd)
            log_print(logger, "✅ Conectado a GeoServer (REST).")
        except Exception as err:
            log_print(logger, f"❌ Error conectando a GeoServer: {err}", level="error")
            sys.exit(1)

    def get_workspace(self, name: str):
        self.workspace = self.catalog.get_workspace(name)
        self.workspace_name = name
        if not self.workspace:
            log_print(logger, f"❌ Workspace no encontrado: {name}", level="error")
            sys.exit(1)
        log_print(logger, f"Workspace encontrado: {name}")

    def get_store(self, store_name: str):
        if not self.workspace:
            return None
        try:
            return self.catalog.get_store(store_name, self.workspace)
        except Exception:
            return None

    def _enable_time_dimension(self, store_name: str):
        """
        Habilita dimensión TIME en el coverage del store.
        (Los valores de time vienen del indexer/timeregex del mosaico)
        """
        try:
            coverage = self.catalog.get_resource(store_name, workspace=self.workspace)
            if not coverage:
                log_print(logger, f"⚠ Coverage no encontrado para {store_name}", level="warning")
                return

            tinfo = DimensionInfo("time", True, "LIST", None, "ISO8601", None)
            md = coverage.metadata or {}
            md["time"] = tinfo
            coverage.metadata = md
            self.catalog.save(coverage)
            log_print(logger, f"🕒 Dimensión TIME habilitada en {store_name}")
        except Exception as e:
            log_print(logger, f"⚠ No se pudo habilitar TIME en {store_name}: {e}", level="warning")

    def create_mosaic(self, store_name: str, rasters_dir: str, props_dir: str, tmp_dir: str, zip_dir: str):
        """
        Crea ImageMosaic usando ZIP (TIF + PROPS).
        """
        zip_path = _zip_tifs_and_props(
            rasters_dir,
            props_dir,
            tmp_dir=os.path.join(tmp_dir, f"{store_name}_tmp_create"),
            zip_dir=os.path.join(zip_dir, f"{store_name}_zip_create"),
            zip_name="mosaic.zip",
        )
        if not zip_path:
            return

        try:
            self.catalog.create_imagemosaic(store_name, zip_path, workspace=self.workspace)
            log_print(logger, f"🧱 ImageMosaic creado: {store_name}")
        except Exception as e:
            log_print(logger, f"[GeoServer] Error en create_imagemosaic '{store_name}': {e}", level="error")
            return

        self._enable_time_dimension(store_name)

    def update_mosaic(self, store, rasters_dir: str, tmp_dir: str, zip_dir: str):
        """
        Actualiza mosaico existente usando harvest (ZIP solo TIF).
        """
        zip_path = _zip_tifs_only(
            rasters_dir,
            tmp_dir=os.path.join(tmp_dir, f"{store.name}_tmp_harvest"),
            zip_dir=os.path.join(zip_dir, f"{store.name}_zip_harvest"),
            zip_name="granules.zip",
        )
        if not zip_path:
            return

        try:
            self.catalog.harvest_uploadgranule(zip_path, store)
            log_print(logger, f"🔄 Mosaico '{store.name}' actualizado (harvest).")
        except Exception as e:
            log_print(logger, f"[GeoServer] Error en harvest_uploadgranule '{store.name}': {e}", level="error")
            return

        self._enable_time_dimension(store.name)


# ──────────────────────────────────────────────────────────────────────────────
# API principal usada por el main (Paso 5)
# ──────────────────────────────────────────────────────────────────────────────
def process_geoserver_mosaics(output_path_deforestation: str, source: str):
    """
    Publica/actualiza mosaicos 'annual' y 'cumulative' para la fuente dada (p.ej. 'SMBYC').

    - Usa properties EXTERNAS (indexer.properties + timeregex.properties).
    - Crea mosaico con ZIP(TIF+PROPS).
    - Si existe, actualiza con harvest ZIP(solo TIF).
    - ADICIÓN: guarda registros en Mongo (colección deforestation).
    """
    try:
        gs_url = _ensure_rest_url(config.get("URL_GEO") or "")
        username = config.get("GEO_USER")
        password = config.get("GEO_PWD")
        ws_name = config.get("GEO_WORKSPACE")

        if not all([gs_url, username, password, ws_name]):
            raise RuntimeError("Faltan variables en .env/config: URL_GEO, GEO_USER, GEO_PWD, GEO_WORKSPACE")

        src_lower = (source or "").lower()

        annual_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation_annual")
        cumulative_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation_cumulative")

        # ===== Properties EXTERNAS =====
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        props_dir = os.path.normpath(os.path.join(BASE_DIR, "..", "utils", "properties"))

        _check_external_properties(props_dir)
        log_print(logger, f"[GeoServer] PROPERTIES externas: {props_dir}")

        tmp_root = os.path.join(output_path_deforestation, "tmp_mosaic")
        zip_root = os.path.join(output_path_deforestation, "zip_mosaic")
        _create_dirs(tmp_root, zip_root)

        log_print(logger, "[GeoServer] Iniciando publicación/actualización de mosaicos...")

        geo = GeoserverClient(gs_url, username, password)
        geo.connect()
        geo.get_workspace(ws_name)

        # === ANUAL ===
        if os.path.isdir(annual_dir):
            store_annual = f"{src_lower}_deforestation_annual"
            store_obj = geo.get_store(store_annual)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_annual}")
                geo.update_mosaic(store_obj, annual_dir, tmp_root, zip_root)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_annual}")
                geo.create_mosaic(store_annual, annual_dir, props_dir, tmp_root, zip_root)

            # ===== ADICIÓN: guardar en Mongo =====
            _save_mosaic_records_to_mongo(annual_dir, store_annual, src_lower)

        else:
            log_print(logger, f"[GeoServer] Carpeta ANUAL no encontrada, se omite: {annual_dir}", level="warning")

        # === ACUMULADO ===
        if os.path.isdir(cumulative_dir):
            store_cum = f"{src_lower}_deforestation_cumulative"
            store_obj = geo.get_store(store_cum)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_cum}")
                geo.update_mosaic(store_obj, cumulative_dir, tmp_root, zip_root)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_cum}")
                geo.create_mosaic(store_cum, cumulative_dir, props_dir, tmp_root, zip_root)

            # ===== ADICIÓN: guardar en Mongo =====
            _save_mosaic_records_to_mongo(cumulative_dir, store_cum, src_lower)

        else:
            log_print(logger, f"[GeoServer] Carpeta ACUMULADA no encontrada, se omite: {cumulative_dir}", level="warning")

        log_print(logger, "[GeoServer] Publicación completada + Mongo actualizado.")

    except Exception as e:
        log_print(logger, f"[GeoServer] Error en publicación: {e}", level="error")
        # raise
