## Get Data SMBYC 
import requests
import logging
import os
from tools.log_print import log_print  # Asegúrate que la ruta sea correcta


# Configuración del logger del módulo
logger = logging.getLogger("get data")

def get_data(years, quarters, output_path, geo, workspace, mosaic, source, deforestation_type=None):
    """
    Descarga datos según la fuente y tipo:
    - source='smbyc' + type='annual'/'cumulative' → Descarga de capa SMBYC a carpeta smbyc/
    - source='smbyc' + type='nad' → Descarga de capa NAD a carpeta nad/
    - source='smbyc' + type='atd' → Descarga de capa ATD a carpeta atd/
    - Sin type especificado → Descarga todos los tipos disponibles
    """
    os.makedirs(output_path, exist_ok=True)
    
    # Determinar qué tipos procesar
    if deforestation_type:
        types_to_process = [deforestation_type.lower()]
    else:
        types_to_process = ["annual", "cumulative", "nad", "atd"]
    
    for dtype in types_to_process:
        if dtype in ["annual", "cumulative"]:
            # Descargar de capa SMBYC a carpeta smbyc/
            type_folder = os.path.join(output_path, "smbyc")
            os.makedirs(type_folder, exist_ok=True)
            _download_smbyc(years, type_folder, geo, workspace, "smbyc")
        elif dtype == "nad":
            # Descargar de capa NAD a carpeta nad/
            type_folder = os.path.join(output_path, "nad")
            os.makedirs(type_folder, exist_ok=True)
            _download_nad_atd(years, quarters, type_folder, geo, workspace, "nad", "nad")
        elif dtype == "atd":
            # Descargar de capa ATD a carpeta atd/
            type_folder = os.path.join(output_path, "atd")
            os.makedirs(type_folder, exist_ok=True)
            _download_nad_atd(years, quarters, type_folder, geo, workspace, "atd", "atd")
        else:
            log_print(logger, f"Tipo desconocido: {dtype}", level="error")


def _download_smbyc(years, output_path, geo, workspace, mosaic):
    """Descarga anual para SMBYC"""
    for year in years:
        if year == 2010:
            # Caso especial: 2010-2012
            start = "2010-01-01T00:00:00.000Z"
            end = "2012-12-31T23:59:59.000Z"
            filename = f"{mosaic}_2010-2012.tif"
        else:
            # Anual: solo el año
            start = f"{year}-01-01T00:00:00.000Z"
            end = f"{year}-12-31T23:59:59.000Z"
            filename = f"{mosaic}_{year}.tif"
        
        _download_file(start, end, filename, output_path, geo, workspace, mosaic, str(year))


def _download_nad_atd(years, quarters, output_path, geo, workspace, mosaic, source):
    """Descarga trimestral para NAD/ATD"""
    quarter_dates = {
        1: ("01-01", "03-31"),
        2: ("04-01", "06-30"),
        3: ("07-01", "09-30"),
        4: ("10-01", "12-31"),
    }
    
    for year in years:
        for quarter in quarters:
            start_md, end_md = quarter_dates[quarter]
            start = f"{year}-{start_md}T00:00:00.000Z"
            end = f"{year}-{end_md}T23:59:59.000Z"
            filename = f"{source}_{year}{quarter:02d}.tif"
            
            _download_file(start, end, filename, output_path, geo, workspace, mosaic, f"{year}Q{quarter}")


def _download_file(start, end, filename, output_path, geo, workspace, mosaic, period_label):
    """Helper común para descargar archivos desde GeoServer WCS"""
    url = (
        f"{geo}/{workspace}/ows?"
        f"service=WCS&version=2.0.1&request=GetCoverage"
        f"&coverageId={mosaic}"
        f"&format=image/geotiff"
        f'&subset=Time("{start}","{end}")'
    )
    
    log_print(logger, f"Descargando período {period_label}:\n{url}")
    logger.propagate = False
    
    try:
        response = requests.get(url, timeout=120)  # Aumentado timeout a 120s
        if response.status_code == 200:
            output_file = os.path.join(output_path, filename)
            with open(output_file, "wb") as f:
                f.write(response.content)
            log_print(logger, f"✅ Archivo guardado: {filename}")
        else:
            log_print(
                logger,
                f"❌ Error {response.status_code} para {period_label}: {response.text}",
                level="error"
            )
    except requests.exceptions.Timeout:
        log_print(logger, f"⏰ Timeout para {period_label}", level="error")
    except requests.exceptions.RequestException as e:
        log_print(logger, f"❗ Error para {period_label}: {e}", level="error")
