"""
Unit tests for raster operations and data filtering.
"""

import pytest
import numpy as np
import rasterio
import tempfile
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rasterio.transform import from_bounds


class TestDataFiltering:
    """Tests for deforestation pixel filtering logic."""
    
    def test_filter_deforestation_pixels_equals_2(self):
        """Test filtering pixels where value == 2."""
        data = np.array([[0, 1, 2], [2, 3, 2]], dtype=np.float32)
        
        filtered = np.full(data.shape, np.nan, dtype='float32')
        mask = (data == 2)
        filtered[mask] = 2
        
        assert np.isnan(filtered[0, 0])
        assert np.isnan(filtered[0, 1])
        assert filtered[0, 2] == 2
        assert filtered[1, 0] == 2
        assert np.isnan(filtered[1, 1])
        assert filtered[1, 2] == 2
    
    def test_filter_all_zeros(self):
        """Test filtering when all values are 0."""
        data = np.zeros((10, 10), dtype=np.float32)
        
        filtered = np.full(data.shape, np.nan, dtype='float32')
        mask = (data == 2)
        filtered[mask] = 2
        
        assert np.isnan(filtered).all()
    
    def test_filter_all_deforestation(self):
        """Test filtering when all values are deforestation."""
        data = np.full((10, 10), 2.0, dtype=np.float32)
        
        filtered = np.full(data.shape, np.nan, dtype='float32')
        mask = (data == 2)
        filtered[mask] = 2
        
        assert np.allclose(filtered, 2.0)
    
    def test_filter_with_nodata_values(self):
        """Test filtering with nodata/NaN values in input."""
        data = np.array([[2, np.nan, 2], [1, 2, 0]], dtype=np.float32)
        
        filtered = np.full(data.shape, np.nan, dtype='float32')
        mask = (data == 2)
        filtered[mask] = 2
        
        assert filtered[0, 0] == 2
        assert np.isnan(filtered[0, 1])
        assert filtered[0, 2] == 2
        assert np.isnan(filtered[1, 0])
        assert filtered[1, 1] == 2
        assert np.isnan(filtered[1, 2])


class TestCumulativeAccumulation:
    """Tests for cumulative deforestation accumulation logic."""
    
    def test_simple_cumulative_sum(self):
        """Test simple cumulative sum."""
        current = np.array([[2, np.nan], [2, 2]], dtype='float32')
        previous = np.array([[2, 2], [np.nan, 2]], dtype='float32')
        
        current_masked = np.where(np.isnan(current), 0, current)
        prev_masked = np.where(np.isnan(previous), 0, previous)
        
        sum_data = current_masked + prev_masked
        
        assert sum_data[0, 0] == 4
        assert sum_data[0, 1] == 2
        assert sum_data[1, 0] == 2
        assert sum_data[1, 1] == 4
    
    def test_cumulative_with_thresholding(self):
        """Test cumulative sum with thresholding."""
        current_masked = np.array([[2, 0], [2, 0]], dtype='float32')
        prev_masked = np.array([[0, 2], [2, 2]], dtype='float32')
        
        sum_data = current_masked + prev_masked
        sum_data = np.where(sum_data > 2, 2, sum_data)
        sum_data = np.where(sum_data == 0, np.nan, sum_data)
        
        assert sum_data[0, 0] == 2  # 2+0=2
        assert sum_data[0, 1] == 2  # 0+2=2 (not > 2, so stays 2)
        assert sum_data[1, 0] == 2  # 2+2=4 > 2, so becomes 2
        assert sum_data[1, 1] == 2  # 0+2=2
    
    def test_cumulative_multiple_years(self):
        """Test cumulative accumulation over multiple years."""
        year1 = np.array([[2, np.nan, np.nan]], dtype='float32')
        year2 = np.array([[np.nan, 2, np.nan]], dtype='float32')
        year3 = np.array([[np.nan, np.nan, 2]], dtype='float32')
        
        cum1 = year1.copy()
        
        cum1_masked = np.where(np.isnan(cum1), 0, cum1)
        year2_masked = np.where(np.isnan(year2), 0, year2)
        cum2_data = cum1_masked + year2_masked
        cum2 = np.where(cum2_data > 2, 2, cum2_data)
        cum2 = np.where(cum2 == 0, np.nan, cum2)
        
        cum2_masked = np.where(np.isnan(cum2), 0, cum2)
        year3_masked = np.where(np.isnan(year3), 0, year3)
        cum3_data = cum2_masked + year3_masked
        cum3 = np.where(cum3_data > 2, 2, cum3_data)
        cum3 = np.where(cum3 == 0, np.nan, cum3)
        
        assert cum1[0, 0] == 2
        assert cum2[0, 0] == 2
        assert cum2[0, 1] == 2
        assert cum3[0, 0] == 2
        assert cum3[0, 1] == 2
        assert cum3[0, 2] == 2


