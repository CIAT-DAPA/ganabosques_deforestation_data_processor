"""
Global pytest configuration and fixtures for Ganabosques testing suite.
Tests directory configuration - simple flat structure.
"""

import pytest
import os
import sys
import tempfile
import numpy as np
import rasterio
from rasterio.transform import from_bounds

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def temp_dir():
    """Temporary directory that gets cleaned up after test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def synthetic_raster_epsg4326(temp_dir):
    """
    Create a synthetic 32x32 GeoTIFF in EPSG:4326.
    - Bounds: -79.22 to -66.65 (lon), -3.41 to 12.58 (lat)
    - Resolution: ~0.000273° (approximately 30m)
    - CRS: EPSG:4326
    """
    width, height = 32, 32
    bounds = (-79.22, -3.41, -66.65, 12.58)
    
    # Create transform
    transform = from_bounds(*bounds, width, height)
    
    # Create synthetic data: raster with some deforestation pixels (value=2)
    data = np.zeros((height, width), dtype=np.float32)
    # Add some deforestation pixels
    data[5:15, 5:15] = 2.0
    data[20:25, 20:25] = 2.0
    
    filepath = os.path.join(temp_dir, "synthetic_4326.tif")
    
    with rasterio.open(
        filepath,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=np.float32,
        crs='EPSG:4326',
        transform=transform,
        nodata=np.nan,
        compress='lzw'
    ) as dst:
        dst.write(data, 1)
    
    return filepath


@pytest.fixture
def synthetic_raster_epsg3116(temp_dir):
    """
    Create a synthetic 32x32 GeoTIFF in EPSG:3116 (Colombia).
    - Resolution: 30 meters
    - CRS: EPSG:3116
    """
    width, height = 32, 32
    # Approximate bounds in EPSG:3116 (meters)
    bounds = (800000, 500000, 800960, 500960)
    
    transform = from_bounds(*bounds, width, height)
    
    # Create synthetic data
    data = np.zeros((height, width), dtype=np.float32)
    data[8:24, 8:24] = 2.0
    
    filepath = os.path.join(temp_dir, "synthetic_3116.tif")
    
    with rasterio.open(
        filepath,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=np.float32,
        crs='EPSG:3116',
        transform=transform,
        nodata=np.nan,
        compress='lzw'
    ) as dst:
        dst.write(data, 1)
    
    return filepath


@pytest.fixture
def synthetic_rasters_multiple_4326(temp_dir):
    """
    Create multiple overlapping rasters in EPSG:4326 with different extents.
    Returns a list of file paths.
    """
    rasters = []
    
    # Raster 1: Left side
    bounds1 = (-79.22, -3.41, -73.0, 12.58)
    data1 = np.random.randint(0, 3, (32, 32), dtype=np.int32).astype(np.float32)
    filepath1 = os.path.join(temp_dir, "raster1_left.tif")
    _save_raster(filepath1, bounds1, data1, 'EPSG:4326')
    rasters.append(filepath1)
    
    # Raster 2: Right side (overlapping)
    bounds2 = (-73.5, -3.41, -66.65, 12.58)
    data2 = np.random.randint(0, 3, (32, 32), dtype=np.int32).astype(np.float32)
    filepath2 = os.path.join(temp_dir, "raster2_right.tif")
    _save_raster(filepath2, bounds2, data2, 'EPSG:4326')
    rasters.append(filepath2)
    
    # Raster 3: Center (overlapping both)
    bounds3 = (-75.0, 0.0, -70.0, 8.0)
    data3 = np.random.randint(0, 3, (32, 32), dtype=np.int32).astype(np.float32)
    filepath3 = os.path.join(temp_dir, "raster3_center.tif")
    _save_raster(filepath3, bounds3, data3, 'EPSG:4326')
    rasters.append(filepath3)
    
    return rasters


@pytest.fixture
def empty_raster(temp_dir):
    """Create an empty raster (all zeros)."""
    width, height = 32, 32
    bounds = (-79.22, -3.41, -66.65, 12.58)
    transform = from_bounds(*bounds, width, height)
    
    data = np.zeros((height, width), dtype=np.float32)
    
    filepath = os.path.join(temp_dir, "empty_raster.tif")
    
    with rasterio.open(
        filepath,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=np.float32,
        crs='EPSG:4326',
        transform=transform,
        nodata=0.0,
        compress='lzw'
    ) as dst:
        dst.write(data, 1)
    
    return filepath


@pytest.fixture
def mock_config():
    """Mock configuration dictionary."""
    return {
        'DEBUG': True,
        'URL_GEO': 'http://localhost:8080/geoserver',
        'WORKSPACE': '/tmp/ganabosques',
        'GEO_USER': 'admin',
        'GEO_PWD': 'geoserver',
        'GEO_WORKSPACE': 'deforestation',
        'MONGO_DB_NAME': 'ganabosques_test',
        'MONGO_URI': 'mongodb://localhost:27017/',
        'SPATIAL_PARAMETERS': {
            'xmin_ref': -79.22432089079678,
            'ymin_ref': -3.413815939872096,
            'xmax_ref': -66.65584054291094,
            'ymax_ref': 12.580743905000004,
            'res_ref': (30, 30),
            'dst_crs_ref': 'EPSG:3116',
        }
    }


def _save_raster(filepath, bounds, data, crs):
    """Helper to save a raster with given parameters."""
    height, width = data.shape
    transform = from_bounds(*bounds, width, height)
    
    with rasterio.open(
        filepath,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
        nodata=np.nan,
        compress='lzw'
    ) as dst:
        dst.write(data, 1)
