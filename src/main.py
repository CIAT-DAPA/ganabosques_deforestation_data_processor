import logging
import os

from quality_control import quality_control
from spatial_processing import mdl_spatial_processing
from calculate_deforestation import deforestation_step_1
#from save_deforestation import save_deforestation_result
from get_data_SMByC import get_data
from config import config


logging.basicConfig(filename='main_pipeline.log', level=logging.INFO)

def main():
    try:
        logging.info("Iniciando pipeline Deforestation Data Processor...")

        # Parámetros generales
        base_path = config['WORKSPACE'] 
        output_path_get_data = os.path.join(base_path, "deforestacion", "outputs", "tmp_get_data_deforestation")
        output_path_quality = os.path.join(base_path, "deforestacion", "outputs", "tmp_quality_control")
        output_path_spatial = os.path.join(base_path, "deforestacion", "outputs", "tmp_spatial_procesing")
        output_path_deforestation = os.path.join(base_path, "deforestacion", "outputs", "tmp_calc_deforestation")

        # Paso 1: Obtener datos
        get_data(
            years=[2012, 2013, 2014, 2015, 2016],
            output_path=output_path_get_data,
            geo=config['URL_GEO'],
            workspace=config['GEO_WORKSPACE'],
            mosaic='smbyc_test'
        )

        # Paso 2: Validación de calidad
        if not quality_control(
            input_dir=output_path_get_data,
            output_dir=output_path_quality):
            logging.error("Fallo en calidad. Abortando.")
            return

        # Paso 3: Validación espacial
        if not mdl_spatial_processing(
            input_folder=output_path_quality,
            output_folder=output_path_spatial):
            logging.error("Fallo en validación espacial. Abortando.")
            return

        # Paso 4: Calcular deforestación
        deforestation_step_1(
            input_folder=output_path_spatial,
            output_folder=output_path_deforestation,
            source='SMBYC'
        )

        # Paso 5: Guardar resultados
        #save_deforestation_result(source_data_path, year, mapserver_path)

        logging.info("Proceso finalizado correctamente.")

    except Exception as e:
        logging.error(f"Error general en el proceso: {e}")

if __name__ == "__main__":
    print(config)
    main()