`timescale 1ns/1ps
module tb_o5_negative;
 logic aclk=0;always #10 aclk=~aclk;
 logic aresetn=0;
 logic s_axi_awid=1,s_axi_arid=1,s_axi_bid,s_axi_rid;
 logic [31:0] s_axi_awaddr=0,s_axi_wdata=0,s_axi_araddr=0,s_axi_rdata;
 logic [7:0] s_axi_awlen=0,s_axi_arlen=0;
 logic [2:0] s_axi_awsize=2,s_axi_arsize=2;
 logic [1:0] s_axi_awburst=1,s_axi_arburst=1,s_axi_bresp,s_axi_rresp;
 logic [3:0] s_axi_wstrb=15,debug_fsm;
 logic s_axi_awvalid=0,s_axi_awready,s_axi_wvalid=0,s_axi_wready,s_axi_wlast=1;
 logic s_axi_bvalid,s_axi_bready=0,s_axi_arvalid=0,s_axi_arready,s_axi_rvalid,s_axi_rready=0,s_axi_rlast,debug_error;
 logic [31:0] words[0:941],read_words[0:511],saved_words[0:255];
 integer guard,i,j,checks=0;
 logic [31:0] value,gen,hold_data;
 logic [1:0] hold_resp;
 fly01_o5_transport dut(.*);

 task automatic wb(input logic [31:0] addr,input integer count,input logic [1:0] wanted,input logic bad_last=0);
  integer k,w;
  begin
   @(negedge aclk);s_axi_awaddr=addr;s_axi_awlen=count-1;s_axi_awvalid=1;s_axi_bready=0;
   w=0;while(!s_axi_awready)begin @(negedge aclk);w++;if(w>6000)$fatal(1,"NEG_AW_TIMEOUT");end
   @(posedge aclk);@(negedge aclk);s_axi_awvalid=0;
   for(k=0;k<count;k++)begin
    s_axi_wdata=words[k];s_axi_wlast=bad_last?!(k==count-1):(k==count-1);s_axi_wvalid=1;
    w=0;while(!s_axi_wready)begin @(negedge aclk);w++;if(w>6000)$fatal(1,"NEG_W_TIMEOUT");end
    @(posedge aclk);@(negedge aclk);s_axi_wvalid=0;
   end
   w=0;while(!s_axi_bvalid)begin @(negedge aclk);w++;if(w>6000)$fatal(1,"NEG_B_TIMEOUT");end
   if(s_axi_bresp!==wanted || s_axi_bid!==1)$fatal(1,"NEG_B_RESPONSE addr=%h actual=%h expected=%h",addr,s_axi_bresp,wanted);
   hold_resp=s_axi_bresp;
   repeat(4)begin @(negedge aclk);if(!s_axi_bvalid||s_axi_bresp!==hold_resp||s_axi_bid!==1)$fatal(1,"NEG_B_UNSTABLE");end
   s_axi_bready=1;@(posedge aclk);@(negedge aclk);s_axi_bready=0;
  end
 endtask
 task automatic wr(input logic [31:0] addr,input logic [31:0] data,input logic [1:0] wanted=0);
  begin words[0]=data;wb(addr,1,wanted);end
 endtask
 task automatic rb(input logic [31:0] addr,input integer count,input logic [1:0] wanted=0);
  integer k,w;
  logic last_hold;
  begin
   @(negedge aclk);s_axi_araddr=addr;s_axi_arlen=count-1;s_axi_arvalid=1;s_axi_rready=0;
   w=0;while(!s_axi_arready)begin @(negedge aclk);w++;if(w>6000)$fatal(1,"NEG_AR_TIMEOUT");end
   @(posedge aclk);@(negedge aclk);s_axi_arvalid=0;
   for(k=0;k<count;k++)begin
    w=0;while(!s_axi_rvalid)begin @(negedge aclk);w++;if(w>6000)$fatal(1,"NEG_R_TIMEOUT");end
    if(s_axi_rresp!==wanted || s_axi_rlast!==(k==count-1)||s_axi_rid!==1)$fatal(1,"NEG_R_RESPONSE addr=%h k=%d resp=%h",addr,k,s_axi_rresp);
    hold_data=s_axi_rdata;hold_resp=s_axi_rresp;last_hold=s_axi_rlast;
    repeat(3)begin
     @(negedge aclk);
     if(!s_axi_rvalid||s_axi_rdata!==hold_data||s_axi_rresp!==hold_resp||s_axi_rlast!==last_hold)$fatal(1,"NEG_R_UNSTABLE");
    end
    read_words[k]=s_axi_rdata;value=s_axi_rdata;
    s_axi_rready=1;@(posedge aclk);@(negedge aclk);s_axi_rready=0;
   end
  end
 endtask
 task automatic reset_load;
  begin
   s_axi_arsize=2;s_axi_arburst=1;s_axi_awsize=2;s_axi_awburst=1;s_axi_wstrb=15;
   wr(32'h50,1);
   guard=0;while(debug_fsm!=2)begin @(negedge aclk);guard++;if(guard>2000)$fatal(1,"NEG_RESET_TIMEOUT");end
   rb(32'h5C,1);if(value!==0 || debug_error)$fatal(1,"NEG_RESET_INVALIDATION");
  end
 endtask
 task automatic check_latch;
  begin
   rb(32'h48,1);if(value==0 || debug_fsm!=15 || !debug_error)$fatal(1,"NEG_NOT_LATCHED");
   rb(32'h5C,1);if(value!==0)$fatal(1,"NEG_ERROR_VALID");
   checks++;$display("O5_NEGATIVE_CASE_PASS check=%0d",checks);
  end
 endtask
 task automatic frame;
  begin
   reset_load();wr(32'h10,0);wr(32'h68,1);wr(32'h18,1);
   guard=0;while(debug_fsm!=6)begin @(negedge aclk);guard++;if(guard>500000)$fatal(1,"NEG_FRAME_TIMEOUT");end
  end
 endtask
 initial begin
  repeat(5)@(negedge aclk);aresetn=1;
  reset_load();rb(32'h100,1,2);check_latch();
  reset_load();rb(32'h900,1,2);check_latch();
  reset_load();wr(32'h1EB8,0,2);check_latch();
  reset_load();wr(32'h100,0,2);check_latch();
  reset_load();wr(32'h8D8,0,2);check_latch();
  reset_load();rb(32'h101,1,2);check_latch();
  reset_load();rb(32'h10000054,1,2);check_latch();
  reset_load();rb(0,2,2);check_latch();
  reset_load();rb(32'hFFC,2,2);check_latch();
  reset_load();s_axi_arsize=1;rb(32'h54,1,2);s_axi_arsize=2;check_latch();
  reset_load();s_axi_arburst=0;rb(32'h54,1,2);s_axi_arburst=1;check_latch();
  reset_load();words[0]=0;wb(32'h10,1,2,1);check_latch();
  reset_load();wr(32'h10,2);wr(32'h1000,0);wr(32'h68,1,2);check_latch();
  reset_load();wr(32'h10,1);wr(32'h1000,0);wr(32'h18,1,2);check_latch();
  reset_load();wr(32'h10,2);wr(32'h1004,0,2);check_latch();
  reset_load();wr(32'h10,1);wr(32'h1000,32'h400,2);check_latch();
  reset_load();wr(32'h10,1);wr(32'h1000,471,2);check_latch();
  reset_load();wr(32'h10,2);wr(32'h1000,1);wr(32'h1004,0,2);check_latch();
  reset_load();wr(32'h10,2);wr(32'h1000,32'h200);wr(32'h1004,1,2);check_latch();
  reset_load();wr(32'h10,1);wr(32'h1000,0);wr(32'h1004,1,2);check_latch();
  frame();wr(32'h18,1,2);check_latch();
  frame();wr(32'h4,2);rb(32'h100,1,2);check_latch();
  frame();rb(32'h58,1);gen=value;rb(32'h100,256);
  for(i=0;i<256;i++)saved_words[i]=read_words[i];
  for(i=0;i<256;i++)begin
   wr(32'h24,i);rb(32'h28,1);if(value!==saved_words[i])$fatal(1,"NEG_STABLE_INDEXED_CROSSCHECK");
  end
  rb(32'h500,256);
  if(read_words[254]!==gen || read_words[255]!==1)$fatal(1,"NEG_SNAPSHOT_METADATA");
  reset_load();rb(32'h58,1);if(value!==gen+1)$fatal(1,"NEG_GENERATION_CHANGE");
  // Maximum legal capacity, four bursts, exact original FIFO order/count.
  wr(32'h10,942);
  for(i=0;i<256;i++)words[i]=i;wb(32'h1000,256,0);
  for(i=0;i<215;i++)words[i]=256+i;
  for(i=215;i<256;i++)words[i]=32'h200+(i-215);wb(32'h1400,256,0);
  for(i=0;i<256;i++)words[i]=32'h200+41+i;wb(32'h1800,256,0);
  for(i=0;i<174;i++)words[i]=32'h200+297+i;wb(32'h1C00,174,0);
  wr(32'h68,1);rb(32'h1C,1);if(value!==942)$fatal(1,"NEG_MAX_COUNT");
  rb(32'h64,1);if(value!==0)$fatal(1,"NEG_DRAIN_NOT_COMPLETE");
  checks++;$display("O5_NEGATIVE_CASE_PASS check=%0d",checks);
  if(checks!=23)$fatal(1,"NEG_CHECK_COUNT");
  $display("O5_NEGATIVE_PASS checks=23 reset_recovery=PASS capacity=942");$finish;
 end
 initial begin #400000000;$fatal(1,"O5_WATCHDOG");end
endmodule
