`timescale 1ns/1ps
module fly01_neuron_update(
    input  logic signed [17:0] state_in,
    input  logic signed [23:0] acc_in,
    input  logic               noise_event,
    output logic signed [17:0] state_out,
    output logic               fired,
    output logic               state_saturated,
    output logic signed [31:0] wide_update_debug
);
    localparam signed [63:0] DECAY_Q = 64'sd107313;
    localparam signed [63:0] TONIC_Q = 64'sd1147;
    localparam signed [63:0] NOISE_Q = 64'sd1802;
    localparam signed [63:0] THRESHOLD_Q = 64'sd8192;
    localparam signed [63:0] S_MAX = 64'sd131071;
    localparam signed [63:0] S_MIN = -64'sd131072;

    function automatic signed [63:0] round_shift_away;
        input signed [63:0] x;
        input integer sh;
        reg signed [63:0] ax;
        reg signed [63:0] q;
        reg signed [63:0] rem;
        reg signed [63:0] half;
        begin
            if (sh <= 0) begin
                round_shift_away = x <<< (-sh);
            end else begin
                ax = (x < 0) ? -x : x;
                q = ax >>> sh;
                rem = ax & ((64'sd1 <<< sh) - 1);
                half = 64'sd1 <<< (sh - 1);
                if (rem >= half) q = q + 1;
                round_shift_away = (x < 0) ? -q : q;
            end
        end
    endfunction

    logic signed [63:0] decay_product;
    logic signed [63:0] decayed;
    logic signed [63:0] gain_acc;
    logic signed [63:0] acc_state;
    logic signed [63:0] wide_update;

    always_comb begin
        decay_product = $signed(state_in) * DECAY_Q;
        decayed = round_shift_away(decay_product, 17);
        gain_acc = $signed(acc_in) * 64'sd3;
        acc_state = round_shift_away(gain_acc, 5);
        wide_update = decayed + acc_state + TONIC_Q;
        if (noise_event) wide_update = wide_update + NOISE_Q;
        wide_update_debug = wide_update[31:0];

        fired = (wide_update >= THRESHOLD_Q);
        state_saturated = 1'b0;
        if (fired) begin
            state_out = 18'sd0;
        end else if (wide_update > S_MAX) begin
            state_out = 18'sh1ffff;
            state_saturated = 1'b1;
        end else if (wide_update < S_MIN) begin
            state_out = 18'sh20000;
            state_saturated = 1'b1;
        end else begin
            state_out = wide_update[17:0];
        end
    end
endmodule
