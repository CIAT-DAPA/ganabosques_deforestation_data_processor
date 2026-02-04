## Get Data SMBYC 
import requests
import logging
import os
from tools.log_print import log_print  # Asegúrate que la ruta sea correcta


# Configuración del logger del módulo
logger = logging.getLogger("get data")

def get_data(years, quarters, output_path, geo, workspace, mosaic, source):
    """
    Descarga datos según la fuente:
    - SMBYC: Anual (2010-2012 especial, resto anual)
    - NAD/ATD: Trimestral según quarters especificados
    """
    os.makedirs(output_path, exist_ok=True)
    
    if source == "smbyc":
        _download_smbyc(years, output_path, geo, workspace, mosaic)
    elif source in ["nad", "atd"]:
        _download_nad_atd(years, quarters, output_path, geo, workspace, mosaic, source)
    else:
        log_print(logger, f"Source desconocido: {source}", level="error")


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
