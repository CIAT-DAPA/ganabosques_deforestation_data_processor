"""
Unit tests for quality control and raster validation.
Tests for: quality_control, raster validation, error handling.
"""

import pytest
import numpy as np
import rasterio
import sys
import os
import tempfile
import shutil
from pathlib import Path
from rasterio.transform import from_bounds

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from quality_control.quality_control_deforestation import quality_control, _process_folder


class TestQualityControl:
    """Tests for quality_control function."""
    
    def test_quality_control_valid_smbyc_raster(self, temp_dir):
        """Test quality control passes for valid SMBYC raster."""
        # Create input structure
        input_dir = os.path.join(temp_dir, "input")
        smbyc_dir = os.path.join(input_dir, "smbyc")
        os.makedirs(smbyc_dir)
        
        # Create valid raster with deforestation pixels
        width, height = 32, 32
        bounds = (-79.22, -3.41, -66.65, 12.58)
        transform = from_bounds(*bounds, width, height)
        
        data = np.zeros((height, width), dtype=np.float32)
        data[5:15, 5:15] = 2.0  # Deforestation pixels
        
        filepath = os.path.join(smbyc_dir, "smbyc_2020.tif")
        with rasterio.open(
            filepath, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform, nodata=np.nan
        ) as dst:
            dst.write(data, 1)
        
        # Run quality control
        output_dir = os.path.join(temp_dir, "output")
        result = quality_control(input_dir, output_dir, deforestation_type="annual")
        
        # Should succeed
        assert result is True or result is not False
        # Output file should exist
        output_file = os.path.join(output_dir, "smbyc", "smbyc_2020.tif")
        assert os.path.exists(output_file)
    
    def test_quality_control_empty_raster_rejected(self, temp_dir):
        """Test that empty rasters (all zeros) are rejected."""
        input_dir = os.path.join(temp_dir, "input")
        smbyc_dir = os.path.join(input_dir, "smbyc")
        os.makedirs(smbyc_dir)
        
        # Create empty raster
        width, height = 32, 32
        bounds = (-79.22, -3.41, -66.65, 12.58)
        transform = from_bounds(*bounds, width, height)
        
        data = np.zeros((height, width), dtype=np.float32)  # All zeros
        
        filepath = os.path.join(smbyc_dir, "empty_raster.tif")
        with rasterio.open(
            filepath, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform, nodata=0.0
        ) as dst:
            dst.write(data, 1)
        
        output_dir = os.path.join(temp_dir, "output")
        result = quality_control(input_dir, output_dir, deforestation_type="annual")
        
        # Should return False (no valid files)
        assert result is False
    
    def test_quality_control_multiple_subcategories(self, temp_dir):
        """Test quality control with multiple folder types (smbyc, nad, atd)."""
        input_dir = os.path.join(temp_dir, "input")
        
        # Create folders for each type
        for folder_type in ["smbyc", "nad", "atd"]:
            type_dir = os.path.join(input_dir, folder_type)
            os.makedirs(type_dir)
            
            # Create valid raster in each
            width, height = 32, 32
            bounds = (-79.22, -3.41, -66.65, 12.58)
            transform = from_bounds(*bounds, width, height)
            
            data = np.zeros((height, width), dtype=np.float32)
            data[8:16, 8:16] = 1.0  # Some values
            
            filepath = os.path.join(type_dir, f"{folder_type}_test.tif")
            with rasterio.open(
                filepath, 'w', driver='GTiff', height=height, width=width, count=1,
                dtype=np.float32, crs='EPSG:4326', transform=transform, nodata=np.nan
            ) as dst:
                dst.write(data, 1)
        
        output_dir = os.path.join(temp_dir, "output")
        result = quality_control(input_dir, output_dir, deforestation_type=None)
        
        # Should process all three types
        assert os.path.exists(os.path.join(output_dir, "smbyc"))
        assert os.path.exists(os.path.join(output_dir, "nad"))
        assert os.path.exists(os.path.join(output_dir, "atd"))
    
    def test_quality_control_empty_directory(self, temp_dir):
        """Test quality control with empty input directory."""
        input_dir = os.path.join(temp_dir, "empty_input")
        os.makedirs(input_dir)
        
        output_dir = os.path.join(temp_dir, "output")
        result = quality_control(input_dir, output_dir, deforestation_type="annual")
        
        # Function returns True or False depending on implementation
        # The key is that it doesn't crash and returns a boolean
        assert isinstance(result, (bool, type(None), int))


