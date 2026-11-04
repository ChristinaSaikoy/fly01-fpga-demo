`timescale 1ns/1ps
module tb_wrapper_full #(
    parameter integer DEFAULT_SEED = 0
);
    localparam integer N = 471;
    localparam integer N_DN = 32;
    localparam integer CASES = 3;
    localparam integer STEPS = 100;
    localparam integer TOTAL_STEPS = CASES*STEPS;

    logic clk = 0;
    always #5 clk = ~clk;
    logic aresetn;
    logic [11:0] awaddr, araddr;
    logic [2:0] awprot, arprot;
    logic awvalid, awready, wvalid, wready, bvalid, bready;
    logic [31:0] wdata, rdata;
    logic [3:0] wstrb;
    logic [1:0] bresp, rresp;
    logic arvalid, arready, rvalid, rready;
    logic [3:0] debug_fsm;
    logic debug_error;

    localparam [11:0] A_CONTROL = 12'h004;
    localparam [11:0] A_STATUS = 12'h008;
    localparam [11:0] A_TIMESTEP = 12'h00C;
    localparam [11:0] A_EVENT_COUNT = 12'h010;
    localparam [11:0] A_EVENT_DATA = 12'h014;
    localparam [11:0] A_EVENT_COMMIT = 12'h018;
    localparam [11:0] A_COMPLETED = 12'h020;
    localparam [11:0] A_STATE_INDEX = 12'h024;
    localparam [11:0] A_STATE_DATA = 12'h028;
    localparam [11:0] A_DN_INDEX = 12'h02C;
    localparam [11:0] A_DN_DATA = 12'h030;
    localparam [11:0] A_ACC_SAT = 12'h034;
    localparam [11:0] A_STATE_SAT = 12'h038;
    localparam [11:0] A_OVERFLOW = 12'h03C;
    localparam [11:0] A_DROP = 12'h040;
    localparam [11:0] A_CYCLES = 12'h044;
    localparam [11:0] A_STEP_CONFIG = 12'h04C;
    localparam [11:0] A_SOFT_RESET = 12'h050;

    logic [N-1:0] drive_vec [0:TOTAL_STEPS-1];
    logic [N-1:0] noise_vec [0:TOTAL_STEPS-1];
    logic [N-1:0] spike_exp [0:TOTAL_STEPS-1];
    logic signed [17:0] state_exp [0:TOTAL_STEPS*N-1];
    logic [31:0] acc_sat_exp [0:TOTAL_STEPS-1];
    logic [31:0] state_sat_exp [0:TOTAL_STEPS-1];
    logic [31:0] dn_final_exp [0:CASES*N_DN-1];
    logic [8:0] dn_local [0:N_DN-1];
    logic [31:0] dn_running [0:N_DN-1];

    fly01_validation_axi dut(
        .aclk(clk), .aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(awprot), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(arprot), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .debug_fsm(debug_fsm), .debug_error(debug_error)
    );

    integer seed, c, t, n, d, gstep, event_count, max_cycles;
    integer guard, polls;
    logic [31:0] rd;
    logic [1:0] resp;
    string vector_dir;

    task automatic axi_write(input logic [11:0] addr, input logic [31:0] data);
        integer wait_count;
        begin
            @(negedge clk);
            awaddr = addr; wdata = data; wstrb = 4'hF;
            awvalid = 1; wvalid = 1; bready = 1;
            wait_count = 0;
            while (!(awready && wready)) begin
                @(posedge clk); wait_count = wait_count + 1;
                if (wait_count > 5000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_write_address seed=%0d addr=%h", seed, addr);
            end
            @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            wait_count = 0;
            while (!bvalid) begin
                @(posedge clk); wait_count = wait_count + 1;
                if (wait_count > 5000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_write_response seed=%0d addr=%h", seed, addr);
            end
            if (bresp !== 2'b00) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_write_slverr seed=%0d case=%0d timestep=%0d addr=%h resp=%b", seed,c,t,addr,bresp);
            @(negedge clk); bready = 0;
        end
    endtask

    task automatic axi_read(input logic [11:0] addr, output logic [31:0] data);
        integer wait_count;
        begin
            @(negedge clk); araddr = addr; arvalid = 1; rready = 1;
            wait_count = 0;
            while (!arready) begin
                @(posedge clk); wait_count = wait_count + 1;
                if (wait_count > 5000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_read_address seed=%0d addr=%h", seed, addr);
            end
            @(posedge clk);
            @(negedge clk); arvalid = 0;
            wait_count = 0;
            while (!rvalid) begin
                @(posedge clk); wait_count = wait_count + 1;
                if (wait_count > 5000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_read_response seed=%0d addr=%h", seed, addr);
            end
            data = rdata;
            if (rresp !== 2'b00) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_read_slverr seed=%0d case=%0d timestep=%0d addr=%h resp=%b", seed,c,t,addr,rresp);
            @(negedge clk); rready = 0;
        end
    endtask

    task automatic soft_reset;
        begin
            axi_write(A_SOFT_RESET, 1);
            guard = 0;
            while (debug_fsm != 4'd2) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 2000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=soft_reset seed=%0d case=%0d fsm=%0d", seed,c,debug_fsm);
            end
        end
    endtask

    initial begin
        seed = DEFAULT_SEED;
        if (!$value$plusargs("SEED=%d", seed)) seed = DEFAULT_SEED;
        if (seed < 0 || seed > 5) $fatal(1, "S5_FPGA1C_FAIL invalid_seed=%0d", seed);
        vector_dir = $sformatf("sim/vectors/l3_seed%0d", seed);
        $readmemh({vector_dir,"/drive_mask.mem"}, drive_vec);
        $readmemh({vector_dir,"/noise_mask.mem"}, noise_vec);
        $readmemh({vector_dir,"/spike_mask_expected.mem"}, spike_exp);
        $readmemh({vector_dir,"/state_expected.mem"}, state_exp);
        $readmemh({vector_dir,"/acc_sat_expected.mem"}, acc_sat_exp);
        $readmemh({vector_dir,"/state_sat_expected.mem"}, state_sat_exp);
        $readmemh({vector_dir,"/dn_counts_expected.mem"}, dn_final_exp);
        $readmemh("generated/dn_local.mem", dn_local);

        aresetn = 0;
        awaddr = 0; awprot = 0; awvalid = 0;
        wdata = 0; wstrb = 4'hF; wvalid = 0; bready = 0;
        araddr = 0; arprot = 0; arvalid = 0; rready = 0;
        max_cycles = 0;
        repeat (5) @(posedge clk);
        @(negedge clk); aresetn = 1;

        for (c = 0; c < CASES; c = c + 1) begin
            soft_reset();
            for (d = 0; d < N_DN; d = d + 1) dn_running[d] = 0;
            for (t = 0; t < STEPS; t = t + 1) begin
                gstep = c*STEPS+t;
                event_count = 0;
                for (n = 0; n < N; n = n + 1) if (drive_vec[gstep][n]) event_count = event_count + 1;
                for (n = 0; n < N; n = n + 1) if (noise_vec[gstep][n]) event_count = event_count + 1;

                axi_write(A_TIMESTEP, t);
                axi_write(A_EVENT_COUNT, event_count);
                axi_write(A_STEP_CONFIG, (t >= 25));
                for (n = 0; n < N; n = n + 1)
                    if (drive_vec[gstep][n]) axi_write(A_EVENT_DATA, n);
                for (n = 0; n < N; n = n + 1)
                    if (noise_vec[gstep][n]) axi_write(A_EVENT_DATA, 32'h00000200+n);
                axi_write(A_EVENT_COMMIT, 1);

                polls = 0;
                rd = 0;
                while (!rd[6]) begin
                    repeat (64) @(posedge clk);
                    axi_read(A_STATUS, rd);
                    polls = polls + 1;
                    if (polls > 8000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=done_poll seed=%0d condition=%0d timestep=%0d fsm=%0d",seed,c,t,rd[3:0]);
                end
                if (rd[7]) $fatal(1, "S5_FPGA1C_FAIL operation_stage=status seed=%0d condition=%0d timestep=%0d status=%h",seed,c,t,rd);
                while (rd[3:0] != 4'd6) begin
                    axi_read(A_STATUS, rd);
                    if (rd[7]) $fatal(1, "S5_FPGA1C_FAIL operation_stage=readback_entry seed=%0d condition=%0d timestep=%0d status=%h",seed,c,t,rd);
                end

                axi_read(A_COMPLETED, rd);
                if (rd !== t) $fatal(1, "S5_FPGA1C_FAIL operation_stage=completed_id seed=%0d condition=%0d timestep=%0d rtl=%0d golden=%0d",seed,c,t,rd,t);
                for (n = 0; n < N; n = n + 1) begin
                    axi_write(A_STATE_INDEX, n);
                    axi_read(A_STATE_DATA, rd);
                    if ($signed(rd) !== $signed(state_exp[gstep*N+n]))
                        $fatal(1, "S5_FPGA1C_FAIL operation_stage=state_readback seed=%0d condition=%0d timestep=%0d neuron=%0d rtl=%0d golden=%0d",seed,c,t,n,$signed(rd),$signed(state_exp[gstep*N+n]));
                end

                if (t >= 25)
                    for (d = 0; d < N_DN; d = d + 1)
                        if (spike_exp[gstep][dn_local[d]]) dn_running[d] = dn_running[d] + 1;
                for (d = 0; d < N_DN; d = d + 1) begin
                    axi_write(A_DN_INDEX, d);
                    axi_read(A_DN_DATA, rd);
                    if (rd !== dn_running[d])
                        $fatal(1, "S5_FPGA1C_FAIL operation_stage=dn_counter seed=%0d condition=%0d timestep=%0d counter=%0d rtl=%0d golden=%0d",seed,c,t,d,rd,dn_running[d]);
                    if (t == STEPS-1 && rd !== dn_final_exp[c*N_DN+d])
                        $fatal(1, "S5_FPGA1C_FAIL operation_stage=dn_final_file seed=%0d condition=%0d timestep=%0d counter=%0d rtl=%0d golden=%0d",seed,c,t,d,rd,dn_final_exp[c*N_DN+d]);
                end

                axi_read(A_ACC_SAT, rd);
                if (rd !== acc_sat_exp[gstep]) $fatal(1, "S5_FPGA1C_FAIL operation_stage=acc_sat seed=%0d condition=%0d timestep=%0d rtl=%0d golden=%0d",seed,c,t,rd,acc_sat_exp[gstep]);
                axi_read(A_STATE_SAT, rd);
                if (rd !== state_sat_exp[gstep]) $fatal(1, "S5_FPGA1C_FAIL operation_stage=state_sat seed=%0d condition=%0d timestep=%0d rtl=%0d golden=%0d",seed,c,t,rd,state_sat_exp[gstep]);
                axi_read(A_OVERFLOW, rd);
                if (rd !== 0) $fatal(1, "S5_FPGA1C_FAIL operation_stage=fifo_overflow seed=%0d condition=%0d timestep=%0d rtl=%0d golden=0",seed,c,t,rd);
                axi_read(A_DROP, rd);
                if (rd !== 0) $fatal(1, "S5_FPGA1C_FAIL operation_stage=event_drop seed=%0d condition=%0d timestep=%0d rtl=%0d golden=0",seed,c,t,rd);
                axi_read(A_CYCLES, rd);
                if (rd > max_cycles) max_cycles = rd;
                if (rd > 500000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=timestep_cycles seed=%0d condition=%0d timestep=%0d rtl=%0d limit=500000",seed,c,t,rd);

                if (t != STEPS-1) axi_write(A_CONTROL, 2);
            end
            $display("S5_FPGA1C_CASE_PASS seed=%0d condition=%0d timesteps=100", seed, c);
        end
        $display("S5_FPGA1C_SEED_PASS seed=%0d cases=3 timesteps=300 max_cycles=%0d", seed, max_cycles);
        $display("S5_FPGA1C_FULL_PASS seed=%0d state=BIT_EXACT dn=EXACT acc_sat=EXACT state_sat=EXACT overflow=0 drop=0", seed);
        $finish;
    end
endmodule
