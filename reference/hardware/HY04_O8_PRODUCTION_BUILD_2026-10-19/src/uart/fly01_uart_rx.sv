`timescale 1ns/1ps
// 50 MHz, asynchronous 8N1 RX. Outputs are one-clock pulses, not a FIFO.
module fly01_uart_rx #(
    parameter integer CLKS_PER_BIT = 25
) (
    input wire clk, input wire reset_n, input wire rx,
    output reg [7:0] data,
    output reg valid, output reg framing_error, output reg break_detect
);
    localparam integer CW = $clog2(CLKS_PER_BIT + 1);
    localparam integer LW = $clog2(11 * CLKS_PER_BIT + 1);
    localparam [2:0] IDLE=0, START=1, BITS=2, STOP=3, WAIT_HIGH=4;
    (* ASYNC_REG = "TRUE" *) reg rx_meta, rx_sync;
    reg [2:0] state, bit_index;
    reg [CW-1:0] timer, high_count;
    reg [LW-1:0] low_count;
    reg [7:0] shift;
    reg break_latched;

    always @(posedge clk) begin
        if (!reset_n) begin
            rx_meta <= 1'b1; rx_sync <= 1'b1;
        end else begin
            rx_meta <= rx; rx_sync <= rx_meta;
        end
    end

    always @(posedge clk) begin
        if (!reset_n) begin
            state <= IDLE; timer <= 0; bit_index <= 0;
            high_count <= 0; low_count <= 0; break_latched <= 0;
            shift <= 0; data <= 0;
            valid <= 0; framing_error <= 0; break_detect <= 0;
        end else begin
            valid <= 0; framing_error <= 0; break_detect <= 0;
            if (rx_sync) begin
                low_count <= 0; break_latched <= 0;
            end else if (low_count < 11 * CLKS_PER_BIT) begin
                low_count <= low_count + 1'b1;
            end

            case (state)
                IDLE: if (!rx_sync) begin
                    // Synchronizer delay is fixed; validate the start midpoint.
                    timer <= CLKS_PER_BIT/2 - 1; state <= START;
                end
                START: if (timer != 0) timer <= timer - 1'b1;
                    else if (rx_sync) state <= IDLE;
                    else begin
                        timer <= CLKS_PER_BIT - 1;
                        bit_index <= 0; state <= BITS;
                    end
                BITS: if (timer != 0) timer <= timer - 1'b1;
                    else begin
                        shift[bit_index] <= rx_sync;
                        timer <= CLKS_PER_BIT - 1;
                        if (bit_index == 7) state <= STOP;
                        else bit_index <= bit_index + 1'b1;
                    end
                STOP: if (timer != 0) timer <= timer - 1'b1;
                    else if (rx_sync) begin
                        data <= shift; valid <= 1; state <= IDLE;
                    end else begin
                        framing_error <= 1;
                        high_count <= 0; state <= WAIT_HIGH;
                    end
                WAIT_HIGH: if (!rx_sync) high_count <= 0;
                    else if (high_count == CLKS_PER_BIT - 1) begin
                        high_count <= 0; state <= IDLE;
                    end else high_count <= high_count + 1'b1;
                default: state <= IDLE;
            endcase
            // A continuous low >= 11 bits is a break, once per low interval.
            // No byte is accepted until the line has been high for a full bit.
            if (!rx_sync && low_count == 11 * CLKS_PER_BIT - 1 &&
                    !break_latched) begin
                break_detect <= 1; break_latched <= 1;
                valid <= 0; state <= WAIT_HIGH; high_count <= 0;
            end
        end
    end
endmodule
