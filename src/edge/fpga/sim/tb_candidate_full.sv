`timescale 1ns/1ps
module tb_candidate_full;
 localparam integer N=471, CASES=3, STEPS=100, TOTAL=300, N_DN=32;
 logic clk=0; always #5 clk=~clk; logic rstn;
 logic [11:0] awaddr;logic [2:0] awprot=0;logic awvalid,awready;
 logic [31:0] wdata;logic [3:0] wstrb;logic wvalid,wready;logic [1:0] bresp;logic bvalid,bready;
 logic [11:0] araddr;logic [2:0] arprot=0;logic arvalid,arready;logic [31:0] rdata;logic [1:0] rresp;logic rvalid,rready;
 logic [3:0] debug_fsm;logic debug_error;
 logic [N-1:0] drive_vec[0:TOTAL-1],noise_vec[0:TOTAL-1];
 logic signed [17:0] state_exp[0:TOTAL*N-1];
 logic [31:0] acc_exp[0:TOTAL-1],state_sat_exp[0:TOTAL-1],dn_exp[0:CASES*N_DN-1];

 fly01_validation_axi dut(.aclk(clk),.aresetn(rstn),
 .s_axi_awaddr(awaddr),.s_axi_awprot(awprot),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
 .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
 .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
 .s_axi_araddr(araddr),.s_axi_arprot(arprot),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
 .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
 .debug_fsm(debug_fsm),.debug_error(debug_error));
 task automatic axi_write(input [11:0] a,input [31:0] d);
  begin
   @(negedge clk);awaddr=a;awvalid=1;wdata=d;wstrb=4'hF;wvalid=1;bready=1;
   do @(posedge clk); while(!(awready&&wready));
   @(negedge clk);awvalid=0;wvalid=0;
   while(!bvalid) @(negedge clk);
   if(bresp!==0)$fatal(1,"AXI_WRITE_FAIL seed=%0d addr=%h resp=%b",seed,a,bresp);
   @(posedge clk);@(negedge clk);bready=0;
  end
 endtask
 task automatic axi_read(input [11:0] a,output [31:0] d);
  begin
   @(negedge clk);araddr=a;arvalid=1;rready=1;
   do @(posedge clk); while(!arready);
   @(negedge clk);arvalid=0;
   while(!rvalid) @(negedge clk); d=rdata;
   if(rresp!==0)$fatal(1,"AXI_READ_FAIL seed=%0d addr=%h resp=%b",seed,a,rresp);
   @(posedge clk);@(negedge clk);rready=0;
  end
 endtask
 task automatic wait_fsm(input [3:0] want,input integer limit);
  integer k;
  begin
   k=0;
   while(debug_fsm!==want) begin @(posedge clk);k=k+1;
    if(k>limit)$fatal(1,"FSM_TIMEOUT seed=%0d want=%0d got=%0d",seed,want,debug_fsm);
   end
  end
 endtask

 integer seed,c,t,n,d,gstep,event_count,max_cycles,case_max;
 logic [31:0] rd; logic signed [17:0] got_state; string dir;
 initial begin
  if(!$value$plusargs("SEED=%d",seed)) seed=0;
  dir=$sformatf("sim/vectors/l3_seed%0d",seed);
  $readmemh({dir,"/drive_mask.mem"},drive_vec);
  $readmemh({dir,"/noise_mask.mem"},noise_vec);
  $readmemh({dir,"/state_expected.mem"},state_exp);
  $readmemh({dir,"/acc_sat_expected.mem"},acc_exp);
  $readmemh({dir,"/state_sat_expected.mem"},state_sat_exp);
  $readmemh({dir,"/dn_counts_expected.mem"},dn_exp);
  awaddr=0;awvalid=0;wdata=0;wstrb=0;wvalid=0;bready=0;araddr=0;arvalid=0;rready=0;rstn=0;
  max_cycles=0;repeat(10)@(posedge clk);@(negedge clk);rstn=1;
  axi_read(12'h000,rd);if(rd!==32'hF1011C01)$fatal(1,"PROTOCOL_ID_FAIL");

  for(c=0;c<CASES;c=c+1) begin
   axi_write(12'h004,32'h1); wait_fsm(4'd2,2000);
   axi_read(12'h008,rd);if(rd[3:0]!==4'd2 || rd[7])$fatal(1,"RESET_LOAD_STATUS_FAIL seed=%0d case=%0d status=%h",seed,c,rd);
   case_max=0;
   for(t=0;t<STEPS;t=t+1) begin
    gstep=c*STEPS+t; event_count=0;
    for(n=0;n<N;n=n+1) begin if(drive_vec[gstep][n])event_count=event_count+1;if(noise_vec[gstep][n])event_count=event_count+1;end
    axi_write(12'h00C,t); axi_write(12'h010,event_count); axi_write(12'h04C,(t>=25)?1:0);
    for(n=0;n<N;n=n+1) if(drive_vec[gstep][n]) axi_write(12'h014,n);
    for(n=0;n<N;n=n+1) if(noise_vec[gstep][n]) axi_write(12'h014,(32'h200|n));
    axi_read(12'h01C,rd);if(rd!==event_count)$fatal(1,"MMIO_LOAD_FAIL seed=%0d case=%0d t=%0d got=%0d exp=%0d",seed,c,t,rd,event_count);
    axi_write(12'h018,1); wait_fsm(4'd6,600000);
    axi_read(12'h008,rd);if(rd[3:0]!==4'd6 || rd[7])$fatal(1,"FSM_READBACK_FAIL seed=%0d case=%0d t=%0d status=%h",seed,c,t,rd);
    axi_read(12'h020,rd);if(rd!==t)$fatal(1,"COMPLETED_ID_FAIL seed=%0d case=%0d t=%0d got=%0d",seed,c,t,rd);

    for(n=0;n<N;n=n+1) begin
     axi_write(12'h024,n);axi_read(12'h028,rd);got_state=rd[17:0];
     if(got_state!==state_exp[gstep*N+n])$fatal(1,"STATE_READBACK_FAIL seed=%0d case=%0d t=%0d n=%0d got=%0d exp=%0d",seed,c,t,n,$signed(got_state),$signed(state_exp[gstep*N+n]));
    end
    axi_read(12'h034,rd);if(rd!==acc_exp[gstep])$fatal(1,"ACC_SAT_FAIL seed=%0d case=%0d t=%0d got=%0d exp=%0d",seed,c,t,rd,acc_exp[gstep]);
    axi_read(12'h038,rd);if(rd!==state_sat_exp[gstep])$fatal(1,"STATE_SAT_FAIL seed=%0d case=%0d t=%0d got=%0d exp=%0d",seed,c,t,rd,state_sat_exp[gstep]);
    axi_read(12'h03C,rd);if(rd!==0)$fatal(1,"FIFO_OVERFLOW seed=%0d case=%0d t=%0d val=%0d",seed,c,t,rd);
    axi_read(12'h040,rd);if(rd!==0)$fatal(1,"EVENT_DROP seed=%0d case=%0d t=%0d val=%0d",seed,c,t,rd);
    axi_read(12'h044,rd);if(rd>500000)$fatal(1,"TIMESTEP_GATE_FAIL seed=%0d case=%0d t=%0d cycles=%0d",seed,c,t,rd);
    if(rd>case_max)case_max=rd;if(rd>max_cycles)max_cycles=rd;
    if(t<STEPS-1)begin axi_write(12'h004,32'h2);wait_fsm(4'd2,100);end
   end

   for(d=0;d<N_DN;d=d+1)begin
    axi_write(12'h02C,d);axi_read(12'h030,rd);
    if(rd!==dn_exp[c*N_DN+d])$fatal(1,"DN_COUNTER_FAIL seed=%0d case=%0d d=%0d got=%0d exp=%0d",seed,c,d,rd,dn_exp[c*N_DN+d]);
   end
   $display("S5_FPGA1C_CASE_PASS seed=%0d case=%0d max_cycles=%0d",seed,c,case_max);
  end
  if(debug_error)$fatal(1,"FINAL_PROTOCOL_ERROR seed=%0d",seed);
  $display("S5_FPGA1C_SEED_PASS seed=%0d cases=3 timesteps=300 state_reads=%0d max_cycles=%0d",seed,TOTAL*N,max_cycles);
  $finish;
 end
endmodule
