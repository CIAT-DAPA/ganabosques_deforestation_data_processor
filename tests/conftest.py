"""
Configuracion global de pytest y fixtures compartidas.

IMPORTANTE: las variables de entorno se definen ANTES de importar cualquier
modulo de ``src``. ``src/config.py`` ejecuta ``load_dotenv()`` en tiempo de
import y el ``.env`` real vive en ``src/``, por lo que al correr pytest desde
la raiz del repositorio no se encuentra y ``config['WORKSPACE']`` queda en
``None``. Eso rompia el import de ``main.py`` (``os.path.join(None, ...)``).
``load_dotenv`` no sobreescribe variables ya presentes en el entorno, asi que
fijarlas aqui deja la configuracion determinista tanto en local como en CI.
"""

import atexit
import os
import shutil
import sys
import tempfile

# ---------------------------------------------------------------------------
# Entorno de pruebas (debe ejecutarse antes de cualquier import de src/)
# ---------------------------------------------------------------------------
_TEST_WORKSPACE = tempfile.mkdtemp(prefix="ganabosques_tests_")
atexit.register(shutil.rmtree, _TEST_WORKSPACE, True)

os.environ.setdefault("WORKSPACE", _TEST_WORKSPACE)
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("URL_GEO", "http://localhost:8080/geoserver")
os.environ.setdefault("GEO_USER", "admin")
os.environ.setdefault("GEO_PWD", "geoserver")
os.environ.setdefault("GEO_WORKSPACE_DEFORESTATION", "deforestation")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "ganabosques_test")

SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import rasterio  # noqa: E402
from rasterio.transform import from_bounds  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers de construccion de rasters
# ---------------------------------------------------------------------------
def write_raster(filepath, data, bounds, crs="EPSG:4326", nodata=np.nan):
    """Escribe un GeoTIFF de una banda con los parametros dados."""
    height, width = data.shape
    transform = from_bounds(*bounds, width, height)

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": data.dtype,
        "crs": crs,
        "transform": transform,
        "compress": "lzw",
    }
    if nodata is not None:
        profile["nodata"] = nodata

    with rasterio.open(filepath, "w", **profile) as dst:
        dst.write(data, 1)

    return filepath


# Ventana pequena dentro del bbox de referencia de Colombia declarado en
# config['SPATIAL_PARAMETERS']. Se usa a proposito un area diminuta (~1 km)
# para que el grid comun a 30 m en EPSG:3116 quepa en memoria: el bbox real
# completo generaria una malla de ~46.000 x 59.000 pixeles.
SMALL_BOUNDS = (-75.00, 5.00, -74.99, 5.01)
SMALL_BOUNDS_SHIFTED = (-74.995, 5.005, -74.985, 5.015)


@pytest.fixture
def temp_dir():
    """Directorio temporal que se limpia al terminar el test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_workspace():
    """Ruta del workspace temporal usado por la suite."""
    return _TEST_WORKSPACE


@pytest.fixture
def raster_factory(temp_dir):
    """
    Fabrica de rasters sinteticos.

    Uso::

        path = raster_factory("smbyc_2013.tif", values=2.0)
    """

    def _make(
        name,
        values=2.0,
        shape=(16, 16),
        bounds=SMALL_BOUNDS,
        crs="EPSG:4326",
        nodata=np.nan,
        subfolder=None,
        dtype="float32",
    ):
        folder = temp_dir if subfolder is None else os.path.join(temp_dir, subfolder)
        os.makedirs(folder, exist_ok=True)

        if isinstance(values, np.ndarray):
            data = values.astype(dtype)
        else:
            data = np.full(shape, values, dtype=dtype)

        return write_raster(
            os.path.join(folder, name), data, bounds, crs=crs, nodata=nodata
        )

    return _make


@pytest.fixture
def smbyc_input_folder(temp_dir, raster_factory):
    """
    Carpeta ``smbyc/`` con tres rasters anuales validos, en el formato real
    que produce el paso 1 del pipeline.
    """
    raster_factory("smbyc_2010-2012.tif", values=2.0, subfolder="smbyc")
    raster_factory("smbyc_2013.tif", values=2.0, subfolder="smbyc")
    raster_factory("smbyc_2014.tif", values=2.0, subfolder="smbyc")
    return temp_dir


@pytest.fixture
def synthetic_raster_epsg4326(temp_dir):
    """GeoTIFF sintetico 32x32 en EPSG:4326 con pixeles de deforestacion."""
    data = np.zeros((32, 32), dtype=np.float32)
    data[5:15, 5:15] = 2.0
    data[20:25, 20:25] = 2.0
    return write_raster(
        os.path.join(temp_dir, "synthetic_4326.tif"), data, SMALL_BOUNDS
    )


@pytest.fixture
def synthetic_raster_epsg3116(temp_dir):
    """GeoTIFF sintetico 32x32 en EPSG:3116 (Colombia, metros)."""
    data = np.zeros((32, 32), dtype=np.float32)
    data[8:24, 8:24] = 2.0
    return write_raster(
        os.path.join(temp_dir, "synthetic_3116.tif"),
        data,
        (800000, 500000, 800960, 500960),
        crs="EPSG:3116",
    )


@pytest.fixture
def empty_raster(temp_dir):
    """Raster completamente vacio (todo ceros, nodata=0)."""
    data = np.zeros((16, 16), dtype=np.float32)
    return write_raster(
        os.path.join(temp_dir, "empty_raster.tif"), data, SMALL_BOUNDS, nodata=0.0
    )


@pytest.fixture
def corrupt_raster(temp_dir):
    """Archivo con extension .tif que no es un GeoTIFF valido."""
    path = os.path.join(temp_dir, "corrupto.tif")
    with open(path, "wb") as f:
        f.write(b"no soy un geotiff")
    return path


@pytest.fixture
def props_dir(temp_dir):
    """
    Carpeta con ``indexer.properties`` y ``timeregex.properties`` validos,
    equivalentes a los de ``src/utils/properties_smbyc``.
    """
    folder = os.path.join(temp_dir, "properties_smbyc")
    os.makedirs(folder, exist_ok=True)

    with open(os.path.join(folder, "indexer.properties"), "w", encoding="utf-8") as f:
        f.write(
            "TimeAttribute=time\n"
            "Schema=*the_geom:Polygon,location:String,time:java.util.Date\n"
            "PropertyCollectors=TimestampFileNameExtractorSPI[timeregex](time)\n"
        )
    with open(os.path.join(folder, "timeregex.properties"), "w", encoding="utf-8") as f:
        f.write("regex=(\\\\d{6})\n")

    return folder


@pytest.fixture
def mock_config():
    """Diccionario de configuracion de referencia para las pruebas."""
    return {
        "DEBUG": True,
        "URL_GEO": "http://localhost:8080/geoserver",
        "WORKSPACE": _TEST_WORKSPACE,
        "GEO_USER": "admin",
        "GEO_PWD": "geoserver",
        "GEO_WORKSPACE": "deforestation",
        "MONGO_DB_NAME": "ganabosques_test",
        "MONGO_URI": "mongodb://localhost:27017/",
        "SPATIAL_PARAMETERS": {
            "xmin_ref": -79.22432089079678,
            "ymin_ref": -3.413815939872096,
            "xmax_ref": -66.65584054291094,
            "ymax_ref": 12.580743905000004,
            "res_ref": (30, 30),
            "dst_crs_ref": "EPSG:3116",
        },
    }
