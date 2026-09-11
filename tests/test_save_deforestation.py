"""
Pruebas unitarias del paso 5 del pipeline: ``src/save_deforestation``.

GeoServer y MongoDB se sustituyen por dobles de prueba: la suite no necesita
ni un catalogo REST ni una base de datos en ejecucion.
"""

import os
import zipfile
from datetime import date, datetime
from unittest.mock import MagicMock, call

import pytest

from ganabosques_orm.enums.deforestationsource import DeforestationSource
from ganabosques_orm.enums.deforestationtype import DeforestationType
from save_deforestation import process_geoserver_mosaics
from save_deforestation.save_deforestation import (
    PROPS_BY_TYPE,
    GeoserverClient,
    _check_external_properties,
    _props_dir_for_type,
    _create_dirs,
    _ensure_rest_url,
    _list_tifs,
    _parse_period_from_filename,
    _read_text_file,
    _save_mosaic_records_to_mongo,
    _zip_tifs_and_props,
    _zip_tifs_only,
)

MODULO = "save_deforestation.save_deforestation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _crear_props(carpeta, timeregex="regex=(\\\\d{6})\n", indexer="TimeAttribute=time\n"):
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, "indexer.properties"), "w", encoding="utf-8") as f:
        f.write(indexer)
    with open(os.path.join(carpeta, "timeregex.properties"), "w", encoding="utf-8") as f:
        f.write(timeregex)
    return carpeta


def _crear_tifs(carpeta, *nombres):
    os.makedirs(carpeta, exist_ok=True)
    for n in nombres:
        with open(os.path.join(carpeta, n), "wb") as f:
            f.write(b"II*\x00fake-tif")
    return carpeta


@pytest.fixture
def mongo_doble(monkeypatch):
    """
    Sustituye ``connect``, ``Deforestation`` y ``Log`` del modulo por dobles.

    Devuelve un objeto con los tres mocks para poder hacer aserciones.
    """
    conectar = MagicMock(name="connect")
    deforestation = MagicMock(name="Deforestation")
    deforestation.objects.return_value.first.return_value = None
    log_cls = MagicMock(name="Log")

    monkeypatch.setattr(f"{MODULO}.connect", conectar)
    monkeypatch.setattr(f"{MODULO}.Deforestation", deforestation)
    monkeypatch.setattr(f"{MODULO}.Log", log_cls)

    doble = MagicMock()
    doble.connect = conectar
    doble.Deforestation = deforestation
    doble.Log = log_cls
    return doble


# ---------------------------------------------------------------------------
# Helpers generales
# ---------------------------------------------------------------------------
class TestEnsureRestUrl:
    """Normalizacion de la URL base de GeoServer a su endpoint REST."""

    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("http://x/geoserver", "http://x/geoserver/rest/"),
            ("http://x/geoserver/", "http://x/geoserver/rest/"),
            ("http://x/geoserver/rest", "http://x/geoserver/rest/"),
            ("http://x/geoserver/rest/", "http://x/geoserver/rest/"),
            ("http://x/otro/rest", "http://x/otro/rest/"),
            ("http://x/otro", "http://x/otro/rest/"),
            ("  http://x/geoserver  ", "http://x/geoserver/rest/"),
        ],
    )
    def test_normalizacion(self, entrada, esperado):
        assert _ensure_rest_url(entrada) == esperado

    @pytest.mark.parametrize("vacio", ["", None])
    def test_valor_vacio_devuelve_cadena_vacia(self, vacio):
        assert _ensure_rest_url(vacio) == ""

    def test_es_idempotente(self):
        una_vez = _ensure_rest_url("http://x/geoserver")
        assert _ensure_rest_url(una_vez) == una_vez


class TestCreateDirs:
    def test_crea_varias_rutas(self, temp_dir):
        a = os.path.join(temp_dir, "a")
        b = os.path.join(temp_dir, "b", "c")

        _create_dirs(a, b)

        assert os.path.isdir(a)
        assert os.path.isdir(b)

    def test_no_falla_si_ya_existen(self, temp_dir):
        _create_dirs(temp_dir, temp_dir)
        assert os.path.isdir(temp_dir)


class TestListTifs:
    def test_carpeta_inexistente_devuelve_lista_vacia(self, temp_dir):
        assert _list_tifs(os.path.join(temp_dir, "no_existe")) == []

    def test_devuelve_los_tif_ordenados(self, temp_dir):
        _crear_tifs(temp_dir, "c.tif", "a.tif", "b.tif")

        resultado = [os.path.basename(p) for p in _list_tifs(temp_dir)]

        assert resultado == ["a.tif", "b.tif", "c.tif"]

    def test_ignora_otras_extensiones(self, temp_dir):
        _crear_tifs(temp_dir, "a.tif")
        with open(os.path.join(temp_dir, "b.txt"), "w") as f:
            f.write("x")

        assert len(_list_tifs(temp_dir)) == 1