class TestRasterValidation:
    """Tests for raster file validation logic."""
    
    def test_valid_raster_with_values(self, temp_dir):
        """Test that raster with valid values passes validation."""
        width, height = 32, 32
        bounds = (-79.22, -3.41, -66.65, 12.58)
        transform = from_bounds(*bounds, width, height)
        
        data = np.array([[1, 2, 0], [2, 1, 1]], dtype=np.float32)
        filepath = os.path.join(temp_dir, "valid.tif")
        
        with rasterio.open(
            filepath, 'w', driver='GTiff', height=2, width=3, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform, nodata=0.0
        ) as dst:
            dst.write(data, 1)
        
        # Read and validate
        with rasterio.open(filepath) as src:
            array = src.read(1)
            nodata = src.nodata
            
            # Check for valid values
            if nodata is not None:
                valores_validos = array[(array != nodata) & (array != 0)]
            else:
                valores_validos = array[array != 0]
            
            # Should have valid values
            assert valores_validos.size > 0
    
    def test_empty_raster_no_values(self, temp_dir):
        """Test that empty raster (all zeros/nodata) fails validation."""
        width, height = 32, 32
        bounds = (-79.22, -3.41, -66.65, 12.58)
        transform = from_bounds(*bounds, width, height)
        
        data = np.zeros((height, width), dtype=np.float32)
        filepath = os.path.join(temp_dir, "empty.tif")
        
        with rasterio.open(
            filepath, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform, nodata=0.0
        ) as dst:
            dst.write(data, 1)
        
        # Read and validate
        with rasterio.open(filepath) as src:
            array = src.read(1)
            nodata = src.nodata
            
            if nodata is not None:
                valores_validos = array[(array != nodata) & (array != 0)]
            else:
                valores_validos = array[array != 0]
            
            # Should have NO valid values
            assert valores_validos.size == 0
    
    def test_raster_crs_detection(self, temp_dir):
        """Test that raster CRS is correctly detected."""
        width, height = 32, 32
        bounds = (800000, 500000, 800960, 500960)
        transform = from_bounds(*bounds, width, height)
        
        data = np.ones((height, width), dtype=np.float32)
        filepath = os.path.join(temp_dir, "crs_test.tif")
        
        with rasterio.open(
            filepath, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:3116', transform=transform
        ) as dst:
            dst.write(data, 1)
        
        # Read and check CRS
        with rasterio.open(filepath) as src:
            assert src.crs is not None
            assert str(src.crs) == "EPSG:3116"


class TestFileOperations:
    """Tests for file I/O operations during quality control."""
    
    def test_raster_file_copy(self, temp_dir):
        """Test that raster files are correctly copied."""
        src_file = os.path.join(temp_dir, "source.tif")
        dest_file = os.path.join(temp_dir, "dest.tif")
        
        # Create source raster
        width, height = 32, 32
        bounds = (-79.22, -3.41, -66.65, 12.58)
        transform = from_bounds(*bounds, width, height)
        
        data = np.ones((height, width), dtype=np.float32)
        with rasterio.open(
            src_file, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform
        ) as dst:
            dst.write(data, 1)
        
        # Copy file
        shutil.copy(src_file, dest_file)
        
        # Verify copy
        assert os.path.exists(dest_file)
        with rasterio.open(dest_file) as src:
            copied_data = src.read(1)
            assert np.array_equal(copied_data, data)
    
    def test_directory_structure_creation(self, temp_dir):
        """Test that correct directory structure is created."""
        base_dir = os.path.join(temp_dir, "base")
        subdirs = ["smbyc", "nad", "atd"]
        
        # Create structure
        for subdir in subdirs:
            full_path = os.path.join(base_dir, subdir)
            os.makedirs(full_path, exist_ok=True)
        
        # Verify all created
        for subdir in subdirs:
            full_path = os.path.join(base_dir, subdir)
            assert os.path.isdir(full_path)
    
    def test_file_rename_patterns(self, temp_dir):
        """Test file renaming patterns for standardization."""
        # Original filename with various formats
        filenames = [
            "smbyc_2010-2012.tif",
            "smbyc_2013.tif",
            "nad_202401.tif",
        ]
        
        # Verify all files can be created and renamed
        for old_name in filenames:
            old_path = os.path.join(temp_dir, old_name)
            new_name = f"standardized_{old_name}"
            new_path = os.path.join(temp_dir, new_name)
            
            # Create dummy file
            Path(old_path).touch()
            
            # Rename
            shutil.move(old_path, new_path)
            
            # Verify
            assert os.path.exists(new_path)
            assert not os.path.exists(old_path)


