import requests
import os

def download_geo(url_geo, workspace, name_layer_base, xmin, xmax, ymin, ymax, crs, year, output_path):
    if isinstance(year, (int, str)):
        year = [str(year)]
    else:
        year = list(map(str, year))

    output_paths = []

    for y in year:
        layer_name = f"{name_layer_base}{y}"
        coverage = f"{workspace}:{layer_name}"

        # Construir URL completa con el workspace en la ruta
        full_url = (
            f"{url_geo.rstrip('/')}/{workspace}/wcs?"
            f"service=WCS&version=1.0.0&request=GetCoverage"
            f"&coverage={coverage}"
            f"&bbox={xmin},{ymin},{xmax},{ymax}"
            f"&crs={crs}"
            f"&width=768&height=485"
            f"&format=GeoTIFF"
        )

        full_output_path = os.path.join(output_path, f"{layer_name}.tif")

        print(f"📥 Descargando: {coverage}")
        response = requests.get(full_url)

        if response.status_code == 200:
            os.makedirs(output_path, exist_ok=True)
            with open(full_output_path, "wb") as f:
                f.write(response.content)
            print(f"✅ Guardado en: {full_output_path}")
            output_paths.append(full_output_path)
        else:
            print(f"❌ Error al descargar {coverage}. Código: {response.status_code}")

    return output_paths

rutas_descargadas = download_geo(
    url_geo="http://localhost:8080/geoserver",
    workspace="deforestation",
    name_layer_base="smbyc_",
    xmin=-79.22,
    xmax=-66.65,
    ymin=-3.41,
    ymax=12.58,
    crs="EPSG:4326",
    year=[2012,2013,2014,2015, 2016,2017],
    output_path="D:/OneDrive - CGIAR/Desktop/ganabosques/ganabosques_project_local/descargas/"
)