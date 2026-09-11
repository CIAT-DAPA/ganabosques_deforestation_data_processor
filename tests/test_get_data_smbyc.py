"""
Pruebas unitarias del paso 1 del pipeline: ``src/get_data_SMByC``.

Todas las llamadas HTTP al WCS de GeoServer se simulan con ``responses``,
de modo que la suite no necesita un GeoServer real.
"""

import os
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from get_data_SMByC import get_data
from get_data_SMByC.get_data_smbyc import (
    _download_file,
    _download_nad_atd,
    _download_smbyc,
)

GEO = "http://geoserver.test/geoserver"
WS = "deforestation"


def _register_ok(body=b"GEOTIFF-BYTES"):
    responses.add(
        responses.GET,
        f"{GEO}/{WS}/ows",
        body=body,
        status=200,
        content_type="image/geotiff",
    )


def _subset_of(request_url):
    """Devuelve el valor del parametro ``subset`` de una URL WCS."""
    return parse_qs(urlparse(request_url).query)["subset"][0]


class TestDownloadFile:
    """``_download_file`` es el helper comun de descarga."""

    @responses.activate
    def test_descarga_exitosa_escribe_archivo(self, temp_dir, capsys):
        _register_ok(b"CONTENIDO-TIF")

        _download_file(
            "2020-01-01T00:00:00.000Z",
            "2020-12-31T23:59:59.000Z",
            "smbyc_2020.tif",
            temp_dir,
            GEO,
            WS,
            "smbyc",
            "2020",
        )

        destino = os.path.join(temp_dir, "smbyc_2020.tif")
        assert os.path.isfile(destino)
        with open(destino, "rb") as f:
            assert f.read() == b"CONTENIDO-TIF"
        assert "Archivo guardado: smbyc_2020.tif" in capsys.readouterr().out

    @responses.activate
    def test_url_wcs_bien_construida(self, temp_dir):
        _register_ok()

        _download_file(
            "2020-01-01T00:00:00.000Z",
            "2020-12-31T23:59:59.000Z",
            "smbyc_2020.tif",
            temp_dir,
            GEO,
            WS,
            "smbyc",
            "2020",
        )

        url = responses.calls[0].request.url
        params = parse_qs(urlparse(url).query)
        assert url.startswith(f"{GEO}/{WS}/ows?")
        assert params["service"] == ["WCS"]
        assert params["version"] == ["2.0.1"]
        assert params["request"] == ["GetCoverage"]
        assert params["coverageId"] == ["smbyc"]
        assert params["format"] == ["image/geotiff"]
        assert (
            params["subset"][0]
            == 'Time("2020-01-01T00:00:00.000Z","2020-12-31T23:59:59.000Z")'
        )

    @responses.activate
    def test_codigo_no_200_no_escribe_archivo(self, temp_dir, capsys):
        responses.add(
            responses.GET, f"{GEO}/{WS}/ows", body="capa inexistente", status=404
        )

        _download_file("s", "e", "fallo.tif", temp_dir, GEO, WS, "smbyc", "2020")

        assert not os.path.exists(os.path.join(temp_dir, "fallo.tif"))
        salida = capsys.readouterr().out
        assert "Error 404" in salida
        assert "capa inexistente" in salida

    @responses.activate
    def test_error_500_del_servidor(self, temp_dir, capsys):
        responses.add(responses.GET, f"{GEO}/{WS}/ows", body="boom", status=500)

        _download_file("s", "e", "fallo.tif", temp_dir, GEO, WS, "smbyc", "2020")

        assert not os.path.exists(os.path.join(temp_dir, "fallo.tif"))
        assert "Error 500" in capsys.readouterr().out

    @responses.activate
    def test_timeout_se_captura(self, temp_dir, capsys):
        responses.add(
            responses.GET, f"{GEO}/{WS}/ows", body=requests.exceptions.Timeout()
        )

        _download_file("s", "e", "t.tif", temp_dir, GEO, WS, "smbyc", "2021Q3")

        assert not os.path.exists(os.path.join(temp_dir, "t.tif"))
        assert "Timeout para 2021Q3" in capsys.readouterr().out

    @responses.activate
    def test_error_de_conexion_se_captura(self, temp_dir, capsys):
        responses.add(
            responses.GET,
            f"{GEO}/{WS}/ows",
            body=requests.exceptions.ConnectionError("sin red"),
        )

        _download_file("s", "e", "c.tif", temp_dir, GEO, WS, "smbyc", "2021")

        assert not os.path.exists(os.path.join(temp_dir, "c.tif"))
        assert "Error para 2021" in capsys.readouterr().out

    @responses.activate
    def test_usa_timeout_de_120_segundos(self, temp_dir):
        _register_ok()
        _download_file("s", "e", "x.tif", temp_dir, GEO, WS, "smbyc", "2020")
        assert responses.calls[0].request.req_kwargs["timeout"] == 120


