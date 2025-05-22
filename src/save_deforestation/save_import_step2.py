import os
from glob import glob
from tools import GeoserverClient
from zipfile import ZipFile
from config import config

def create_mosaic_zip(source_folder, properties_folder, output_zip):
    # Archivos que se incluirán
    files_to_zip = []

    # Archivos .tif
    for file_name in os.listdir(source_folder):
        if file_name.endswith(".tif"):
            full_path = os.path.join(source_folder, file_name)
            files_to_zip.append(full_path)

    # Archivos de propiedades
    for prop_file in ["indexer.properties", "timeregex.properties"]:
        prop_path = os.path.join(properties_folder, prop_file)
        if os.path.exists(prop_path):
            files_to_zip.append(prop_path)
        else:
            print(f"⚠️ No se encontró {prop_file} en {properties_folder}")

    # Crear ZIP
    with ZipFile(output_zip, 'w') as zipf:
        for file_path in files_to_zip:
            arcname = os.path.basename(file_path)
            zipf.write(file_path, arcname=arcname)
            print(f"Agregado al ZIP: {arcname}")

    print(f"✅ ZIP creado correctamente: {output_zip}")
    print(f"Contenido del ZIP: {files_to_zip}")

# Configuración
folder_root = config['WORKSPACE']
folder_data = os.path.join(folder_root, "data")
folder_layers = os.path.join(folder_data, "layers")
folder_properties = os.path.join(folder_data, "properties")
folder_tmp = os.path.join(folder_data, "tmp")
output_zip_path = os.path.join(folder_root, "mosaic.zip")

geo_url = config['URL_GEO']
geo_user = config['GEO_USER']
geo_pwd = config['GEO_PWD']
workspace_name = config['GEO_WORKSPACE']

stores_aclimate = [os.path.basename(x) for x in glob(os.path.join(folder_layers, "*"))]
print(f"Stores to process: {stores_aclimate}")

# Conexión inicial
print("Connecting to GeoServer...")
geoclient = GeoserverClient(geo_url, geo_user, geo_pwd)
geoclient.connect()
geoclient.get_workspace(workspace_name)
print("Connected successfully.")

# Proceso de cada store
for current_store in stores_aclimate:
    try:
        current_rasters_folder = os.path.join(folder_layers, current_store)
        rasters_files = [f for f in os.listdir(current_rasters_folder) if f.endswith(".tif")]
        print(f"Raster files found: {rasters_files}")
        print(f"Importing mosaic for store: {current_store}")

        geoclient.connect()
        geoclient.get_workspace(workspace_name)

        store = geoclient.get_store(current_store)
        print(f"Ruta del folder de mosaicos: {current_rasters_folder}")

        # Crear el zip con mosaico + propiedades
        create_mosaic_zip(current_rasters_folder, folder_properties, output_zip_path)

        # Subir a GeoServer
        print(f"Subiendo ZIP a GeoServer: {output_zip_path}")
        geoclient.upload_mosaic(store_name=current_store, zip_path= output_zip_path)

    except Exception as e:
        print(f"❌ Error processing store {current_store}: {str(e)}")
        continue

print("✅ Process completed")