"""
Pruebas unitarias del paso 2 del pipeline: ``src/quality_control``.
"""

import os

import numpy as np
import pytest
import rasterio
from rasterio.errors import RasterioIOError

from quality_control import quality_control
from quality_control.quality_control_deforestation import _process_folder


def _leer_log(carpeta):
    with open(
        os.path.join(carpeta, "log_quality_control.txt"), encoding="utf-8"
    ) as f:
        return f.read()


class TestQualityControlRuteo:
    """``quality_control`` decide que subcarpetas procesar segun el tipo."""

    @pytest.mark.parametrize("tipo", ["annual", "cumulative", "ANNUAL", "Cumulative"])
    def test_tipos_smbyc_procesan_la_carpeta_smbyc(
        self, temp_dir, raster_factory, tipo
    ):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert quality_control(entrada, salida, deforestation_type=tipo) is True
        assert os.path.isfile(os.path.join(salida, "smbyc", "smbyc_2013.tif"))

    @pytest.mark.parametrize("tipo", ["nad", "atd"])
    def test_tipos_trimestrales_procesan_su_propia_carpeta(
        self, temp_dir, raster_factory, tipo
    ):
        raster_factory(f"{tipo}_202401.tif", values=1.0, subfolder=f"in/{tipo}")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert quality_control(entrada, salida, deforestation_type=tipo) is True
        assert os.path.isfile(os.path.join(salida, tipo, f"{tipo}_202401.tif"))

    def test_sin_tipo_descubre_todas_las_subcarpetas(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        raster_factory("nad_202401.tif", values=2.0, subfolder="in/nad")
        raster_factory("atd_202401.tif", values=2.0, subfolder="in/atd")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert quality_control(entrada, salida) is True
        for sub in ("smbyc", "nad", "atd"):
            assert os.path.isdir(os.path.join(salida, sub))

    def test_sin_subcarpetas_devuelve_false(self, temp_dir, capsys):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)
        salida = os.path.join(temp_dir, "out")

        assert quality_control(entrada, salida) is False
        assert "No se encontraron carpetas para procesar" in capsys.readouterr().out

    def test_tipo_pedido_sin_carpeta_en_disco_se_omite(self, temp_dir, capsys):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)
        salida = os.path.join(temp_dir, "out")

        # La carpeta 'nad' se solicita pero no existe: se registra y se omite.
        assert quality_control(entrada, salida, deforestation_type="nad") is True
        assert "Carpeta no encontrada" in capsys.readouterr().out

    def test_una_carpeta_fallida_marca_todo_como_fallido(
        self, temp_dir, raster_factory
    ):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        # nad/ solo tiene un raster vacio -> esa carpeta falla.
        raster_factory("nad_202401.tif", values=0.0, subfolder="in/nad", nodata=None)
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert quality_control(entrada, salida) is False

    def test_crea_el_directorio_de_salida(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "nueva", "salida")

        quality_control(os.path.join(temp_dir, "in"), salida, deforestation_type="annual")

        assert os.path.isdir(salida)


