"""
Unit tests for data parsing functions.
Tests for: extract_years_from_filename, parse_steps, parse_quarters
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from calculate_deforestation.deforestation_calc import extract_years_from_filename
from main import parse_steps, parse_quarters


class TestExtractYearsFromFilename:
    """Tests for extract_years_from_filename function."""
    
    def test_extract_two_years_smbyc(self):
        """Test extracting two years from SMBYC annual format."""
        filename = "smbyc_2010-2012.tif"
        year_start, year_end = extract_years_from_filename(filename)
        assert year_start == 2010
        assert year_end == 2012
    
    def test_extract_single_year_smbyc(self):
        """Test extracting single year and auto-increment."""
        filename = "smbyc_2013.tif"
        year_start, year_end = extract_years_from_filename(filename)
        assert year_start == 2013
        assert year_end == 2014
    
    def test_extract_special_case_2010(self):
        """Test special case 2010 -> 2010-2012."""
        filename = "smbyc_2010-2012.tif"
        year_start, year_end = extract_years_from_filename(filename)
        assert year_start == 2010
        assert year_end == 2012
    
    def test_extract_cumulative_format(self):
        """Test extracting years from cumulative format."""
        filename = "smbyc_deforestation_cumulative_2010-2015.tif"
        year_start, year_end = extract_years_from_filename(filename)
        assert year_start == 2010
        assert year_end == 2015
    
    def test_extract_nad_format(self):
        """Test extracting from NAD format (YYYYQQ)."""
        filename = "nad_202401.tif"
        year_start, year_end = extract_years_from_filename(filename)
        assert year_start == 2024
        assert year_end == 2025
    
    def test_extract_annual_format(self):
        """Test extracting from annual format."""
        filename = "smbyc_deforestation_annual_2012-2013.tif"
        year_start, year_end = extract_years_from_filename(filename)
        assert year_start == 2012
        assert year_end == 2013
    
    def test_no_years_in_filename(self):
        """Test that ValueError is raised when no years found."""
        filename = "random_file_with_no_years.tif"
        with pytest.raises(ValueError, match="No se encontraron años válidos"):
            extract_years_from_filename(filename)
    
    def test_multiple_filenames_various_formats(self):
        """Test various filename formats."""
        test_cases = [
            ("smbyc_2016.tif", (2016, 2017)),
            ("smbyc_2020-2021.tif", (2020, 2021)),
            ("nad_202202.tif", (2022, 2023)),
            ("atd_202304.tif", (2023, 2024)),
        ]
        
        for filename, expected_years in test_cases:
            year_start, year_end = extract_years_from_filename(filename)
            assert (year_start, year_end) == expected_years, f"Failed for {filename}"


class TestParseSteps:
    """Tests for parse_steps function."""
    
    def test_parse_none_returns_all_steps(self):
        """Test that None returns all 5 steps."""
        result = parse_steps(None)
        assert result == {1, 2, 3, 4, 5}
    
    def test_parse_single_step(self):
        """Test parsing single step."""
        result = parse_steps("2")
        assert result == {2}
    
    def test_parse_multiple_steps_comma_separated(self):
        """Test parsing comma-separated steps."""
        result = parse_steps("1,3,5")
        assert result == {1, 3, 5}
    
    def test_parse_range_steps(self):
        """Test parsing step range."""
        result = parse_steps("2-4")
        assert result == {2, 3, 4}
    
    def test_parse_mixed_range_and_comma(self):
        """Test parsing mixed range and comma-separated."""
        result = parse_steps("1-3,5")
        assert result == {1, 2, 3, 5}
    
    def test_parse_complex_mixed_format(self):
        """Test parsing complex format."""
        result = parse_steps("1,3-4,2")
        assert result == {1, 2, 3, 4}
    
    def test_parse_invalid_steps_filtered(self):
        """Test that invalid steps (outside 1-5) are filtered."""
        result = parse_steps("0,1,5,6")
        assert result == {1, 5}
    
    def test_parse_duplicate_steps_deduplicated(self):
        """Test that duplicates are removed."""
        result = parse_steps("1,1,1,2,2")
        assert result == {1, 2}
    
    def test_parse_empty_string(self):
        """Test parsing empty string (treated as None, returns all)."""
        result = parse_steps("")
        assert result == {1, 2, 3, 4, 5}


class TestParseQuarters:
    """Tests for parse_quarters function."""
    
    def test_parse_none_returns_all_quarters(self):
        """Test that None returns all 4 quarters."""
        result = parse_quarters(None)
        assert result == [1, 2, 3, 4]
    
    def test_parse_single_quarter(self):
        """Test parsing single quarter."""
        result = parse_quarters("2")
        assert result == [2]
    
    def test_parse_multiple_quarters_comma_separated(self):
        """Test parsing comma-separated quarters."""
        result = parse_quarters("1,3")
        assert result == [1, 3]
    
    def test_parse_quarter_range(self):
        """Test parsing quarter range."""
        result = parse_quarters("1-3")
        assert result == [1, 2, 3]
    
    def test_parse_all_quarters_range(self):
        """Test parsing all quarters as range."""
        result = parse_quarters("1-4")
        assert result == [1, 2, 3, 4]
    
    def test_parse_mixed_range_and_comma(self):
        """Test parsing mixed range and comma."""
        result = parse_quarters("1-2,4")
        assert result == [1, 2, 4]
    
    def test_parse_invalid_quarters_filtered(self):
        """Test that invalid quarters (outside 1-4) are filtered."""
        result = parse_quarters("0,1,4,5")
        assert result == [1, 4]
    
    def test_parse_quarters_sorted(self):
        """Test that result is sorted."""
        result = parse_quarters("4,2,1,3")
        assert result == [1, 2, 3, 4]
    
    def test_parse_empty_string(self):
        """Test parsing empty string (treated as None, returns all)."""
        result = parse_quarters("")
        assert result == [1, 2, 3, 4]
    
    def test_parse_duplicate_quarters_deduplicated(self):
        """Test that duplicates are removed."""
        result = parse_quarters("1,1,2,2,3")
        assert result == [1, 2, 3]


class TestIntegrationParsingFunctions:
    """Integration tests for all parsing functions together."""
    
    def test_real_pipeline_parameters(self):
        """Test real-world parameter combinations."""
        years = list(range(2020, 2024))
        steps = parse_steps("1,3-5")
        
        assert years == [2020, 2021, 2022, 2023]
        assert steps == {1, 3, 4, 5}
    
    def test_nad_atd_quarterly_processing(self):
        """Test NAD/ATD quarterly processing parameters."""
        quarters = parse_quarters("1-2")
        assert quarters == [1, 2]
