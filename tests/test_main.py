"""
Pruebas unitarias del orquestador ``src/main.py``.

Los cinco pasos del pipeline se sustituyen por dobles: estas pruebas validan
el ruteo, el salto de pasos y el manejo de errores, no el trabajo de cada paso
(que se cubre en sus propios modulos de prueba).
"""

import os
import runpy
import shutil
import sys

import pytest

import main as main_module
from main import _prepare_nad_atd_files, main, parse_quarters, parse_steps

MAIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "main.py"
)


@pytest.fixture
def pasos(monkeypatch):
    """
    Reemplaza los cinco pasos dentro del espacio de nombres de ``main``.

    Devuelve un dict ``{numero_de_paso: llamadas}`` donde cada entrada acumula
    los kwargs con que se invoco el paso.
    """
    registro = {1: [], 2: [], 3: [], 4: [], 5: []}

    def _grabar(n, retorno=None):
        def _fn(*args, **kwargs):
            registro[n].append(kwargs or args)
            return retorno

        return _fn

    monkeypatch.setattr(main_module, "get_data", _grabar(1))
    monkeypatch.setattr(main_module, "quality_control", _grabar(2, True))
    monkeypatch.setattr(main_module, "mdl_spatial_processing", _grabar(3, True))
    monkeypatch.setattr(main_module, "deforestation_calc", _grabar(4))
    monkeypatch.setattr(main_module, "process_geoserver_mosaics", _grabar(5))
    monkeypatch.setattr(main_module, "_prepare_nad_atd_files", _grabar(4))
    return registro


class TestParseSteps:
    """``-p/--steps`` acepta numeros sueltos y rangos."""

    @pytest.mark.parametrize("vacio", [None, ""])
    def test_valor_vacio_devuelve_todos_los_pasos(self, vacio):
        assert parse_steps(vacio) == {1, 2, 3, 4, 5}

    def test_cadena_de_solo_espacios_lanza_value_error(self):
        # Comportamiento actual: '   ' no se considera vacio y el int() falla.
        with pytest.raises(ValueError):
            parse_steps("   ")

    def test_paso_unico(self):
        assert parse_steps("2") == {2}

    def test_lista_separada_por_comas(self):
        assert parse_steps("1,3,5") == {1, 3, 5}

    def test_rango(self):
        assert parse_steps("2-4") == {2, 3, 4}

    def test_mezcla_de_rango_y_lista(self):
        assert parse_steps("1-3,5") == {1, 2, 3, 5}

    def test_ignora_espacios(self):
        assert parse_steps(" 1 , 3 - 4 ") == {1, 3, 4}

    def test_descarta_valores_fuera_de_rango(self):
        assert parse_steps("0,1,5,6,99") == {1, 5}

    def test_elimina_duplicados(self):
        assert parse_steps("1,1,1,2,2") == {1, 2}

    def test_rango_completo_equivale_a_todos(self):
        assert parse_steps("1-5") == {1, 2, 3, 4, 5}


class TestParseQuarters:
    """``-q/--quarters`` devuelve una lista ordenada de trimestres validos."""

    @pytest.mark.parametrize("vacio", [None, ""])
    def test_valor_vacio_devuelve_todos_los_trimestres(self, vacio):
        assert parse_quarters(vacio) == [1, 2, 3, 4]

    def test_trimestre_unico(self):
        assert parse_quarters("2") == [2]

    def test_lista_separada_por_comas(self):
        assert parse_quarters("1,3") == [1, 3]

    def test_rango(self):
        assert parse_quarters("1-3") == [1, 2, 3]

    def test_mezcla_de_rango_y_lista(self):
        assert parse_quarters("1-2,4") == [1, 2, 4]

    def test_resultado_siempre_ordenado(self):
        assert parse_quarters("4,2,1,3") == [1, 2, 3, 4]

    def test_descarta_valores_fuera_de_rango(self):
        assert parse_quarters("0,1,4,5") == [1, 4]

    def test_elimina_duplicados(self):
        assert parse_quarters("1,1,2,2,3") == [1, 2, 3]


