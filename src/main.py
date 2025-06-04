import logging
import os
import argparse

from quality_control import quality_control
from spatial_processing import mdl_spatial_processing
from calculate_deforestation import deforestation_step_1
from save_deforestation import process_geoserver_mosaics
from get_data_SMByC import get_data
from tools.log_print import log_print
from ganabosques_orm.enums.deforestationsource import DeforestationSource
from config import config


logging.basicConfig(
    filename=os.path.join(config['WORKSPACE'], 'main_pipeline.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("main")

def main(years, source, deforestation_value=None):
    try:
        log_print(logger, "Iniciando pipeline Deforestation Data Processor...")

        # Parámetros generales
        base_path = config['WORKSPACE']
        output_path_get_data = os.path.join(base_path, "deforestacion", "outputs", "01_tmp_get_data_deforestation")
        output_path_quality = os.path.join(base_path, "deforestacion", "outputs", "02_tmp_quality_control")
        output_path_spatial = os.path.join(base_path, "deforestacion", "outputs", "03_tmp_spatial_procesing")
        output_path_deforestation = os.path.join(base_path, "deforestacion", "outputs", "04_tmp_calc_deforestation")

        # Paso 1: Obtener datos
        log_print(logger, "Paso 1: Obtener datos...")
        get_data(
            years=years,
            output_path=output_path_get_data,
            geo=config['URL_GEO'],
            workspace=config['GEO_WORKSPACE'],
            mosaic=source
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
            source=source,
            deforestation_value=deforestation_value
        )

        # Paso 5: Guardar resultados
        log_print(logger, "Paso 5: Guardar resultados...")
        process_geoserver_mosaics(output_path_deforestation, source)
        log_print(logger, "Proceso finalizado.")

    except Exception as e:
        log_print(logger, f"Error general en el proceso: {e}", level="error")

if __name__ == "__main__":

    valid_sources = [source.value for source in DeforestationSource]
    parser = argparse.ArgumentParser(
        description="Pipeline de procesamiento de datos de deforestación."
    )
    parser.add_argument(
        "-y",
        "--years",
        nargs="+",
        type=int,
        required=True,
        help="Lista de años a procesar (por ejemplo: --years 2012 2013 2014  ó  -y 2012 2013 2014 )",
    )
    parser.add_argument(
        "-s",
        "--source",
        type=str,
        required=True,
        choices=valid_sources,
        help=f"Fuente de los datos. Opciones disponibles: {', '.join(valid_sources)}",
    )
    parser.add_argument(
        "-d", "--deforestation_value",
        type=str,
        help=f"Nombre de la capa de deforestación (obligatorio si la fuente no es '{DeforestationSource.SMBYC.value}')"
    )

    args = parser.parse_args()

    # Convertir string a Enum
    source_enum = DeforestationSource(args.source)

    # Validación condicional
    if source_enum != DeforestationSource.SMBYC and not args.deforestation_value:
        parser.error(f"El parámetro --deforestation_value es obligatorio si la fuente no es '{DeforestationSource.SMBYC.value}'.")

    main(args.years, args.source, args.deforestation_value)
