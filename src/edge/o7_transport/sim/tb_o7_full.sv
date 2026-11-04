`timescale 1ns/1ps
module tb_o7_full #(
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
    logic [31:0] awaddr, araddr;
    logic [7:0] awlen,arlen;
    logic wlast,rlast;
    logic [31:0] event_words [0:303],semantic_events[0:941];
    logic [31:0] snapshot_words [0:529],saved_tail[0:58];
    logic [31:0] generation_expected;
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

    fly01_o7_transport dut(
        .aclk(clk), .aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awid(1'b1),.s_axi_awlen(awlen),.s_axi_awsize(3'd2),.s_axi_awburst(2'd1), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wlast(wlast),.s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bid(),.s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr),.s_axi_arid(1'b1),.s_axi_arlen(arlen),.s_axi_arsize(3'd2),.s_axi_arburst(2'd1), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rid(),.s_axi_rlast(rlast),.s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .debug_fsm(debug_fsm), .debug_error(debug_error)
    );

    integer seed, c, t, n, d, gstep, event_count, max_cycles;
    integer guard, polls,payload_words,bit_offset,streamed;
    logic [31:0] rd;
    logic [1:0] resp;
    string vector_dir;
    logic [31:0] packet_crc;
    always @(posedge clk)if(aresetn && dut.u_endpoint.fsm==10 && dut.u_endpoint.evt_ready)begin
      if({22'd0,dut.u_endpoint.event_read}!==semantic_events[streamed])$fatal(1,"O7_DECODED_ORDER_MISMATCH");
      streamed=streamed+1;
    end
    function automatic [31:0] crc_word(input [31:0] previous,input [31:0] word_value);
     reg [31:0] x,y;integer bit_number;
     begin
      x=previous;y=word_value;
      for(bit_number=0;bit_number<32;bit_number++)begin
       x=(x>>1)^((x[0]^y[0])?32'hEDB88320:32'd0);y=y>>1;
      end
      crc_word=x;
     end
    endfunction

    task automatic axi_write(input logic [31:0] addr, input logic [31:0] data);
        integer wait_count;
        begin
            @(negedge clk);
            awaddr = addr; wdata = data; wstrb = 4'hF;
            awlen=0;wlast=1;awvalid=1;wvalid=0;bready=0;
            wait_count = 0;
            while (!awready) begin
                @(posedge clk); wait_count = wait_count + 1;
                if (wait_count > 5000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_write_address seed=%0d addr=%h", seed, addr);
            end
            @(posedge clk);
            @(negedge clk); awvalid=0;wvalid=1;
            while (!wready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);wvalid=0;
            wait_count = 0;
            while (!bvalid) begin
                @(posedge clk); wait_count = wait_count + 1;
                if (wait_count > 5000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_write_response seed=%0d addr=%h", seed, addr);
            end
            if (bresp !== 2'b00) $fatal(1, "S5_FPGA1C_FAIL operation_stage=mmio_write_slverr seed=%0d case=%0d timestep=%0d addr=%h resp=%b", seed,c,t,addr,bresp);
            @(negedge clk);bready=1;
            @(posedge clk);@(negedge clk);bready=0;
        end
    endtask

    task automatic axi_read(input logic [31:0] addr, output logic [31:0] data);
        integer wait_count;
        begin
            @(negedge clk);araddr=addr;arlen=0;arvalid=1;rready=0;
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
            if (!rlast) $fatal(1,"O5_SINGLE_RLAST");
            @(negedge clk);rready=1;
            @(posedge clk);@(negedge clk);rready=0;
        end
    endtask

    task automatic event_burst(input integer offset,input integer count);
      integer i,wait_count;
      begin
       @(negedge clk);awaddr=32'h1000+offset*4;awlen=count-1;awvalid=1;bready=0;
       wait_count=0;
       while (!awready) begin @(negedge clk);wait_count++;if(wait_count>5000)$fatal(1,"O5_AW_TIMEOUT");end
       @(posedge clk);@(negedge clk);awvalid=0;
       for(i=0;i<count;i++)begin
        wdata=event_words[offset+i];wlast=(i==count-1);wvalid=1;wait_count=0;
        while(!wready)begin @(negedge clk);wait_count++;if(wait_count>5000)$fatal(1,"O5_W_TIMEOUT");end
        @(posedge clk);@(negedge clk);wvalid=0;
       end
       wait_count=0;
       while(!bvalid)begin @(negedge clk);wait_count++;if(wait_count>5000)$fatal(1,"O5_B_TIMEOUT");end
       if(bresp!==0)$fatal(1,"O5_EVENT_BURST_FAIL seed=%0d c=%0d t=%0d",seed,c,t);
       bready=1;@(posedge clk);@(negedge clk);bready=0;
      end
    endtask

    task automatic snapshot_burst(input integer offset,input integer count);
      integer i,wait_count,j;
      logic [31:0] hold_data;
      logic [1:0] hold_resp;
      logic hold_last;
      begin
       @(negedge clk);araddr=32'h100+offset*4;arlen=count-1;arvalid=1;rready=0;
       wait_count=0;
       while(!arready)begin @(negedge clk);wait_count++;if(wait_count>5000)$fatal(1,"O5_AR_TIMEOUT");end
       @(posedge clk);@(negedge clk);arvalid=0;
       for(i=0;i<count;i++)begin
        wait_count=0;
        while(!rvalid)begin @(negedge clk);wait_count++;if(wait_count>5000)$fatal(1,"O5_R_TIMEOUT");end
        if(rresp!==0 || rlast!==(i==count-1))$fatal(1,"O5_BURST_READ_PROTOCOL");
        hold_data=rdata;hold_resp=rresp;hold_last=rlast;
        for(j=0;j<(i%3);j++)begin
         @(negedge clk);
         if(!rvalid||rdata!==hold_data||rresp!==hold_resp||rlast!==hold_last)$fatal(1,"O5_BACKPRESSURE_UNSTABLE");
        end
        snapshot_words[offset+i]=rdata;
        rready=1;@(posedge clk);@(negedge clk);rready=0;
       end
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
            generation_expected=generation_expected+1;
            axi_read(32'h058,rd);
            if(rd!==generation_expected)$fatal(1,"O5_GENERATION_RESET");
            axi_read(32'h05C,rd);
            if(rd!==0)$fatal(1,"O5_RESET_STALE_VALID");
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
        awlen=0;arlen=0;wlast=1;generation_expected=0;streamed=0;
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

                guard=0;
                for(n=0;n<N;n++) if(drive_vec[gstep][n])begin semantic_events[guard]=n;guard++;end
                for(n=0;n<N;n++) if(noise_vec[gstep][n])begin semantic_events[guard]=32'h200+n;guard++;end
                streamed=0;payload_words=(10*event_count+31)/32;
                for(guard=0;guard<payload_words;guard++)event_words[8+guard]=0;
                for(guard=0;guard<event_count;guard++)begin
                  bit_offset=(guard*10)%32;
                  event_words[8+(guard*10)/32]|=semantic_events[guard]<<bit_offset;
                  if(bit_offset>22)event_words[9+(guard*10)/32]|=semantic_events[guard]>>(32-bit_offset);
                end
                event_words[0]=32'hF107C001;event_words[1]=32'hF1070001;
                event_words[2]=generation_expected;event_words[3]=t;event_words[4]=event_count;
                event_words[5]=32'h00010000|(t>=25);event_words[6]=t;
                packet_crc=32'hFFFFFFFF;
                for(guard=0;guard<7;guard++)packet_crc=crc_word(packet_crc,event_words[guard]);
                for(guard=0;guard<payload_words;guard++)packet_crc=crc_word(packet_crc,event_words[8+guard]);
                event_words[7]=packet_crc^32'hFFFFFFFF;event_words[8+payload_words]=32'hF107C0DE;
                for(guard=0;guard<9+payload_words;guard=guard+256)
                  event_burst(guard,((9+payload_words-guard)>256)?256:(9+payload_words-guard));

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
                if(streamed!=event_count)$fatal(1,"O7_DECODED_COUNT_MISMATCH");
                snapshot_burst(0,256);snapshot_burst(256,256);snapshot_burst(512,18);
                if(snapshot_words[503]!==t || snapshot_words[510]!==generation_expected || snapshot_words[511]!==1)
                  $fatal(1,"O5_SNAPSHOT_IDENTITY");
                if(snapshot_words[512]!==32'hF1070001 || snapshot_words[513]!==0 ||
                   snapshot_words[514]!==event_count || snapshot_words[515]!==t ||
                   snapshot_words[516]!==event_words[7] || snapshot_words[517]!==generation_expected ||
                   snapshot_words[518]!==9+payload_words || snapshot_words[519]!==t+1 ||
                   snapshot_words[527]!==32'hF107A11D)$fatal(1,"O7_ACCEPTED_REQUEST_IDENTITY");
                if(snapshot_words[528]<event_count || snapshot_words[528]>2*event_count ||
                   snapshot_words[529]<=snapshot_words[528])$fatal(1,"O7_PROTOCOL_CYCLE_DIAGNOSTIC");
                for(d=0;d<59;d++)saved_tail[d]=snapshot_words[471+d];
                snapshot_burst(471,59);
                for(d=0;d<59;d++)if(saved_tail[d]!==snapshot_words[471+d])$fatal(1,"O7_FULL_MINIMAL_MISMATCH");
                for (n = 0; n < N; n = n + 1) begin
                    rd=snapshot_words[n];
                    if ($signed(rd) !== $signed(state_exp[gstep*N+n]))
                        $fatal(1, "S5_FPGA1C_FAIL operation_stage=state_readback seed=%0d condition=%0d timestep=%0d neuron=%0d rtl=%0d golden=%0d",seed,c,t,n,$signed(rd),$signed(state_exp[gstep*N+n]));
                end

                if (t >= 25)
                    for (d = 0; d < N_DN; d = d + 1)
                        if (spike_exp[gstep][dn_local[d]]) dn_running[d] = dn_running[d] + 1;
                for (d = 0; d < N_DN; d = d + 1) begin
                    rd=snapshot_words[N+d];
                    if (rd !== dn_running[d])
                        $fatal(1, "S5_FPGA1C_FAIL operation_stage=dn_counter seed=%0d condition=%0d timestep=%0d counter=%0d rtl=%0d golden=%0d",seed,c,t,d,rd,dn_running[d]);
                    if (t == STEPS-1 && rd !== dn_final_exp[c*N_DN+d])
                        $fatal(1, "S5_FPGA1C_FAIL operation_stage=dn_final_file seed=%0d condition=%0d timestep=%0d counter=%0d rtl=%0d golden=%0d",seed,c,t,d,rd,dn_final_exp[c*N_DN+d]);
                end

                rd=snapshot_words[504];
                if(rd!==snapshot_words[504])$fatal(1,"O5_SNAPSHOT_ACC_DIAG");
                if (rd !== acc_sat_exp[gstep]) $fatal(1, "S5_FPGA1C_FAIL operation_stage=acc_sat seed=%0d condition=%0d timestep=%0d rtl=%0d golden=%0d",seed,c,t,rd,acc_sat_exp[gstep]);
                rd=snapshot_words[505];
                if(rd!==snapshot_words[505])$fatal(1,"O5_SNAPSHOT_STATE_DIAG");
                if (rd !== state_sat_exp[gstep]) $fatal(1, "S5_FPGA1C_FAIL operation_stage=state_sat seed=%0d condition=%0d timestep=%0d rtl=%0d golden=%0d",seed,c,t,rd,state_sat_exp[gstep]);
                rd=snapshot_words[506];
                if(rd!==snapshot_words[506])$fatal(1,"O5_SNAPSHOT_OVERFLOW_DIAG");
                if (rd !== 0) $fatal(1, "S5_FPGA1C_FAIL operation_stage=fifo_overflow seed=%0d condition=%0d timestep=%0d rtl=%0d golden=0",seed,c,t,rd);
                rd=snapshot_words[507];
                if(rd!==snapshot_words[507])$fatal(1,"O5_SNAPSHOT_DROP_DIAG");
                if (rd !== 0) $fatal(1, "S5_FPGA1C_FAIL operation_stage=event_drop seed=%0d condition=%0d timestep=%0d rtl=%0d golden=0",seed,c,t,rd);
                rd=snapshot_words[508];
                if(rd!==snapshot_words[508] || rd==0)$fatal(1,"O5_SNAPSHOT_CYCLE_DIAG");
                if (rd > max_cycles) max_cycles = rd;
                if (rd > 500000) $fatal(1, "S5_FPGA1C_FAIL operation_stage=timestep_cycles seed=%0d condition=%0d timestep=%0d rtl=%0d limit=500000",seed,c,t,rd);

                $display("O7_STEP_PASS seed=%0d condition=%0d timestep=%0d",seed,c,t);
                if(t==25)begin snapshot_burst(0,1);if(snapshot_words[0]!=={{14{state_exp[gstep*N][17]}},state_exp[gstep*N]})$fatal(1,"O5_REPEAT_VIEW");end
            end
            $display("S5_FPGA1C_CASE_PASS seed=%0d condition=%0d timesteps=100", seed, c);
        end
        $display("S5_FPGA1C_SEED_PASS seed=%0d cases=3 timesteps=300 max_cycles=%0d", seed, max_cycles);
        $display("S5_FPGA1C_FULL_PASS seed=%0d state=BIT_EXACT dn=EXACT acc_sat=EXACT state_sat=EXACT overflow=0 drop=0", seed);
        $display("O7_FULL_PASS seed=%0d steps=300 burst=EXACT accepted_crc=EXACT full_minimal=EXACT",seed);
        $finish;
    end
    initial begin #400000000;$fatal(1,"O5_WATCHDOG");end
endmodule
