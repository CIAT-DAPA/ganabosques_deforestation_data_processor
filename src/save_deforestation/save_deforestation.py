# save_deforestation.py
# =====================================================================
# Publicar/actualizar mosaicos (annual + cumulative) en GeoServer
# USANDO indexer.properties y timeregex.properties EXTERNOS
#
# Estructura esperada de salida:
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
#
# CAMBIO IMPORTANTE (formatos nuevos):
# - Antes: _2010-01-01-2012-01-01.tif  (YYYY-MM-DD)
# - Ahora: _20100101-20120101.tif      (YYYYMMDD)
#   -> Se ajusta el parser de fechas para Mongo.
#   -> Se agrega verificación/advertencia sobre timeregex.properties.
# =====================================================================

import os
import sys
import glob
import re
import shutil
import logging
from zipfile import ZipFile
from datetime import datetime, date
from typing import Optional, Tuple

from mongoengine import connect

from geoserver.catalog import Catalog
from geoserver.support import DimensionInfo

from ganabosques_orm.collections.deforestation import Deforestation
from ganabosques_orm.enums.deforestationtype import DeforestationType
from ganabosques_orm.enums.deforestationsource import DeforestationSource
from ganabosques_orm.auxiliaries.log import Log

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


def _read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _check_external_properties(props_dir: str):
    idx = os.path.join(props_dir, "indexer.properties")
    trg = os.path.join(props_dir, "timeregex.properties")
    if not os.path.isfile(idx):
        raise FileNotFoundError(f"indexer.properties no encontrado en: {props_dir}")
    if not os.path.isfile(trg):
        raise FileNotFoundError(f"timeregex.properties no encontrado en: {props_dir}")

    # Advertencia útil por el cambio de formato de nombres (YYYYMMDD)
    trg_txt = _read_text_file(trg)
    # Si el regex contiene patrones con guiones, probablemente no matchea YYYYMMDD
    if re.search(r"\d\{4\}-\d\{2\}-\d\{2\}", trg_txt) or re.search(r"\d{4}-\d{2}-\d{2}", trg_txt):
        log_print(
            logger,
            "[GeoServer] ⚠ timeregex.properties parece estar configurado para fechas con guiones "
            "(YYYY-MM-DD). Tus archivos actuales son YYYYMMDD. Revisa regex/format.",
            level="warning",
        )
    else:
        # Si detectamos \d{8} es buena señal para YYYYMMDD
        if re.search(r"\\d\{8\}", trg_txt) or re.search(r"\d{8}", trg_txt):
            log_print(logger, "[GeoServer] timeregex.properties parece compatible con YYYYMMDD.")

        # Si detectamos \d{8} es buena señal para YYYYMM
        if re.search(r"\\d\{6\}", trg_txt) or re.search(r"\d{6}", trg_txt):
            log_print(logger, "[GeoServer] timeregex.properties parece compatible con YYYYMM.")

        else:
            log_print(
                logger,
                "[GeoServer] ⚠ No pude inferir el formato en timeregex.properties. "
                "Asegúrate que el regex capture la fecha y tenga format=yyyyMMdd si aplica.",
                level="warning",
            )

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
# Mongo helpers
# ──────────────────────────────────────────────────────────────────────────────
def _parse_period_from_filename(filename: str) -> Tuple[date, date]:
    """
    Extrae period_start y period_end desde nombres tipo:

      Formatos soportados:
        - Trimestral NAD/ATD: nad_deforestation_201701.tif (YYYYQQ)
        - Anual SMBYC simple: smbyc_deforestation_annual_2013.tif (YYYY)
        - Rango SMBYC: smbyc_deforestation_annual_2010-2012.tif (YYYY-YYYY)
        - Formato fecha completa: smbyc_deforestation_annual_20100101-20120101.tif (YYYYMMDD-YYYYMMDD)
        - Formato legacy: smbyc_deforestation_annual_2010-01-01-2012-01-01.tif (YYYY-MM-DD-YYYY-MM-DD)

    Devuelve (date_inicio, date_fin).
    """
    base = os.path.basename(filename)

    # 1. Formato TRIMESTRAL: _YYYYQQ.tif (NAD/ATD)
    m = re.search(r"_(\d{4})(\d{2})\.tif$", base)
    if m:
        year = int(m.group(1))
        quarter = int(m.group(2))
        
        # Mapeo de trimestre a fechas
        quarter_dates = {
            1: (1, 1, 3, 31),  # Q1: Enero 1 - Marzo 31
            2: (4, 1, 6, 30),  # Q2: Abril 1 - Junio 30
            3: (7, 1, 9, 30),  # Q3: Julio 1 - Septiembre 30
            4: (10, 1, 12, 31),  # Q4: Octubre 1 - Diciembre 31
        }
        
        if quarter in quarter_dates:
            start_m, start_d, end_m, end_d = quarter_dates[quarter]
            start_dt = date(year, start_m, start_d)
            end_dt = date(year, end_m, end_d)
            return start_dt, end_dt

    # 2. Formato ANUAL SIMPLE: _YYYY.tif (SMBYC anual)
    m = re.search(r"_(\d{4})\.tif$", base)
    if m:
        year = int(m.group(1))
        start_dt = date(year, 1, 1)
        end_dt = date(year, 12, 31)
        return start_dt, end_dt

    # 3. Formato RANGO AÑOS: _YYYY-YYYY.tif (SMBYC 2010-2012)
    m = re.search(r"_(\d{4})-(\d{4})\.tif$", base)
    if m:
        start_year = int(m.group(1))
        end_year = int(m.group(2))
        start_dt = date(start_year, 1, 1)
        end_dt = date(end_year, 12, 31)
        return start_dt, end_dt

    # 4. Formato YYYYMMDD-YYYYMMDD.tif
    m = re.search(r"_(\d{8})-(\d{8})\.tif$", base)
    if m:
        start_dt = datetime.strptime(m.group(1), "%Y%m%d").date()
        end_dt = datetime.strptime(m.group(2), "%Y%m%d").date()
        return start_dt, end_dt

    # 5. Formato LEGACY: _YYYY-MM-DD-YYYY-MM-DD.tif
    m = re.search(r"_(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})\.tif$", base)
    if m:
        start_dt = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        end_dt = datetime.strptime(m.group(2), "%Y-%m-%d").date()
        return start_dt, end_dt

    raise ValueError(f"No se pudo extraer rango de fechas desde '{base}'")

