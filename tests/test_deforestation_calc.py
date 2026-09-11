"""
Pruebas unitarias del paso 4 del pipeline: ``src/calculate_deforestation``.
"""

import importlib
import os

import numpy as np
import pytest
import rasterio

from calculate_deforestation import deforestation_calc
from calculate_deforestation.deforestation_calc import extract_years_from_filename

ANNUAL_DIR = "smbyc_deforestation_annual"
CUMULATIVE_DIR = "smbyc_deforestation_cumulative"


def _leer_log(carpeta):
    # NOTA: deforestation_calc escribe log_parte1.txt con open(path, 'w') sin
    # declarar encoding, a diferencia de los pasos 2 y 3 que usan utf-8. Se lee
    # con la codificacion por defecto de la plataforma para no depender de ella.
    with open(os.path.join(carpeta, "log_parte1.txt")) as f:
        return f.read()


def _leer_banda(path):
    with rasterio.open(path) as src:
        return src.read(1)


class TestExtractYearsFromFilename:
    """Extraccion de los anios que codifica el nombre del raster."""

    @pytest.mark.parametrize(
        "nombre, esperado",
        [
            ("smbyc_2010-2012.tif", (2010, 2012)),
            ("smbyc_2020-2021.tif", (2020, 2021)),
            ("smbyc_deforestation_cumulative_2010-2015.tif", (2010, 2015)),
            ("smbyc_deforestation_annual_2012-2013.tif", (2012, 2013)),
        ],
    )
    def test_dos_anios_se_devuelven_tal_cual(self, nombre, esperado):
        assert extract_years_from_filename(nombre) == esperado

    @pytest.mark.parametrize(
        "nombre, esperado",
        [
            ("smbyc_2013.tif", (2013, 2014)),
            ("smbyc_2016.tif", (2016, 2017)),
        ],
    )
    def test_un_solo_anio_se_autoincrementa(self, nombre, esperado):
        assert extract_years_from_filename(nombre) == esperado

    @pytest.mark.parametrize(
        "nombre, esperado",
        [
            ("nad_202401.tif", (2024, 2025)),
            ("atd_202304.tif", (2023, 2024)),
        ],
    )
    def test_formato_trimestral_yyyyqq(self, nombre, esperado):
        # '202401' contiene un unico '20\\d{2}' (2024), asi que se autoincrementa.
        assert extract_years_from_filename(nombre) == esperado

    def test_sin_anios_lanza_value_error(self):
        with pytest.raises(ValueError, match="No se encontraron años válidos"):
            extract_years_from_filename("archivo_sin_fecha.tif")

    def test_anios_fuera_del_siglo_xxi_no_cuentan(self):
        with pytest.raises(ValueError):
            extract_years_from_filename("smbyc_1998.tif")

    def test_mas_de_dos_anios_lanza_value_error(self):
        # Con 3 coincidencias no entra en ninguna rama valida.
        with pytest.raises(ValueError):
            extract_years_from_filename("smbyc_2010_2011_2012.tif")


