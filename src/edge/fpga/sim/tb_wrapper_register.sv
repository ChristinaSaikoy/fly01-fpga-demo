`timescale 1ns/1ps
module tb_wrapper_register;
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

    localparam [11:0] A_PROTOCOL = 12'h000;
    localparam [11:0] A_CONTROL = 12'h004;
    localparam [11:0] A_STATUS = 12'h008;
    localparam [11:0] A_TIMESTEP = 12'h00C;
    localparam [11:0] A_EVENT_COUNT = 12'h010;
    localparam [11:0] A_EVENT_DATA = 12'h014;
    localparam [11:0] A_EVENT_COMMIT = 12'h018;
    localparam [11:0] A_ACCEPTED = 12'h01C;
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
    localparam [11:0] A_ERROR = 12'h048;
    localparam [11:0] A_STEP_CONFIG = 12'h04C;
    localparam [11:0] A_SOFT_RESET = 12'h050;

    fly01_validation_axi dut(
        .aclk(clk), .aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(awprot), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(arprot), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .debug_fsm(debug_fsm), .debug_error(debug_error)
    );

    integer timeout;
    logic [31:0] rd;
    logic [1:0] resp;
    logic saw_reset, saw_load, saw_arm, saw_run, saw_done, saw_readback, saw_error;

    always @(posedge clk) begin
        if (aresetn) begin
            if (debug_fsm == 4'd1) saw_reset <= 1;
            if (debug_fsm == 4'd2) saw_load <= 1;
            if (debug_fsm == 4'd3) saw_arm <= 1;
            if (debug_fsm == 4'd4) saw_run <= 1;
            if (debug_fsm == 4'd5) saw_done <= 1;
            if (debug_fsm == 4'd6) saw_readback <= 1;
            if (debug_fsm == 4'd15) saw_error <= 1;
        end
    end

    task automatic axi_write(input logic [11:0] addr, input logic [31:0] data, output logic [1:0] response);
        integer guard;
        begin
            @(negedge clk);
            awaddr = addr; wdata = data; wstrb = 4'hF;
            awvalid = 1; wvalid = 1; bready = 1;
            guard = 0;
            while (!(awready && wready)) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 2000) $fatal(1, "REGISTER_TB_FAIL write_address_timeout addr=%h", addr);
            end
            @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            guard = 0;
            while (!bvalid) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 2000) $fatal(1, "REGISTER_TB_FAIL write_response_timeout addr=%h", addr);
            end
            response = bresp;
            @(negedge clk); bready = 0;
        end
    endtask

    task automatic axi_read(input logic [11:0] addr, output logic [31:0] data, output logic [1:0] response);
        integer guard;
        begin
            @(negedge clk); araddr = addr; arvalid = 1; rready = 1;
            guard = 0;
            while (!arready) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 2000) $fatal(1, "REGISTER_TB_FAIL read_address_timeout addr=%h", addr);
            end
            @(posedge clk);
            @(negedge clk); arvalid = 0;
            guard = 0;
            while (!rvalid) begin
                @(posedge clk); guard = guard + 1;
                if (guard > 2000) $fatal(1, "REGISTER_TB_FAIL read_response_timeout addr=%h", addr);
            end
            data = rdata; response = rresp;
            @(negedge clk); rready = 0;
        end
    endtask

    task automatic expect_ok_write(input logic [11:0] addr, input logic [31:0] data);
        begin
            axi_write(addr, data, resp);
            if (resp !== 2'b00) $fatal(1, "REGISTER_TB_FAIL unexpected_write_resp addr=%h resp=%b", addr, resp);
        end
    endtask

    task automatic expect_ok_read(input logic [11:0] addr, output logic [31:0] data);
        begin
            axi_read(addr, data, resp);
            if (resp !== 2'b00) $fatal(1, "REGISTER_TB_FAIL unexpected_read_resp addr=%h resp=%b", addr, resp);
        end
    endtask

    task automatic wait_load;
        begin
            timeout = 0;
            while (debug_fsm != 4'd2) begin
                @(posedge clk); timeout = timeout + 1;
                if (timeout > 2000) $fatal(1, "REGISTER_TB_FAIL load_timeout fsm=%0d", debug_fsm);
            end
        end
    endtask

    task automatic soft_reset_and_wait;
        begin
            expect_ok_write(A_SOFT_RESET, 32'd1);
            wait_load();
            expect_ok_read(A_ERROR, rd);
            if (rd !== 0 || debug_error) $fatal(1, "REGISTER_TB_FAIL soft_reset_did_not_clear error=%h", rd);
        end
    endtask

    initial begin
        aresetn = 0;
        awaddr = 0; awprot = 0; awvalid = 0;
        wdata = 0; wstrb = 4'hF; wvalid = 0; bready = 0;
        araddr = 0; arprot = 0; arvalid = 0; rready = 0;
        saw_reset = 0; saw_load = 0; saw_arm = 0; saw_run = 0;
        saw_done = 0; saw_readback = 0; saw_error = 0;
        repeat (5) @(posedge clk);
        @(negedge clk); aresetn = 1;

        expect_ok_read(A_PROTOCOL, rd);
        if (rd !== 32'hF1011C01) $fatal(1, "REGISTER_TB_FAIL protocol_id=%h", rd);
        soft_reset_and_wait();

        expect_ok_write(A_TIMESTEP, 0);
        expect_ok_write(A_EVENT_COUNT, 2);
        expect_ok_write(A_STEP_CONFIG, 1);
        expect_ok_write(A_EVENT_DATA, 32'd3);
        expect_ok_write(A_EVENT_DATA, 32'h00000207);
        expect_ok_read(A_ACCEPTED, rd);
        if (rd !== 2) $fatal(1, "REGISTER_TB_FAIL accepted=%0d", rd);
        expect_ok_read(A_STEP_CONFIG, rd);
        if (rd !== 1) $fatal(1, "REGISTER_TB_FAIL dn_count_enable=%0d", rd);
        expect_ok_write(A_EVENT_COMMIT, 1);

        timeout = 0;
        while (debug_fsm != 4'd6) begin
            @(posedge clk); timeout = timeout + 1;
            if (timeout > 500000) $fatal(1, "REGISTER_TB_FAIL run_timeout fsm=%0d", debug_fsm);
        end
        expect_ok_read(A_STATUS, rd);
        if (rd[6] !== 1 || rd[3:0] !== 4'd6) $fatal(1, "REGISTER_TB_FAIL done_status=%h", rd);
        expect_ok_read(A_COMPLETED, rd);
        if (rd !== 0) $fatal(1, "REGISTER_TB_FAIL completed_id=%0d", rd);
        expect_ok_write(A_STATE_INDEX, 3);
        expect_ok_read(A_STATE_DATA, rd);
        if (^rd === 1'bx) $fatal(1, "REGISTER_TB_FAIL state_read_x");
        expect_ok_write(A_DN_INDEX, 0);
        expect_ok_read(A_DN_DATA, rd);
        expect_ok_read(A_ACC_SAT, rd);
        expect_ok_read(A_STATE_SAT, rd);
        expect_ok_read(A_OVERFLOW, rd);
        if (rd !== 0) $fatal(1, "REGISTER_TB_FAIL overflow=%0d", rd);
        expect_ok_read(A_DROP, rd);
        if (rd !== 0) $fatal(1, "REGISTER_TB_FAIL drop=%0d", rd);
        expect_ok_read(A_CYCLES, rd);
        if (rd == 0 || rd > 500000) $fatal(1, "REGISTER_TB_FAIL cycles=%0d", rd);
        expect_ok_write(A_CONTROL, 2);
        wait_load();
        expect_ok_read(A_TIMESTEP, rd);
        if (rd !== 1) $fatal(1, "REGISTER_TB_FAIL next_timestep=%0d", rd);

        expect_ok_write(A_EVENT_COUNT, 1);
        axi_write(A_EVENT_DATA, 32'd471, resp);
        if (resp !== 2'b10) $fatal(1, "REGISTER_TB_FAIL invalid_event_resp=%b", resp);
        expect_ok_read(A_ERROR, rd);
        if (rd !== 2 || !debug_error) $fatal(1, "REGISTER_TB_FAIL invalid_event_error=%0d", rd);
        soft_reset_and_wait();

        expect_ok_write(A_TIMESTEP, 9);
        expect_ok_write(A_EVENT_COUNT, 0);
        axi_write(A_EVENT_COMMIT, 1, resp);
        if (resp !== 2'b10) $fatal(1, "REGISTER_TB_FAIL timestep_sequence_resp=%b", resp);
        expect_ok_read(A_ERROR, rd);
        if (rd !== 5) $fatal(1, "REGISTER_TB_FAIL timestep_sequence_error=%0d", rd);
        soft_reset_and_wait();

        axi_read(12'h0FC, rd, resp);
        if (resp !== 2'b10) $fatal(1, "REGISTER_TB_FAIL invalid_address_resp=%b", resp);
        expect_ok_read(A_ERROR, rd);
        if (rd !== 7) $fatal(1, "REGISTER_TB_FAIL invalid_address_error=%0d", rd);
        soft_reset_and_wait();

        if (!(saw_reset && saw_load && saw_arm && saw_run && saw_done && saw_readback && saw_error))
            $fatal(1, "REGISTER_TB_FAIL fsm_coverage reset=%0d load=%0d arm=%0d run=%0d done=%0d readback=%0d error=%0d",
                saw_reset,saw_load,saw_arm,saw_run,saw_done,saw_readback,saw_error);
        $display("MMIO_LOAD_PASS accepted_event_count=2 state_and_dn_indexed_read=PASS");
        $display("FSM_PASS IDLE_RESET_LOAD_ARM_RUN_DONE_READBACK_ERROR=OBSERVED");
        $display("S5_FPGA1C_REGISTER_WRAPPER_PASS");
        $finish;
    end
endmodule
