# Deforestation Data Processor

![GitHub release (latest by date)](https://img.shields.io/github/v/release/CIAT-DAPA/ganabosques_deforestation_data_processor) ![](https://img.shields.io/github/v/tag/CIAT-DAPA/ganabosques_deforestation_data_processor)

The Deforestation data processor works as an ETL (Extraction, Transformation and Loading) process designed to query and process the information coming from the Forest and Carbon Monitoring System (SMByC). Its main function is to extract pixels corresponding to areas with changes in vegetation cover, specifically deforestation events. Once extracted, these polygons are standardized to ensure their compatibility with subsequent analysis systems. The resulting information is stored in the MapServer container. 