def _save_mosaic_records_to_mongo(rasters_dir: str, store_name: str, source_value: str):
    """
    Recorre los TIF de rasters_dir y hace upsert en colección 'deforestation' usando MongoEngine ORM.

    Guarda:
      - deforestation_source: DeforestationSource enum (ej: DeforestationSource.SMBYC)
      - deforestation_type: DeforestationType enum (ej: DeforestationType.ANNUAL)
      - name: tif sin extensión
      - period_start / period_end: datetime.date desde el nombre
      - path: nombre del store (ej: "nad_deforestation")
      - log.enable / log.created / log.updated
    """
    if not os.path.isdir(rasters_dir):
        log_print(logger, f"[Mongo] Carpeta no encontrada, se omite: {rasters_dir}", level="warning")
        return

    # Conectar MongoEngine usando config
    connect(
        db=config['MONGO_DB_NAME'],
        host=config['MONGO_URI']
    )

    # Normalizar store_name para consistencia
    store_name_norm = (store_name or "").lower().strip()

    # Determinar deforestation_type basado en el nombre del store
    if "annual" in store_name_norm:
        deforestation_type = DeforestationType.ANNUAL
    elif "cumulative" in store_name_norm:
        deforestation_type = DeforestationType.CUMULATIVE
    else:
        deforestation_type = DeforestationType.QUARTERLY

    # Determinar deforestation_source
    source_lower = source_value.lower().strip()
    try:
        deforestation_source = DeforestationSource[source_lower.upper()]
    except KeyError:
        log_print(logger, f"[Mongo] ⚠ Fuente desconocida: {source_value}", level="warning")
        return

    tifs = _list_tifs(rasters_dir)
    if not tifs:
        log_print(logger, f"[Mongo] ⚠ No se encontraron TIF en {rasters_dir}", level="warning")
        return

    now = datetime.utcnow()

    for tif_path in tifs:
        fname = os.path.basename(tif_path)
        name_no_ext, _ = os.path.splitext(fname)

        try:
            period_start, period_end = _parse_period_from_filename(fname)
        except Exception as e:
            log_print(logger, f"[Mongo] ❌ No se pudo parsear fechas para '{fname}': {e}", level="error")
            continue

        try:
            # Buscar registro existente usando MongoEngine
            existing = Deforestation.objects(
                name=name_no_ext,
                period_start=period_start,
                period_end=period_end,
                deforestation_type=deforestation_type,
                deforestation_source=deforestation_source
            ).first()

            if existing:
                # Actualizar registro existente
                existing.path = store_name_norm
                if existing.log:
                    existing.log.updated = now
                else:
                    existing.log = Log(enable=True, created=now, updated=now)
                existing.save()
                log_print(logger, f"[Mongo] Registro actualizado: {name_no_ext}")
            else:
                # Crear nuevo registro
                log_obj = Log(enable=True, created=now, updated=now)
                defo = Deforestation(
                    deforestation_source=deforestation_source,
                    deforestation_type=deforestation_type,
                    name=name_no_ext,
                    period_start=period_start,
                    period_end=period_end,
                    path=store_name_norm,
                    log=log_obj
                )
                defo.save()
                log_print(logger, f"[Mongo] Registro creado: {name_no_ext}")

        except Exception as e:
            log_print(logger, f"[Mongo] ❌ Error guardando '{name_no_ext}': {e}", level="error")

    log_print(logger, f"[Mongo] ✅ Registros guardados para store={store_name_norm}")