class TestPrepareNadAtdFiles:
    """Paso 4 para NAD/ATD: copia y renombrado al formato final."""

    @pytest.mark.parametrize("tipo", ["nad", "atd"])
    def test_renombra_al_formato_final(self, temp_dir, tipo):
        entrada = os.path.join(temp_dir, "03_spatial")
        subcarpeta = os.path.join(entrada, tipo)
        os.makedirs(subcarpeta)
        with open(os.path.join(subcarpeta, f"{tipo}_201701.tif"), "wb") as f:
            f.write(b"contenido")
        salida = os.path.join(temp_dir, "04_final")

        _prepare_nad_atd_files(entrada, salida, tipo)

        destino = os.path.join(
            salida, f"smbyc_deforestation_{tipo}", f"smbyc_deforestation_{tipo}_201701.tif"
        )
        assert os.path.isfile(destino)
        with open(destino, "rb") as f:
            assert f.read() == b"contenido"

    def test_procesa_varios_trimestres(self, temp_dir):
        subcarpeta = os.path.join(temp_dir, "03_spatial", "nad")
        os.makedirs(subcarpeta)
        for periodo in ("201701", "201702", "201703"):
            with open(os.path.join(subcarpeta, f"nad_{periodo}.tif"), "wb") as f:
                f.write(b"x")
        salida = os.path.join(temp_dir, "04_final")

        _prepare_nad_atd_files(os.path.join(temp_dir, "03_spatial"), salida, "nad")

        assert sorted(os.listdir(os.path.join(salida, "smbyc_deforestation_nad"))) == [
            "smbyc_deforestation_nad_201701.tif",
            "smbyc_deforestation_nad_201702.tif",
            "smbyc_deforestation_nad_201703.tif",
        ]

    def test_carpeta_de_entrada_inexistente_solo_avisa(self, temp_dir, capsys):
        salida = os.path.join(temp_dir, "04_final")

        _prepare_nad_atd_files(os.path.join(temp_dir, "no_existe"), salida, "nad")

        assert "Carpeta de entrada no existe" in capsys.readouterr().out

    def test_ignora_archivos_que_no_son_tif(self, temp_dir):
        subcarpeta = os.path.join(temp_dir, "03_spatial", "nad")
        os.makedirs(subcarpeta)
        with open(os.path.join(subcarpeta, "log_procesamiento.txt"), "w") as f:
            f.write("log")
        with open(os.path.join(subcarpeta, "nad_201701.tif"), "wb") as f:
            f.write(b"x")
        salida = os.path.join(temp_dir, "04_final")

        _prepare_nad_atd_files(os.path.join(temp_dir, "03_spatial"), salida, "nad")

        assert os.listdir(os.path.join(salida, "smbyc_deforestation_nad")) == [
            "smbyc_deforestation_nad_201701.tif"
        ]

    def test_ignora_tifs_con_otro_prefijo(self, temp_dir):
        subcarpeta = os.path.join(temp_dir, "03_spatial", "nad")
        os.makedirs(subcarpeta)
        with open(os.path.join(subcarpeta, "otro_201701.tif"), "wb") as f:
            f.write(b"x")
        salida = os.path.join(temp_dir, "04_final")

        _prepare_nad_atd_files(os.path.join(temp_dir, "03_spatial"), salida, "nad")

        assert os.listdir(os.path.join(salida, "smbyc_deforestation_nad")) == []

    def test_tipo_sin_mapeo_usa_el_propio_tipo_como_carpeta(self, temp_dir):
        subcarpeta = os.path.join(temp_dir, "03_spatial", "otro")
        os.makedirs(subcarpeta)
        with open(os.path.join(subcarpeta, "otro_201701.tif"), "wb") as f:
            f.write(b"x")
        salida = os.path.join(temp_dir, "04_final")

        _prepare_nad_atd_files(os.path.join(temp_dir, "03_spatial"), salida, "otro")

        assert os.listdir(os.path.join(salida, "smbyc_deforestation_otro")) == [
            "smbyc_deforestation_otro_201701.tif"
        ]


