`timescale 1ns/1ps
module fly01_accum_add(
    input  logic signed [23:0] acc_in,
    input  logic signed [15:0] weight_q,
    output logic signed [23:0] acc_out,
    output logic               saturated
);
    localparam signed [24:0] A_MAX = 25'sd8388607;
    localparam signed [24:0] A_MIN = -25'sd8388608;
    logic signed [24:0] term;
    logic signed [24:0] wide;
    always_comb begin
        term = $signed(weight_q) <<< 4;
        wide = $signed(acc_in) + term;
        saturated = 1'b0;
        if (wide > A_MAX) begin acc_out = 24'sh7fffff; saturated = 1'b1; end
        else if (wide < A_MIN) begin acc_out = 24'sh800000; saturated = 1'b1; end
        else acc_out = wide[23:0];
    end
endmodule
