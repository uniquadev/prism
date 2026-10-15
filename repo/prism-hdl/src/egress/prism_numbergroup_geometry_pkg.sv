//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_geometry_pkg.sv
// Package: prism_numbergroup_geometry_pkg
// Description: Bit widths and step counts of the NumberGroup geometry modules.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps
package prism_numbergroup_geometry_pkg;
  function automatic integer byte_width(input integer width, input integer lanes);
    return $clog2(lanes*(4+(((width+7)/8+7)&~3))+1);
  endfunction
  function automatic integer geometry_width(input integer width, input integer lanes);
    return lanes*(byte_width(width,lanes)+$clog2(lanes+1)+4);
  endfunction
  function automatic integer summary_width(input integer width, input integer lanes);
    return byte_width(width,lanes)+$clog2(lanes+1)+22;
  endfunction

  // The geometry modules run without stalls: every result appears a fixed
  // number of clock cycles after its inputs.
  localparam int unsigned RUN_GEOMETRY_STEPS = 5;
  function automatic integer scan_steps(input integer banks);
    return $clog2(banks);
  endfunction
  function automatic integer join_steps(input integer banks);
    return $clog2(banks) + 3;
  endfunction
endpackage
