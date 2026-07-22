//-
// Copyright (c) 2026 Sapienza University of Rome
// Author: Lorenzo Cipolletti
//
// File: prism_build_config_pkg.sv
// Package: prism_build_config_pkg
// Description: Defines developer-selectable default elaboration parameters.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps

package prism_build_config_pkg;

  // Default elaboration profile for the OpenNIC prototype.
  localparam int unsigned PRISM_DEFAULT_DATA_W = 512;
  localparam int unsigned PRISM_DEFAULT_NUM_PORTS = 2;
  localparam int unsigned PRISM_DEFAULT_USER_W = 1;
  localparam int unsigned PRISM_DEFAULT_INGRESS_FIFO_DEPTH = 64;
  localparam int unsigned PRISM_DEFAULT_EGRESS_FIFO_DEPTH = 64;
  localparam int unsigned PRISM_DEFAULT_WORK_FIFO_DEPTH = 32;
  localparam int unsigned PRISM_DEFAULT_SESSIONS = 4;
  localparam int unsigned PRISM_DEFAULT_GROUPS = 8;
  localparam int unsigned PRISM_DEFAULT_OPERATION_CONTEXTS = 8;
  localparam int unsigned PRISM_DEFAULT_ACCUMULATOR_RANGES = 64;
  localparam int unsigned PRISM_DEFAULT_CONTRIBUTORS = 2;
  localparam int unsigned PRISM_DEFAULT_ARITH_LANES = 16;
  localparam int unsigned PRISM_DEFAULT_CONTROL_CONTEXTS = 2;
  localparam int unsigned PRISM_DEFAULT_CONTROL_BYTES = 8192;
  localparam int unsigned PRISM_DEFAULT_RESULT_SLOTS = 64;
  localparam int unsigned PRISM_DEFAULT_RESULT_ROUTE_RANGES = 2;
  localparam int unsigned PRISM_DEFAULT_REPLICATION_GROUPS = 2;
  localparam logic [63:0] PRISM_DEFAULT_DEVICE_BOOT_ID = 64'h5052_4953_4D00_0001;

  // Authoritative Kulisch width set for the default profile.
  localparam int unsigned PRISM_DEFAULT_KULISCH_WIDTH_COUNT = 3;
  localparam int unsigned PRISM_DEFAULT_KULISCH_WIDTH_0 = 64;
  localparam int unsigned PRISM_DEFAULT_KULISCH_WIDTH_1 = 288;
  localparam int unsigned PRISM_DEFAULT_KULISCH_WIDTH_2 = 320;

endpackage