class TestReadTextFile:
    def test_lee_el_contenido(self, temp_dir):
        ruta = os.path.join(temp_dir, "f.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("hola")

        assert _read_text_file(ruta) == "hola"

    def test_archivo_inexistente_devuelve_cadena_vacia(self, temp_dir):
        assert _read_text_file(os.path.join(temp_dir, "no_existe.txt")) == ""


class TestCheckExternalProperties:
    """Validacion de indexer.properties y timeregex.properties."""

    def test_devuelve_ambas_rutas(self, temp_dir):
        carpeta = _crear_props(os.path.join(temp_dir, "props"))

        idx, trg = _check_external_properties(carpeta)

        assert idx.endswith("indexer.properties")
        assert trg.endswith("timeregex.properties")

    def test_sin_indexer_lanza_file_not_found(self, temp_dir):
        carpeta = os.path.join(temp_dir, "props")
        os.makedirs(carpeta)
        with open(os.path.join(carpeta, "timeregex.properties"), "w") as f:
            f.write("regex=(\\d{6})")

        with pytest.raises(FileNotFoundError, match="indexer.properties no encontrado"):
            _check_external_properties(carpeta)

    def test_sin_timeregex_lanza_file_not_found(self, temp_dir):
        carpeta = os.path.join(temp_dir, "props")
        os.makedirs(carpeta)
        with open(os.path.join(carpeta, "indexer.properties"), "w") as f:
            f.write("TimeAttribute=time")

        with pytest.raises(
            FileNotFoundError, match="timeregex.properties no encontrado"
        ):
            _check_external_properties(carpeta)

    def test_regex_con_guiones_advierte(self, temp_dir, capsys):
        # El chequeo busca una fecha literal con guiones dentro del archivo,
        # tipica de la configuracion antigua (YYYY-MM-DD).
        carpeta = _crear_props(
            os.path.join(temp_dir, "props"),
            timeregex=(
                "# ejemplo: smbyc_2010-01-01-2012-01-01.tif\n"
                "regex=([0-9]{8})-[0-9]{8}\n"
                "format=yyyy-MM-dd\n"
            ),
        )

        _check_external_properties(carpeta)

        assert "parece estar configurado para fechas con guiones" in capsys.readouterr().out

    def test_regex_de_seis_digitos_se_reconoce(self, temp_dir, capsys):
        carpeta = _crear_props(
            os.path.join(temp_dir, "props"), timeregex="regex=(\\\\d{6})\n"
        )

        _check_external_properties(carpeta)

        assert "compatible con YYYYMM" in capsys.readouterr().out

    def test_regex_de_ocho_digitos_se_reconoce(self, temp_dir, capsys):
        carpeta = _crear_props(
            os.path.join(temp_dir, "props"),
            timeregex="regex=(\\\\d{8})\nformat=yyyyMMdd\n",
        )

        _check_external_properties(carpeta)

        salida = capsys.readouterr().out
        assert "compatible con YYYYMMDD" in salida
        # El chequeo de YYYYMM no aplica: se emite la advertencia del else.
        assert "No pude inferir el formato" in salida

    def test_regex_irreconocible_advierte(self, temp_dir, capsys):
        carpeta = _crear_props(
            os.path.join(temp_dir, "props"), timeregex="regex=(.*)\n"
        )

        _check_external_properties(carpeta)

        assert "No pude inferir el formato" in capsys.readouterr().out


class TestPropsDirForType:
    """
    Cada tipo resuelve su carpeta de properties de forma determinista.

    Regresion: antes la carpeta se buscaba recorriendo ``os.listdir`` y
    quedandose con la primera cuyo nombre contuviera el source o el tipo. Para
    nad/atd coincidian las dos carpetas ('properties_nad_atd' por el tipo y
    'properties_smbyc' por el source), asi que el resultado dependia del orden
    del sistema de archivos: alfabetico en Windows, por hash en Linux.
    """

    @pytest.mark.parametrize(
        "tipo, carpeta_esperada",
        [
            ("annual", "properties_smbyc"),
            ("cumulative", "properties_smbyc"),
            ("nad", "properties_nad_atd"),
            ("atd", "properties_nad_atd"),
        ],
    )
    def test_mapeo_por_tipo(self, temp_dir, tipo, carpeta_esperada):
        for nombre in ("properties_smbyc", "properties_nad_atd"):
            _crear_props(os.path.join(temp_dir, nombre))

        resultado = _props_dir_for_type(temp_dir, tipo)

        assert os.path.basename(resultado) == carpeta_esperada

    def test_el_orden_del_sistema_de_archivos_no_influye(self, temp_dir, monkeypatch):
        for nombre in ("properties_smbyc", "properties_nad_atd"):
            _crear_props(os.path.join(temp_dir, nombre))

        # Aunque listdir devuelva primero la carpeta de SMByC, nad debe seguir
        # resolviendo a properties_nad_atd.
        monkeypatch.setattr(
            os, "listdir", lambda p: ["properties_smbyc", "properties_nad_atd"]
        )

        assert os.path.basename(_props_dir_for_type(temp_dir, "nad")) == (
            "properties_nad_atd"
        )

    def test_el_mapeo_cubre_los_cuatro_tipos(self):
        assert set(PROPS_BY_TYPE) == {"annual", "cumulative", "nad", "atd"}

    def test_tipo_sin_carpeta_asignada(self, temp_dir):
        with pytest.raises(
            FileNotFoundError, match="No hay carpeta de propiedades definida"
        ):
            _props_dir_for_type(temp_dir, "inventado")

    def test_carpeta_asignada_que_no_existe_en_disco(self, temp_dir):
        with pytest.raises(
            FileNotFoundError, match="No se encontró la carpeta de propiedades"
        ):
            _props_dir_for_type(temp_dir, "annual")

    def test_carpeta_sin_los_properties_requeridos(self, temp_dir):
        os.makedirs(os.path.join(temp_dir, "properties_smbyc"))

        with pytest.raises(FileNotFoundError, match="indexer.properties no encontrado"):
            _props_dir_for_type(temp_dir, "annual")

    def test_las_carpetas_reales_del_repositorio_son_validas(self):
        utils_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "utils"
        )

        for tipo in PROPS_BY_TYPE:
            assert os.path.isdir(_props_dir_for_type(utils_dir, tipo))


