# 🌳 Deforestation Data Processor

![GitHub release (latest by date)](https://img.shields.io/github/v/release/CIAT-DAPA/ganabosques_deforestation_data_processor) ![](https://img.shields.io/github/v/tag/CIAT-DAPA/ganabosques_deforestation_data_processor)


## Descripcion: 

The **Deforestation data processor** works as an ETL (Extraction, Transformation and Loading) process designed to query and process the information coming from the Forest and Carbon Monitoring System (SMByC). Its main function is to extract pixels corresponding to areas with changes in vegetation cover, specifically deforestation events. Once extracted, these polygons are standardized to ensure their compatibility with subsequent analysis systems. The resulting information is stored in the MapServer container. 

The **Deforestation Data Processor** contains 5 modules, which are described below:

🧩 Modules Overview
The Deforestation Data Processor contains 5 modules, described below:

1. get_data_SMByC 📥
Automatically downloads raster layers by year from a temporal mosaic in GeoServer.
Inputs required:

    - 📅 years: list of years to query (e.g., [2012, 2013, 2014])

    - 📂 output_path: local folder where downloaded files will be saved

    - 🌐 geo: base URL of GeoServer (e.g., http://localhost:8080/geoserver)

    - 🗂 workspace: name of GeoServer workspace (e.g., deforestation)

    - 🖼 mosaic: name of the mosaic (e.g., smbyc)

2. quality_control ✔️
Loads output from get_data_SMByC and checks that raster files are not corrupted, properly processed, and non-empty.

3. spatial_processing 🌍
Loads results from quality_control and performs spatial processing:

    - 📏 Standardizes spatial extent (longitudes: -79.22 to -66.65, latitudes: -3.41 to 12.58)

    - 📐 Standardizes spatial resolution (~30 meters / 0.000273°)

    - 📌 Standardizes coordinate reference system (EPSG:4326)

    - 💾 Saves file with standardized spatial properties

4. calculate_deforestation 🌿
Loads results from spatial_processing and extracts deforestation pixels based on the source data layer.

    - Retains only deforestation pixels

    - Saves yearly information

    - Calculates cumulative deforestation

    - Saves results

5. save_deforestation 💾📡
Loads results from calculate_deforestation, builds a raster mosaic, publishes it on GeoServer, stores metadata in MongoDB, and cleans up temporary files.


## ⚙️ Features
- 🧩 Modular design focused on geospatial processing

-  🗄 Developed with MongoEngine for document mapping on MongoDB

- 🌐 Integrated with GeoServer for geospatial data management and publishing

- 🐍 Compatible with Python > 3.10

- 🏗 Designed for integration into GANABOSQUES infrastructure

## Requirements
- Python > 3.10
- MongoDB (for managing deforestation records)
- Full integration with the GeoServer REST API for publishing, updating, and managing raster mosaics.
- GeoServer runs inside a Docker container, which facilitates portability and deployment across different environments.

## 🚀 Installation
1.  Clone repository 
 ```bash
 git clone https://github.com/CIAT-DAPA/ganabosques_deforestation_data_processor.git
 ```
2. Create  a virtual environment
```bash
 python -m venv envt
 ```

3. Ativate a virtual environment
```bash
 venv\Scripts\activate
```

4. Install the dependencies
 ```bash
pip install -r requirements.txt
```
## 🛠 Environment Configuration
1. Creating a .env file in your project
2. Setting environment variables directly in your system

#### Option 1: Using .env file

Create a file named .env with these configurations:

 ```bash
URL_GEO=http://localhost:8600/geoserver
WORKSPACE=D:/OneDrive - CGIAR/Desktop/ganabosques/deforestacion
GEO_USER=admin
GEO_PWD=geoserver
GEO_WORKSPACE=deforestation
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=ganabosques
```
#### Option 2: Setting Environment Variables
- Windows (CMD/PowerShell)
 ```bash
set URL_GEO=http://localhost:8600/geoserver
set WORKSPACE=D:/OneDrive - CGIAR/Desktop/ganabosques/deforestacion
set GEO_USER=admin
set GEO_PWD=geoserver
set GEO_WORKSPACE=deforestation
set MONGO_URI=mongodb://localhost:27017
set MONGO_DB_NAME=ganabosques
```
- Linux/Ubuntu (Terminal)
export 

 ```bash
export URL_GEO=http:"//localhost:8600/geoserver"
export WORKSPACE="D:/OneDrive - CGIAR/Desktop/ganabosques/deforestacion"
export GEO_USER="admin"
export GEO_PWD="geoserver"
export GEO_WORKSPACE="deforestation"
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB_NAME="ganabosques"
```

#### 💡 Notes
 - Replace GEO_USER, GEO_PWD with your actual credentials.
 - URL_GEO refers to the URL of the GeoServer instance enabled through Docker.
 - WORKSPACE refers to the local path where the results are to be temporarily stored.
 - GEO_WORKSPACE refers to the name of the GeoServer workspace, which must be created before running the code.
 - MONGO_URI refers to the MongoDB URL enabled through Docker.
 - MONGO_DB_NAME refers to the database where the information is stored within MongoDB.

## ▶️ Running the modules
```bash
Windows CMD o PowerShell
py deforestation\src\main.py

Linux, macOS o Git Bash
python3 deforestation/src/main.py
```


