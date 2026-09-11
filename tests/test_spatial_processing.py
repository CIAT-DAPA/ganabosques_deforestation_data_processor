"""
Pruebas unitarias del paso 3 del pipeline: ``src/spatial_processing``.

Los rasters de prueba cubren una ventana diminuta dentro del bbox de
referencia de Colombia (ver ``SMALL_BOUNDS`` en conftest) para que el grid
comun a 30 m en EPSG:3116 sea de ~37x36 pixeles en lugar de decenas de miles.
"""

import os

import numpy as np
import pytest
import rasterio

from tests.conftest import SMALL_BOUNDS, SMALL_BOUNDS_SHIFTED
from spatial_processing import mdl_spatial_processing
from spatial_processing.spatial_proccesing import (
    _apply_nad_atd_reclass_block,
    _build_grid,
    _calculate_common_intersection_bounds,
    _fixed_bounds_to_dst_crs,
    _intersect_bounds,
    _process_spatial_folder,
    resoluciones_iguales,
)


class TestResolucionesIguales:
    """Comparacion de resoluciones con tolerancia."""

    def test_resoluciones_identicas(self):
        assert resoluciones_iguales((30, 30), (30, 30)) is True

    def test_diferencia_dentro_de_la_tolerancia(self):
        assert resoluciones_iguales((30.0, 30.0), (30.0000001, 30.0000001)) is True

    def test_diferencia_fuera_de_la_tolerancia(self):
        assert resoluciones_iguales((30, 30), (30.1, 30)) is False

    def test_solo_difiere_el_eje_y(self):
        assert resoluciones_iguales((30, 30), (30, 60)) is False

    def test_tolerancia_personalizada(self):
        assert resoluciones_iguales((30, 30), (30.5, 30.5), tol=1.0) is True


class TestIntersectBounds:
    """Interseccion de dos cajas envolventes."""

    def test_interseccion_valida(self):
        assert _intersect_bounds((0, 0, 10, 10), (5, 5, 15, 15)) == (5, 5, 10, 10)

    def test_una_caja_contiene_a_la_otra(self):
        assert _intersect_bounds((0, 0, 20, 20), (5, 5, 15, 15)) == (5, 5, 15, 15)

    def test_cajas_identicas(self):
        assert _intersect_bounds((0, 0, 10, 10), (0, 0, 10, 10)) == (0, 0, 10, 10)

    def test_cajas_que_solo_se_tocan_en_una_esquina(self):
        with pytest.raises(ValueError, match="Interseccion invalida"):
            _intersect_bounds((0, 0, 10, 10), (10, 10, 20, 20))

    def test_cajas_disjuntas(self):
        with pytest.raises(ValueError, match="Interseccion invalida"):
            _intersect_bounds((0, 0, 5, 5), (10, 10, 15, 15))

    def test_solapan_en_x_pero_no_en_y(self):
        with pytest.raises(ValueError):
            _intersect_bounds((0, 0, 10, 5), (5, 10, 15, 20))


class TestBuildGrid:
    """Construccion del grid destino."""

    def test_grid_valido(self):
        transform, width, height = _build_grid((0, 0, 100, 100), (10, 10))
        assert (width, height) == (10, 10)

    def test_origen_en_la_esquina_superior_izquierda(self):
        transform, _, _ = _build_grid((100, 200, 400, 500), (10, 10))
        assert transform.c == 100  # minx
        assert transform.f == 500  # maxy

    def test_resolucion_reflejada_en_el_transform(self):
        transform, _, _ = _build_grid((0, 0, 100, 100), (10, 20))
        assert transform.a == 10
        assert transform.e == -20

    def test_resolucion_flotante(self):
        _, width, height = _build_grid((0, 0, 99.5, 99.5), (0.5, 0.5))
        assert (width, height) == (199, 199)

    def test_se_aplica_floor(self):
        _, width, height = _build_grid((0, 0, 99.9, 99.9), (10, 10))
        assert (width, height) == (9, 9)

    def test_grid_demasiado_pequeno(self):
        with pytest.raises(ValueError, match="Grid invalido"):
            _build_grid((0, 0, 1, 1), (100, 100))

    def test_grid_nulo_en_un_solo_eje(self):
        with pytest.raises(ValueError, match="Grid invalido"):
            _build_grid((0, 0, 1000, 5), (100, 100))


