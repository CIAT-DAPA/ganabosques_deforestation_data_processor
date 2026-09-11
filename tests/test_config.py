"""
Pruebas unitarias de ``src/config.py`` y ``src/tools/log_print.py``.
"""

import importlib
import logging

import pytest

import config as config_module
from config import config
from tools.log_print import log_print


class TestConfigKeys:
    """El diccionario de configuracion expone todo lo que consume el pipeline."""

    @pytest.mark.parametrize(
        "key",
        [
            "DEBUG",
            "URL_GEO",
            "WORKSPACE",
            "GEO_USER",
            "GEO_PWD",
            "GEO_WORKSPACE",
            "MONGO_DB_NAME",
            "MONGO_URI",
            "STORES",
            "NAMING_PATTERNS",
            "SPATIAL_PARAMETERS",
        ],
    )
    def test_clave_presente(self, key):
        assert key in config

    def test_valores_leidos_del_entorno(self):
        assert config["URL_GEO"] == "http://localhost:8080/geoserver"
        assert config["GEO_USER"] == "admin"
        assert config["GEO_PWD"] == "geoserver"
        # GEO_WORKSPACE se lee de la variable GEO_WORKSPACE_DEFORESTATION.
        assert config["GEO_WORKSPACE"] == "deforestation"
        assert config["MONGO_DB_NAME"] == "ganabosques_test"

    def test_workspace_no_es_none(self):
        """
        Regresion: con WORKSPACE en None, ``main.py`` fallaba al importarse
        porque ``os.path.join(None, ...)`` lanza TypeError.
        """
        assert config["WORKSPACE"] is not None
        assert isinstance(config["WORKSPACE"], str)


class TestConfigDebugFlag:
    """El flag DEBUG se interpreta como booleano sin distinguir mayusculas."""

    @pytest.mark.parametrize(
        "valor_env, esperado",
        [
            ("true", True),
            ("TRUE", True),
            ("True", True),
            ("false", False),
            ("FALSE", False),
            ("cualquier-cosa", False),
        ],
    )
    def test_parseo_debug(self, monkeypatch, valor_env, esperado):
        monkeypatch.setenv("DEBUG", valor_env)
        recargado = importlib.reload(config_module)
        try:
            assert recargado.config["DEBUG"] is esperado
        finally:
            monkeypatch.setenv("DEBUG", "true")
            importlib.reload(config_module)

    def test_debug_por_defecto_es_true(self, monkeypatch):
        monkeypatch.delenv("DEBUG", raising=False)
        recargado = importlib.reload(config_module)
        try:
            assert recargado.config["DEBUG"] is True
        finally:
            monkeypatch.setenv("DEBUG", "true")
            importlib.reload(config_module)


class TestConfigConstantes:
    """Constantes espaciales y de nombrado usadas por los pasos 3 y 5."""

    def test_parametros_espaciales(self):
        sp = config["SPATIAL_PARAMETERS"]
        assert sp["xmin_ref"] < sp["xmax_ref"]
        assert sp["ymin_ref"] < sp["ymax_ref"]
        assert sp["res_ref"] == (30, 30)
        assert sp["dst_crs_ref"] == "EPSG:3116"

    def test_bbox_cubre_colombia_continental(self):
        sp = config["SPATIAL_PARAMETERS"]
        # Bogota debe caer dentro del bbox de referencia.
        assert sp["xmin_ref"] <= -74.07 <= sp["xmax_ref"]
        assert sp["ymin_ref"] <= 4.71 <= sp["ymax_ref"]

    def test_stores(self):
        assert config["STORES"] == {
            "raw": "smbyc",
            "annual": "smbyc_deforestation_annual",
            "cumulative": "smbyc_deforestation_cumulative",
        }

    def test_naming_patterns_son_formateables(self):
        patterns = config["NAMING_PATTERNS"]
        assert patterns["raw"].format(year=2013) == "smbyc_2013.tiff"
        assert (
            patterns["annual"].format(years="2012-2013")
            == "smbyc_deforestation_anual_2012-2013.tiff"
        )
        assert (
            patterns["cumulative"].format(years="2010-2013")
            == "smbyc_deforestation_cumulative_2010-2013.tiff"
        )


class TestLogPrint:
    """``log_print`` debe escribir en el logger y en stdout a la vez."""

    @pytest.mark.parametrize(
        "level, nivel_logging",
        [
            ("debug", logging.DEBUG),
            ("info", logging.INFO),
            ("warning", logging.WARNING),
            ("error", logging.ERROR),
            ("critical", logging.CRITICAL),
        ],
    )
    def test_cada_nivel_usa_el_metodo_correcto(
        self, capsys, caplog, level, nivel_logging
    ):
        logger = logging.getLogger("test_log_print")
        logger.propagate = True

        with caplog.at_level(logging.DEBUG, logger="test_log_print"):
            log_print(logger, f"mensaje {level}", level=level)

        assert f"mensaje {level}" in capsys.readouterr().out
        assert caplog.records[-1].levelno == nivel_logging

    def test_nivel_desconocido_cae_en_info(self, capsys, caplog):
        logger = logging.getLogger("test_log_print")
        with caplog.at_level(logging.DEBUG, logger="test_log_print"):
            log_print(logger, "sin nivel valido", level="inexistente")

        assert "sin nivel valido" in capsys.readouterr().out
        assert caplog.records[-1].levelno == logging.INFO

    def test_nivel_por_defecto_es_info(self, capsys, caplog):
        logger = logging.getLogger("test_log_print")
        with caplog.at_level(logging.DEBUG, logger="test_log_print"):
            log_print(logger, "por defecto")

        assert "por defecto" in capsys.readouterr().out
        assert caplog.records[-1].levelno == logging.INFO

    def test_nivel_en_mayusculas(self, capsys, caplog):
        logger = logging.getLogger("test_log_print")
        with caplog.at_level(logging.DEBUG, logger="test_log_print"):
            log_print(logger, "en mayusculas", level="WARNING")

        assert "en mayusculas" in capsys.readouterr().out
        assert caplog.records[-1].levelno == logging.WARNING

    def test_mensaje_con_caracteres_especiales(self, capsys):
        logger = logging.getLogger("test_log_print")
        log_print(logger, "Deforestación: ñ, é, ü, ✅", level="info")
        assert "Deforestación" in capsys.readouterr().out

    def test_mensaje_vacio_no_falla(self, capsys):
        logger = logging.getLogger("test_log_print")
        log_print(logger, "", level="info")
        assert capsys.readouterr().out == "\n"