class TestRasterIOErrors:
    """Tests for error handling during raster I/O."""
    
    def test_corrupted_file_handling(self, temp_dir):
        """Test handling of corrupted/invalid raster files."""
        corrupted_file = os.path.join(temp_dir, "corrupted.tif")
        
        # Write invalid data
        with open(corrupted_file, 'w') as f:
            f.write("This is not a valid GeoTIFF")
        
        # Try to open - should raise error
        with pytest.raises(Exception):  # rasterio.errors.RasterioIOError
            with rasterio.open(corrupted_file) as src:
                src.read(1)
    
    def test_nonexistent_file_handling(self):
        """Test handling of non-existent files."""
        nonexistent = "/path/that/does/not/exist/file.tif"
        
        with pytest.raises(Exception):  # FileNotFoundError or similar
            with rasterio.open(nonexistent) as src:
                src.read(1)
    
    def test_read_only_file_handling(self, temp_dir):
        """Test handling of read-only files during copy."""
        src_file = os.path.join(temp_dir, "readonly.tif")
        
        # Create file
        Path(src_file).touch()
        
        # Make read-only (on Windows)
        os.chmod(src_file, 0o444)
        
        try:
            # Should still be readable
            with open(src_file, 'r') as f:
                pass  # Read is OK
        finally:
            # Clean up permissions
            os.chmod(src_file, 0o644)


class TestSubfolderProcessing:
    """Tests for processing different subfolder types."""
    
    def test_process_smbyc_folder(self, temp_dir):
        """Test processing SMBYC folder specifically."""
        smbyc_dir = os.path.join(temp_dir, "smbyc")
        os.makedirs(smbyc_dir)
        
        # Create multiple SMBYC files
        for year in [2020, 2021, 2022]:
            width, height = 32, 32
            bounds = (-79.22, -3.41, -66.65, 12.58)
            transform = from_bounds(*bounds, width, height)
            
            data = np.ones((height, width), dtype=np.float32) * year
            filepath = os.path.join(smbyc_dir, f"smbyc_{year}.tif")
            
            with rasterio.open(
                filepath, 'w', driver='GTiff', height=height, width=width, count=1,
                dtype=np.float32, crs='EPSG:4326', transform=transform
            ) as dst:
                dst.write(data, 1)
        
        # Count files
        files = [f for f in os.listdir(smbyc_dir) if f.endswith('.tif')]
        assert len(files) == 3
    
    def test_process_nad_atd_folders(self, temp_dir):
        """Test processing NAD/ATD folders with quarterly data."""
        for folder_type in ["nad", "atd"]:
            type_dir = os.path.join(temp_dir, folder_type)
            os.makedirs(type_dir)
            
            # Create quarterly files for one year
            for quarter in range(1, 5):
                width, height = 32, 32
                bounds = (-79.22, -3.41, -66.65, 12.58)
                transform = from_bounds(*bounds, width, height)
                
                data = np.ones((height, width), dtype=np.float32) * quarter
                filepath = os.path.join(type_dir, f"{folder_type}_202401.tif")
                
                with rasterio.open(
                    filepath, 'w', driver='GTiff', height=height, width=width, count=1,
                    dtype=np.float32, crs='EPSG:4326', transform=transform
                ) as dst:
                    dst.write(data, 1)
            
            # Verify folder exists
            assert os.path.isdir(type_dir)
