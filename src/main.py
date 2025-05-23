import logging
import os
import argparse

from quality_control import quality_control
from spatial_processing import mdl_spatial_processing
from calculate_deforestation import deforestation_step_1
from save_deforestation import process_geoserver_mosaics
from get_data_SMByC import get_data
from tools.log_print import log_print
from config import config


logging.basicConfig(
    filename='main_pipeline.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("main")

def main(years):
    try:
        log_print(logger, "Iniciando pipeline Deforestation Data Processor...")

        # Parámetros generales
        base_path = config['WORKSPACE']
        output_path_get_data = os.path.join(base_path, "deforestacion", "outputs", "tmp_get_data_deforestation")
        output_path_quality = os.path.join(base_path, "deforestacion", "outputs", "tmp_quality_control")
        output_path_spatial = os.path.join(base_path, "deforestacion", "outputs", "tmp_spatial_procesing")
        output_path_deforestation = os.path.join(base_path, "deforestacion", "outputs", "tmp_calc_deforestation")

        # Paso 1: Obtener datos
        log_print(logger, "Paso 1: Obtener datos...")
        get_data(
            years=years,
            output_path=output_path_get_data,
            geo=config['URL_GEO'],
            workspace=config['GEO_WORKSPACE'],
            mosaic='smbyc'
        )

        # Paso 2: Validación de calidad
        log_print(logger, "Paso 2: Validación de calidad...")
        if not quality_control(
            input_dir=output_path_get_data,
            output_dir=output_path_quality):
            log_print(logger, "Fallo en calidad. Abortando.", level="error")
            return

        # Paso 3: Validación espacial
        log_print(logger, "Paso 3: Validación espacial...")
        if not mdl_spatial_processing(
            input_folder=output_path_quality,
            output_folder=output_path_spatial):
            log_print(logger, "Fallo en validación espacial. Abortando.", level="error")
            return

        # Paso 4: Calcular deforestación
        log_print(logger, "Paso 4: Calcular deforestación...")
        deforestation_step_1(
            input_folder=output_path_spatial,
            output_folder=output_path_deforestation,
            source='SMBYC'
        )

        # Paso 5: Guardar resultados
        log_print(logger, "Paso 5: Guardar resultados...")
        process_geoserver_mosaics(output_path_deforestation)

        log_print(logger, "Proceso finalizado correctamente.")

    except Exception as e:
        log_print(logger, f"Error general en el proceso: {e}", level="error")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de procesamiento de datos de deforestación.")
    parser.add_argument("-y", "--years", nargs='+', type=int, required=True, help="Lista de años a procesar (por ejemplo: --years 2012 2013 2014  ó  -y 2012 2013 2014 )")

    args = parser.parse_args()
    main(args.years) 