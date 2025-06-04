import os
from dotenv import load_dotenv

load_dotenv()

config = {}

config['DEBUG'] = os.getenv('DEBUG', 'true').lower() == 'true'
config['URL_GEO'] = os.getenv("URL_GEO")
config['WORKSPACE'] = os.getenv('WORKSPACE')
config['GEO_USER'] = os.getenv("GEO_USER")
config['GEO_PWD'] = os.getenv("GEO_PWD")
config['GEO_WORKSPACE'] = os.getenv("GEO_WORKSPACE")
config['MONGO_DB_NAME'] = os.getenv("MONGO_DB_NAME")
config['MONGO_URI'] = os.getenv("MONGO_URI")

config['STORES'] = {
    'raw': 'smbyc',
    'annual': 'smbyc_deforestation_annual',
    'cumulative': 'smbyc_deforestation_cumulative',
}

config['NAMING_PATTERNS'] = {
    'raw': 'smbyc_{year}.tiff',
    'annual': 'smbyc_deforestation_annual_{year}.tiff',
    'cumulative': 'smbyc_deforestation_cumulative_{year}.tiff',
}

config["SPATIAL_PARAMETERS"]= {
    'xmin_ref': -79.22432089079678,
    'ymin_ref':-3.413815939872096,
    'xmax_ref': -66.65584054291094,
    'ymax_ref': 12.580743905000004,
    'res_ref' : (0.000273037894245, 0.000273037894245),
    'dst_crs_ref' : 'EPSG:4326',
}

if __name__ == "__main__":
    print(config)