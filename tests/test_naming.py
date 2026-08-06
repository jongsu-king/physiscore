"""Sample-label rules shared by the J-V and dark-J-V parsers.

These rules used to be duplicated in both cores, so a correction applied to one
scan type silently did not apply to the other even though the same source-meter
wrote both files. Testing the shared helper is what keeps them in step.
"""
import pytest

from scripts.common.naming import (base_name, cell_number,
                                   display_name_from_path, natural_sort_key)
from scripts.JV import jv_core
from scripts.Dark_JV import dark_jv_core


class TestDisplayName:
    @pytest.mark.parametrize("filename, expected", [
        ("Ref 1.txt", "Ref 1"),
        ("Ref 1.TXT", "Ref 1"),
        # the export timestamp the instrument appends is not part of the sample
        ("Ref 1 2026-01-20 18-35-48.txt", "Ref 1"),
        # leading export sequence number, and the dot that follows a cell number
        ("01. Target 3.txt", "Target 3"),
        ("Target 01..txt", "Target 01"),
        # lab display conventions
        ("PEI_coated_2.txt", "PEI coated 2"),
        ("anneal 110C.txt", "anneal 110°C"),
    ])
    def test_normalisation(self, filename, expected):
        assert display_name_from_path(filename) == expected

    def test_decimal_in_the_name_survives(self):
        """The extension is stripped by exact suffix, not by splitting on the
        last dot -- otherwise a concentration like 2.5k loses its fraction."""
        assert display_name_from_path("spin 2.5k.txt") == "spin 2.5k"
        assert display_name_from_path("spin 3.0k.txt") == "spin 3.0k"

    def test_full_path_uses_only_the_basename(self):
        assert display_name_from_path("/data/2026-01/run/Ref 2.txt") == "Ref 2"

    def test_both_jv_parsers_agree(self, tmp_path):
        """The light and dark parsers must label the same device identically,
        or its two scans cannot be matched up afterwards."""
        name = "01. PEI_coated 2 2026-01-20 18-35-48.txt"
        light = tmp_path / name
        light.write_text("Vmeas\tImeas\n0.0\t-0.001\n", encoding="utf-8")

        light_summary, _ = jv_core.parse_jv_file(str(light))
        dark_summary, _ = dark_jv_core.parse_dark_jv_file(str(light))

        assert light_summary["Filename"] == dark_summary["Filename"] == "PEI coated 2"


class TestNaturalSort:
    def test_numbers_order_numerically(self):
        """Lexicographic order puts 2.5k before 2k and 10 before 2."""
        names = ["spin 3k", "spin 2k", "spin 10k", "spin 2.5k"]
        assert sorted(names, key=natural_sort_key) == [
            "spin 2k", "spin 2.5k", "spin 3k", "spin 10k"]

    def test_case_insensitive_on_the_text_parts(self):
        assert sorted(["b 1", "A 2"], key=natural_sort_key) == ["A 2", "b 1"]

    def test_accepts_non_string_input(self):
        assert sorted([2, 10, 1], key=natural_sort_key) == [1, 2, 10]


class TestGrouping:
    @pytest.mark.parametrize("name, base, number", [
        ("Ref 1", "Ref ", 1),
        ("Ref 12", "Ref ", 12),
        ("Ref", "Ref", 0),      # no cell index
        ("Target 3 ", "Target ", 3),   # trailing whitespace stripped first
    ])
    def test_cells_split_into_condition_and_index(self, name, base, number):
        assert base_name(name) == base
        assert cell_number(name) == number

    def test_cells_of_one_condition_share_a_base(self):
        cells = ["Target 1", "Target 2", "Target 10"]
        assert len({base_name(c) for c in cells}) == 1