class TestMainOrquestacion:
    """``main()`` encadena los cinco pasos y respeta el filtro de pasos."""

    def test_ejecuta_los_cinco_pasos_para_annual(self, pasos):
        main([2013], "smbyc", deforestation_type="annual")

        assert len(pasos[1]) == 1
        assert len(pasos[2]) == 1
        assert len(pasos[3]) == 1
        assert len(pasos[4]) == 1
        assert len(pasos[5]) == 1

    def test_pasa_los_parametros_correctos_al_paso_1(self, pasos):
        main([2013, 2014], "smbyc", deforestation_type="annual", quarters=[1, 2])

        kwargs = pasos[1][0]
        assert kwargs["years"] == [2013, 2014]
        assert kwargs["quarters"] == [1, 2]
        assert kwargs["source"] == "smbyc"
        assert kwargs["deforestation_type"] == "annual"
        assert kwargs["geo"] == "http://localhost:8080/geoserver"
        assert kwargs["workspace"] == "deforestation"

    def test_las_carpetas_se_organizan_por_fuente_y_paso(self, pasos):
        main([2013], "smbyc", deforestation_type="annual")

        entrada_paso2 = pasos[2][0]["input_dir"]
        assert entrada_paso2.endswith(
            os.path.join("smbyc", "01_tmp_get_data_deforestation")
        )
        assert pasos[3][0]["input_folder"].endswith(
            os.path.join("smbyc", "02_tmp_quality_control")
        )
        assert pasos[4][0]["input_folder"].endswith(
            os.path.join("smbyc", "03_tmp_spatial_procesing")
        )

    @pytest.mark.parametrize("tipo", ["annual", "cumulative"])
    def test_tipos_smbyc_usan_deforestation_calc(self, pasos, tipo):
        main([2013], "smbyc", deforestation_type=tipo)

        assert len(pasos[4]) == 1
        assert pasos[4][0]["deforestation_type"] == tipo

    @pytest.mark.parametrize("tipo", ["nad", "atd"])
    def test_tipos_trimestrales_usan_prepare_nad_atd_files(self, pasos, tipo, capsys):
        main([2024], "smbyc", deforestation_type=tipo)

        assert len(pasos[4]) == 1
        assert f"Preparar archivos finales para {tipo}" in capsys.readouterr().out

    def test_tipo_no_reconocido_omite_el_paso_4(self, pasos, capsys):
        main([2013], "smbyc", deforestation_type="inventado")

        assert pasos[4] == []
        assert "no reconocido, omitiendo paso 4" in capsys.readouterr().out

    def test_sin_tipo_omite_el_paso_4(self, pasos):
        main([2013], "smbyc", deforestation_type=None)

        assert pasos[4] == []
        assert len(pasos[5]) == 1


class TestMainSaltoDePasos:
    """El parametro ``steps`` permite reejecutar tramos sueltos."""

    def test_solo_el_paso_1(self, pasos, capsys):
        main([2013], "smbyc", deforestation_type="annual", steps={1})

        assert len(pasos[1]) == 1
        assert pasos[2] == pasos[3] == pasos[4] == pasos[5] == []
        salida = capsys.readouterr().out
        assert "Paso 2 omitido." in salida
        assert "Paso 5 omitido." in salida

    def test_solo_el_paso_5(self, pasos):
        main([2013], "smbyc", deforestation_type="annual", steps={5})

        assert pasos[1] == pasos[2] == pasos[3] == pasos[4] == []
        assert len(pasos[5]) == 1

    def test_tramo_intermedio(self, pasos):
        main([2013], "smbyc", deforestation_type="annual", steps={2, 3})

        assert pasos[1] == []
        assert len(pasos[2]) == 1
        assert len(pasos[3]) == 1
        assert pasos[4] == pasos[5] == []

    def test_ningun_paso(self, pasos, capsys):
        main([2013], "smbyc", deforestation_type="annual", steps=set())

        assert all(pasos[n] == [] for n in range(1, 6))
        assert "Pipeline finalizado." in capsys.readouterr().out


class TestMainManejoDeErrores:
    """Fallos de calidad o espaciales abortan el pipeline."""

    def test_fallo_de_calidad_aborta(self, pasos, monkeypatch, capsys):
        monkeypatch.setattr(main_module, "quality_control", lambda **kw: False)

        main([2013], "smbyc", deforestation_type="annual")

        assert pasos[3] == pasos[4] == pasos[5] == []
        assert "Fallo en calidad. Abortando." in capsys.readouterr().out

    def test_fallo_espacial_aborta(self, pasos, monkeypatch, capsys):
        monkeypatch.setattr(main_module, "mdl_spatial_processing", lambda **kw: False)

        main([2013], "smbyc", deforestation_type="annual")

        assert pasos[4] == pasos[5] == []
        assert "Fallo en validación espacial. Abortando." in capsys.readouterr().out

    def test_excepcion_de_un_paso_se_registra_y_se_repropaga(
        self, pasos, monkeypatch, capsys
    ):
        def _explota(**kwargs):
            raise RuntimeError("GeoServer caido")

        monkeypatch.setattr(main_module, "get_data", _explota)

        with pytest.raises(RuntimeError, match="GeoServer caido"):
            main([2013], "smbyc", deforestation_type="annual")

        assert "Error general en el proceso: GeoServer caido" in capsys.readouterr().out