class TestBlockWindowProcessing:
    """Tests for block window iteration and processing."""
    
    def test_block_window_iteration(self, temp_dir):
        """Test that block window iteration covers full raster."""
        width, height = 64, 64
        bounds = (0, 0, 100, 100)
        transform = from_bounds(*bounds, width, height)
        
        data = np.arange(height * width, dtype=np.float32).reshape((height, width))
        filepath = os.path.join(temp_dir, "test_blocks.tif")
        
        with rasterio.open(
            filepath, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform
        ) as dst:
            dst.write(data, 1)
        
        with rasterio.open(filepath) as src:
            total_pixels = 0
            for ji, window in src.block_windows(1):
                block_data = src.read(1, window=window)
                total_pixels += block_data.size
        
        assert total_pixels == height * width
    
    def test_block_processing_accumulation(self, temp_dir):
        """Test accumulating values across block windows."""
        width, height = 32, 32
        bounds = (0, 0, 100, 100)
        transform = from_bounds(*bounds, width, height)
        
        data = np.ones((height, width), dtype=np.float32) * 2
        input_path = os.path.join(temp_dir, "input.tif")
        output_path = os.path.join(temp_dir, "output.tif")
        
        with rasterio.open(
            input_path, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform
        ) as dst:
            dst.write(data, 1)
        
        with rasterio.open(input_path) as src:
            profile = src.profile.copy()
            profile.update(dtype='float32', nodata=None, compress='lzw')
            
            with rasterio.open(output_path, 'w', **profile) as dst:
                sum_total = 0
                for ji, window in src.block_windows(1):
                    block_data = src.read(1, window=window)
                    sum_total += np.sum(block_data)
                    dst.write(block_data, 1, window=window)
        
        expected_sum = height * width * 2
        assert sum_total == expected_sum
    
    def test_block_processing_with_filtering(self, temp_dir):
        """Test filtering during block window processing."""
        width, height = 32, 32
        bounds = (0, 0, 100, 100)
        transform = from_bounds(*bounds, width, height)
        
        data = np.array(np.random.randint(0, 5, (height, width)), dtype=np.float32)
        input_path = os.path.join(temp_dir, "input_mixed.tif")
        output_path = os.path.join(temp_dir, "output_filtered.tif")
        
        with rasterio.open(
            input_path, 'w', driver='GTiff', height=height, width=width, count=1,
            dtype=np.float32, crs='EPSG:4326', transform=transform
        ) as dst:
            dst.write(data, 1)
        
        with rasterio.open(input_path) as src:
            profile = src.profile.copy()
            profile.update(dtype='float32', nodata=None, compress='lzw')
            
            with rasterio.open(output_path, 'w', **profile) as dst:
                count_2 = 0
                for ji, window in src.block_windows(1):
                    block_data = src.read(1, window=window)
                    filtered = np.full(block_data.shape, np.nan, dtype='float32')
                    mask = (block_data == 2)
                    filtered[mask] = 2
                    count_2 += np.sum(mask)
                    dst.write(filtered, 1, window=window)
        
        original_count_2 = np.sum(data == 2)
        assert count_2 == original_count_2


class TestRasterProfile:
    """Tests for raster profile configuration."""
    
    def test_profile_dtype_update(self):
        """Test updating profile dtype to float32."""
        profile = {
            'dtype': 'uint8',
            'driver': 'GTiff',
            'height': 100,
            'width': 100,
        }
        
        profile.update({'dtype': 'float32', 'nodata': None, 'compress': 'lzw'})
        
        assert profile['dtype'] == 'float32'
        assert profile['nodata'] is None
        assert profile['compress'] == 'lzw'
        assert profile['height'] == 100
        assert profile['driver'] == 'GTiff'
    
    def test_profile_compression_options(self):
        """Test different compression options."""
        compressions = ['lzw', 'deflate', 'packbits']
        
        for compression in compressions:
            profile = {
                'dtype': 'float32',
                'compress': compression,
            }
            assert profile['compress'] == compression
