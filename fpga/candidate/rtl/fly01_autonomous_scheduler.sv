`timescale 1ns/1ps
module fly01_autonomous_scheduler #(
    parameter integer CLOCK_HZ = 50_000_000,
    parameter integer STEP_MS = 20,
    parameter integer USE_VISUAL_MASK = 0,
    parameter integer MAX_OBSERVATION_AGE_STEPS = 12
)(
    input  logic clk,
    input  logic reset_n,
    input  logic run_enable,
    input  logic debug_mode,

    input  logic observation_valid,
    output logic observation_ready,
    input  logic observation_usable,
    input  logic observation_integrity_ok,
    input  logic [31:0] observation_session,
    input  logic [31:0] observation_source_seq,
    input  logic [15:0] observation_age_ms,
    input  logic [31:0] observation_queue_cycles,
    input  logic [1:0] observation_group,
    input logic [470:0] observation_mask,
    input logic observation_mask_valid,
    input  logic [31:0] observation_target_step,

    input  logic noise_valid,
    output logic noise_ready,
    input  logic [31:0] noise_step,
    input  logic [31:0] noise_session,
    input  logic noise_integrity_ok,
    input  logic [470:0] noise_mask,

    output logic core_evt_valid,
    input  logic core_evt_ready,
    output logic core_evt_kind_noise,
    output logic [8:0] core_evt_neuron,
    output logic core_step_commit,
    input  logic core_step_busy,
    input  logic core_step_done,
    output logic core_dn_count_enable,
    output logic [4:0] core_dn_counter_sel,
    input  logic [31:0] core_dn_counter_data,

    output logic [31:0] model_step,
    output logic [31:0] deadline_miss_count,
    output logic [31:0] completed_step_count,
    output logic output_valid,
    input  logic output_ready,
    output logic [31:0] output_step,
    output logic [1023:0] output_dn_delta,
    output logic [31:0] adopted_session, adopted_seq,
    output logic adopted_usable,
    output logic [31:0] adopted_age_cycles,
    output logic fault,
    output logic [7:0] fault_code
);
    localparam integer STEP_CYCLES = (CLOCK_HZ / 1000) * STEP_MS;
    localparam integer CYCLES_PER_MS = CLOCK_HZ / 1000;
    localparam integer MAX_AGE_CYCLES = CYCLES_PER_MS * 250;
    localparam logic [7:0] FAULT_NOISE_MISSING = 8'h01;
    localparam logic [7:0] FAULT_NOISE_STEP = 8'h02;
    localparam logic [7:0] FAULT_OBSERVATION_ORDER = 8'h03;
    localparam logic [7:0] FAULT_DN_NONBINARY = 8'h04;
    localparam logic [7:0] FAULT_MODE_CONFLICT = 8'h05;
    localparam logic [7:0] FAULT_OBSERVATION_IDENTITY = 8'h06;
    localparam logic [7:0] FAULT_NOISE_IDENTITY = 8'h07;

    localparam logic [1:0] GROUP_NONE = 2'd0;
    localparam logic [1:0] GROUP_LEFT = 2'd1;
    localparam logic [1:0] GROUP_RIGHT = 2'd2;
    localparam logic [1:0] GROUP_BILATERAL = 2'd3;

    typedef enum logic [3:0] {
        S_IDLE, S_PREPARE, S_STIM_SCAN, S_NOISE_SCAN, S_COMMIT,
        S_WAIT_CORE, S_DN_ADDR, S_DN_CAPTURE, S_PUBLISH, S_FAULT
    } state_t;
    state_t state;

    logic [31:0] tick_counter;
    logic tick_due;
    logic [470:0] stimulus_masks [0:3];
    logic [470:0] applied_stimulus;
    logic [470:0] latched_noise;
    logic [8:0] scan_index;
    logic pending_valid;
    logic [470:0] pending_mask,held_mask;
    logic pending_transient;
    logic [1:0] pending_group;
    logic [31:0] pending_target_step;
    logic [31:0] pending_age_cycles;
    logic [31:0] active_session, last_observation_seq;
    logic [31:0] latched_session, latched_seq;
    logic latched_usable;
    logic [31:0] latched_age_cycles;
    logic held_valid;
    logic [1:0] held_group;
    logic [31:0] held_age_cycles, held_session, held_seq, pending_session, pending_seq;
    logic [31:0] dn_previous [0:31];
    logic [31:0] dn_current;
    logic [5:0] dn_index;
    integer i;

    initial $readmemh("assets/stimulus_masks_471.mem", stimulus_masks);

    // Preserve the already scheduled next-step observation. An explicit invalid
    // observation may still clear it immediately.
    assign observation_ready = run_enable && !fault && (!pending_valid || !observation_usable);
    assign noise_ready = run_enable && !fault && state == S_IDLE && tick_due && !output_valid;
    assign core_dn_count_enable = 1'b1;
    wire observation_bad = observation_valid && observation_ready &&
        (!observation_integrity_ok || observation_age_ms >= 250 || observation_queue_cycles >= MAX_AGE_CYCLES ||
         (active_session != 0 && observation_session != active_session) ||
         (active_session != 0 && observation_source_seq <= last_observation_seq));
    wire mode_bad = run_enable && debug_mode;
    wire observation_order_bad = observation_valid && observation_ready && observation_usable &&
        (observation_target_step <= model_step || observation_target_step > model_step + MAX_OBSERVATION_AGE_STEPS);
    assign core_evt_valid = !fault && !mode_bad && !observation_bad && !observation_order_bad &&
                            ((state == S_STIM_SCAN && applied_stimulus[scan_index]) ||
                             (state == S_NOISE_SCAN && latched_noise[scan_index]));
    assign core_evt_kind_noise = state == S_NOISE_SCAN;
    assign core_evt_neuron = scan_index;
    assign core_step_commit = !fault && !mode_bad && !observation_bad && !observation_order_bad && state == S_COMMIT && !core_step_busy;
    assign core_dn_counter_sel = dn_index[4:0];

    always_ff @(posedge clk) begin
        if (!reset_n) begin
            state <= S_IDLE;
            tick_counter <= 0;
            tick_due <= 1'b0;
            model_step <= 0;
            deadline_miss_count <= 0;
            completed_step_count <= 0;
            output_valid <= 1'b0;
            output_step <= 0;
            output_dn_delta <= '0;
            fault <= 1'b0;
            fault_code <= 0;
            adopted_session <= 0; adopted_seq <= 0; adopted_usable <= 0;
            latched_session <= 0; latched_seq <= 0; latched_usable <= 0;
            latched_age_cycles <= 0; adopted_age_cycles <= MAX_AGE_CYCLES;
            held_valid <= 0; held_group <= 0; held_age_cycles <= 0;
            held_session <= 0; held_seq <= 0; pending_session <= 0; pending_seq <= 0;
            pending_valid <= 1'b0;
            pending_mask<=0;held_mask<=0;pending_transient<=0;
            pending_group <= GROUP_NONE;
            pending_target_step <= 0;
            pending_age_cycles <= 0;
            active_session <= 0;
            last_observation_seq <= 0;
            applied_stimulus <= '0;
            latched_noise <= '0;
            scan_index <= 0;
            dn_current <= 0;
            dn_index <= 0;
            for (i = 0; i < 32; i = i + 1) dn_previous[i] <= 0;
        end else begin
            if (pending_valid && pending_age_cycles < MAX_AGE_CYCLES)
                pending_age_cycles <= pending_age_cycles + 1'b1;
            if (held_valid && held_age_cycles < MAX_AGE_CYCLES)
                held_age_cycles <= held_age_cycles + 1'b1;
            if (state != S_IDLE && latched_age_cycles < MAX_AGE_CYCLES)
                latched_age_cycles <= latched_age_cycles + 1'b1;

            if (fault) begin
                state <= S_FAULT;
                output_valid <= 1'b0;
            end else if (mode_bad) begin
                fault <= 1'b1;
                fault_code <= FAULT_MODE_CONFLICT;
                state <= S_FAULT;
                output_valid <= 1'b0;
            end else if (observation_bad) begin
                fault <= 1'b1;
                fault_code <= FAULT_OBSERVATION_IDENTITY;
                state <= S_FAULT;
                output_valid <= 1'b0;
            end else if (observation_order_bad) begin
                fault <= 1'b1;
                fault_code <= FAULT_OBSERVATION_ORDER;
                state <= S_FAULT;
                output_valid <= 1'b0;
            end else begin
            if (!run_enable) begin
                tick_counter <= 0;
                tick_due <= 1'b0;
            end else if (tick_counter == STEP_CYCLES-1) begin
                tick_counter <= 0;
                if (tick_due || state != S_IDLE || output_valid) deadline_miss_count <= deadline_miss_count + 1'b1;
                else tick_due <= 1'b1;
            end else tick_counter <= tick_counter + 1'b1;

            if (output_valid && output_ready) output_valid <= 1'b0;

            if (observation_valid && observation_ready) begin
                if (!observation_usable) begin
                    held_valid <= 0;
                    pending_valid <= 1'b0;
                    pending_group <= GROUP_NONE;
                    pending_age_cycles <= 0;
                    active_session <= observation_session;
                    last_observation_seq <= observation_source_seq;
                end else begin
                    pending_valid <= 1'b1;
                    pending_group <= observation_group;
                    pending_mask <= observation_mask_valid ? observation_mask : stimulus_masks[observation_group];
                    pending_transient <= observation_mask_valid;
                    pending_target_step <= observation_target_step;
                    pending_age_cycles <= observation_age_ms * CYCLES_PER_MS + observation_queue_cycles;
                    pending_session <= observation_session; pending_seq <= observation_source_seq;
                    active_session <= observation_session;
                    last_observation_seq <= observation_source_seq;
                end
            end

            case (state)
                S_IDLE: begin
                    if (run_enable && tick_due && !output_valid && noise_valid) begin
                        if (!noise_integrity_ok || noise_session != active_session) begin
                            fault <= 1'b1;
                            fault_code <= FAULT_NOISE_IDENTITY;
                            state <= S_FAULT;
                        end else if (noise_step != model_step) begin
                            fault <= 1'b1;
                            fault_code <= FAULT_NOISE_STEP;
                            state <= S_FAULT;
                        end else begin
                            tick_due <= 1'b0;
                            latched_noise <= noise_mask;
                            latched_session <= active_session; latched_seq <= last_observation_seq;
                            latched_usable <= 0;
                            latched_age_cycles <= MAX_AGE_CYCLES;
                            if (observation_valid && observation_ready && !observation_usable) begin
                                applied_stimulus <= stimulus_masks[GROUP_NONE];
                            end else if (pending_valid && pending_target_step <= model_step &&
                                pending_age_cycles < MAX_AGE_CYCLES) begin
                                applied_stimulus <= USE_VISUAL_MASK ? pending_mask : stimulus_masks[pending_group];
                                held_mask <= pending_transient ? 471'b0 : pending_mask;
                                latched_usable <= 1;
                                latched_session <= pending_session; latched_seq <= pending_seq;
                                latched_age_cycles <= pending_age_cycles;
                                held_valid <= 1; held_group <= pending_group; held_age_cycles <= pending_age_cycles;
                                held_session <= pending_session; held_seq <= pending_seq;
                                if (!(observation_valid && observation_ready)) pending_valid <= 0;
                            end else if (held_valid && held_age_cycles < MAX_AGE_CYCLES) begin
                                applied_stimulus <= USE_VISUAL_MASK ? held_mask : stimulus_masks[held_group];
                                latched_usable <= 1; latched_session <= held_session; latched_seq <= held_seq;
                                latched_age_cycles <= held_age_cycles;
                            end else begin
                                applied_stimulus <= stimulus_masks[GROUP_NONE];
                                if (pending_age_cycles >= MAX_AGE_CYCLES) pending_valid <= 1'b0;
                            end
                            scan_index <= 0;
                            state <= S_PREPARE;
                        end
                    end
                end
                S_PREPARE: state <= S_STIM_SCAN;
                S_STIM_SCAN: begin
                    if (!applied_stimulus[scan_index] || core_evt_ready) begin
                        if (scan_index == 470) begin scan_index <= 0; state <= S_NOISE_SCAN; end
                        else scan_index <= scan_index + 1'b1;
                    end
                end
                S_NOISE_SCAN: begin
                    if (!latched_noise[scan_index] || core_evt_ready) begin
                        if (scan_index == 470) state <= S_COMMIT;
                        else scan_index <= scan_index + 1'b1;
                    end
                end
                S_COMMIT: if (!core_step_busy) state <= S_WAIT_CORE;
                S_WAIT_CORE: begin
                    if (core_step_done) begin
                        dn_index <= 0;
                        state <= S_DN_ADDR;
                    end
                end
                S_DN_ADDR: state <= S_DN_CAPTURE;
                S_DN_CAPTURE: begin
                    dn_current = core_dn_counter_data - dn_previous[dn_index];
                    if (dn_current > 1) begin
                        fault <= 1'b1;
                        fault_code <= FAULT_DN_NONBINARY;
                        state <= S_FAULT;
                    end else begin
                        output_dn_delta[dn_index*32 +: 32] <= dn_current;
                        dn_previous[dn_index] <= core_dn_counter_data;
                        if (dn_index == 31) state <= S_PUBLISH;
                        else begin dn_index <= dn_index + 1'b1; state <= S_DN_ADDR; end
                    end
                end
                S_PUBLISH: begin
                    output_step <= model_step;
                    adopted_session <= latched_session; adopted_seq <= latched_seq; adopted_usable <= latched_usable;
                    adopted_age_cycles <= latched_age_cycles;
                    output_valid <= 1'b1;
                    model_step <= model_step + 1'b1;
                    completed_step_count <= completed_step_count + 1'b1;
                    state <= S_IDLE;
                end
                S_FAULT: begin fault <= 1'b1; state <= S_FAULT; end
                default: state <= S_FAULT;
            endcase
            end
        end
    end
endmodule