class TestDownloadSmbyc:
    """Descarga anual de la capa SMByC."""

    @responses.activate
    def test_anio_2010_usa_rango_especial_2010_2012(self, temp_dir):
        _register_ok()

        _download_smbyc([2010], temp_dir, GEO, WS, "smbyc")

        assert os.path.isfile(os.path.join(temp_dir, "smbyc_2010-2012.tif"))
        subset = _subset_of(responses.calls[0].request.url)
        assert "2010-01-01T00:00:00.000Z" in subset
        assert "2012-12-31T23:59:59.000Z" in subset

    @responses.activate
    def test_anio_normal_usa_rango_anual(self, temp_dir):
        _register_ok()

        _download_smbyc([2015], temp_dir, GEO, WS, "smbyc")

        assert os.path.isfile(os.path.join(temp_dir, "smbyc_2015.tif"))
        subset = _subset_of(responses.calls[0].request.url)
        assert "2015-01-01T00:00:00.000Z" in subset
        assert "2015-12-31T23:59:59.000Z" in subset

    @responses.activate
    def test_varios_anios_generan_una_descarga_cada_uno(self, temp_dir):
        _register_ok()

        _download_smbyc([2010, 2013, 2014], temp_dir, GEO, WS, "smbyc")

        assert len(responses.calls) == 3
        assert sorted(os.listdir(temp_dir)) == [
            "smbyc_2010-2012.tif",
            "smbyc_2013.tif",
            "smbyc_2014.tif",
        ]


class TestDownloadNadAtd:
    """Descarga trimestral de las capas NAD y ATD."""

    @responses.activate
    @pytest.mark.parametrize(
        "quarter, inicio, fin",
        [
            (1, "2024-01-01", "2024-03-31"),
            (2, "2024-04-01", "2024-06-30"),
            (3, "2024-07-01", "2024-09-30"),
            (4, "2024-10-01", "2024-12-31"),
        ],
    )
    def test_fechas_por_trimestre(self, temp_dir, quarter, inicio, fin):
        _register_ok()

        _download_nad_atd([2024], [quarter], temp_dir, GEO, WS, "nad", "nad")

        subset = _subset_of(responses.calls[0].request.url)
        assert f"{inicio}T00:00:00.000Z" in subset
        assert f"{fin}T23:59:59.000Z" in subset
        assert os.path.isfile(os.path.join(temp_dir, f"nad_2024{quarter:02d}.tif"))

    @responses.activate
    def test_nombre_de_archivo_lleva_trimestre_con_dos_digitos(self, temp_dir):
        _register_ok()

        _download_nad_atd([2017], [1, 4], temp_dir, GEO, WS, "atd", "atd")

        assert sorted(os.listdir(temp_dir)) == ["atd_201701.tif", "atd_201704.tif"]

    @responses.activate
    def test_producto_cartesiano_anios_por_trimestres(self, temp_dir):
        _register_ok()

        _download_nad_atd([2022, 2023], [1, 2, 3], temp_dir, GEO, WS, "nad", "nad")

        assert len(responses.calls) == 6
        assert len(os.listdir(temp_dir)) == 6


class TestGetData:
    """Punto de entrada del paso 1: enruta por tipo de deforestacion."""

    @responses.activate
    @pytest.mark.parametrize("tipo", ["annual", "cumulative"])
    def test_tipos_smbyc_descargan_en_subcarpeta_smbyc(self, temp_dir, tipo):
        _register_ok()
        salida = os.path.join(temp_dir, "01_get_data")

        get_data([2013], [1], salida, GEO, WS, "smbyc", "smbyc", deforestation_type=tipo)

        assert os.path.isfile(os.path.join(salida, "smbyc", "smbyc_2013.tif"))

    @responses.activate
    @pytest.mark.parametrize("tipo", ["nad", "atd"])
    def test_tipos_trimestrales_descargan_en_su_carpeta(self, temp_dir, tipo):
        _register_ok()
        salida = os.path.join(temp_dir, "01_get_data")

        get_data([2024], [2], salida, GEO, WS, "smbyc", "smbyc", deforestation_type=tipo)

        assert os.path.isfile(os.path.join(salida, tipo, f"{tipo}_202402.tif"))
        assert parse_qs(urlparse(responses.calls[0].request.url).query)[
            "coverageId"
        ] == [tipo]

    @responses.activate
    def test_tipo_en_mayusculas_se_normaliza(self, temp_dir):
        _register_ok()
        salida = os.path.join(temp_dir, "01_get_data")

        get_data([2024], [1], salida, GEO, WS, "smbyc", "smbyc", deforestation_type="NAD")

        assert os.path.isfile(os.path.join(salida, "nad", "nad_202401.tif"))

    @responses.activate
    def test_sin_tipo_descarga_todos(self, temp_dir):
        _register_ok()
        salida = os.path.join(temp_dir, "01_get_data")

        get_data([2024], [1], salida, GEO, WS, "smbyc", "smbyc")

        # annual + cumulative escriben ambos en smbyc/ (mismo archivo), nad y atd
        # crean su propia carpeta.
        assert os.path.isdir(os.path.join(salida, "smbyc"))
        assert os.path.isfile(os.path.join(salida, "nad", "nad_202401.tif"))
        assert os.path.isfile(os.path.join(salida, "atd", "atd_202401.tif"))
        assert len(responses.calls) == 4

    @responses.activate
    def test_tipo_desconocido_registra_error(self, temp_dir, capsys):
        salida = os.path.join(temp_dir, "01_get_data")

        get_data(
            [2024], [1], salida, GEO, WS, "smbyc", "smbyc", deforestation_type="ninguno"
        )

        assert "Tipo desconocido: ninguno" in capsys.readouterr().out
        assert len(responses.calls) == 0

    @responses.activate
    def test_crea_el_directorio_de_salida(self, temp_dir):
        _register_ok()
        salida = os.path.join(temp_dir, "no", "existe", "todavia")

        get_data(
            [2013], [1], salida, GEO, WS, "smbyc", "smbyc", deforestation_type="annual"
        )

        assert os.path.isdir(salida)
