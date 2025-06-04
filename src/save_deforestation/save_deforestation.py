import os
from urllib.parse import urljoin
from glob import glob
from tools.GeoserverClient import GeoserverClient
from config import config
from ganabosques_orm.collections.deforestation import Deforestation
from ganabosques_orm.enums.deforestationtype import DeforestationType
from ganabosques_orm.enums.deforestationsource import DeforestationSource
from ganabosques_orm.auxiliaries.log import Log
from mongoengine import connect
from datetime import datetime

from tools.log_print import log_print
import logging

# Configuración del logger de este script
logger = logging.getLogger("importador_mosaicos")

def process_geoserver_mosaics( folder_root, source ):
    # Rutas basadas en la variable WORKSPACE del .env
    folder_layers = folder_root
    
    # Ruta al directorio actual (src/save_deforestation/)
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

    # Ruta al folder de properties
    folder_properties = os.path.join(CURRENT_DIR, "..", "utils", "properties")
    folder_properties = os.path.abspath(folder_properties) 
    folder_tmp = os.path.join(folder_root, "tmp")
    output_zip_path = os.path.join(folder_root, "mosaic.zip")

    # Configuración de conexión
    geo_url = urljoin(config["URL_GEO"], "rest/")
    geo_user = config["GEO_USER"]
    geo_pwd = config["GEO_PWD"]
    workspace_name = config["GEO_WORKSPACE"]

    # Listar los posibles mosaicos a procesar
    stores = [name for name in os.listdir(folder_layers)
                   if os.path.isdir(os.path.join(folder_layers, name))]
    log_print(logger, f"Stores a procesar: {stores}")

    # Conexión a GeoServer
    log_print(logger, "Conectando a GeoServer...")
    geoclient = GeoserverClient(geo_url, geo_user, geo_pwd)
    geoclient.connect()
    geoclient.get_workspace(workspace_name)
    log_print(logger, "Conexión establecida correctamente con GeoServer.")

    # Procesamiento de cada mosaico
    for current_store in stores:
        try:
            current_rasters_folder = os.path.join(folder_layers, current_store)
            rasters_files = [f for f in os.listdir(current_rasters_folder) if f.endswith(".tif")]

            if not rasters_files:
                log_print(logger, f"No se encontraron archivos .tif en {current_rasters_folder}", level="warning")
                continue

            log_print(logger, f"Procesando el store: {current_store}")
            log_print(logger, f"Archivos raster encontrados: {rasters_files}")

            mosaic_success = False

            try:
                store = geoclient.get_store(current_store)
                log_print(logger, f"Ruta de la carpeta del mosaico: {current_rasters_folder}")

                if store:
                    log_print(logger, f"El store '{current_store}' ya existe. Se procederá a actualizarlo.")
                    geoclient.update_mosaic(store, current_rasters_folder, folder_properties, folder_tmp, os.path.dirname(output_zip_path))
                else:
                    log_print(logger, f"El store '{current_store}' no existe. Se procederá a crearlo.")
                    geoclient.create_mosaic(current_store, current_rasters_folder, folder_properties, folder_tmp, os.path.dirname(output_zip_path))
                
                mosaic_success = True 

            except Exception as geo_err:
                log_print(logger, f"Error al crear/actualizar mosaico '{current_store}': {geo_err}", level="error")
                continue

            if mosaic_success:
                # Determinar tipo de deforestación y ruta
                deforestation_type = (
                    DeforestationType.ANNUAL if DeforestationType.ANNUAL in current_store.lower()
                    else DeforestationType.CUMULATIVE
                )
                server_store_path = f"{workspace_name}/{current_store}/"

                connect(
                    db=config['MONGO_DB_NAME'],
                    host=config['MONGO_URI']
                )

                for f in rasters_files:
                    try:
                        year = log_year = int(''.join(filter(str.isdigit, f)))
                        file_name = os.path.splitext(f)[0]

                        if deforestation_type == DeforestationType.ANNUAL:
                            year_start, year_end = year, year + 1
                        else:
                            # Año del acumulado (del archivo .tif)
                            year_end = int(''.join(filter(str.isdigit, f)))
                            log_year = year_end
                            # Buscar los .tif anuales disponibles
                            all_annual_years = []
                            for name in os.listdir(folder_layers):
                                if DeforestationType.ANNUAL in name.lower():
                                    annual_folder = os.path.join(folder_layers, name)
                                    annual_tifs = [
                                        int(''.join(filter(str.isdigit, t)))
                                        for t in os.listdir(annual_folder)
                                        if t.endswith(".tif")
                                    ]
                                    all_annual_years.extend(annual_tifs)

                            if all_annual_years:
                                year_start = min(all_annual_years)
                            else:
                                year_start = year_end  # fallback

                        existing = Deforestation.objects(
                            name=file_name,
                            year_start=year_start,
                            year_end=year_end,
                            deforestation_type=deforestation_type,
                            deforestation_source=DeforestationSource(source)
                        ).first()

                        if existing:
                            existing.path = server_store_path
                            if existing.log:
                                existing.log.updated = datetime.now()
                            else:
                                existing.log = Log(enable=True, created=datetime.now(), updated=datetime.now())
                            existing.save()
                            
                            log_print(logger, f"Registro actualizado en MongoDB: {current_store} - {log_year}")
                        else:
                            log_obj = Log(enable=True, created=datetime.now(), updated=datetime.now())
                            defo = Deforestation(
                                deforestation_source=DeforestationSource(source),
                                deforestation_type=deforestation_type,
                                name=file_name,
                                year_start=year_start,
                                year_end=year_end,
                                path=server_store_path,
                                log=log_obj
                            )
                            defo.save()
                            log_print(logger, f"Registro creado en MongoDB: {current_store} - {log_year}")

                    except Exception as mongo_err:
                        log_print(logger, f"Error al guardar/actualizar '{f}' en MongoDB: {mongo_err}", level="error")
            else:
                log_print(logger, f"Se omitió el guardado en MongoDB porque falló el procesamiento del mosaico '{current_store}'", level="warning")
            
            # Limpiar archivos ZIP generados
            try:
                zip_files = glob(os.path.join(folder_root, "*.zip"))
                for zip_file in zip_files:
                    os.remove(zip_file)
                    log_print(logger, f"Archivo ZIP eliminado: {zip_file}")
            except Exception as e:
                log_print(logger, f"Error al eliminar archivos ZIP: {e}", level="warning")

            # Eliminar carpeta temporal TMP
            try:
                if os.path.exists(folder_tmp):
                    for item in os.listdir(folder_tmp):
                        item_path = os.path.join(folder_tmp, item)
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        else:
                            import shutil
                            shutil.rmtree(item_path)
                    os.rmdir(folder_tmp)
                    log_print(logger, f"Carpeta TMP eliminada: {folder_tmp}")
            except Exception as e:
                log_print(logger, f"Error al eliminar carpeta TMP: {e}", level="warning")

        except Exception as e:
            log_print(logger, f"Error al procesar el store '{current_store}': {str(e)}", level="error")
            continue

    log_print(logger, "Proceso de guardado completado.")