class TestZipTifsAndProps:
    """ZIP de creacion de mosaico: TIFs + properties."""

    def test_genera_zip_con_tifs_y_properties(self, temp_dir):
        origen = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif", "b.tif")
        props = _crear_props(os.path.join(temp_dir, "props"))

        ruta = _zip_tifs_and_props(
            origen,
            props,
            os.path.join(temp_dir, "tmp"),
            os.path.join(temp_dir, "zip"),
            "mosaic.zip",
        )

        assert ruta.endswith("mosaic.zip")
        with zipfile.ZipFile(ruta) as z:
            assert sorted(z.namelist()) == [
                "a.tif",
                "b.tif",
                "indexer.properties",
                "timeregex.properties",
            ]

    def test_sin_tifs_devuelve_none(self, temp_dir, capsys):
        origen = os.path.join(temp_dir, "rasters")
        os.makedirs(origen)
        props = _crear_props(os.path.join(temp_dir, "props"))

        resultado = _zip_tifs_and_props(
            origen, props, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip"), "m.zip"
        )

        assert resultado is None
        assert "No hay .tif" in capsys.readouterr().out

    def test_limpia_el_directorio_temporal_previo(self, temp_dir):
        origen = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        props = _crear_props(os.path.join(temp_dir, "props"))
        tmp = os.path.join(temp_dir, "tmp")
        _crear_tifs(tmp, "basura_anterior.tif")

        ruta = _zip_tifs_and_props(
            origen, props, tmp, os.path.join(temp_dir, "zip"), "m.zip"
        )

        with zipfile.ZipFile(ruta) as z:
            assert "basura_anterior.tif" not in z.namelist()
        assert not os.path.exists(tmp), "el temporal debe borrarse al terminar"

    def test_propiedades_invalidas_propagan_el_error(self, temp_dir):
        origen = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        props_vacias = os.path.join(temp_dir, "props")
        os.makedirs(props_vacias)

        with pytest.raises(FileNotFoundError):
            _zip_tifs_and_props(
                origen,
                props_vacias,
                os.path.join(temp_dir, "tmp"),
                os.path.join(temp_dir, "zip"),
                "m.zip",
            )


class TestZipTifsOnly:
    """ZIP de harvest: solo TIFs."""

    def test_genera_zip_solo_con_tifs(self, temp_dir):
        origen = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif", "b.tif")

        ruta = _zip_tifs_only(
            origen,
            os.path.join(temp_dir, "tmp"),
            os.path.join(temp_dir, "zip"),
            "granules.zip",
        )

        with zipfile.ZipFile(ruta) as z:
            assert sorted(z.namelist()) == ["a.tif", "b.tif"]

    def test_sin_tifs_devuelve_none(self, temp_dir, capsys):
        origen = os.path.join(temp_dir, "rasters")
        os.makedirs(origen)

        resultado = _zip_tifs_only(
            origen, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip"), "g.zip"
        )

        assert resultado is None
        assert "No hay .tif" in capsys.readouterr().out

    def test_limpia_el_directorio_temporal_previo(self, temp_dir):
        origen = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        tmp = os.path.join(temp_dir, "tmp")
        _crear_tifs(tmp, "viejo.tif")

        ruta = _zip_tifs_only(origen, tmp, os.path.join(temp_dir, "zip"), "g.zip")

        with zipfile.ZipFile(ruta) as z:
            assert z.namelist() == ["a.tif"]


