import logging
import os
import argparse

from quality_control import quality_control
from spatial_processing import mdl_spatial_processing
from calculate_deforestation import deforestation_calc
from save_deforestation import process_geoserver_mosaics
from get_data_SMByC import get_data
from tools.log_print import log_print
from ganabosques_orm.enums.deforestationsource import DeforestationSource
from config import config

# ===== Helpers =====
def parse_steps(steps_str: str | None):
    """
    Convierte '1,3,5' o '1-3,5' en un set {1,2,3,5}.
    Si steps_str es None -> {1,2,3,4,5}
    """
    if not steps_str:
        return {1,2,3,4,5}
    result = set()
    for part in steps_str.split(","):
        part = part.strip()
        if "-" in part:
            a,b = part.split("-",1)
            result.update(range(int(a), int(b)+1))
        else:
            result.add(int(part))
    # solo válidos
    return {s for s in result if 1 <= s <= 5}

# ===== Paths / logging =====
base_path = os.path.join(config['WORKSPACE'], "deforestacion", "outputs")
os.makedirs(base_path, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(base_path, 'main_pipeline.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True,   # <- clave: evita duplicados por configuraciones previas
)
logger = logging.getLogger("main")


def main(years, source, deforestation_value=None, steps={1,2,3,4,5}):
    try:
        log_print(logger, f"Iniciando pipeline… (steps={sorted(steps)})")

        # Parámetros generales de carpetas
        output_path_get_data = os.path.join(base_path, "01_tmp_get_data_deforestation")
        output_path_quality = os.path.join(base_path, "02_tmp_quality_control")
        output_path_spatial = os.path.join(base_path, "03_tmp_spatial_procesing")
        output_path_deforestation = os.path.join(base_path, "04_tmp_calc_deforestation")

        # ===== Paso 1: Obtener datos =====
        if 1 in steps:
            log_print(logger, "Paso 1: Obtener datos…")
            get_data(
                years=years,
                output_path=output_path_get_data,
                geo=config['URL_GEO'],
                workspace=config['GEO_WORKSPACE'],
                mosaic=source
            )
        else:
            log_print(logger, "Paso 1 omitido.")

        # ===== Paso 2: Control de calidad =====
        if 2 in steps:
            log_print(logger, "Paso 2: Validación de calidad…")
            ok = quality_control(
                input_dir=output_path_get_data,
                output_dir=output_path_quality
            )
            if not ok:
                log_print(logger, "Fallo en calidad. Abortando.", level="error")
                return
        else:
            log_print(logger, "Paso 2 omitido.")

        # ===== Paso 3: Procesamiento espacial =====
        if 3 in steps:
            log_print(logger, "Paso 3: Validación/procesamiento espacial…")
            ok = mdl_spatial_processing(
                input_folder=output_path_quality,
                output_folder=output_path_spatial
            )
            if not ok:
                log_print(logger, "Fallo en validación espacial. Abortando.", level="error")
                return
        else:
            log_print(logger, "Paso 3 omitido.")

        # ===== Paso 4: Cálculo de deforestación =====
        if 4 in steps:
            log_print(logger, "Paso 4: Calcular deforestación…")
            deforestation_calc(
                input_folder=output_path_spatial,
                output_folder=output_path_deforestation,
                source=source,
                deforestation_value=deforestation_value
            )
        else:
            log_print(logger, "Paso 4 omitido.")

        # ===== Paso 5: Publicar en GeoServer / Guardar en Mongo =====
        if 5 in steps:
            log_print(logger, "Paso 5: Publicar resultados en GeoServer / Mongo…")
            # (hace todo: crea/actualiza mosaicos + registra en Mongo)
            process_geoserver_mosaics(output_path_deforestation, source)
        else:
            log_print(logger, "Paso 5 omitido.")

        log_print(logger, "Pipeline finalizado.")

    except Exception as e:
        log_print(logger, f"Error general en el proceso: {e}", level="error")

if __name__ == "__main__":
    valid_sources = [source.value for source in DeforestationSource]
    parser = argparse.ArgumentParser(description="Pipeline de procesamiento de datos de deforestación.")
    parser.add_argument(
        "-y","--years", nargs="+", type=int, required=True,
        help="Lista de años a procesar (ej: -y 2012 2013 2014)"
    )
    parser.add_argument(
        "-s","--source", type=str, required=True, choices=valid_sources,
        help=f"Fuente de los datos. Opciones: {', '.join(valid_sources)}"
    )
    parser.add_argument(
        "-d","--deforestation_value", type=str,
        help=f"Nombre de la capa de deforestación (obligatorio si la fuente no es '{DeforestationSource.SMBYC.value}')"
    )
    parser.add_argument(
        "--steps", type=str, default=None,
        help="Pasos a ejecutar: ej. '1', '1,3,5' o '1-3,5'. Por defecto ejecuta 1-5."
    )

    args = parser.parse_args()
    source_enum = DeforestationSource(args.source)

    # Validación condicional para el paso 4 si se ejecuta y la fuente no es SMBYC
    requested_steps = parse_steps(args.steps)
    if 4 in requested_steps and source_enum != DeforestationSource.SMBYC and not args.deforestation_value:
        parser.error(f"--deforestation_value es obligatorio si ejecutas el paso 4 y la fuente no es '{DeforestationSource.SMBYC.value}'.")

    main(args.years, args.source, args.deforestation_value, requested_steps)
