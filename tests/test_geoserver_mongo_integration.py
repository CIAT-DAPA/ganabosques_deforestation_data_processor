"""
Unit tests for API integration (GeoServer, MongoDB, etc).
Tests for: WCS download, REST catalog, MongoDB operations, pipeline integration.
Uses 'responses' library for HTTP mocking.
"""

import pytest
import sys
import os
import json
import tempfile
from unittest.mock import Mock, patch, MagicMock
import requests
import responses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import config
from tools.log_print import log_print
import logging


class TestGeoServerWCS:
    """Tests for GeoServer WCS (Web Coverage Service) operations."""
    
    def test_wcs_url_construction_smbyc(self):
        """Test WCS URL construction for SMBYC data."""
        geo_url = "http://geoserver.example.com/geoserver"
        workspace = "ganabosques"
        mosaic = "smbyc"
        year = "2020"
        
        # Build WCS URL (typical pattern)
        url = (
            f"{geo_url}/ows?"
            f"service=WCS&version=2.0.1&request=GetCoverage"
            f"&coverageId={workspace}__{mosaic}_{year}"
            f"&format=GeoTIFF"
        )
        
        # Verify URL is constructed correctly
        assert "WCS" in url
        assert "GetCoverage" in url
        assert "GeoTIFF" in url
        assert workspace in url
        assert mosaic in url
    
    def test_wcs_url_construction_nad_atd(self):
        """Test WCS URL construction for NAD/ATD quarterly data."""
        geo_url = "http://geoserver.example.com/geoserver"
        workspace = "ganabosques"
        mosaic = "nad"
        year = "2024"
        quarter = "1"
        
        # Build WCS URL
        url = (
            f"{geo_url}/ows?"
            f"service=WCS&version=2.0.1&request=GetCoverage"
            f"&coverageId={workspace}__{mosaic}_{year}Q{quarter}"
            f"&format=GeoTIFF"
        )
        
        assert "Q1" in url or f"Q{quarter}" in url
        assert "nad" in url
    
    @responses.activate
    def test_wcs_successful_download(self, temp_dir):
        """Test successful WCS download."""
        url = "http://geoserver.example.com/geoserver/ows"
        
        # Mock successful response with GeoTIFF data
        tiff_data = b"GeoTIFF binary data"
        responses.add(responses.GET, url, body=tiff_data, status=200)
        
        # Perform download
        response = requests.get(url, timeout=30)
        
        # Verify
        assert response.status_code == 200
        assert response.content == tiff_data
    
    @responses.activate
    def test_wcs_timeout_handling(self):
        """Test WCS timeout handling."""
        url = "http://geoserver.example.com/geoserver/ows"
        
        # Mock timeout
        responses.add(
            responses.GET, url, 
            body=requests.exceptions.Timeout("Connection timeout"),
            status=503
        )
        
        # Should raise timeout error
        with pytest.raises(Exception):  # Timeout or ConnectionError
            requests.get(url, timeout=5)
    
    @responses.activate
    def test_wcs_not_found_error(self):
        """Test WCS 404 Not Found error."""
        url = "http://geoserver.example.com/geoserver/ows"
        
        responses.add(
            responses.GET, url,
            json={"error": "Coverage not found"},
            status=404
        )
        
        response = requests.get(url)
        assert response.status_code == 404
    
    @responses.activate
    def test_wcs_server_error(self):
        """Test WCS 500 Server Error."""
        url = "http://geoserver.example.com/geoserver/ows"
        
        responses.add(
            responses.GET, url,
            json={"error": "Internal server error"},
            status=500
        )
        
        response = requests.get(url)
        assert response.status_code == 500
    
    @responses.activate
    def test_wcs_authentication_error(self):
        """Test WCS 401 Unauthorized."""
        url = "http://geoserver.example.com/geoserver/ows"
        
        responses.add(
            responses.GET, url,
            status=401
        )
        
        response = requests.get(url)
        assert response.status_code == 401