# ---------------------------------------------------------------------------
# Parseo de periodos
# ---------------------------------------------------------------------------
class TestParsePeriodFromFilename:
    """Los cinco formatos de nombre soportados."""

    @pytest.mark.parametrize(
        "nombre, inicio, fin",
        [
            ("nad_deforestation_201701.tif", date(2017, 1, 1), date(2017, 3, 31)),
            ("nad_deforestation_201702.tif", date(2017, 4, 1), date(2017, 6, 30)),
            ("atd_deforestation_202303.tif", date(2023, 7, 1), date(2023, 9, 30)),
            ("atd_deforestation_202404.tif", date(2024, 10, 1), date(2024, 12, 31)),
        ],
    )
    def test_formato_trimestral(self, nombre, inicio, fin):
        assert _parse_period_from_filename(nombre) == (inicio, fin)

    def test_formato_anual_simple(self):
        assert _parse_period_from_filename(
            "smbyc_deforestation_annual_2013.tif"
        ) == (date(2013, 1, 1), date(2013, 1, 1))

    def test_formato_rango_de_anios(self):
        assert _parse_period_from_filename(
            "smbyc_deforestation_annual_2010-2012.tif"
        ) == (date(2010, 1, 1), date(2012, 1, 1))

    def test_formato_yyyymmdd(self):
        assert _parse_period_from_filename(
            "smbyc_deforestation_annual_20100101-20120315.tif"
        ) == (date(2010, 1, 1), date(2012, 3, 15))

    def test_formato_legacy_con_guiones(self):
        assert _parse_period_from_filename(
            "smbyc_deforestation_annual_2010-01-01-2012-01-01.tif"
        ) == (date(2010, 1, 1), date(2012, 1, 1))

    def test_usa_solo_el_nombre_base_no_la_ruta(self):
        assert _parse_period_from_filename(
            os.path.join("/datos/2099", "smbyc_deforestation_annual_2013.tif")
        ) == (date(2013, 1, 1), date(2013, 1, 1))

    def test_trimestre_invalido_no_matchea_ningun_formato(self):
        # '_202405.tif' se lee como trimestre 5, que no existe, y ningun otro
        # patron encaja -> error explicito.
        with pytest.raises(ValueError, match="No se pudo extraer rango de fechas"):
            _parse_period_from_filename("nad_deforestation_202405.tif")

    def test_nombre_sin_fechas(self):
        with pytest.raises(ValueError, match="No se pudo extraer rango de fechas"):
            _parse_period_from_filename("capa_sin_fecha.tif")


