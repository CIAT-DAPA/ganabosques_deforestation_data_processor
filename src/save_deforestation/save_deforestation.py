# save_deforestation.py
# Paso 5: Publicar/actualizar mosaicos en GeoServer y guardar registros en MongoDB
import os
import sys
import glob
import re
import shutil
import logging
from zipfile import ZipFile
from datetime import datetime

from geoserver.catalog import Catalog
from geoserver.resource import Coverage
from geoserver.support import DimensionInfo

from mongoengine import connect
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
    """
    Normaliza URL_GEO para que termine en /rest/ (endpoint de gsconfig).
    Acepta:
      - https://host/geoserver
      - https://host/geoserver/
      - https://host/geoserver/rest
      - https://host/geoserver/rest/
    """
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


def _must_exist(path: str, what: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{what} no existe: {path}")


def _create_dirs(*paths: str):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def _write_file_if_missing(path: str, content: str):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def _ensure_properties(props_dir: str):
    """
    Garantiza que existan EXACTAMENTE estos contenidos si faltan:

      timeregex.properties:
        regex=(\d{4}-\d{4})

      indexer.properties:
        TimeAttribute=time
        Schema=*the_geom:Polygon,location:String,time:java.util.Date
        PropertyCollectors=TimestampFileNameExtractorSPI[timeregex](time)
    """
    _create_dirs(props_dir)

    indexer_path = os.path.join(props_dir, "indexer.properties")
    timeregex_path = os.path.join(props_dir, "timeregex.properties")

    indexer_content = (
        "TimeAttribute=time\n"
        "Schema=*the_geom:Polygon,location:String,time:java.util.Date\n"
        "PropertyCollectors=TimestampFileNameExtractorSPI[timeregex](time)\n"
    )
    timeregex_content = "regex=(\\d{4}-\\d{4})\n"

    _write_file_if_missing(indexer_path, indexer_content)
    _write_file_if_missing(timeregex_path, timeregex_content)

    return indexer_path, timeregex_path


def _extract_years_from_filename(filename: str):
    """
    Devuelve (year_start, year_end) buscando 'YYYY-YYYY' en el nombre del archivo.
    Si sólo encuentra un año, asume (year, year).
    Lanza ValueError si no encuentra ningún año.
    """
    m = re.search(r'(\d{4})[-_](\d{4})', filename)
    if m:
        return int(m.group(1)), int(m.group(2))
    m1 = re.search(r'(\d{4})', filename)
    if m1:
        y = int(m1.group(1))
        return y, y
    raise ValueError(f"No se pudieron extraer años desde el archivo: {filename}")


# ──────────────────────────────────────────────────────────────────────────────
# Cliente GeoServer integrado (sin dependencia externa)
# ──────────────────────────────────────────────────────────────────────────────
class GeoserverClient(object):
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
        if not self.catalog:
            log_print(logger, "❌ Catálogo no inicializado.", level="error")
            sys.exit(1)
        self.workspace = self.catalog.get_workspace(name)
        self.workspace_name = name
        if not self.workspace:
            log_print(logger, f"❌ Workspace no encontrado: {name}", level="error")
            sys.exit(1)
        log_print(logger, f"Workspace encontrado: {name}")

    def get_store(self, store_name: str):
        if not self.workspace:
            log_print(logger, "❌ Workspace no establecido.", level="error")
            return None
        try:
            return self.catalog.get_store(store_name, self.workspace)
        except Exception:
            return None

    def zip_files(self, folder: str, folder_properties: str, folder_tmp: str, zip_path: str):
        """
        Arma un ZIP con:
          - todos los *.properties (mínimo 2) de folder_properties
          - todos los *.tif de folder
        """
        if not (os.path.exists(folder) and os.path.exists(folder_properties)):
            log_print(logger, f"❌ Rutas inválidas. Datos: {folder} | Properties: {folder_properties}", level="error")
            return None

        if os.path.exists(folder_tmp):
            shutil.rmtree(folder_tmp)
        os.makedirs(folder_tmp, exist_ok=True)

        # Copiar .properties
        props = glob.glob(os.path.join(folder_properties, "*.properties"))
        if len(props) < 2:
            log_print(logger, "❌ Se esperaban al menos 2 archivos .properties (indexer y timeregex).", level="error")
            return None
        for p in props:
            shutil.copyfile(p, os.path.join(folder_tmp, os.path.basename(p)))

        # Copiar rásters (.tif)
        tifs = glob.glob(os.path.join(folder, "*.tif"))
        if not tifs:
            log_print(logger, f"❌ No se encontraron .tif en: {folder}", level="error")
            return None
        for t in tifs:
            shutil.copyfile(t, os.path.join(folder_tmp, os.path.basename(t)))

        os.makedirs(zip_path, exist_ok=True)
        zip_fullpath = os.path.join(zip_path, "mosaic.zip")
        with ZipFile(zip_fullpath, mode="w") as z:
            for f in glob.glob(os.path.join(folder_tmp, "*.*")):
                z.write(f, os.path.basename(f))

        log_print(logger, f"ZIP generado: {zip_fullpath}")
        return zip_fullpath

    def create_mosaic(self, store_name: str, file: str, folder_properties: str, folder_tmp: str, zip_path: str):
        output_zip = self.zip_files(file, folder_properties, folder_tmp, zip_path)
        if not output_zip:
            return

        # Limpieza del tmp tras empaquetar
        if os.path.exists(folder_tmp):
            shutil.rmtree(folder_tmp)

        # Crear ImageMosaic
        self.catalog.create_imagemosaic(store_name, output_zip, workspace=self.workspace)
        log_print(logger, f"🧱 ImageMosaic creado: {store_name}")

        # Habilitar dimensión temporal en la cobertura
        store = self.catalog.get_store(store_name, workspace=self.workspace)
        url = f"{self.url}workspaces/{self.workspace_name}/coveragestores/{store_name}/coverages/{store_name}.xml"
        xml = self.catalog.get_xml(url)
        name = xml.find("name").text
        coverage = Coverage(self.catalog, store=store, name=name, href=url, workspace=self.workspace)

        coverage.supported_formats = ["GEOTIFF"]
        time_info = DimensionInfo(
            name="time", enabled="true", presentation="LIST",
            resolution=None, units="ISO8601", unit_symbol=None
        )
        coverage.metadata = {"time": time_info}
        self.catalog.save(coverage)
        log_print(logger, "🕒 Dimensión temporal habilitada.")

    def update_mosaic(self, store, file: str, folder_properties: str, folder_tmp: str, zip_path: str):
        output_zip = self.zip_files(file, folder_properties, folder_tmp, zip_path)
        if not output_zip:
            return
        self.catalog.harvest_uploadgranule(output_zip, store)
        log_print(logger, f"🔄 Mosaico '{store.name}' actualizado con nuevos granules.")


# ──────────────────────────────────────────────────────────────────────────────
# Guardado/Actualización en MongoDB
# ──────────────────────────────────────────────────────────────────────────────
def _connect_mongo():
    db = config.get('MONGO_DB_NAME')
    uri = config.get('MONGO_URI')
    if not (db and uri):
        raise RuntimeError("Faltan variables de Mongo en .env/config: MONGO_DB_NAME, MONGO_URI")
    connect(db=db, host=uri)


def _save_folder_records_to_mongo(
    rasters_dir: str,
    workspace_name: str,
    store_name: str,
    source: str,
    deforestation_type: DeforestationType,
):
    """
    Recorre los .tif del directorio y crea/actualiza registros en la colección Deforestation.
    """
    _must_exist(rasters_dir, "Carpeta de rásters (Mongo)")
    _connect_mongo()

    # Ruta que guardaremos (como en tu implementación previa)
    server_store_path = f"{workspace_name}/{store_name}/"

    files = [f for f in os.listdir(rasters_dir) if f.lower().endswith(".tif")]
    for f in files:
        try:
            file_name = os.path.splitext(f)[0]
            y1, y2 = _extract_years_from_filename(f)

            existing = Deforestation.objects(
                name=file_name,
                year_start=y1,
                year_end=y2,
                deforestation_type=deforestation_type,
                deforestation_source=source
            ).first()

            if existing:
                existing.path = server_store_path
                if existing.log:
                    existing.log.updated = datetime.now()
                else:
                    existing.log = Log(enable=True, created=datetime.now(), updated=datetime.now())
                existing.save()
                log_print(logger, f"[Mongo] Registro actualizado: {store_name} {y1}-{y2}")
            else:
                log_obj = Log(enable=True, created=datetime.now(), updated=datetime.now())
                defo = Deforestation(
                    deforestation_source=source,
                    deforestation_type=deforestation_type,
                    name=file_name,
                    year_start=y1,
                    year_end=y2,
                    path=server_store_path,
                    log=log_obj
                )
                defo.save()
                log_print(logger, f"[Mongo] Registro creado: {store_name} {y1}-{y2}")

        except Exception as e:
            log_print(logger, f"[Mongo] Error con '{f}': {e}", level="error")


# ──────────────────────────────────────────────────────────────────────────────
# API principal usada por el main (Paso 5)
# ──────────────────────────────────────────────────────────────────────────────
def process_geoserver_mosaics(output_path_deforestation: str, source: str):
    """
    Publica/actualiza mosaicos 'annual' y 'cumulative' para la fuente dada (p.ej. 'SMBYC')
    y guarda/actualiza los registros en MongoDB.

    Espera la estructura producida por el Paso 4:
      <...>/04_tmp_calc_deforestation/
        ├─ smbyc_deforestation_annual/         # rásters anuales
        ├─ smbyc_deforestation_cumulative/     # rásters acumulados
        └─ properties/                         # indexer.properties, timeregex.properties (se crean si faltan)
        (+) tmp/ y zip/ se crean automáticamente si no existen
    """
    try:
        # Credenciales/URL desde config/.env
        gs_url = _ensure_rest_url(config.get("URL_GEO") or "")
        username = config.get("GEO_USER")
        password = config.get("GEO_PWD")  # ¡ojo! GEO_PWD
        ws_name = config.get("GEO_WORKSPACE")

        if not all([gs_url, username, password, ws_name]):
            raise RuntimeError("Faltan variables en .env/config: URL_GEO, GEO_USER, GEO_PWD, GEO_WORKSPACE")

        # Carpetas derivadas del paso 4
        src_lower = (source or "").lower()
        annual_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation_annual")
        cumulative_dir = os.path.join(output_path_deforestation, f"{src_lower}_deforestation_cumulative")
        props_dir = os.path.join(output_path_deforestation, "properties")
        tmp_dir = os.path.join(output_path_deforestation, "tmp")
        zip_dir = os.path.join(output_path_deforestation, "zip")

        log_print(logger, "[GeoServer] Iniciando publicación/actualización de mosaicos...")

        # Asegurar .properties EXACTOS si faltan
        _ensure_properties(props_dir)
        _create_dirs(tmp_dir, zip_dir)

        # Conexión a GeoServer
        geo = GeoserverClient(gs_url, username, password)
        geo.connect()
        geo.get_workspace(ws_name)

        # === ANUAL ===
        if os.path.isdir(annual_dir):
            store_annual = f"{src_lower}_deforestation_annual"
            store_obj = geo.get_store(store_annual)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_annual}")
                geo.update_mosaic(store_obj, annual_dir, props_dir, tmp_dir, zip_dir)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_annual}")
                geo.create_mosaic(store_annual, annual_dir, props_dir, tmp_dir, zip_dir)

            # Guardar en Mongo
            _save_folder_records_to_mongo(
                rasters_dir=annual_dir,
                workspace_name=ws_name,
                store_name=store_annual,
                source=source,
                deforestation_type=DeforestationType.ANNUAL
            )
        else:
            log_print(logger, f"[GeoServer] Carpeta ANUAL no encontrada, se omite: {annual_dir}", level="warning")

        # === ACUMULADO ===
        if os.path.isdir(cumulative_dir):
            store_cum = f"{src_lower}_deforestation_cumulative"
            store_obj = geo.get_store(store_cum)
            if store_obj:
                log_print(logger, f"[GeoServer] Actualizando store existente: {store_cum}")
                geo.update_mosaic(store_obj, cumulative_dir, props_dir, tmp_dir, zip_dir)
            else:
                log_print(logger, f"[GeoServer] Creando store: {store_cum}")
                geo.create_mosaic(store_cum, cumulative_dir, props_dir, tmp_dir, zip_dir)

            # Guardar en Mongo
            _save_folder_records_to_mongo(
                rasters_dir=cumulative_dir,
                workspace_name=ws_name,
                store_name=store_cum,
                source=source,
                deforestation_type=DeforestationType.CUMULATIVE
            )
        else:
            log_print(logger, f"[GeoServer] Carpeta ACUMULADA no encontrada, se omite: {cumulative_dir}", level="warning")

        log_print(logger, "[GeoServer/Mongo] Publicación y guardado completados.")

    except Exception as e:
        log_print(logger, f"[GeoServer/Mongo] Error en publicación/guardado: {e}", level="error")
        # Si quieres que el pipeline falle aquí:
        # raise