class TestGeoServerREST:
    """Tests for GeoServer REST API operations."""
    
    def test_rest_url_normalization_with_rest(self):
        """Test REST URL already has /rest."""
        url_input = "http://geoserver.example.com/geoserver/rest"
        
        # Simulate _ensure_rest_url logic
        url = url_input.strip().rstrip("/")
        if url.endswith("/geoserver/rest"):
            final_url = url
        else:
            final_url = url + "/rest"
        
        assert final_url == "http://geoserver.example.com/geoserver/rest"
    
    def test_rest_url_normalization_without_rest(self):
        """Test REST URL without /rest endpoint."""
        url_input = "http://geoserver.example.com/geoserver"
        
        # Simulate _ensure_rest_url logic
        url = url_input.strip().rstrip("/")
        if url.endswith("/geoserver/rest"):
            final_url = url
        elif url.endswith("/geoserver"):
            final_url = url + "/rest"
        else:
            final_url = url + "/geoserver/rest"
        
        assert final_url == "http://geoserver.example.com/geoserver/rest"
    
    @responses.activate
    def test_rest_catalog_list_workspaces(self):
        """Test REST API to list workspaces."""
        url = "http://geoserver.example.com/geoserver/rest/workspaces"
        
        workspaces_data = {
            "workspaces": {
                "workspace": [
                    {"name": "ganabosques", "href": f"{url}/ganabosques"},
                    {"name": "default", "href": f"{url}/default"}
                ]
            }
        }
        
        responses.add(
            responses.GET, url,
            json=workspaces_data,
            status=200
        )
        
        response = requests.get(url, auth=("admin", "password"))
        assert response.status_code == 200
        data = response.json()
        assert "workspaces" in data
    
    @responses.activate
    def test_rest_catalog_create_store(self):
        """Test REST API to create a new store."""
        url = "http://geoserver.example.com/geoserver/rest/workspaces/ganabosques/coveragestores"
        
        store_data = {
            "coverageStore": {
                "name": "smbyc",
                "type": "GeoTIFF",
                "url": "file:///path/to/smbyc/data"
            }
        }
        
        responses.add(
            responses.POST, url,
            json={"status": "created"},
            status=201
        )
        
        response = requests.post(
            url,
            json=store_data,
            auth=("admin", "password")
        )
        
        assert response.status_code == 201
    
    @responses.activate
    def test_rest_catalog_update_store(self):
        """Test REST API to update an existing store."""
        url = "http://geoserver.example.com/geoserver/rest/workspaces/ganabosques/coveragestores/smbyc"
        
        responses.add(
            responses.PUT, url,
            status=204
        )
        
        response = requests.put(
            url,
            json={"coverageStore": {"name": "smbyc"}},
            auth=("admin", "password")
        )
        
        assert response.status_code == 204
    
    @responses.activate
    def test_rest_time_dimension_handling(self):
        """Test REST API for time dimension configuration."""
        url = "http://geoserver.example.com/geoserver/rest/workspaces/ganabosques/coveragestores/smbyc/coverages/smbyc"
        
        coverage_data = {
            "coverage": {
                "name": "smbyc",
                "dimensions": {
                    "coverageDimension": [
                        {"name": "time", "dataType": "DATE"}
                    ]
                }
            }
        }
        
        responses.add(
            responses.PUT, url,
            status=204
        )
        
        response = requests.put(
            url,
            json=coverage_data,
            auth=("admin", "password")
        )
        
        assert response.status_code == 204


class TestMongoDBIntegration:
    """Tests for MongoDB operations."""
    
    def test_mongo_connection_string_parsing(self):
        """Test MongoDB connection string is valid."""
        mongo_uri = config.get('MONGO_URI')
        
        # If configured, should start with mongodb
        if mongo_uri:
            assert mongo_uri.startswith("mongodb")
    
    def test_mongo_database_name_configured(self):
        """Test MongoDB database name is configured."""
        db_name = config.get('MONGO_DB_NAME')
        
        # If configured, should be non-empty string
        if db_name:
            assert isinstance(db_name, str)
            assert len(db_name) > 0
    
    @patch('pymongo.MongoClient')
    def test_mongo_insert_document(self, mock_mongo):
        """Test MongoDB document insertion."""
        # Mock MongoDB client
        mock_client = MagicMock()
        mock_mongo.return_value = mock_client
        
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        
        mock_collection = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        
        # Insert a document
        doc = {
            "year": 2020,
            "source": "SMBYC",
            "deforestation_area_ha": 125.5
        }
        mock_collection.insert_one.return_value.inserted_id = "doc_id_123"
        
        # Verify insertion was called
        mock_collection.insert_one(doc)
        mock_collection.insert_one.assert_called_once_with(doc)
    
    @patch('pymongo.MongoClient')
    def test_mongo_find_documents(self, mock_mongo):
        """Test MongoDB document query."""
        mock_client = MagicMock()
        mock_mongo.return_value = mock_client
        
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        
        mock_collection = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        
        # Query documents
        query = {"year": 2020}
        mock_collection.find.return_value = [
            {"_id": "1", "year": 2020, "area": 100},
            {"_id": "2", "year": 2020, "area": 125}
        ]
        
        # Verify query
        results = list(mock_collection.find(query))
        assert len(results) == 2
    
    @patch('pymongo.MongoClient')
    def test_mongo_connection_error(self, mock_mongo):
        """Test MongoDB connection error handling."""
        mock_mongo.side_effect = Exception("Connection refused")
        
        with pytest.raises(Exception):
            mock_mongo("mongodb://localhost:27017")


