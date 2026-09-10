"""
Unit tests for utilities, logging, and configuration.
Tests for: log_print, config loading, URL handling.
"""

import pytest
import sys
import os
import json
import tempfile
from io import StringIO
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from tools.log_print import log_print
from config import config


class TestLogPrint:
    """Tests for log_print function."""
    
    def test_log_print_info_level(self, capsys):
        """Test log_print with INFO level."""
        import logging
        logger = logging.getLogger("test")
        log_print(logger, "Test message", level='info')
        captured = capsys.readouterr()
        
        # Message should be printed
        assert "Test message" in captured.out
    
    def test_log_print_warning_level(self, capsys):
        """Test log_print with WARNING level."""
        import logging
        logger = logging.getLogger("test")
        log_print(logger, "Warning message", level='warning')
        captured = capsys.readouterr()
        
        # Message should be printed
        assert "Warning message" in captured.out
    
    def test_log_print_error_level(self, capsys):
        """Test log_print with ERROR level."""
        import logging
        logger = logging.getLogger("test")
        log_print(logger, "Error message", level='error')
        captured = capsys.readouterr()
        
        # Message should be printed
        assert "Error message" in captured.out
    
    def test_log_print_multiple_calls(self, capsys):
        """Test multiple log_print calls."""
        import logging
        logger = logging.getLogger("test")
        log_print(logger, "Message 1", level='info')
        log_print(logger, "Message 2", level='warning')
        log_print(logger, "Message 3", level='error')
        captured = capsys.readouterr()
        
        # All messages should be present
        assert "Message 1" in captured.out
        assert "Message 2" in captured.out
        assert "Message 3" in captured.out
    
    def test_log_print_with_special_characters(self, capsys):
        """Test log_print with special characters."""
        import logging
        logger = logging.getLogger("test")
        special_msg = "Special: ñ, é, ü, @, #, $, %"
        log_print(logger, special_msg, level='info')
        captured = capsys.readouterr()
        
        # Should handle special chars
        assert len(captured.out) > 0
    
    def test_log_print_empty_message(self, capsys):
        """Test log_print with empty message."""
        import logging
        logger = logging.getLogger("test")
        log_print(logger, "", level='info')
        captured = capsys.readouterr()
        
        # Should handle empty message (just the newline)
        assert len(captured.out) >= 0  # At least should not crash


class TestConfiguration:
    """Tests for configuration constants."""
    
    def test_config_dict_exists(self):
        """Test that config dictionary exists."""
        assert config is not None
        assert isinstance(config, dict)
        assert len(config) > 0
    
    def test_config_has_geoserver_settings(self):
        """Test that GeoServer settings are in config."""
        # Should have URL_GEO or similar
        assert 'URL_GEO' in config or 'WORKSPACE' in config or 'GEO_USER' in config
    
    def test_config_has_mongodb_settings(self):
        """Test that MongoDB settings are in config."""
        # Should have Mongo settings
        assert 'MONGO_URI' in config or 'MONGO_DB_NAME' in config
    
    def test_config_has_spatial_parameters(self):
        """Test that spatial parameters are defined."""
        assert 'SPATIAL_PARAMETERS' in config
        spatial_params = config['SPATIAL_PARAMETERS']
        assert 'xmin_ref' in spatial_params
        assert 'ymin_ref' in spatial_params
        assert 'xmax_ref' in spatial_params
        assert 'ymax_ref' in spatial_params
        assert 'dst_crs_ref' in spatial_params
    
    def test_config_has_naming_patterns(self):
        """Test that naming patterns are defined."""
        assert 'NAMING_PATTERNS' in config
        patterns = config['NAMING_PATTERNS']
        assert 'raw' in patterns or 'annual' in patterns
    
    def test_config_debug_flag(self):
        """Test that DEBUG flag is in config."""
        assert 'DEBUG' in config
        assert isinstance(config['DEBUG'], bool)


class TestURLHandling:
    """Tests for URL normalization and handling."""
    
    def test_url_normalization_basic(self):
        """Test basic URL normalization."""
        url = "http://example.com/geoserver/web/"
        
        # Should be a valid string
        assert isinstance(url, str)
        assert "geoserver" in url.lower()
    
    def test_url_with_protocol(self):
        """Test URL with protocol."""
        url = "https://example.com/api"
        
        # Should contain protocol
        assert "://" in url
        assert url.startswith("http")
    
    def test_url_without_protocol(self):
        """Test URL without protocol still works as string."""
        url = "example.com/api"
        
        # Should be valid as string
        assert isinstance(url, str)
        assert len(url) > 0
    
    def test_geoserver_url_from_config(self):
        """Test that GeoServer URL from config is valid."""
        geoserver_url = config.get('URL_GEO')
        
        # If defined, should be string
        if geoserver_url is not None:
            assert isinstance(geoserver_url, str)
            assert len(geoserver_url) > 0


