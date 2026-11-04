`timescale 1ns/1ps
module fly01_engine_core #(
    parameter integer N_NEURONS = 471,
    parameter integer N_EDGES = 44236,
    parameter integer ADDR_W = 9,
    parameter integer EDGE_W = 16,
    parameter integer N_DN = 32,
    parameter integer ENABLE_DN = 0,
    parameter ROW_FILE = "",
    parameter DST_FILE = "",
    parameter WEIGHT_FILE = "",
    parameter DN_FILE = ""
)(
    input  logic clk,
    input  logic rst,
    input  logic start_step,
    input  logic [N_NEURONS-1:0] drive_mask,
    input  logic [N_NEURONS-1:0] noise_mask,
    input  logic dn_count_enable,
    input  logic [ADDR_W-1:0] probe_addr,
    output logic signed [17:0] probe_state,
    output logic [N_NEURONS-1:0] spike_mask,
    output logic ready,
    output logic done,
    output logic [31:0] acc_saturation_count,
    output logic [31:0] state_saturation_count,
    output logic [31:0] overflow_count,
    output logic [31:0] drop_count,
    output logic [31:0] cycle_count_last,
    output logic [N_DN*32-1:0] dn_event_counts_flat
);

    localparam integer COUNT_W = $clog2(N_NEURONS + 1);
    localparam integer IDX_W = (N_NEURONS <= 2) ? 1 : $clog2(N_NEURONS);

    logic [EDGE_W-1:0] row_mem [0:N_NEURONS];
    logic signed [17:0] state_mem [0:N_NEURONS-1];
    logic signed [23:0] acc_mem [0:N_NEURONS-1];
    logic [ADDR_W-1:0] prev_spike_mem [0:N_NEURONS-1];
    logic [ADDR_W-1:0] next_spike_mem [0:N_NEURONS-1];
    logic [ADDR_W-1:0] dn_mem [0:N_DN-1];
    logic [31:0] dn_count_mem [0:N_DN-1];

    logic [N_NEURONS-1:0] drive_latched, noise_latched;
    logic dn_count_enable_latched;
    logic [COUNT_W-1:0] prev_count, next_count;
    logic [IDX_W-1:0] neuron_idx, spike_idx, swap_idx;
    logic [ADDR_W-1:0] active_src;
    logic [EDGE_W-1:0] edge_idx, edge_end;
    logic [31:0] cycle_counter;

    initial begin
        if (ROW_FILE != "") $readmemh(ROW_FILE, row_mem);
        if (DN_FILE != "") $readmemh(DN_FILE, dn_mem);
    end

    genvar dn_g;
    generate
        for (dn_g = 0; dn_g < N_DN; dn_g = dn_g + 1) begin : g_dn_flat
            always_comb dn_event_counts_flat[dn_g*32 +: 32] = dn_count_mem[dn_g];
        end
    endgenerate

    assign probe_state = state_mem[probe_addr];

    logic signed [17:0] src_state_out;
    logic src_sat;
    fly01_source_drive u_source_drive(
        .state_in(state_mem[neuron_idx]),
        .state_out(src_state_out),
        .saturated(src_sat)
    );

    logic [ADDR_W-1:0] edge_dst;
    logic signed [15:0] edge_weight;
    fly01_synapse_banks u_synapse_banks(
        .clk(clk), .addr(edge_idx), .weight_q(edge_weight), .dst_q(edge_dst)
    );
    logic signed [23:0] acc_add_out;
    logic acc_add_sat;
    fly01_accum_add u_acc_add(
        .acc_in(acc_mem[edge_dst]),
        .weight_q(edge_weight),
        .acc_out(acc_add_out),
        .saturated(acc_add_sat)
    );

    logic signed [17:0] neuron_state_out;
    logic neuron_fired, neuron_state_sat;
    logic signed [31:0] neuron_wide_debug;
    fly01_neuron_update u_neuron_update(
        .state_in(state_mem[neuron_idx]),
        .acc_in(acc_mem[neuron_idx]),
        .noise_event(noise_latched[neuron_idx]),
        .state_out(neuron_state_out),
        .fired(neuron_fired),
        .state_saturated(neuron_state_sat),
        .wide_update_debug(neuron_wide_debug)
    );

    typedef enum logic [3:0] {
        ST_INIT,
        ST_IDLE,
        ST_DRIVE,
        ST_ACC_LOAD,
        ST_ACC_REQ,
        ST_ACC_USE,
        ST_NEURON,
        ST_SWAP_PREP,
        ST_SWAP,
        ST_DONE
    } state_t;
    state_t fsm;
    integer dn_j;

    always_ff @(posedge clk) begin
        if (rst) begin
            fsm <= ST_INIT;
            neuron_idx <= '0;
            spike_idx <= '0;
            swap_idx <= '0;            prev_count <= '0;
            next_count <= '0;
            active_src <= '0;
            edge_idx <= '0;
            edge_end <= '0;
            drive_latched <= '0;
            noise_latched <= '0;
            dn_count_enable_latched <= 1'b0;
            spike_mask <= '0;
            ready <= 1'b0;
            done <= 1'b0;
            acc_saturation_count <= 32'd0;
            state_saturation_count <= 32'd0;
            overflow_count <= 32'd0;
            drop_count <= 32'd0;
            cycle_counter <= 32'd0;
            cycle_count_last <= 32'd0;
            for (dn_j = 0; dn_j < N_DN; dn_j = dn_j + 1)
                dn_count_mem[dn_j] <= 32'd0;
        end else begin
            done <= 1'b0;
            if (fsm != ST_IDLE && fsm != ST_DONE) cycle_counter <= cycle_counter + 1'b1;
            case (fsm)
                ST_INIT: begin
                    state_mem[neuron_idx] <= 18'sd0;
                    acc_mem[neuron_idx] <= 24'sd0;
                    if (neuron_idx == N_NEURONS-1) begin
                        neuron_idx <= '0;
                        ready <= 1'b1;
                        fsm <= ST_IDLE;
                    end else neuron_idx <= neuron_idx + 1'b1;
                end

                ST_IDLE: begin
                    if (start_step) begin
                        ready <= 1'b0;
                        drive_latched <= drive_mask;
                        noise_latched <= noise_mask;
                        dn_count_enable_latched <= dn_count_enable;
                        spike_mask <= '0;
                        next_count <= '0;
                        neuron_idx <= '0;
                        cycle_counter <= 32'd0;
                        fsm <= ST_DRIVE;
                    end
                end
                ST_DRIVE: begin
                    if (drive_latched[neuron_idx]) begin
                        state_mem[neuron_idx] <= src_state_out;
                        if (src_sat) state_saturation_count <= state_saturation_count + 1'b1;
                    end
                    if (neuron_idx == N_NEURONS-1) begin
                        neuron_idx <= '0;
                        spike_idx <= '0;
                        if (prev_count == 0) fsm <= ST_NEURON;
                        else fsm <= ST_ACC_LOAD;
                    end else neuron_idx <= neuron_idx + 1'b1;
                end

                ST_ACC_LOAD: begin
                    active_src <= prev_spike_mem[spike_idx];
                    edge_idx <= row_mem[prev_spike_mem[spike_idx]];
                    edge_end <= row_mem[$unsigned(prev_spike_mem[spike_idx]) + 1];
                    fsm <= ST_ACC_REQ;
                end

                ST_ACC_REQ: begin
                    if (edge_idx < edge_end) begin
                        fsm <= ST_ACC_USE;
                    end else if ($unsigned(spike_idx) + 1 < prev_count) begin
                        spike_idx <= spike_idx + 1'b1;
                        fsm <= ST_ACC_LOAD;
                    end else begin
                        neuron_idx <= '0;
                        fsm <= ST_NEURON;
                    end
                end

                ST_ACC_USE: begin
                    acc_mem[edge_dst] <= acc_add_out;
                    if (acc_add_sat) acc_saturation_count <= acc_saturation_count + 1'b1;
                    edge_idx <= edge_idx + 1'b1;
                    fsm <= ST_ACC_REQ;
                end

                ST_NEURON: begin
                    state_mem[neuron_idx] <= neuron_state_out;
                    acc_mem[neuron_idx] <= 24'sd0;
                    if (neuron_state_sat) state_saturation_count <= state_saturation_count + 1'b1;
                    if (neuron_fired) begin
                        spike_mask[neuron_idx] <= 1'b1;
                        if ((ENABLE_DN != 0) && dn_count_enable_latched) begin
                            for (dn_j = 0; dn_j < N_DN; dn_j = dn_j + 1)
                                if (dn_mem[dn_j] == neuron_idx)
                                    dn_count_mem[dn_j] <= dn_count_mem[dn_j] + 1'b1;
                        end
                        if (next_count < N_NEURONS) begin
                            next_spike_mem[next_count] <= neuron_idx;
                            next_count <= next_count + 1'b1;
                        end else begin
                            overflow_count <= overflow_count + 1'b1;
                            drop_count <= drop_count + 1'b1;
                        end
                    end
                    if (neuron_idx == N_NEURONS-1) begin
                        neuron_idx <= '0;
                        fsm <= ST_SWAP_PREP;
                    end else neuron_idx <= neuron_idx + 1'b1;
                end

                ST_SWAP_PREP: begin
                    prev_count <= next_count;
                    swap_idx <= '0;
                    if (next_count == 0) fsm <= ST_DONE;
                    else fsm <= ST_SWAP;
                end

                ST_SWAP: begin
                    prev_spike_mem[swap_idx] <= next_spike_mem[swap_idx];
                    if ($unsigned(swap_idx) + 1 >= next_count) fsm <= ST_DONE;
                    else swap_idx <= swap_idx + 1'b1;
                end

                ST_DONE: begin
                    cycle_count_last <= cycle_counter;
                    done <= 1'b1;
                    ready <= 1'b1;
                    fsm <= ST_IDLE;
                end

                default: fsm <= ST_INIT;
            endcase
        end
    end
endmodule