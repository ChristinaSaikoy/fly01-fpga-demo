`timescale 1ns/1ps
module tb_o8_ownership;
 logic aclk=0;always #10 aclk=~aclk;
 logic aresetn=0;
 logic s_axi_awid=1,s_axi_arid=1,s_axi_bid,s_axi_rid;
 logic [31:0] s_axi_awaddr=0,s_axi_wdata=0,s_axi_araddr=0,s_axi_rdata;
 logic [7:0] s_axi_awlen=0,s_axi_arlen=0;
 logic [2:0] s_axi_awsize=2,s_axi_arsize=2;
 logic [1:0] s_axi_awburst=1,s_axi_arburst=1,s_axi_bresp,s_axi_rresp;
 logic [3:0] s_axi_wstrb=15;
 logic s_axi_awvalid=0,s_axi_awready,s_axi_wvalid=0,s_axi_wready,s_axi_wlast=1;
 logic s_axi_bvalid,s_axi_bready=0,s_axi_arvalid=0,s_axi_arready,s_axi_rvalid,s_axi_rready=0,s_axi_rlast;
 logic [31:0] generation=17,next_frame=43,session=32'h7D7E1234,errors=9;
 logic pending=1,core_error=0;logic [3:0] core_fsm=6;
 logic [31:0] hold_word;
 integer checks=0,k,guard;
 fly01_o8_debug_axi dut(.*);
 task automatic pass_case(input string name);
  begin checks++;$display("O8_OWNERSHIP_CASE_PASS index=%0d name=%s",checks,name);end
 endtask
 task automatic deny_write(input logic [31:0] address,input integer count);
  begin
   @(negedge aclk);s_axi_awaddr=address;s_axi_awlen=count-1;s_axi_awvalid=1;
   guard=0;while(!s_axi_awready)begin @(negedge aclk);guard++;if(guard>100)$fatal(1,"OWN_AW_TIMEOUT");end
   @(posedge aclk);@(negedge aclk);s_axi_awvalid=0;
   for(k=0;k<count;k++)begin
    s_axi_wdata=32'hC0DEF00D;s_axi_wlast=k==count-1;s_axi_wvalid=1;
    guard=0;while(!s_axi_wready)begin @(negedge aclk);guard++;if(guard>100)$fatal(1,"OWN_W_TIMEOUT");end
    @(posedge aclk);@(negedge aclk);s_axi_wvalid=0;
   end
   guard=0;while(!s_axi_bvalid)begin @(negedge aclk);guard++;if(guard>100)$fatal(1,"OWN_B_TIMEOUT");end
   repeat(7)begin @(negedge aclk);if(!s_axi_bvalid || s_axi_bresp!==2 || s_axi_bid!==1)$fatal(1,"OWN_WRITE_NOT_DENIED_STABLE");end
   if(generation!==17 || next_frame!==43 || session!==32'h7D7E1234 || !pending || errors!==9)$fatal(1,"OWN_WRITE_CHANGED_MIRRORS");
   s_axi_bready=1;@(posedge aclk);@(negedge aclk);s_axi_bready=0;
  end
 endtask
 task automatic start_read(input logic [31:0] address,input integer count);
  begin
   @(negedge aclk);s_axi_araddr=address;s_axi_arlen=count-1;s_axi_arvalid=1;
   guard=0;while(!s_axi_arready)begin @(negedge aclk);guard++;if(guard>100)$fatal(1,"OWN_AR_TIMEOUT");end
   @(posedge aclk);@(negedge aclk);s_axi_arvalid=0;
  end
 endtask
 task automatic read_beat(input logic [31:0] expected,input logic [1:0] wanted_resp,input logic wanted_last);
  begin
   guard=0;while(!s_axi_rvalid)begin @(negedge aclk);guard++;if(guard>100)$fatal(1,"OWN_R_TIMEOUT");end
   hold_word=s_axi_rdata;
   repeat(7)begin @(negedge aclk);if(!s_axi_rvalid || s_axi_rdata!==hold_word || s_axi_rresp!==wanted_resp || s_axi_rid!==1 || s_axi_rlast!==wanted_last)$fatal(1,"OWN_READ_NOT_STABLE");end
   if(s_axi_rdata!==expected)$fatal(1,"OWN_READ_VALUE got=%h expected=%h",s_axi_rdata,expected);
   s_axi_rready=1;@(posedge aclk);@(negedge aclk);s_axi_rready=0;
  end
 endtask
 initial begin
  repeat(7)@(negedge aclk);aresetn=1;
  deny_write(32'h050,1);pass_case("legacy_science_reset_denied");
  deny_write(32'h1000,2);pass_case("legacy_neural_input_burst_denied");
  deny_write(32'h018,1);pass_case("legacy_commit_denied");
  deny_write(32'h004,1);pass_case("legacy_ack_control_denied");
  start_read(32'h070,3);
  // A multi-beat diagnostic read sees the AR-time snapshot, not mixed live state.
  session=55;pending=0;errors=77;generation=18;next_frame=44;
  read_beat(32'h7D7E1234,0,0);read_beat(1,0,0);read_beat(9,0,1);pass_case("ar_time_mirror_snapshot_and_backpressure");
  start_read(32'h85C,1);read_beat(0,2,1);pass_case("jtag_cannot_consume_uart_dn_result");
  start_read(32'hFFFFFFFC,2);read_beat(0,2,0);read_beat(0,2,1);pass_case("overflowing_address_burst_denied");
  start_read(32'h064,2);read_beat(2000000,0,0);read_beat(1,0,1);pass_case("read_only_uart_owner_identity");
  if(checks!==8)$fatal(1,"OWN_CASE_COUNT");
  $display("O8_OWNERSHIP_PASS checks=8 writes=SLVERR debug_read=NON_CONSUMING ar_snapshot=STABLE");$finish;
 end
 initial begin #1000000;$fatal(1,"O8_OWNERSHIP_WATCHDOG");end
endmodule
