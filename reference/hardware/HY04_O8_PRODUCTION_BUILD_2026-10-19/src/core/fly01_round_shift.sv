`timescale 1ns/1ps
module fly01_round_shift(
    input  logic signed [63:0] value_in,
    input  logic [5:0]         shift,
    output logic signed [63:0] value_out
);
    logic signed [63:0] ax;
    logic signed [63:0] q;
    logic signed [63:0] rem;
    logic signed [63:0] half;
    always_comb begin
        if (shift == 0) begin
            value_out = value_in;
            ax = '0; q = '0; rem = '0; half = '0;
        end else begin
            ax = (value_in < 0) ? -value_in : value_in;
            q = ax >>> shift;
            rem = ax & ((64'sd1 <<< shift) - 1);
            half = 64'sd1 <<< (shift - 1);
            if (rem >= half) q = q + 1;
            value_out = (value_in < 0) ? -q : q;
        end
    end
endmodule