class TestProcessFolderValidacion:
    """``_process_folder`` valida el contenido de cada raster."""

    def test_raster_valido_se_copia_y_se_registra(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert _process_folder(entrada, salida, "smbyc") is True
        assert os.path.isfile(os.path.join(salida, "smbyc_2013.tif"))

        log = _leer_log(salida)
        assert "Archivo válido con valores distintos de 0 y nodata." in log
        assert "Total procesados correctamente: 1" in log
        assert "Total con errores o vacíos: 0" in log

    def test_raster_solo_ceros_sin_nodata_se_rechaza(self, temp_dir, raster_factory):
        # nodata=None ejercita la rama `valores_validos = array[array != 0]`.
        raster_factory("vacio.tif", values=0.0, subfolder="in", nodata=None)
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert _process_folder(entrada, salida, "smbyc") is False
        assert not os.path.exists(os.path.join(salida, "vacio.tif"))
        assert "Archivo sin valores válidos" in _leer_log(salida)

    def test_raster_solo_nodata_se_rechaza(self, temp_dir, raster_factory):
        raster_factory("solo_nodata.tif", values=-9999.0, subfolder="in", nodata=-9999.0)
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert _process_folder(entrada, salida, "smbyc") is False
        assert "Archivo sin valores válidos" in _leer_log(salida)

    def test_raster_mixto_valido(self, temp_dir, raster_factory):
        datos = np.zeros((8, 8), dtype="float32")
        datos[0, 0] = 2.0
        raster_factory("mixto.tif", values=datos, subfolder="in", nodata=0.0)
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert _process_folder(entrada, salida, "smbyc") is True
        assert os.path.isfile(os.path.join(salida, "mixto.tif"))

    def test_carpeta_sin_tif_devuelve_false(self, temp_dir):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)
        with open(os.path.join(entrada, "notas.txt"), "w") as f:
            f.write("no soy un raster")
        salida = os.path.join(temp_dir, "out")

        assert _process_folder(entrada, salida, "smbyc") is False
        assert "No se encontraron archivos .tif o .tiff" in _leer_log(salida)

    def test_acepta_extension_tiff_y_mayusculas(self, temp_dir, raster_factory):
        raster_factory("capa.TIFF", values=2.0, subfolder="in")
        raster_factory("otra.TIF", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert _process_folder(entrada, salida, "smbyc") is True
        assert "Total procesados correctamente: 2" in _leer_log(salida)

    def test_mezcla_de_validos_e_invalidos(self, temp_dir, raster_factory):
        raster_factory("ok.tif", values=2.0, subfolder="in")
        raster_factory("vacio.tif", values=0.0, subfolder="in", nodata=None)
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        # Basta con un archivo valido para que la carpeta se considere correcta.
        assert _process_folder(entrada, salida, "smbyc") is True
        log = _leer_log(salida)
        assert "Total procesados correctamente: 1" in log
        assert "Total con errores o vacíos: 1" in log


class TestProcessFolderNombrado:
    """El renombrado conserva el nombre original en ambas ramas del patron."""

    def test_nombre_en_formato_corto_se_conserva(self, temp_dir, raster_factory):
        raster_factory("smbyc_2010-2012.tif", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        _process_folder(entrada, salida, "smbyc")

        assert os.path.isfile(os.path.join(salida, "smbyc_2010-2012.tif"))

    def test_nombre_fuera_del_patron_tambien_se_conserva(
        self, temp_dir, raster_factory
    ):
        raster_factory("nad_202401.tif", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        _process_folder(entrada, salida, "nad")

        assert os.path.isfile(os.path.join(salida, "nad_202401.tif"))


class TestProcessFolderErrores:
    """Errores de lectura se registran sin abortar el resto de la carpeta."""

    def test_archivo_corrupto_se_registra_como_error(self, temp_dir, raster_factory):
        raster_factory("bueno.tif", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        with open(os.path.join(entrada, "corrupto.tif"), "wb") as f:
            f.write(b"esto no es un geotiff")
        salida = os.path.join(temp_dir, "out")

        # El archivo valido sigue procesandose pese al corrupto.
        assert _process_folder(entrada, salida, "smbyc") is True
        log = _leer_log(salida)
        assert "Error al abrir el archivo" in log
        assert "Total procesados correctamente: 1" in log
        assert "Total con errores o vacíos: 1" in log

    def test_error_inesperado_se_captura(self, temp_dir, raster_factory, monkeypatch):
        raster_factory("raro.tif", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        def _explota(*args, **kwargs):
            raise MemoryError("sin memoria")

        monkeypatch.setattr(
            "quality_control.quality_control_deforestation.rasterio.open", _explota
        )

        assert _process_folder(entrada, salida, "smbyc") is False
        log = _leer_log(salida)
        assert "Error inesperado: sin memoria" in log
        assert "Total con errores o vacíos: 1" in log

    def test_rasterio_io_error_se_captura(self, temp_dir, raster_factory, monkeypatch):
        raster_factory("raro.tif", values=2.0, subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        def _explota(*args, **kwargs):
            raise RasterioIOError("no se puede abrir")

        monkeypatch.setattr(
            "quality_control.quality_control_deforestation.rasterio.open", _explota
        )

        assert _process_folder(entrada, salida, "smbyc") is False
        assert "Error al abrir el archivo" in _leer_log(salida)


class TestProcessFolderLog:
    """El log de la carpeta deja trazabilidad de cada archivo."""

    def test_log_incluye_encabezado_y_resumen(self, temp_dir, raster_factory):
        raster_factory("a.tif", values=2.0, subfolder="in")
        raster_factory("b.tif", values=2.0, subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_folder(os.path.join(temp_dir, "in"), salida, "smbyc")

        log = _leer_log(salida)
        assert log.startswith("LOG DE REVISIÓN DE RASTERS - ")
        assert "--- Archivo: a.tif ---" in log
        assert "--- Archivo: b.tif ---" in log
        assert "Resumen:" in log

    def test_copia_preserva_el_contenido_del_raster(self, temp_dir, raster_factory):
        origen = raster_factory("datos.tif", values=2.0, subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_folder(os.path.join(temp_dir, "in"), salida, "smbyc")

        with rasterio.open(origen) as src, rasterio.open(
            os.path.join(salida, "datos.tif")
        ) as dst:
            assert np.array_equal(src.read(1), dst.read(1))
            assert src.crs == dst.crs
            assert src.transform == dst.transform
