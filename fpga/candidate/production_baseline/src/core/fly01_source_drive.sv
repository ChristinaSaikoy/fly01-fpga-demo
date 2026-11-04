`timescale 1ns/1ps
module fly01_source_drive(
    input  logic signed [17:0] state_in,
    output logic signed [17:0] state_out,
    output logic               saturated
);
    localparam signed [18:0] STIM_Q = 19'sd2458;
    localparam signed [18:0] S_MAX = 19'sd131071;
    localparam signed [18:0] S_MIN = -19'sd131072;
    logic signed [18:0] wide;
    always_comb begin
        wide = $signed(state_in) + STIM_Q;
        saturated = 1'b0;
        if (wide > S_MAX) begin state_out = 18'sh1ffff; saturated = 1'b1; end
        else if (wide < S_MIN) begin state_out = 18'sh20000; saturated = 1'b1; end
        else state_out = wide[17:0];
    end
endmodule