class TestFixedBoundsToDstCrs:
    """Reproyeccion del bbox fijo de referencia."""

    def test_de_4326_a_3116(self):
        xmin, ymin, xmax, ymax = _fixed_bounds_to_dst_crs(
            -79.22, -3.41, -66.65, 12.58, "EPSG:3116"
        )
        assert xmin < xmax
        assert ymin < ymax
        # EPSG:3116 esta en metros: los valores deben ser mucho mayores que grados.
        assert abs(xmax - xmin) > 1000

    def test_mismo_crs_devuelve_los_mismos_valores(self):
        resultado = _fixed_bounds_to_dst_crs(-79.0, -3.0, -67.0, 12.0, "EPSG:4326")
        assert np.allclose(resultado, (-79.0, -3.0, -67.0, 12.0), atol=1e-9)

    def test_ordena_las_coordenadas_aunque_lleguen_invertidas(self):
        xmin, ymin, xmax, ymax = _fixed_bounds_to_dst_crs(
            -66.65, 12.58, -79.22, -3.41, "EPSG:3116"
        )
        assert xmin < xmax
        assert ymin < ymax


class TestApplyNadAtdReclassBlock:
    """Reclasificacion NAD/ATD: positivo -> 2.0, resto -> NaN."""

    def test_valores_positivos_pasan_a_dos(self):
        resultado = _apply_nad_atd_reclass_block(
            np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        )
        assert np.all(resultado == 2.0)

    def test_ceros_pasan_a_nan(self):
        resultado = _apply_nad_atd_reclass_block(np.zeros((3, 3), dtype=np.float32))
        assert np.isnan(resultado).all()

    def test_negativos_pasan_a_nan(self):
        resultado = _apply_nad_atd_reclass_block(
            np.array([[-1, -100, 0]], dtype=np.float32)
        )
        assert np.isnan(resultado).all()

    def test_valores_mixtos(self):
        resultado = _apply_nad_atd_reclass_block(
            np.array([[0, 1, 2], [0, 3, 0]], dtype=np.float32)
        )
        assert np.isnan(resultado[0, 0])
        assert resultado[0, 1] == 2.0
        assert resultado[0, 2] == 2.0
        assert np.isnan(resultado[1, 2])

    def test_nan_de_entrada_sigue_siendo_nan(self):
        resultado = _apply_nad_atd_reclass_block(
            np.array([[1, np.nan, 0]], dtype=np.float32)
        )
        assert resultado[0, 0] == 2.0
        assert np.isnan(resultado[0, 1])

    def test_conserva_forma_y_dtype(self):
        entrada = np.zeros((7, 5), dtype=np.float64)
        resultado = _apply_nad_atd_reclass_block(entrada)
        assert resultado.shape == (7, 5)
        assert resultado.dtype == np.float32


class TestCalculateCommonIntersectionBounds:
    """Pasada 1: bbox comun de todos los rasters, normalizado al CRS destino."""

    def test_un_solo_raster(self, temp_dir, raster_factory):
        raster_factory("a.tif", subfolder="in")
        bounds = _calculate_common_intersection_bounds(
            os.path.join(temp_dir, "in"), "EPSG:3116"
        )
        assert bounds[0] < bounds[2]
        assert bounds[1] < bounds[3]

    def test_dos_rasters_solapados_dan_la_interseccion(self, temp_dir, raster_factory):
        raster_factory("a.tif", subfolder="solo_a", bounds=SMALL_BOUNDS)
        raster_factory("a.tif", subfolder="ambos", bounds=SMALL_BOUNDS)
        raster_factory("b.tif", subfolder="ambos", bounds=SMALL_BOUNDS_SHIFTED)

        solo_a = _calculate_common_intersection_bounds(
            os.path.join(temp_dir, "solo_a"), "EPSG:3116"
        )
        interseccion = _calculate_common_intersection_bounds(
            os.path.join(temp_dir, "ambos"), "EPSG:3116"
        )

        # 'b' esta desplazado al noreste: la interseccion recorta 'a' por el
        # suroeste y queda estrictamente contenida en el.
        assert interseccion[0] > solo_a[0]
        assert interseccion[1] > solo_a[1]
        assert interseccion[2] == pytest.approx(solo_a[2])
        assert interseccion[3] == pytest.approx(solo_a[3])

    def test_carpeta_sin_tif(self, temp_dir):
        entrada = os.path.join(temp_dir, "vacia")
        os.makedirs(entrada)
        with pytest.raises(ValueError, match="No se encontraron archivos .tif"):
            _calculate_common_intersection_bounds(entrada, "EPSG:3116")

    def test_raster_sin_crs(self, temp_dir, raster_factory):
        raster_factory("sin_crs.tif", subfolder="in", crs=None)
        with pytest.raises(ValueError, match="no tiene CRS definido"):
            _calculate_common_intersection_bounds(
                os.path.join(temp_dir, "in"), "EPSG:3116"
            )

    def test_rasters_sin_solape_no_tienen_interseccion(self, temp_dir, raster_factory):
        raster_factory("a.tif", subfolder="in", bounds=(-75.00, 5.00, -74.99, 5.01))
        raster_factory("b.tif", subfolder="in", bounds=(-70.00, 8.00, -69.99, 8.01))
        with pytest.raises(ValueError, match="No hay intersección válida"):
            _calculate_common_intersection_bounds(
                os.path.join(temp_dir, "in"), "EPSG:3116"
            )