class TestDeforestationCalcValidaciones:
    """Validaciones previas al procesamiento."""

    def test_fuente_distinta_sin_valor_lanza_value_error(self, temp_dir):
        salida = os.path.join(temp_dir, "out")

        with pytest.raises(ValueError, match="debes especificar 'deforestation_value'"):
            deforestation_calc(os.path.join(temp_dir, "in"), salida, source="otra")

        assert "ERROR: Si la fuente no es 'smbyc'" in _leer_log(salida)

    def test_carpeta_smbyc_inexistente_lanza_file_not_found(self, temp_dir):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)
        salida = os.path.join(temp_dir, "out")

        with pytest.raises(FileNotFoundError, match="No existe la carpeta de entrada"):
            deforestation_calc(entrada, salida, source="smbyc")

        assert "ERROR: No existe la carpeta de entrada" in _leer_log(salida)

    def test_fuente_distinta_con_valor_usa_ese_valor_como_filtro(
        self, temp_dir, raster_factory
    ):
        raster_factory("capa_2013.tif", values=9.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(
            os.path.join(temp_dir, "in"),
            salida,
            source="otra",
            deforestation_value=9,
        )

        datos = _leer_banda(
            os.path.join(salida, ANNUAL_DIR, "smbyc_deforestation_annual_2013-2014.tif")
        )
        # El valor 9 se reconoce como deforestacion y se normaliza a 2.
        assert np.all(datos == 2)

    def test_carpeta_smbyc_vacia_no_genera_acumulado(self, temp_dir, capsys):
        entrada = os.path.join(temp_dir, "in", "smbyc")
        os.makedirs(entrada)
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        log = _leer_log(salida)
        assert "No se encontraron archivos .tif en el directorio de entrada." in log
        assert "No se generó acumulado" in log
        assert not os.path.isdir(os.path.join(salida, CUMULATIVE_DIR))


class TestDeforestationCalcAnual:
    """Generacion de las capas anuales."""

    def test_filtra_el_valor_dos_y_lo_marca_como_deforestacion(
        self, temp_dir, raster_factory
    ):
        datos = np.zeros((8, 8), dtype="float32")
        datos[0:4, 0:4] = 2.0
        datos[4:8, 4:8] = 1.0  # no es deforestacion
        raster_factory("smbyc_2013.tif", values=datos, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        resultado = _leer_banda(
            os.path.join(salida, ANNUAL_DIR, "smbyc_deforestation_annual_2013-2014.tif")
        )
        assert np.all(resultado[0:4, 0:4] == 2)
        assert np.isnan(resultado[4:8, 4:8]).all()

    def test_nombre_de_salida_para_rango_de_anios(self, temp_dir, raster_factory):
        raster_factory("smbyc_2010-2012.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        assert os.path.isfile(
            os.path.join(
                salida, ANNUAL_DIR, "smbyc_deforestation_annual_2010-2012.tif"
            )
        )

    def test_salida_es_float32_sin_nodata(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        with rasterio.open(
            os.path.join(salida, ANNUAL_DIR, "smbyc_deforestation_annual_2013-2014.tif")
        ) as src:
            assert src.dtypes[0] == "float32"
            assert src.nodata is None
            assert src.profile["compress"] == "lzw"

    def test_archivo_con_nombre_invalido_se_registra_y_no_aborta(
        self, temp_dir, raster_factory
    ):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        raster_factory("sin_fecha.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        log = _leer_log(salida)
        assert "ERROR procesando sin_fecha.tif" in log
        assert "smbyc_2013.tif procesado correctamente" in log

    def test_ignora_archivos_que_no_son_tif(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        with open(os.path.join(temp_dir, "in", "smbyc", "notas.txt"), "w") as f:
            f.write("ignorame")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        assert os.listdir(os.path.join(salida, ANNUAL_DIR)) == [
            "smbyc_deforestation_annual_2013-2014.tif"
        ]


class TestDeforestationCalcAcumulado:
    """Acumulado progresivo sobre las capas anuales ya generadas."""

    def test_primer_acumulado_replica_la_primera_capa(self, temp_dir, raster_factory):
        datos = np.zeros((8, 8), dtype="float32")
        datos[0, 0] = 2.0
        raster_factory("smbyc_2010-2012.tif", values=datos, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        acumulado = _leer_banda(
            os.path.join(
                salida, CUMULATIVE_DIR, "smbyc_deforestation_cumulative_2010-2012.tif"
            )
        )
        assert acumulado[0, 0] == 2
        assert np.isnan(acumulado[1, 1])

    def test_acumulado_progresivo_une_los_pixeles_de_cada_anio(
        self, temp_dir, raster_factory
    ):
        base = np.zeros((8, 8), dtype="float32")

        a = base.copy()
        a[0, 0] = 2.0
        b = base.copy()
        b[0, 1] = 2.0
        c = base.copy()
        c[0, 2] = 2.0

        raster_factory("smbyc_2010-2012.tif", values=a, subfolder="in/smbyc")
        raster_factory("smbyc_2012-2013.tif", values=b, subfolder="in/smbyc")
        raster_factory("smbyc_2013-2014.tif", values=c, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        cum_dir = os.path.join(salida, CUMULATIVE_DIR)
        assert sorted(os.listdir(cum_dir)) == [
            "smbyc_deforestation_cumulative_2010-2012.tif",
            "smbyc_deforestation_cumulative_2010-2013.tif",
            "smbyc_deforestation_cumulative_2010-2014.tif",
        ]

        final = _leer_banda(
            os.path.join(cum_dir, "smbyc_deforestation_cumulative_2010-2014.tif")
        )
        # Los tres pixeles deforestados de 2012, 2013 y 2014 estan presentes.
        assert final[0, 0] == 2
        assert final[0, 1] == 2
        assert final[0, 2] == 2
        assert np.isnan(final[1, 1])

    def test_el_acumulado_se_mantiene_binario(self, temp_dir, raster_factory):
        """Un pixel deforestado dos anios seguidos sigue valiendo 2, no 4."""
        datos = np.full((8, 8), 2.0, dtype="float32")
        raster_factory("smbyc_2010-2012.tif", values=datos, subfolder="in/smbyc")
        raster_factory("smbyc_2012-2013.tif", values=datos, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        final = _leer_banda(
            os.path.join(
                salida, CUMULATIVE_DIR, "smbyc_deforestation_cumulative_2010-2013.tif"
            )
        )
        assert np.all(final == 2)

    def test_el_acumulado_arranca_siempre_en_2010(self, temp_dir, raster_factory):
        raster_factory("smbyc_2018-2019.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        assert os.path.isfile(
            os.path.join(
                salida, CUMULATIVE_DIR, "smbyc_deforestation_cumulative_2010-2019.tif"
            )
        )

    def test_error_en_el_acumulado_se_registra_sin_propagar(
        self, temp_dir, raster_factory, monkeypatch
    ):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        modulo = importlib.import_module(
            "calculate_deforestation.deforestation_calc"
        )
        tqdm_original = modulo.tqdm

        def _tqdm_que_falla_en_el_acumulado(iterable, *args, **kwargs):
            if kwargs.get("desc") == "Generando acumulado":
                raise OSError("disco lleno simulado")
            return tqdm_original(iterable, *args, **kwargs)

        monkeypatch.setattr(modulo, "tqdm", _tqdm_que_falla_en_el_acumulado)

        # No debe propagar: el error queda registrado en el log.
        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        log = _leer_log(salida)
        assert "ERROR generando acumulado: disco lleno simulado" in log


class TestDeforestationCalcLog:
    """Contenido del log del paso 4."""

    def test_log_tiene_encabezado_y_cierre(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(os.path.join(temp_dir, "in"), salida, source="smbyc")

        log = _leer_log(salida)
        assert "--- LOG PARTE 1: CARGA Y FILTRADO ---" in log
        assert "Inicio:" in log
        assert "Fin del procesamiento:" in log

    def test_acepta_el_parametro_deforestation_type(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "out")

        deforestation_calc(
            os.path.join(temp_dir, "in"),
            salida,
            source="smbyc",
            deforestation_type="annual",
        )

        assert os.path.isdir(os.path.join(salida, ANNUAL_DIR))
