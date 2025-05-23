import os
from glob import glob
from tools.GeoserverClient import GeoserverClient
from config import config

from tools.log_print import log_print
import logging

# Configuración del logger de este script
logger = logging.getLogger("importador_mosaicos")


def process_geoserver_mosaics( folder_root ):
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
    geo_url = config["URL_GEO"].rstrip("/") + "/rest/"
    geo_user = config["GEO_USER"]
    geo_pwd = config["GEO_PWD"]
    workspace_name = config["GEO_WORKSPACE"]

    # Listar los posibles mosaicos a procesar
    stores_aclimate = [name for name in os.listdir(folder_layers)
                   if os.path.isdir(os.path.join(folder_layers, name))]
    log_print(logger, f"Stores a procesar: {stores_aclimate}")

    # Conexión a GeoServer
    log_print(logger, "Conectando a GeoServer...")
    geoclient = GeoserverClient(geo_url, geo_user, geo_pwd)
    geoclient.connect()
    geoclient.get_workspace(workspace_name)
    log_print(logger, "Conexión establecida correctamente con GeoServer.")

    # Procesamiento de cada mosaico
    for current_store in stores_aclimate:
        try:
            current_rasters_folder = os.path.join(folder_layers, current_store)
            rasters_files = [f for f in os.listdir(current_rasters_folder) if f.endswith(".tif")]

            if not rasters_files:
                log_print(logger, f"No se encontraron archivos .tif en {current_rasters_folder}", level="warning")
                continue

            log_print(logger, f"Procesando el store: {current_store}")
            log_print(logger, f"Archivos raster encontrados: {rasters_files}")

            store = geoclient.get_store(current_store)
            log_print(logger, f"Ruta de la carpeta del mosaico: {current_rasters_folder}")

            if store:
                log_print(logger, f"El store '{current_store}' ya existe. Se procederá a actualizarlo.")
                geoclient.update_mosaic(store, current_rasters_folder, folder_properties, folder_tmp, os.path.dirname(output_zip_path))
            else:
                log_print(logger, f"El store '{current_store}' no existe. Se procederá a crearlo.")
                geoclient.create_mosaic(current_store, current_rasters_folder, folder_properties, folder_tmp, os.path.dirname(output_zip_path))

        except Exception as e:
            log_print(logger, f"Error al procesar el store '{current_store}': {str(e)}", level="error")
            continue

    log_print(logger, "Proceso completado con éxito.")
