`timescale 1ns/1ps
// 50 MHz, 8N1 TX. Accept data exactly when valid && ready at a rising edge.
module fly01_uart_tx #(
    parameter integer CLKS_PER_BIT = 25
) (
    input wire clk, input wire reset_n,
    input wire [7:0] data, input wire valid,
    output wire ready, output reg tx
);
    localparam integer CW = $clog2(CLKS_PER_BIT + 1);
    localparam [1:0] IDLE=0, START=1, BITS=2, STOP=3;
    reg [1:0] state;
    reg [CW-1:0] timer;
    reg [2:0] bit_index;
    reg [7:0] shift;
    assign ready = reset_n && state == IDLE;
    always @(posedge clk) begin
        if (!reset_n) begin
            state <= IDLE; timer <= 0; bit_index <= 0;
            shift <= 0; tx <= 1;
        end else case (state)
            IDLE: begin
                tx <= 1;
                if (valid) begin
                    shift <= data; timer <= CLKS_PER_BIT - 1;
                    tx <= 0; state <= START;
                end
            end
            START: if (timer != 0) timer <= timer - 1'b1;
                else begin
                    tx <= shift[0]; bit_index <= 0;
                    timer <= CLKS_PER_BIT - 1; state <= BITS;
                end
            BITS: if (timer != 0) timer <= timer - 1'b1;
                else begin
                    timer <= CLKS_PER_BIT - 1;
                    if (bit_index == 7) begin tx <= 1; state <= STOP; end
                    else begin
                        bit_index <= bit_index + 1'b1;
                        tx <= shift[bit_index + 1'b1];
                    end
                end
            STOP: if (timer != 0) timer <= timer - 1'b1;
                else begin state <= IDLE; tx <= 1; end
            default: begin state <= IDLE; tx <= 1; end
        endcase
    end
endmodule