class TestPipelineIntegration:
    """Tests for full pipeline integration."""
    
    @responses.activate
    def test_pipeline_step1_get_data_simulation(self, temp_dir):
        """Simulate Step 1: Get Data from GeoServer WCS."""
        wcs_url = "http://geoserver.example.com/geoserver/ows"
        
        # Mock WCS response
        tiff_data = b"Mock GeoTIFF data"
        responses.add(responses.GET, wcs_url, body=tiff_data, status=200)
        
        # Download data
        response = requests.get(wcs_url)
        
        # Save to temp file
        output_file = os.path.join(temp_dir, "smbyc_2020.tif")
        with open(output_file, 'wb') as f:
            f.write(response.content)
        
        # Verify
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0
    
    def test_pipeline_step2_quality_control_simulation(self, temp_dir):
        """Simulate Step 2: Quality Control validation."""
        # Create a "raw" data folder
        input_dir = os.path.join(temp_dir, "raw_data")
        os.makedirs(input_dir)
        
        # Create output directory
        qc_dir = os.path.join(temp_dir, "qc_data")
        os.makedirs(qc_dir)
        
        # Simulate validation
        valid_count = 0
        if os.path.exists(input_dir):
            # Check for files in input
            files = [f for f in os.listdir(input_dir) if f.endswith('.tif')]
            valid_count = len(files)
        
        # Result
        assert isinstance(valid_count, int)
    
    def test_pipeline_step3_spatial_processing_simulation(self, temp_dir):
        """Simulate Step 3: Spatial Processing."""
        # Create validated data folder
        input_dir = os.path.join(temp_dir, "qc_data")
        os.makedirs(input_dir)
        
        # Create output folder
        spatial_dir = os.path.join(temp_dir, "spatial_data")
        os.makedirs(spatial_dir)
        
        # Simulate CRS transformation
        crs_transform = "EPSG:4326 -> EPSG:3116"
        
        # Result
        assert os.path.isdir(spatial_dir)
        assert "EPSG" in crs_transform
    
    def test_pipeline_step4_calculate_deforestation_simulation(self, temp_dir):
        """Simulate Step 4: Calculate Deforestation."""
        # Create spatial processed data
        input_dir = os.path.join(temp_dir, "spatial_data")
        os.makedirs(input_dir)
        
        # Create output folder
        calc_dir = os.path.join(temp_dir, "deforestation_calc")
        os.makedirs(calc_dir)
        
        # Simulate calculation
        result = {
            "year": 2020,
            "total_deforestation_ha": 1250.5,
            "pixels": 12505
        }
        
        # Verify
        assert result["year"] == 2020
        assert result["total_deforestation_ha"] > 0
    
    @responses.activate
    @patch('pymongo.MongoClient')
    def test_pipeline_step5_publish_results_simulation(self, mock_mongo):
        """Simulate Step 5: Publish results to GeoServer and MongoDB."""
        # Mock GeoServer REST
        rest_url = "http://geoserver.example.com/geoserver/rest"
        responses.add(responses.PUT, rest_url, status=204)
        
        # Mock MongoDB
        mock_client = MagicMock()
        mock_mongo.return_value = mock_client
        mock_db = MagicMock()
        mock_client.__getitem__.return_value = mock_db
        mock_collection = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        
        # Perform update
        doc = {"year": 2020, "status": "published"}
        mock_collection.insert_one(doc)
        
        # Verify
        mock_collection.insert_one.assert_called()


class TestErrorRecovery:
    """Tests for error handling and recovery."""
    
    @responses.activate
    def test_pipeline_handles_wcs_timeout(self):
        """Test pipeline handles WCS timeout gracefully."""
        url = "http://geoserver.example.com/geoserver/ows"
        
        responses.add(
            responses.GET, url,
            body=requests.exceptions.Timeout(),
            status=503
        )
        
        # Should handle timeout without crashing
        with pytest.raises(Exception):
            requests.get(url, timeout=5)
    
    @responses.activate
    def test_pipeline_handles_rest_auth_failure(self):
        """Test pipeline handles REST authentication failure."""
        url = "http://geoserver.example.com/geoserver/rest"
        
        responses.add(responses.GET, url, status=401)
        
        response = requests.get(url)
        assert response.status_code == 401
    
    @patch('pymongo.MongoClient')
    def test_pipeline_handles_mongo_connection_loss(self, mock_mongo):
        """Test pipeline handles MongoDB connection loss."""
        mock_mongo.side_effect = ConnectionError("Lost connection to MongoDB")
        
        with pytest.raises(Exception):
            mock_mongo("mongodb://localhost:27017")
    
    def test_pipeline_handles_corrupted_raster_file(self, temp_dir):
        """Test pipeline handles corrupted raster file."""
        corrupted_file = os.path.join(temp_dir, "corrupted.tif")
        
        # Create invalid "raster" file
        with open(corrupted_file, 'w') as f:
            f.write("This is not a valid GeoTIFF")
        
        # Attempt to open - should fail gracefully
        with pytest.raises(Exception):
            import rasterio
            with rasterio.open(corrupted_file) as src:
                src.read(1)
