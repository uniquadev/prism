//-
// Copyright (c) 2026 Lorenzo Cipolletti
// Author: Lorenzo Cipolletti
//
// File: prism_numbergroup_size_sum.sv
// Module: prism_numbergroup_size_sum
// Description: Carry-save sum of NumberGroup size contributions, modulo the output width.
//
// SPDX-License-Identifier: Apache-2.0
// See LICENSE for the full license text.
//-

`timescale 1ns / 1ps
module prism_numbergroup_size_sum #(
    parameter int unsigned INPUTS = 128,
    parameter int unsigned WIDTH = 16
) (
    input logic [INPUTS*WIDTH-1:0] s_values,
    output logic [WIDTH-1:0] m_sum
);
    function automatic int unsigned terms_at(input int unsigned level);
        int unsigned terms;
        terms = INPUTS;
        for (int i=0; i<int'(level); i++) terms = (terms/3)*2 + terms%3;
        return terms;
    endfunction
    function automatic int unsigned reduction_levels();
        int unsigned terms, levels;
        terms = INPUTS; levels = 0;
        while (terms > 2) begin terms = (terms/3)*2 + terms%3; levels++; end
        return levels;
    endfunction
    localparam int unsigned LEVELS = reduction_levels();
    for (genvar level=0; level<=LEVELS; level++) begin: reduction
        localparam int unsigned TERMS = terms_at(level);
        logic [TERMS*WIDTH-1:0] values;
        if (level==0) begin: input_level
            assign values = s_values;
        end else begin: compress
            localparam int unsigned PREVIOUS = terms_at(level-1);
            localparam int unsigned TRIPLES = PREVIOUS/3;
            for (genvar group_index=0; group_index<TRIPLES; group_index++) begin: triple
                wire [WIDTH-1:0] a = reduction[level-1].values[(3*group_index)*WIDTH+:WIDTH];
                wire [WIDTH-1:0] b = reduction[level-1].values[(3*group_index+1)*WIDTH+:WIDTH];
                wire [WIDTH-1:0] c = reduction[level-1].values[(3*group_index+2)*WIDTH+:WIDTH];
                assign values[(2*group_index)*WIDTH+:WIDTH] = a ^ b ^ c;
                assign values[(2*group_index+1)*WIDTH+:WIDTH] = ((a & b) | (a & c) | (b & c)) << 1;
            end
            for (genvar tail=0; tail<PREVIOUS%3; tail++) begin: remainder
                assign values[(2*TRIPLES+tail)*WIDTH+:WIDTH]
                    = reduction[level-1].values[(3*TRIPLES+tail)*WIDTH+:WIDTH];
            end
        end
    end
    if (INPUTS==1) assign m_sum = reduction[LEVELS].values;
    else assign m_sum = reduction[LEVELS].values[0+:WIDTH] + reduction[LEVELS].values[WIDTH+:WIDTH];
endmodule