class TestProcessSpatialFolderSmbyc:
    """Pasada 2 para rasters SMByC (annual/cumulative)."""

    def test_todos_los_salidas_comparten_el_mismo_grid(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", subfolder="in", bounds=SMALL_BOUNDS)
        raster_factory("smbyc_2014.tif", subfolder="in", bounds=SMALL_BOUNDS_SHIFTED)
        salida = os.path.join(temp_dir, "out")

        assert _process_spatial_folder(
            os.path.join(temp_dir, "in"), salida, "smbyc", False
        ) is True

        perfiles = []
        for nombre in ("smbyc_2013.tif", "smbyc_2014.tif"):
            with rasterio.open(os.path.join(salida, nombre)) as src:
                perfiles.append((src.width, src.height, src.transform, src.crs))

        assert perfiles[0] == perfiles[1], "los rasters deben quedar alineados"

    def test_reproyecta_a_epsg_3116(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_spatial_folder(os.path.join(temp_dir, "in"), salida, "smbyc", False)

        with rasterio.open(os.path.join(salida, "smbyc_2013.tif")) as src:
            assert src.crs.to_string() == "EPSG:3116"
            assert src.nodata == 0
            assert src.res == pytest.approx((30.0, 30.0))

    def test_conserva_el_nombre_original(self, temp_dir, raster_factory):
        raster_factory("smbyc_2010-2012.tif", subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_spatial_folder(os.path.join(temp_dir, "in"), salida, "smbyc", False)

        assert os.path.isfile(os.path.join(salida, "smbyc_2010-2012.tif"))

    def test_no_reclasifica_los_valores_smbyc(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", values=5.0, subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_spatial_folder(os.path.join(temp_dir, "in"), salida, "smbyc", False)

        with rasterio.open(os.path.join(salida, "smbyc_2013.tif")) as src:
            datos = src.read(1)
        assert 5.0 in np.unique(datos)

    def test_escribe_log_de_exito(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_spatial_folder(os.path.join(temp_dir, "in"), salida, "smbyc", False)

        with open(
            os.path.join(salida, "log_procesamiento.txt"), encoding="utf-8"
        ) as f:
            log = f.read()
        assert "El código ha corrido perfectamente" in log
        assert "1 archivos procesados correctamente" in log
        assert "Bbox común:" in log

    def test_ignora_archivos_que_no_son_tif(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", subfolder="in")
        entrada = os.path.join(temp_dir, "in")
        with open(os.path.join(entrada, "leeme.txt"), "w") as f:
            f.write("ignorame")
        salida = os.path.join(temp_dir, "out")

        assert _process_spatial_folder(entrada, salida, "smbyc", False) is True
        assert not os.path.exists(os.path.join(salida, "leeme.txt"))


class TestProcessSpatialFolderNadAtd:
    """Pasada 2 para rasters NAD/ATD, con reclasificacion a 2.0/NaN."""

    def test_reclasifica_a_dos_y_nan(self, temp_dir, raster_factory):
        datos = np.zeros((16, 16), dtype="float32")
        datos[0:8, 0:8] = 7.0
        raster_factory("nad_202401.tif", values=datos, subfolder="in")
        salida = os.path.join(temp_dir, "out")

        assert _process_spatial_folder(
            os.path.join(temp_dir, "in"), salida, "nad", True
        ) is True

        with rasterio.open(os.path.join(salida, "nad_202401.tif")) as src:
            leidos = src.read(1)
            assert src.dtypes[0] == "float32"

        unicos = np.unique(leidos[~np.isnan(leidos)])
        assert set(unicos.tolist()) <= {2.0}
        assert np.isnan(leidos).any(), "las zonas sin dato deben quedar en NaN"

    def test_nodata_es_nan_para_nad_atd(self, temp_dir, raster_factory):
        raster_factory("atd_202401.tif", values=3.0, subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_spatial_folder(os.path.join(temp_dir, "in"), salida, "atd", True)

        with rasterio.open(os.path.join(salida, "atd_202401.tif")) as src:
            assert np.isnan(src.nodata)

    def test_raster_todo_en_cero_queda_todo_nan(self, temp_dir, raster_factory):
        raster_factory("nad_202402.tif", values=0.0, subfolder="in")
        salida = os.path.join(temp_dir, "out")

        _process_spatial_folder(os.path.join(temp_dir, "in"), salida, "nad", True)

        with rasterio.open(os.path.join(salida, "nad_202402.tif")) as src:
            assert np.isnan(src.read(1)).all()


class TestProcessSpatialFolderErrores:
    """Rutas de error del procesamiento espacial."""

    def test_carpeta_sin_tif_devuelve_false(self, temp_dir, capsys):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)
        salida = os.path.join(temp_dir, "out")

        assert _process_spatial_folder(entrada, salida, "smbyc", False) is False
        assert "No se encontraron archivos .tif" in capsys.readouterr().out

    def test_bbox_invalido_devuelve_false(self, temp_dir, raster_factory, capsys):
        raster_factory("a.tif", subfolder="in", bounds=(-75.00, 5.00, -74.99, 5.01))
        raster_factory("b.tif", subfolder="in", bounds=(-70.00, 8.00, -69.99, 8.01))
        salida = os.path.join(temp_dir, "out")

        assert _process_spatial_folder(
            os.path.join(temp_dir, "in"), salida, "smbyc", False
        ) is False
        assert "Error calculando bbox común" in capsys.readouterr().out

    def test_raster_fuera_del_bbox_de_referencia(self, temp_dir, raster_factory):
        # Europa: no intersecta el bbox fijo de Colombia.
        raster_factory("fuera.tif", subfolder="in", bounds=(2.0, 48.0, 2.01, 48.01))
        salida = os.path.join(temp_dir, "out")

        assert _process_spatial_folder(
            os.path.join(temp_dir, "in"), salida, "smbyc", False
        ) is False

    def test_archivo_sin_crs_se_omite_en_la_pasada_dos(
        self, temp_dir, raster_factory, monkeypatch, capsys
    ):
        raster_factory("sin_crs.tif", subfolder="in", crs=None)
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        # La pasada 1 normalmente aborta ante un raster sin CRS; la forzamos a
        # devolver un bbox valido para llegar a la guarda de la pasada 2.
        monkeypatch.setattr(
            "spatial_processing.spatial_proccesing._calculate_common_intersection_bounds",
            lambda folder, dst_crs: (897692.0, 1044724.0, 898803.0, 1045829.0),
        )

        assert _process_spatial_folder(entrada, salida, "smbyc", False) is True
        assert "Archivo sin CRS, se omite: sin_crs.tif" in capsys.readouterr().out
        assert not os.path.exists(os.path.join(salida, "sin_crs.tif"))

    def test_excepcion_inesperada_se_registra_en_el_log(
        self, temp_dir, raster_factory, monkeypatch, capsys
    ):
        raster_factory("smbyc_2013.tif", subfolder="in")
        salida = os.path.join(temp_dir, "out")

        def _explota(*args, **kwargs):
            raise RuntimeError("fallo de disco simulado")

        monkeypatch.setattr("spatial_processing.spatial_proccesing.tqdm", _explota)

        assert _process_spatial_folder(
            os.path.join(temp_dir, "in"), salida, "smbyc", False
        ) is False
        assert "Ha ocurrido un error durante el procesamiento" in capsys.readouterr().out

        with open(
            os.path.join(salida, "log_procesamiento.txt"), encoding="utf-8"
        ) as f:
            log = f.read()
        assert "Ha ocurrido un error durante el procesamiento:" in log
        assert "fallo de disco simulado" in log


class TestMdlSpatialProcessing:
    """Punto de entrada del paso 3: enrutado por tipo de deforestacion."""

    @pytest.mark.parametrize("tipo", ["annual", "cumulative", "ANNUAL"])
    def test_tipos_smbyc_procesan_la_carpeta_smbyc_sin_reclasificar(
        self, temp_dir, raster_factory, tipo
    ):
        raster_factory("smbyc_2013.tif", values=5.0, subfolder="in/smbyc")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert mdl_spatial_processing(entrada, salida, deforestation_type=tipo) is True

        with rasterio.open(os.path.join(salida, "smbyc", "smbyc_2013.tif")) as src:
            assert 5.0 in np.unique(src.read(1))

    @pytest.mark.parametrize("tipo", ["nad", "atd"])
    def test_tipos_trimestrales_reclasifican(self, temp_dir, raster_factory, tipo):
        raster_factory(f"{tipo}_202401.tif", values=7.0, subfolder=f"in/{tipo}")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert mdl_spatial_processing(entrada, salida, deforestation_type=tipo) is True

        with rasterio.open(os.path.join(salida, tipo, f"{tipo}_202401.tif")) as src:
            datos = src.read(1)
        assert set(np.unique(datos[~np.isnan(datos)]).tolist()) <= {2.0}

    def test_sin_tipo_descubre_las_carpetas_y_aplica_la_regla_correcta(
        self, temp_dir, raster_factory
    ):
        raster_factory("smbyc_2013.tif", values=5.0, subfolder="in/smbyc")
        raster_factory("nad_202401.tif", values=7.0, subfolder="in/nad")
        entrada = os.path.join(temp_dir, "in")
        salida = os.path.join(temp_dir, "out")

        assert mdl_spatial_processing(entrada, salida) is True

        with rasterio.open(os.path.join(salida, "smbyc", "smbyc_2013.tif")) as src:
            assert 5.0 in np.unique(src.read(1))
        with rasterio.open(os.path.join(salida, "nad", "nad_202401.tif")) as src:
            datos = src.read(1)
        assert set(np.unique(datos[~np.isnan(datos)]).tolist()) <= {2.0}

    def test_sin_subcarpetas_devuelve_false(self, temp_dir, capsys):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)

        assert mdl_spatial_processing(entrada, os.path.join(temp_dir, "out")) is False
        assert "No se encontraron carpetas para procesar" in capsys.readouterr().out

    def test_tipo_pedido_sin_carpeta_en_disco_se_omite(self, temp_dir, capsys):
        entrada = os.path.join(temp_dir, "in")
        os.makedirs(entrada)

        resultado = mdl_spatial_processing(
            entrada, os.path.join(temp_dir, "out"), deforestation_type="nad"
        )

        assert resultado is True
        assert "Carpeta no encontrada" in capsys.readouterr().out

    def test_una_carpeta_fallida_marca_todo_como_fallido(
        self, temp_dir, raster_factory
    ):
        raster_factory("smbyc_2013.tif", subfolder="in/smbyc")
        os.makedirs(os.path.join(temp_dir, "in", "nad"))  # sin .tif -> falla

        resultado = mdl_spatial_processing(
            os.path.join(temp_dir, "in"), os.path.join(temp_dir, "out")
        )

        assert resultado is False

    def test_acepta_el_parametro_source_por_compatibilidad(
        self, temp_dir, raster_factory
    ):
        raster_factory("smbyc_2013.tif", subfolder="in/smbyc")

        resultado = mdl_spatial_processing(
            os.path.join(temp_dir, "in"),
            os.path.join(temp_dir, "out"),
            source="smbyc",
            deforestation_type="annual",
        )

        assert resultado is True

    def test_crea_el_directorio_de_salida(self, temp_dir, raster_factory):
        raster_factory("smbyc_2013.tif", subfolder="in/smbyc")
        salida = os.path.join(temp_dir, "nueva", "salida")

        mdl_spatial_processing(
            os.path.join(temp_dir, "in"), salida, deforestation_type="annual"
        )

        assert os.path.isdir(salida)