class TestMainCLI:
    """El bloque ``__main__``: parseo de argumentos y validaciones."""

    @pytest.fixture
    def cli(self, monkeypatch):
        """
        Sustituye los pasos en los paquetes de origen para que el modulo
        reejecutado con runpy importe dobles en lugar de los pasos reales.
        """
        llamadas = {}

        def _grabar(nombre, retorno=None):
            def _fn(*args, **kwargs):
                llamadas.setdefault(nombre, []).append(kwargs or args)
                return retorno

            return _fn

        monkeypatch.setattr("get_data_SMByC.get_data", _grabar("get_data"))
        monkeypatch.setattr(
            "quality_control.quality_control", _grabar("quality_control", True)
        )
        monkeypatch.setattr(
            "spatial_processing.mdl_spatial_processing",
            _grabar("spatial", True),
        )
        monkeypatch.setattr(
            "calculate_deforestation.deforestation_calc", _grabar("calc")
        )
        monkeypatch.setattr(
            "save_deforestation.process_geoserver_mosaics", _grabar("publish")
        )
        return llamadas

    def _ejecutar(self, monkeypatch, argv):
        monkeypatch.setattr(sys, "argv", ["main.py"] + argv)
        runpy.run_path(MAIN_PATH, run_name="__main__")

    def test_ejecucion_minima(self, cli, monkeypatch):
        self._ejecutar(monkeypatch, ["-y", "2013", "-s", "smbyc", "-t", "annual"])

        assert cli["get_data"][0]["years"] == [2013]
        assert cli["get_data"][0]["source"] == "smbyc"
        assert "publish" in cli

    def test_varios_anios(self, cli, monkeypatch):
        self._ejecutar(
            monkeypatch, ["-y", "2012", "2013", "2014", "-s", "smbyc", "-t", "annual"]
        )

        assert cli["get_data"][0]["years"] == [2012, 2013, 2014]

    def test_filtro_de_pasos(self, cli, monkeypatch):
        self._ejecutar(
            monkeypatch, ["-y", "2013", "-s", "smbyc", "-t", "annual", "-p", "1,2"]
        )

        assert "get_data" in cli
        assert "quality_control" in cli
        assert "publish" not in cli

    def test_trimestres_para_nad(self, cli, monkeypatch):
        self._ejecutar(
            monkeypatch, ["-y", "2024", "-s", "smbyc", "-t", "nad", "-q", "1-2"]
        )

        assert cli["get_data"][0]["quarters"] == [1, 2]

    def test_nad_sin_trimestres_usa_los_cuatro(self, cli, monkeypatch):
        self._ejecutar(monkeypatch, ["-y", "2024", "-s", "smbyc", "-t", "nad"])

        assert cli["get_data"][0]["quarters"] == [1, 2, 3, 4]

    def test_nad_con_trimestres_todos_invalidos_cae_al_valor_por_defecto(
        self, cli, monkeypatch
    ):
        # '0' y '9' se descartan por estar fuera de 1-4, parse_quarters devuelve
        # una lista vacia y el bloque __main__ la repuebla con los cuatro.
        self._ejecutar(
            monkeypatch, ["-y", "2024", "-s", "smbyc", "-t", "nad", "-q", "0,9"]
        )

        assert cli["get_data"][0]["quarters"] == [1, 2, 3, 4]

    def test_trimestres_en_tipo_no_trimestral_avisa(self, cli, monkeypatch, capsys):
        self._ejecutar(
            monkeypatch, ["-y", "2013", "-s", "smbyc", "-t", "annual", "-q", "1"]
        )

        assert "--quarters solo aplica para tipos NAD/ATD" in capsys.readouterr().out

    def test_sin_tipo_es_valido(self, cli, monkeypatch):
        self._ejecutar(monkeypatch, ["-y", "2013", "-s", "smbyc"])

        assert cli["get_data"][0]["deforestation_type"] is None

    def test_deforestation_value_se_propaga(self, cli, monkeypatch):
        self._ejecutar(
            monkeypatch,
            ["-y", "2013", "-s", "smbyc", "-t", "annual", "-d", "7"],
        )

        assert cli["calc"][0]["deforestation_value"] == "7"

    def test_fuente_invalida_termina_con_error(self, cli, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            self._ejecutar(monkeypatch, ["-y", "2013", "-s", "fuente_inventada"])

        assert exc.value.code == 2

    def test_tipo_invalido_termina_con_error(self, cli, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            self._ejecutar(
                monkeypatch, ["-y", "2013", "-s", "smbyc", "-t", "tipo_inventado"]
            )

        assert exc.value.code == 2

    def test_anios_son_obligatorios(self, cli, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            self._ejecutar(monkeypatch, ["-s", "smbyc"])

        assert exc.value.code == 2


class TestMainEfectosDeImportacion:
    """El modulo prepara su carpeta de salida y su log al importarse."""

    def test_crea_la_carpeta_base_de_salidas(self):
        assert os.path.isdir(main_module.base_path)
        assert main_module.base_path.endswith(
            os.path.join("deforestacion", "outputs")
        )

    def test_configura_el_logger_del_pipeline(self):
        assert main_module.logger.name == "main"
