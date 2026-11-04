`timescale 1ns/1ps
module fly01_event_fifo #(
    parameter integer WIDTH = 9,
    parameter integer DEPTH = 16,
    parameter integer AW = $clog2(DEPTH)
)(
    input  logic                 clk,
    input  logic                 rst,
    input  logic                 push,
    input  logic [WIDTH-1:0]     push_data,
    input  logic                 pop,
    output logic [WIDTH-1:0]     pop_data,
    output logic                 pop_valid,
    output logic                 full,
    output logic                 empty,
    output logic [AW:0]          level,
    output logic [31:0]          overflow_count,
    output logic [31:0]          drop_count
);
    logic [WIDTH-1:0] mem [0:DEPTH-1];
    logic [AW-1:0] wptr, rptr;
    logic do_pop, do_push;

    always_comb begin
        full = (level == DEPTH);
        empty = (level == 0);
        do_pop = pop && !empty;
        do_push = push && (!full || do_pop);
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            wptr <= '0;
            rptr <= '0;
            level <= '0;
            pop_data <= '0;
            pop_valid <= 1'b0;
            overflow_count <= 32'd0;
            drop_count <= 32'd0;
        end else begin
            pop_valid <= 1'b0;
            if (do_push) begin
                mem[wptr] <= push_data;
                wptr <= (wptr == DEPTH-1) ? '0 : wptr + 1'b1;
            end
            if (do_pop) begin
                pop_data <= mem[rptr];
                pop_valid <= 1'b1;
                rptr <= (rptr == DEPTH-1) ? '0 : rptr + 1'b1;
            end
            case ({do_push, do_pop})
                2'b10: level <= level + 1'b1;
                2'b01: level <= level - 1'b1;
                default: level <= level;
            endcase
            if (push && full && !do_pop) begin
                overflow_count <= overflow_count + 1'b1;
                drop_count <= drop_count + 1'b1;
            end
        end
    end
endmodule
