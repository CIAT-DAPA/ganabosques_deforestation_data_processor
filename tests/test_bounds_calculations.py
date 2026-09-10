"""
Unit tests for spatial processing and bounds calculations.
"""

import pytest
import numpy as np
import rasterio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from spatial_processing.spatial_proccesing import (
    _intersect_bounds,
    _build_grid,
    _apply_nad_atd_reclass_block,
    _fixed_bounds_to_dst_crs,
    _calculate_common_intersection_bounds,
)


class TestIntersectBounds:
    """Tests for _intersect_bounds function."""
    
    def test_valid_intersection(self):
        """Test valid intersection of two bounds."""
        bounds_a = (0, 0, 10, 10)
        bounds_b = (5, 5, 15, 15)
        
        result = _intersect_bounds(bounds_a, bounds_b)
        assert result == (5, 5, 10, 10)
    
    def test_complete_overlap(self):
        """Test when one bounds completely contains another."""
        bounds_a = (0, 0, 20, 20)
        bounds_b = (5, 5, 15, 15)
        
        result = _intersect_bounds(bounds_a, bounds_b)
        assert result == (5, 5, 15, 15)
    
    def test_identical_bounds(self):
        """Test intersection of identical bounds."""
        bounds = (0, 0, 10, 10)
        result = _intersect_bounds(bounds, bounds)
        assert result == bounds
    
    def test_edge_touching_bounds(self):
        """Test bounds that touch at an edge."""
        bounds_a = (0, 0, 10, 10)
        bounds_b = (10, 10, 20, 20)
        
        with pytest.raises(ValueError):
            _intersect_bounds(bounds_a, bounds_b)
    
    def test_no_intersection(self):
        """Test non-overlapping bounds."""
        bounds_a = (0, 0, 5, 5)
        bounds_b = (10, 10, 15, 15)
        
        with pytest.raises(ValueError):
            _intersect_bounds(bounds_a, bounds_b)


class TestBuildGrid:
    """Tests for _build_grid function."""
    
    def test_valid_grid_creation(self):
        """Test creating a valid grid."""
        bounds = (0, 0, 100, 100)
        res_ref = (10, 10)
        
        transform, width, height = _build_grid(bounds, res_ref)
        
        assert width == 10
        assert height == 10
    
    def test_grid_with_float_resolution(self):
        """Test grid creation with float resolution."""
        bounds = (0, 0, 99.5, 99.5)
        res_ref = (0.5, 0.5)
        
        transform, width, height = _build_grid(bounds, res_ref)
        assert width == 199
        assert height == 199
    
    def test_grid_floor_behavior(self):
        """Test that floor is applied."""
        bounds = (0, 0, 99.9, 99.9)
        res_ref = (10, 10)
        
        transform, width, height = _build_grid(bounds, res_ref)
        assert width == 9
        assert height == 9
    
    def test_invalid_grid_too_small(self):
        """Test that ValueError is raised for invalid grid."""
        bounds = (0, 0, 1, 1)
        res_ref = (100, 100)
        
        with pytest.raises(ValueError):
            _build_grid(bounds, res_ref)


class TestApplyNadAtdReclassBlock:
    """Tests for _apply_nad_atd_reclass_block function."""
    
    def test_reclassify_positive_values(self):
        """Test that positive values become 2.0."""
        data = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        
        result = _apply_nad_atd_reclass_block(data)
        
        assert np.allclose(result[result == 2.0], 2.0)
        assert np.isnan(result[result != 2.0]).all()
    
    def test_reclassify_zero_values(self):
        """Test that zero values become NaN."""
        data = np.array([[0, 0, 0]], dtype=np.float32)
        
        result = _apply_nad_atd_reclass_block(data)
        assert np.isnan(result).all()
    
    def test_reclassify_mixed_values(self):
        """Test reclassification with mixed values."""
        data = np.array([[0, 1, 2], [0, 3, 0]], dtype=np.float32)
        
        result = _apply_nad_atd_reclass_block(data)
        
        assert result.shape == data.shape
        assert result.dtype == np.float32
        assert np.isnan(result[0, 0])
        assert result[0, 1] == 2.0
        assert result[0, 2] == 2.0
    
    def test_reclassify_with_nan_input(self):
        """Test reclassification with NaN in input."""
        data = np.array([[1, np.nan, 0]], dtype=np.float32)
        
        result = _apply_nad_atd_reclass_block(data)
        
        assert result[0, 0] == 2.0
        assert np.isnan(result[0, 1])
        assert np.isnan(result[0, 2])
    
    def test_reclassify_large_values(self):
        """Test that large values also become 2.0."""
        data = np.array([[100, 999, 10000]], dtype=np.float32)
        
        result = _apply_nad_atd_reclass_block(data)
        assert np.allclose(result[result == 2.0], 2.0)
    
    def test_reclassify_negative_values(self):
        """Test that negative values become NaN."""
        data = np.array([[-1, -100, 0]], dtype=np.float32)
        
        result = _apply_nad_atd_reclass_block(data)
        assert np.isnan(result).all()


class TestFixedBoundsToDstCrs:
    """Tests for _fixed_bounds_to_dst_crs function."""
    
    def test_transform_4326_to_3116(self):
        """Test transforming from EPSG:4326 to EPSG:3116."""
        xmin_ref, ymin_ref = -79.22, -3.41
        xmax_ref, ymax_ref = -66.65, 12.58
        
        xmin_m, ymin_m, xmax_m, ymax_m = _fixed_bounds_to_dst_crs(
            xmin_ref, ymin_ref, xmax_ref, ymax_ref, 'EPSG:3116'
        )
        
        assert isinstance(xmin_m, (int, float))
        assert isinstance(ymin_m, (int, float))
        assert isinstance(xmax_m, (int, float))
        assert isinstance(ymax_m, (int, float))
        
        assert xmin_m < xmax_m
        assert ymin_m < ymax_m
    
    def test_transform_maintains_area_order(self):
        """Test that transformation maintains correct spatial ordering."""
        xmin_ref, ymin_ref = -79.0, -3.0
        xmax_ref, ymax_ref = -67.0, 12.0
        
        xmin_m, ymin_m, xmax_m, ymax_m = _fixed_bounds_to_dst_crs(
            xmin_ref, ymin_ref, xmax_ref, ymax_ref, 'EPSG:3116'
        )
        
        assert xmin_m <= xmax_m
        assert ymin_m <= ymax_m
    
    def test_transform_same_crs(self):
        """Test that same CRS transformation works."""
        xmin_ref, ymin_ref = 0.0, 0.0
        xmax_ref, ymax_ref = 10.0, 10.0
        
        xmin_m, ymin_m, xmax_m, ymax_m = _fixed_bounds_to_dst_crs(
            xmin_ref, ymin_ref, xmax_ref, ymax_ref, 'EPSG:4326'
        )
        
        assert np.isclose(xmin_m, xmin_ref, atol=1e-6)
        assert np.isclose(ymin_m, ymin_ref, atol=1e-6)
        assert np.isclose(xmax_m, xmax_ref, atol=1e-6)
        assert np.isclose(ymax_m, ymax_ref, atol=1e-6)