# ---------------------------------------------------------------------------
# Persistencia en Mongo
# ---------------------------------------------------------------------------
class TestSaveMosaicRecordsToMongo:
    """Upsert de los registros de la coleccion ``deforestation``."""

    def test_carpeta_inexistente_se_omite(self, temp_dir, mongo_doble, capsys):
        _save_mosaic_records_to_mongo(
            os.path.join(temp_dir, "no_existe"), "smbyc_deforestation_annual", "smbyc"
        )

        assert "Carpeta no encontrada, se omite" in capsys.readouterr().out
        mongo_doble.connect.assert_not_called()

    @pytest.mark.parametrize(
        "store, tipo_esperado",
        [
            ("smbyc_deforestation_nad", DeforestationType.NAD),
            ("smbyc_deforestation_atd", DeforestationType.ATD),
            ("smbyc_deforestation_annual", DeforestationType.ANNUAL),
            ("smbyc_deforestation_cumulative", DeforestationType.CUMULATIVE),
        ],
    )
    def test_tipo_se_deduce_del_nombre_del_store(
        self, temp_dir, mongo_doble, store, tipo_esperado
    ):
        _crear_tifs(temp_dir, "capa_deforestation_2013.tif")

        _save_mosaic_records_to_mongo(temp_dir, store, "smbyc")

        kwargs = mongo_doble.Deforestation.call_args.kwargs
        assert kwargs["deforestation_type"] is tipo_esperado
        assert kwargs["deforestation_source"] is DeforestationSource.SMBYC

    def test_store_desconocido_no_escribe_nada(self, temp_dir, mongo_doble, capsys):
        _crear_tifs(temp_dir, "capa_2013.tif")

        _save_mosaic_records_to_mongo(temp_dir, "store_raro", "smbyc")

        assert "No se pudo determinar tipo de deforestación" in capsys.readouterr().out
        mongo_doble.Deforestation.assert_not_called()

    def test_store_vacio_no_escribe_nada(self, temp_dir, mongo_doble):
        _crear_tifs(temp_dir, "capa_2013.tif")

        _save_mosaic_records_to_mongo(temp_dir, None, "smbyc")

        mongo_doble.Deforestation.assert_not_called()

    def test_carpeta_sin_tifs_avisa(self, temp_dir, mongo_doble, capsys):
        os.makedirs(os.path.join(temp_dir, "vacia"))

        _save_mosaic_records_to_mongo(
            os.path.join(temp_dir, "vacia"), "smbyc_deforestation_annual", "smbyc"
        )

        assert "No se encontraron TIF" in capsys.readouterr().out
        mongo_doble.Deforestation.assert_not_called()

    def test_conecta_con_la_configuracion(self, temp_dir, mongo_doble):
        _crear_tifs(temp_dir, "capa_2013.tif")

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        mongo_doble.connect.assert_called_once_with(
            db="ganabosques_test", host="mongodb://localhost:27017"
        )

    def test_crea_registro_nuevo(self, temp_dir, mongo_doble):
        _crear_tifs(temp_dir, "smbyc_deforestation_annual_2013.tif")

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        kwargs = mongo_doble.Deforestation.call_args.kwargs
        assert kwargs["name"] == "smbyc_deforestation_annual_2013"
        assert kwargs["period_start"] == date(2013, 1, 1)
        assert kwargs["period_end"] == date(2013, 1, 1)
        assert kwargs["path"] == "smbyc_deforestation_annual"
        mongo_doble.Deforestation.return_value.save.assert_called_once()

    def test_normaliza_el_nombre_del_store(self, temp_dir, mongo_doble):
        _crear_tifs(temp_dir, "smbyc_deforestation_annual_2013.tif")

        _save_mosaic_records_to_mongo(
            temp_dir, "  SMBYC_Deforestation_ANNUAL  ", "smbyc"
        )

        assert (
            mongo_doble.Deforestation.call_args.kwargs["path"]
            == "smbyc_deforestation_annual"
        )

    def test_actualiza_registro_existente_con_log(self, temp_dir, mongo_doble):
        _crear_tifs(temp_dir, "smbyc_deforestation_annual_2013.tif")
        existente = MagicMock()
        existente.log = MagicMock()
        mongo_doble.Deforestation.objects.return_value.first.return_value = existente

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        assert existente.path == "smbyc_deforestation_annual"
        assert isinstance(existente.log.updated, datetime)
        existente.save.assert_called_once()
        mongo_doble.Deforestation.assert_not_called()

    def test_actualiza_registro_existente_sin_log_le_crea_uno(
        self, temp_dir, mongo_doble
    ):
        _crear_tifs(temp_dir, "smbyc_deforestation_annual_2013.tif")
        existente = MagicMock()
        existente.log = None
        mongo_doble.Deforestation.objects.return_value.first.return_value = existente

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        mongo_doble.Log.assert_called_once()
        assert mongo_doble.Log.call_args.kwargs["enable"] is True
        existente.save.assert_called_once()

    def test_nombre_sin_fecha_se_salta_sin_abortar(self, temp_dir, mongo_doble, capsys):
        _crear_tifs(
            temp_dir, "sin_fecha.tif", "smbyc_deforestation_annual_2013.tif"
        )

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        assert "No se pudo parsear fechas para 'sin_fecha.tif'" in capsys.readouterr().out
        # El archivo valido si se guarda.
        assert mongo_doble.Deforestation.call_count == 1

    def test_error_al_guardar_se_registra_sin_abortar(
        self, temp_dir, mongo_doble, capsys
    ):
        _crear_tifs(temp_dir, "smbyc_deforestation_annual_2013.tif")
        mongo_doble.Deforestation.return_value.save.side_effect = RuntimeError(
            "mongo caido"
        )

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        salida = capsys.readouterr().out
        assert "Error guardando 'smbyc_deforestation_annual_2013': mongo caido" in salida
        assert "Registros guardados para store=" in salida

    def test_procesa_todos_los_tifs_de_la_carpeta(self, temp_dir, mongo_doble):
        _crear_tifs(
            temp_dir,
            "smbyc_deforestation_annual_2013.tif",
            "smbyc_deforestation_annual_2014.tif",
            "smbyc_deforestation_annual_2010-2012.tif",
        )

        _save_mosaic_records_to_mongo(temp_dir, "smbyc_deforestation_annual", "smbyc")

        assert mongo_doble.Deforestation.call_count == 3


# ---------------------------------------------------------------------------
# Cliente GeoServer
# ---------------------------------------------------------------------------
class TestGeoserverClientConnect:
    def test_conexion_exitosa(self, monkeypatch, capsys):
        catalogo = MagicMock()
        monkeypatch.setattr(f"{MODULO}.Catalog", MagicMock(return_value=catalogo))

        cliente = GeoserverClient("http://x/geoserver/rest/", "u", "p")
        cliente.connect()

        assert cliente.catalog is catalogo
        assert "Conectado a GeoServer" in capsys.readouterr().out

    def test_error_de_conexion_termina_el_proceso(self, monkeypatch, capsys):
        monkeypatch.setattr(
            f"{MODULO}.Catalog", MagicMock(side_effect=OSError("sin red"))
        )

        cliente = GeoserverClient("http://x/geoserver/rest/", "u", "p")
        with pytest.raises(SystemExit) as exc:
            cliente.connect()

        assert exc.value.code == 1
        assert "Error conectando a GeoServer" in capsys.readouterr().out