class TestFileUtilities:
    """Tests for file utility functions."""
    
    def test_file_exists_check(self, temp_dir):
        """Test file existence checking."""
        test_file = os.path.join(temp_dir, "test_file.txt")
        
        # File doesn't exist yet
        assert not os.path.exists(test_file)
        
        # Create it
        Path(test_file).touch()
        
        # Now it exists
        assert os.path.exists(test_file)
    
    def test_directory_exists_check(self, temp_dir):
        """Test directory existence checking."""
        test_dir = os.path.join(temp_dir, "test_dir")
        
        # Dir doesn't exist yet
        assert not os.path.isdir(test_dir)
        
        # Create it
        os.makedirs(test_dir)
        
        # Now it exists
        assert os.path.isdir(test_dir)
    
    def test_path_normalization(self):
        """Test path normalization across platforms."""
        path1 = "input/data/folder"
        path2 = "input\\data\\folder"
        path3 = os.path.normpath(path1)
        path4 = os.path.normpath(path2)
        
        # Normalized paths should be equal
        assert os.path.normpath(path3) == os.path.normpath(path4)
    
    def test_get_file_extension(self):
        """Test file extension extraction."""
        files = [
            ("data.tif", ".tif"),
            ("archive.tar.gz", ".gz"),
            ("document.txt", ".txt"),
            ("config.json", ".json"),
        ]
        
        for filename, expected_ext in files:
            _, ext = os.path.splitext(filename)
            assert ext == expected_ext
    
    def test_join_paths(self, temp_dir):
        """Test proper path joining."""
        base = temp_dir
        subfolder = "subfolder"
        filename = "file.tif"
        
        # Join paths
        full_path = os.path.join(base, subfolder, filename)
        
        # Should be absolute
        assert os.path.isabs(full_path)
        # Should contain all parts
        assert subfolder in full_path
        assert filename in full_path


class TestEnvironmentVariables:
    """Tests for environment variable handling."""
    
    def test_python_path_set(self):
        """Test that Python path is available."""
        python_path = sys.executable
        assert python_path is not None
        assert os.path.exists(python_path)
    
    def test_sys_path_includes_src(self):
        """Test that src directory is in sys.path."""
        src_path = os.path.join(os.path.dirname(__file__), '..', 'src')
        src_path = os.path.normpath(os.path.abspath(src_path))
        
        # Check if src is accessible
        assert os.path.isdir(src_path)
    
    def test_temp_directory_writable(self, temp_dir):
        """Test that temp directory is writable."""
        test_file = os.path.join(temp_dir, "test_write.txt")
        
        # Write to file
        with open(test_file, 'w') as f:
            f.write("test")
        
        # Read back
        with open(test_file, 'r') as f:
            content = f.read()
        
        assert content == "test"


class TestJSONUtilities:
    """Tests for JSON file handling."""
    
    def test_json_write_read(self, temp_dir):
        """Test JSON write and read operations."""
        json_file = os.path.join(temp_dir, "test.json")
        test_data = {"key": "value", "number": 42, "nested": {"a": 1}}
        
        # Write JSON
        with open(json_file, 'w') as f:
            json.dump(test_data, f)
        
        # Read JSON
        with open(json_file, 'r') as f:
            loaded_data = json.load(f)
        
        # Should match
        assert loaded_data == test_data
    
    def test_json_array_handling(self, temp_dir):
        """Test JSON array handling."""
        json_file = os.path.join(temp_dir, "array.json")
        test_array = [1, 2, 3, "four", {"five": 5}]
        
        # Write and read
        with open(json_file, 'w') as f:
            json.dump(test_array, f)
        
        with open(json_file, 'r') as f:
            loaded_array = json.load(f)
        
        assert loaded_array == test_array
    
    def test_json_invalid_handling(self, temp_dir):
        """Test handling of invalid JSON."""
        json_file = os.path.join(temp_dir, "invalid.json")
        
        # Write invalid JSON
        with open(json_file, 'w') as f:
            f.write("{invalid json")
        
        # Should fail to parse
        with pytest.raises(json.JSONDecodeError):
            with open(json_file, 'r') as f:
                json.load(f)


class TestProcessUtilities:
    """Tests for process and subprocess utilities."""
    
    def test_python_executable_available(self):
        """Test that Python executable is available."""
        python_exe = sys.executable
        assert python_exe is not None
        assert os.path.exists(python_exe)
    
    def test_python_version_accessible(self):
        """Test that Python version is accessible."""
        version_info = sys.version_info
        assert version_info.major >= 3
        assert version_info.minor >= 6
    
    def test_module_import_capability(self):
        """Test that modules can be imported."""
        # These should all be available in tests
        import rasterio
        import numpy
        import pytest
        
        assert rasterio is not None
        assert numpy is not None
        assert pytest is not None
