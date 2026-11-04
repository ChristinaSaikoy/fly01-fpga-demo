`timescale 1ns/1ps
module fly01_formal_top(
    input  logic        sys_clk,
    input  logic        sys_rst_n,
    input  logic        evt_valid,
    input  logic        evt_kind_noise,
    input  logic [8:0]  evt_neuron,
    output logic        evt_ready,
    input  logic        step_commit,
    input  logic        dn_count_enable,
    output logic        step_busy,
    output logic        step_done,
    input  logic [8:0]  state_probe_addr,
    output logic signed [17:0] state_probe_data,
    input  logic [4:0]  dn_counter_sel,
    output logic [31:0] dn_counter_data,
    output logic [31:0] timestep_cycles,
    output logic [31:0] acc_saturation_count,
    output logic [31:0] state_saturation_count,
    output logic [31:0] overflow_count,
    output logic [31:0] drop_count
);
    logic rst;
    assign rst = ~sys_rst_n;

    logic fifo_push, fifo_pop, fifo_pop_valid, fifo_full, fifo_empty;
    logic [9:0] fifo_push_data, fifo_pop_data;
    logic [10:0] fifo_level;
    logic [31:0] input_overflow, input_drop;

    logic accept_events;
    assign fifo_push = evt_valid && evt_ready;
    assign fifo_push_data = {evt_kind_noise, evt_neuron};
    assign evt_ready = accept_events;

    fly01_event_fifo #(.WIDTH(10), .DEPTH(1024), .AW(10)) u_input_fifo (
        .clk(sys_clk), .rst(rst), .push(fifo_push), .push_data(fifo_push_data),
        .pop(fifo_pop), .pop_data(fifo_pop_data), .pop_valid(fifo_pop_valid),
        .full(fifo_full), .empty(fifo_empty), .level(fifo_level),
        .overflow_count(input_overflow), .drop_count(input_drop)
    );
    logic [470:0] drive_mask_reg, noise_mask_reg;
    logic core_start, core_ready, core_done;
    logic [470:0] core_spike_mask;
    logic [31:0] core_overflow, core_drop;
    logic [1023:0] dn_counts_flat;

    fly01_engine_core #(
        .N_NEURONS(471), .N_EDGES(44236), .ADDR_W(9), .EDGE_W(16),
        .N_DN(32), .ENABLE_DN(1),
        .ROW_FILE("generated/csr_row_ptr.mem"),
        .DST_FILE("generated/syn_dst.mem"),
        .WEIGHT_FILE("generated/syn_weight_w16f14.mem"),
        .DN_FILE("generated/dn_local.mem")
    ) u_core (
        .clk(sys_clk), .rst(rst), .start_step(core_start),
        .drive_mask(drive_mask_reg), .noise_mask(noise_mask_reg),
        .dn_count_enable(dn_count_enable),
        .probe_addr(state_probe_addr), .probe_state(state_probe_data),
        .spike_mask(core_spike_mask), .ready(core_ready), .done(core_done),
        .acc_saturation_count(acc_saturation_count),
        .state_saturation_count(state_saturation_count),
        .overflow_count(core_overflow), .drop_count(core_drop),
        .cycle_count_last(timestep_cycles), .dn_event_counts_flat(dn_counts_flat)
    );

    assign overflow_count = input_overflow + core_overflow;
    assign drop_count = input_drop + core_drop;
    always_comb dn_counter_data = dn_counts_flat[dn_counter_sel*32 +: 32];

    typedef enum logic [2:0] {TOP_IDLE, TOP_POP_REQ, TOP_POP_WAIT, TOP_START, TOP_WAIT} top_state_t;
    top_state_t top_state;
    logic commit_pending;

    always_comb begin
        accept_events = !fifo_full && (top_state == TOP_IDLE) && !commit_pending && !step_commit;
        fifo_pop = (top_state == TOP_POP_REQ);
        core_start = (top_state == TOP_START);
        step_busy = (top_state != TOP_IDLE);
    end

    always_ff @(posedge sys_clk) begin
        if (rst) begin
            top_state <= TOP_IDLE;
            commit_pending <= 1'b0;
            drive_mask_reg <= '0;
            noise_mask_reg <= '0;
            step_done <= 1'b0;
        end else begin
            step_done <= 1'b0;
            if (step_commit) commit_pending <= 1'b1;

            case (top_state)
                TOP_IDLE: begin
                    if (commit_pending || step_commit) begin
                        if (!fifo_empty) top_state <= TOP_POP_REQ;
                        else if (core_ready) top_state <= TOP_START;
                    end
                end

                TOP_POP_REQ: begin
                    top_state <= TOP_POP_WAIT;
                end

                TOP_POP_WAIT: begin
                    if (fifo_pop_valid) begin
                        if (fifo_pop_data[9]) noise_mask_reg[fifo_pop_data[8:0]] <= 1'b1;
                        else drive_mask_reg[fifo_pop_data[8:0]] <= 1'b1;
                        if (fifo_empty) begin
                            if (core_ready) top_state <= TOP_START;
                            else top_state <= TOP_POP_WAIT;
                        end else top_state <= TOP_POP_REQ;
                    end else if (fifo_empty && core_ready) begin
                        top_state <= TOP_START;
                    end
                end

                TOP_START: begin
                    commit_pending <= 1'b0;
                    top_state <= TOP_WAIT;
                end

                TOP_WAIT: begin
                    if (core_done) begin
                        drive_mask_reg <= '0;
                        noise_mask_reg <= '0;
                        step_done <= 1'b1;
                        top_state <= TOP_IDLE;
                    end
                end

                default: top_state <= TOP_IDLE;
            endcase
        end
    end
endmodule