class TestGeoserverClientWorkspace:
    def test_sin_catalogo_lanza_runtime_error(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        with pytest.raises(RuntimeError, match="Catálogo de GeoServer no inicializado"):
            cliente.get_workspace("deforestation")

    def test_workspace_encontrado(self, capsys):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.get_workspace.return_value = MagicMock(name="ws")

        cliente.get_workspace("deforestation")

        assert cliente.workspace_name == "deforestation"
        assert "Workspace encontrado: deforestation" in capsys.readouterr().out

    def test_workspace_inexistente_termina_el_proceso(self, capsys):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.get_workspace.return_value = None

        with pytest.raises(SystemExit) as exc:
            cliente.get_workspace("fantasma")

        assert exc.value.code == 1
        assert "Workspace no encontrado: fantasma" in capsys.readouterr().out


class TestGeoserverClientGetStore:
    def test_sin_workspace_devuelve_none(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()

        assert cliente.get_store("s") is None

    def test_sin_catalogo_devuelve_none(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.workspace = MagicMock()

        assert cliente.get_store("s") is None

    def test_store_encontrado(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.workspace = MagicMock()
        store = MagicMock()
        cliente.catalog.get_store.return_value = store

        assert cliente.get_store("s") is store

    def test_excepcion_del_catalogo_devuelve_none(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.workspace = MagicMock()
        cliente.catalog.get_store.side_effect = RuntimeError("404")

        assert cliente.get_store("s") is None


class TestGeoserverClientTimeDimension:
    def test_sin_catalogo_no_hace_nada(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        # No debe lanzar.
        assert cliente._enable_time_dimension("s") is None

    def test_habilita_la_dimension_time(self, capsys):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.workspace = MagicMock()
        coverage = MagicMock()
        coverage.metadata = {}
        cliente.catalog.get_resource.return_value = coverage

        cliente._enable_time_dimension("mi_store")

        assert "time" in coverage.metadata
        cliente.catalog.save.assert_called_once_with(coverage)
        assert "Dimensión TIME habilitada en mi_store" in capsys.readouterr().out

    def test_metadata_none_se_inicializa(self):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        coverage = MagicMock()
        coverage.metadata = None
        cliente.catalog.get_resource.return_value = coverage

        cliente._enable_time_dimension("mi_store")

        assert "time" in coverage.metadata

    def test_coverage_inexistente_avisa(self, capsys):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.get_resource.return_value = None

        cliente._enable_time_dimension("mi_store")

        assert "Coverage no encontrado para mi_store" in capsys.readouterr().out
        cliente.catalog.save.assert_not_called()

    def test_error_del_catalogo_se_captura(self, capsys):
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.get_resource.side_effect = RuntimeError("boom")

        cliente._enable_time_dimension("mi_store")

        assert "No se pudo habilitar TIME en mi_store" in capsys.readouterr().out


class TestGeoserverClientCreateMosaic:
    def test_sin_catalogo_lanza_runtime_error(self, temp_dir):
        cliente = GeoserverClient("http://x/", "u", "p")

        with pytest.raises(RuntimeError, match="Catálogo de GeoServer no inicializado"):
            cliente.create_mosaic("s", temp_dir, temp_dir, temp_dir, temp_dir)

    def test_creacion_exitosa(self, temp_dir, capsys):
        rasters = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        props = _crear_props(os.path.join(temp_dir, "props"))
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.workspace = MagicMock()
        cliente.catalog.get_resource.return_value = MagicMock(metadata={})

        cliente.create_mosaic(
            "mi_store", rasters, props, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip")
        )

        cliente.catalog.create_imagemosaic.assert_called_once()
        salida = capsys.readouterr().out
        assert "ImageMosaic creado: mi_store" in salida
        assert "Dimensión TIME habilitada" in salida

    def test_sin_rasters_no_llama_a_geoserver(self, temp_dir):
        rasters = os.path.join(temp_dir, "rasters")
        os.makedirs(rasters)
        props = _crear_props(os.path.join(temp_dir, "props"))
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()

        cliente.create_mosaic(
            "mi_store", rasters, props, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip")
        )

        cliente.catalog.create_imagemosaic.assert_not_called()

    def test_error_de_geoserver_no_habilita_time(self, temp_dir, capsys):
        rasters = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        props = _crear_props(os.path.join(temp_dir, "props"))
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.create_imagemosaic.side_effect = RuntimeError("500")

        cliente.create_mosaic(
            "mi_store", rasters, props, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip")
        )

        assert "Error en create_imagemosaic 'mi_store'" in capsys.readouterr().out
        cliente.catalog.get_resource.assert_not_called()


class TestGeoserverClientUpdateMosaic:
    def test_sin_catalogo_lanza_runtime_error(self, temp_dir):
        cliente = GeoserverClient("http://x/", "u", "p")
        store = MagicMock()
        store.name = "mi_store"

        with pytest.raises(RuntimeError, match="Catálogo de GeoServer no inicializado"):
            cliente.update_mosaic(store, temp_dir, temp_dir, temp_dir)

    def test_harvest_exitoso(self, temp_dir, capsys):
        rasters = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.get_resource.return_value = MagicMock(metadata={})
        store = MagicMock()
        store.name = "mi_store"

        cliente.update_mosaic(
            store, rasters, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip")
        )

        cliente.catalog.harvest_uploadgranule.assert_called_once()
        assert "actualizado (harvest)" in capsys.readouterr().out

    def test_sin_rasters_no_llama_a_geoserver(self, temp_dir):
        rasters = os.path.join(temp_dir, "rasters")
        os.makedirs(rasters)
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        store = MagicMock()
        store.name = "mi_store"

        cliente.update_mosaic(
            store, rasters, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip")
        )

        cliente.catalog.harvest_uploadgranule.assert_not_called()

    def test_error_de_harvest_se_registra(self, temp_dir, capsys):
        rasters = _crear_tifs(os.path.join(temp_dir, "rasters"), "a.tif")
        cliente = GeoserverClient("http://x/", "u", "p")
        cliente.catalog = MagicMock()
        cliente.catalog.harvest_uploadgranule.side_effect = RuntimeError("409")
        store = MagicMock()
        store.name = "mi_store"

        cliente.update_mosaic(
            store, rasters, os.path.join(temp_dir, "tmp"), os.path.join(temp_dir, "zip")
        )

        assert "Error en harvest_uploadgranule 'mi_store'" in capsys.readouterr().out
        cliente.catalog.get_resource.assert_not_called()


# ---------------------------------------------------------------------------
# Orquestacion del paso 5
# ---------------------------------------------------------------------------
@pytest.fixture
def geo_doble(monkeypatch):
    """Reemplaza la clase ``GeoserverClient`` del modulo por un mock."""
    cliente = MagicMock(name="GeoserverClient instancia")
    cliente.get_store.return_value = None
    fabrica = MagicMock(name="GeoserverClient", return_value=cliente)
    monkeypatch.setattr(f"{MODULO}.GeoserverClient", fabrica)
    fabrica.instancia = cliente
    return fabrica


@pytest.fixture
def salida_paso4(temp_dir):
    """
    Estructura de salida del paso 4 con las cuatro carpetas por tipo.
    """
    for tipo in ("annual", "cumulative", "nad", "atd"):
        _crear_tifs(
            os.path.join(temp_dir, f"smbyc_deforestation_{tipo}"),
            "smbyc_deforestation_2013.tif",
        )
    return temp_dir


class TestProcessGeoserverMosaics:
    """Publicacion/actualizacion de mosaicos y registro en Mongo."""

    def test_procesa_solo_el_tipo_indicado(
        self, salida_paso4, geo_doble, mongo_doble, capsys
    ):
        process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        cliente = geo_doble.instancia
        cliente.connect.assert_called_once()
        cliente.get_workspace.assert_called_once_with("deforestation")
        assert cliente.get_store.call_args_list == [call("smbyc_deforestation_annual")]
        assert "Procesando solo tipo: annual" in capsys.readouterr().out

    def test_sin_tipo_procesa_los_cuatro(self, salida_paso4, geo_doble, mongo_doble):
        process_geoserver_mosaics(salida_paso4, "smbyc")

        stores = [c.args[0] for c in geo_doble.instancia.get_store.call_args_list]
        assert stores == [
            "smbyc_deforestation_annual",
            "smbyc_deforestation_cumulative",
            "smbyc_deforestation_nad",
            "smbyc_deforestation_atd",
        ]

    def test_store_inexistente_se_crea(self, salida_paso4, geo_doble, mongo_doble):
        geo_doble.instancia.get_store.return_value = None

        process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        geo_doble.instancia.create_mosaic.assert_called_once()
        geo_doble.instancia.update_mosaic.assert_not_called()

    def test_store_existente_se_actualiza(self, salida_paso4, geo_doble, mongo_doble):
        store = MagicMock()
        geo_doble.instancia.get_store.return_value = store

        process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        geo_doble.instancia.update_mosaic.assert_called_once()
        assert geo_doble.instancia.update_mosaic.call_args.args[0] is store
        geo_doble.instancia.create_mosaic.assert_not_called()

    def test_registra_en_mongo_despues_de_publicar(
        self, salida_paso4, geo_doble, mongo_doble
    ):
        process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        assert mongo_doble.Deforestation.call_count == 1
        assert (
            mongo_doble.Deforestation.call_args.kwargs["deforestation_type"]
            is DeforestationType.ANNUAL
        )

    def test_carpeta_de_tipo_ausente_se_omite(
        self, temp_dir, geo_doble, mongo_doble, capsys
    ):
        # Solo existe annual; se piden todos.
        _crear_tifs(
            os.path.join(temp_dir, "smbyc_deforestation_annual"), "smbyc_2013.tif"
        )

        process_geoserver_mosaics(temp_dir, "smbyc")

        assert "Carpeta no encontrada, se omite" in capsys.readouterr().out
        assert geo_doble.instancia.get_store.call_count == 1

    def test_tipo_desconocido_se_omite(
        self, salida_paso4, geo_doble, mongo_doble, capsys
    ):
        process_geoserver_mosaics(
            salida_paso4, "smbyc", deforestation_type="inventado"
        )

        assert "Tipo desconocido: inventado" in capsys.readouterr().out
        geo_doble.instancia.get_store.assert_not_called()

    def test_normaliza_la_fuente_a_minusculas(
        self, salida_paso4, geo_doble, mongo_doble
    ):
        process_geoserver_mosaics(salida_paso4, "  SMBYC  ", deforestation_type="annual")

        assert geo_doble.instancia.get_store.call_args.args[0] == (
            "smbyc_deforestation_annual"
        )

    def test_crea_los_directorios_de_trabajo(
        self, salida_paso4, geo_doble, mongo_doble
    ):
        process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        assert os.path.isdir(os.path.join(salida_paso4, "tmp_mosaic"))
        assert os.path.isdir(os.path.join(salida_paso4, "zip_mosaic"))

    @pytest.mark.parametrize(
        "tipo, carpeta_esperada",
        [
            ("annual", "properties_smbyc"),
            ("cumulative", "properties_smbyc"),
            ("nad", "properties_nad_atd"),
            ("atd", "properties_nad_atd"),
        ],
    )
    def test_cada_tipo_usa_su_carpeta_de_properties(
        self, salida_paso4, geo_doble, mongo_doble, tipo, carpeta_esperada
    ):
        process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type=tipo)

        # create_mosaic(store_name, rasters_dir, props_dir, tmp_dir, zip_dir)
        props_dir = geo_doble.instancia.create_mosaic.call_args.args[2]
        assert os.path.basename(props_dir) == carpeta_esperada

    def test_sin_tipo_cada_uno_recibe_sus_propias_properties(
        self, salida_paso4, geo_doble, mongo_doble
    ):
        """
        Regresion: props_dir se resolvia una sola vez fuera del bucle, asi que
        los cuatro tipos compartian carpeta y al menos dos quedaban con el
        timeregex equivocado.
        """
        process_geoserver_mosaics(salida_paso4, "smbyc")

        usadas = [
            os.path.basename(c.args[2])
            for c in geo_doble.instancia.create_mosaic.call_args_list
        ]
        assert usadas == [
            "properties_smbyc",
            "properties_smbyc",
            "properties_nad_atd",
            "properties_nad_atd",
        ]

    @pytest.mark.parametrize(
        "clave", ["URL_GEO", "GEO_USER", "GEO_PWD", "GEO_WORKSPACE"]
    )
    def test_configuracion_incompleta_lanza_runtime_error(
        self, salida_paso4, geo_doble, mongo_doble, monkeypatch, clave, capsys
    ):
        from save_deforestation import save_deforestation as modulo

        incompleta = dict(modulo.config)
        incompleta[clave] = None
        monkeypatch.setattr(modulo, "config", incompleta)

        with pytest.raises(RuntimeError, match="Faltan variables en .env/config"):
            process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        assert "Error en publicación" in capsys.readouterr().out

    def test_sin_carpeta_de_properties_lanza_file_not_found(
        self, salida_paso4, geo_doble, mongo_doble, monkeypatch
    ):
        isdir_real = os.path.isdir

        def _sin_properties(ruta):
            if "properties_" in str(ruta):
                return False
            return isdir_real(ruta)

        monkeypatch.setattr(os.path, "isdir", _sin_properties)

        with pytest.raises(
            FileNotFoundError, match="No se encontró la carpeta de propiedades"
        ):
            process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

    def test_error_de_geoserver_se_propaga(
        self, salida_paso4, geo_doble, mongo_doble, capsys
    ):
        geo_doble.instancia.connect.side_effect = RuntimeError("GeoServer caido")

        with pytest.raises(RuntimeError, match="GeoServer caido"):
            process_geoserver_mosaics(salida_paso4, "smbyc", deforestation_type="annual")

        assert "Error en publicación: GeoServer caido" in capsys.readouterr().out