# ──────────────────────────────────────────────────────────────────────────────
# Cliente GeoServer
# ──────────────────────────────────────────────────────────────────────────────
class GeoserverClient:
    def __init__(self, url: str, user: str, pwd: str):
        self.url = url
        self.user = user
        self.pwd = pwd
        self.catalog: Optional[Catalog] = None
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
        if not self.catalog:
            raise RuntimeError("Catálogo de GeoServer no inicializado.")
        self.workspace = self.catalog.get_workspace(name)
        self.workspace_name = name
        if not self.workspace:
            log_print(logger, f"❌ Workspace no encontrado: {name}", level="error")
            sys.exit(1)
        log_print(logger, f"Workspace encontrado: {name}")

    def get_store(self, store_name: str):
        if not self.workspace or not self.catalog:
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
        if not self.catalog:
            return
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
        if not self.catalog:
            raise RuntimeError("Catálogo de GeoServer no inicializado.")

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
        if not self.catalog:
            raise RuntimeError("Catálogo de GeoServer no inicializado.")

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
# API principal usada por el main
# ──────────────────────────────────────────────────────────────────────────────
def process_geoserver_mosaics(output_path_deforestation: str, source: str):
    """
    Publica/actualiza mosaicos 'annual' y 'cumulative' para la fuente dada (p.ej. 'SMBYC').

    - Usa properties EXTERNAS (indexer.properties + timeregex.properties).
    - Crea mosaico con ZIP(TIF+PROPS).
    - Si existe, actualiza con harvest ZIP(solo TIF).
    - Guarda registros en Mongo (colección deforestation) con period_start/period_end parseado.
    """
    try:
        gs_url = _ensure_rest_url(config.get("URL_GEO") or "")
        username = config.get("GEO_USER")
        password = config.get("GEO_PWD")
        ws_name = config.get("GEO_WORKSPACE")

        if not all([gs_url, username, password, ws_name]):
            raise RuntimeError("Faltan variables en .env/config: URL_GEO, GEO_USER, GEO_PWD, GEO_WORKSPACE")

        src_lower = (source or "").lower().strip()

        annual_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation_annual")
        cumulative_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation_cumulative")
        
        general_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation")

        # ===== Properties EXTERNAS =====
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        utils_dir = os.path.normpath(os.path.join(BASE_DIR, "..", "utils"))

        # Buscar carpeta de propiedades que contenga el source
        # (ej: si source="nad", busca "properties_nad_atd" o "properties_nad")
        props_dir = None
        if os.path.isdir(utils_dir):
            for folder in os.listdir(utils_dir):
                folder_path = os.path.join(utils_dir, folder)
                if os.path.isdir(folder_path) and folder.startswith("properties_") and src_lower in folder:
                    props_dir = folder_path
                    break

        if not props_dir:
            raise FileNotFoundError(
                f"No se encontró carpeta de propiedades para source='{src_lower}' en {utils_dir}. "
                "Esperaba una carpeta del tipo 'properties_*' que contenga '{src_lower}'."
            )

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
            store_annual = f"{src_lower}_deforestation_annual".lower()
            store_obj = geo.get_store(store_annual)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_annual}")
                geo.update_mosaic(store_obj, annual_dir, tmp_root, zip_root)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_annual}")
                geo.create_mosaic(store_annual, annual_dir, props_dir, tmp_root, zip_root)

            # guardar en Mongo
            _save_mosaic_records_to_mongo(annual_dir, store_annual, src_lower)
        else:
            log_print(logger, f"[GeoServer] Carpeta ANUAL no encontrada, se omite: {annual_dir}", level="warning")

        # === ACUMULADO ===
        if os.path.isdir(cumulative_dir):
            store_cum = f"{src_lower}_deforestation_cumulative".lower()
            store_obj = geo.get_store(store_cum)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_cum}")
                geo.update_mosaic(store_obj, cumulative_dir, tmp_root, zip_root)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_cum}")
                geo.create_mosaic(store_cum, cumulative_dir, props_dir, tmp_root, zip_root)

            # guardar en Mongo
            _save_mosaic_records_to_mongo(cumulative_dir, store_cum, src_lower)
        else:
            log_print(logger, f"[GeoServer] Carpeta ACUMULADA no encontrada, se omite: {cumulative_dir}", level="warning")

        # === GENERAL (opcional) ===

        if os.path.isdir(general_dir):
            store_gen = f"{src_lower}_deforestation".lower()
            store_obj = geo.get_store(store_gen)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_gen}")
                geo.update_mosaic(store_obj, general_dir, tmp_root, zip_root)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_gen}")
                geo.create_mosaic(store_gen, general_dir, props_dir, tmp_root, zip_root)

            # guardar en Mongo
            _save_mosaic_records_to_mongo(general_dir, store_gen, src_lower)
        else:
            log_print(logger, f"[GeoServer] Carpeta GENERAL no encontrada, se omite: {general_dir}", level="warning")
        log_print(logger, "[GeoServer] Publicación completada + Mongo actualizado.")

    except Exception as e:
        log_print(logger, f"[GeoServer] Error en publicación: {e}", level="error")
        raise
