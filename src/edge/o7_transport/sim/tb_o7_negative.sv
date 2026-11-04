`timescale 1ns/1ps
module tb_o7_negative;
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
 logic [31:0] words[0:950],read_words[0:529],packet[0:950],semantic_events[0:941];
 integer guard,i,j,checks=0;
 logic [31:0] value,gen,hold_data;
 logic [1:0] hold_resp;
 fly01_o7_transport #(.PACKET_TIMEOUT_CYCLES(5000)) dut(.*);
 integer commits=0,packet_count,packet_size,expected_commits,aborted_commits;
 integer payload_words,bit_offset,core_events=0,expected_core_events;
 logic [31:0] crc;
 logic [31:0] collision_crc;
 logic [9:0] collision_a[0:19],collision_b[0:19];
 always @(posedge aclk)if(aresetn && dut.u_endpoint.step_commit)commits++;
 always @(posedge aclk)if(aresetn && dut.u_endpoint.fsm==10 && !debug_error && dut.u_endpoint.evt_ready)begin
  if(dut.u_endpoint.event_read!==semantic_events[core_events-expected_core_events][9:0])$fatal(1,"NEG_DECODE_ORDER");
  core_events++;
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
   expected_commits=commits;expected_core_events=core_events;
  end
 endtask
 task automatic check_latch;
  begin
   rb(32'h48,1);if(value==0 || debug_fsm!=15 || !debug_error)$fatal(1,"NEG_NOT_LATCHED");
   rb(32'h5C,1);if(value!==0)$fatal(1,"NEG_ERROR_VALID");
   if(commits!=expected_commits)$fatal(1,"NEG_INVALID_PACKET_COMMITTED");
   if(core_events!=expected_core_events)$fatal(1,"NEG_INVALID_PACKET_STIMULATED_CORE");
   checks++;$display("O7_NEGATIVE_CASE_PASS check=%0d",checks);
  end
 endtask
 task automatic repack;
  begin
   payload_words=(10*packet_count+31)/32;packet_size=9+payload_words;
   for(i=0;i<payload_words;i++)packet[8+i]=0;
   for(i=0;i<packet_count;i++)begin
    bit_offset=(i*10)%32;packet[8+(i*10)/32]|=semantic_events[i]<<bit_offset;
    if(bit_offset>22)packet[9+(i*10)/32]|=semantic_events[i]>>(32-bit_offset);
   end
   crc=32'hFFFFFFFF;for(i=0;i<7;i++)crc=crc_word(crc,packet[i]);
   for(i=0;i<payload_words;i++)crc=crc_word(crc,packet[8+i]);
   packet[7]=crc^32'hFFFFFFFF;packet[8+payload_words]=32'hF107C0DE;
  end
 endtask
 task automatic make_packet(input integer frame_id,input integer count);
  begin
   rb(32'h58,1);gen=value;packet_count=count;
   packet[0]=32'hF107C001;packet[1]=32'hF1070001;packet[2]=gen;packet[3]=frame_id;
   packet[4]=count;packet[5]=32'h00010001;packet[6]=frame_id;
   for(i=0;i<count;i++)semantic_events[i]=i<471?i:32'h200+(i-471);
   repack();
  end
 endtask
 task automatic send_prefix(input integer length,input logic [1:0] wanted=0);
  integer offset,k,count;
  begin
   for(offset=0;offset<length;offset+=256)begin
    count=(length-offset)>256?256:length-offset;
    for(k=0;k<count;k++)words[k]=packet[offset+k];
    wb(32'h1000+4*offset,count,wanted);
   end
  end
 endtask
 task automatic step_zero;
  begin
   make_packet(0,0);send_prefix(9);
   guard=0;while(debug_fsm!=6)begin @(negedge aclk);guard++;if(guard>500000)$fatal(1,"NEG_FRAME_TIMEOUT");end
   expected_commits=commits;expected_core_events=core_events;
  end
 endtask
 task automatic pass_case;
  begin checks++;$display("O7_NEGATIVE_CASE_PASS check=%0d",checks);end
 endtask
 initial begin
  `include "sim/o7_crc_collision.svh"
  repeat(5)@(negedge aclk);aresetn=1;
  reset_load();make_packet(0,0);
  if(packet[7]!==32'h3DEF8EB8)$fatal(1,"NEG_CRC_ZLIB_KNOWN_VECTOR");
  rb(0,1);if(value!==32'hF1071C01)$fatal(1,"NEG_PROTOCOL_IDENTITY");
  // Retained AXI shape/address/backpressure gates.
  reset_load();rb(32'h100,1,2);check_latch();
  reset_load();rb(32'h101,1,2);check_latch();
  reset_load();rb(32'h10000054,1,2);check_latch();
  reset_load();rb(0,2,2);check_latch();
  reset_load();rb(32'hFFC,2,2);check_latch();
  reset_load();s_axi_arsize=1;rb(32'h54,1,2);s_axi_arsize=2;check_latch();
  reset_load();s_axi_arburst=0;rb(32'h54,1,2);s_axi_arburst=1;check_latch();
  reset_load();words[0]=32'hF107C001;wb(32'h1000,1,2,1);check_latch();
  reset_load();wr(32'h4,2,2);check_latch();
  reset_load();wr(32'h1004,0,2);check_latch();
  reset_load();wr(32'h1000,0,2);check_latch();
  reset_load();make_packet(0,0);packet[1]=32'hF1050002;send_prefix(2,2);check_latch();
  reset_load();make_packet(0,0);packet[2]=gen+1;send_prefix(3,2);check_latch();
  reset_load();make_packet(2,0);send_prefix(4,2);check_latch();
  reset_load();make_packet(0,0);packet[4]=943;send_prefix(5,2);check_latch();
  reset_load();make_packet(0,0);packet[5]=2;send_prefix(6,2);check_latch();
  reset_load();make_packet(0,0);packet[6]=1;send_prefix(7,2);check_latch();
  reset_load();make_packet(0,0);packet[7]^=1;send_prefix(9,2);check_latch();
  reset_load();make_packet(0,0);packet[8]=0;send_prefix(9,2);check_latch();
  reset_load();make_packet(0,1);packet[8]=32'h400;send_prefix(9,2);check_latch();
  reset_load();make_packet(0,1);packet[8]=471;send_prefix(9,2);check_latch();
  reset_load();make_packet(0,2);semantic_events[0]=1;semantic_events[1]=0;repack();send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,2);semantic_events[0]=0;semantic_events[1]=0;repack();send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,2);semantic_events[0]=512;semantic_events[1]=1;repack();send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,2);semantic_events[0]=513;semantic_events[1]=512;repack();send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,0);send_prefix(1);wr(32'h1008,0,2);check_latch();
  reset_load();make_packet(0,0);send_prefix(1);repeat(5100)@(negedge aclk);check_latch();
  // Half-packet reset does not commit; clean generation and new frame0 recover.
  reset_load();expected_commits=commits;make_packet(0,1);send_prefix(8);reset_load();
  if(commits!=expected_commits)$fatal(1,"NEG_HALF_PACKET_COMMITTED");step_zero();rb(32'h85C,59);pass_case();
  // Identical retry is a hardware idempotent replay, not a second neural step.
  reset_load();step_zero();rb(32'h85C,59);expected_commits=commits;
  send_prefix(9);rb(32'h85C,59);if(commits!=expected_commits || read_words[48]!==1 || read_words[49]!==1)$fatal(1,"NEG_REPLAY_EXECUTED");pass_case();
  // Conflicting valid checksum on the same completed frame is rejected.
  reset_load();step_zero();rb(32'h85C,59);make_packet(0,1);send_prefix(10,2);check_latch();
  // Next frame cannot ACK an unread or only partly read result.
  reset_load();step_zero();make_packet(1,0);send_prefix(9,2);check_latch();
  reset_load();step_zero();rb(32'h85C,58);make_packet(1,0);send_prefix(9,2);check_latch();
  // A legal, same-length CRC collision must not impersonate an identical retry.
  reset_load();make_packet(0,20);
  for(i=0;i<20;i++)semantic_events[i]=collision_a[i];
  repack();collision_crc=packet[7];send_prefix(packet_size);guard=0;
  while(debug_fsm!=6)begin @(negedge aclk);guard++;if(guard>500000)$fatal(1,"NEG_COLLISION_FIRST_RUN_TIMEOUT");end
  expected_commits=commits;expected_core_events=core_events;rb(32'h85C,59);make_packet(0,20);
  for(i=0;i<20;i++)semantic_events[i]=collision_b[i];repack();
  if(packet[7]!==collision_crc)$fatal(1,"NEG_COLLISION_NOT_REAL");
  send_prefix(packet_size,2);check_latch();
  // Maximum legal capacity, two packed bursts, then full diagnostic consume.
  reset_load();make_packet(0,942);send_prefix(packet_size);
  guard=0;while(debug_fsm!=6)begin @(negedge aclk);guard++;if(guard>500000)$fatal(1,"NEG_MAX_RUN_TIMEOUT");end
  rb(32'h85C,59);if(read_words[43]!==942 || read_words[47]!==304 || core_events-expected_core_events!=942)$fatal(1,"NEG_MAX_COUNT");pass_case();
  // External reset during a half packet; subsequent guarded reset restores core.
  reset_load();make_packet(0,1);send_prefix(8);aresetn=0;repeat(5)@(negedge aclk);aresetn=1;
  reset_load();step_zero();rb(32'h85C,59);pass_case();
  // Guarded reset interrupts accepted-event drain before any neural commit.
  reset_load();aborted_commits=commits;make_packet(0,942);send_prefix(packet_size);
  if(debug_fsm!=10 && debug_fsm!=11)$fatal(1,"NEG_NOT_IN_DRAIN");
  reset_load();if(commits!=aborted_commits)$fatal(1,"NEG_DRAIN_ABORT_COMMITTED");
  step_zero();rb(32'h85C,59);pass_case();
  // Reset during neural RUN invalidates the in-flight result and rebuilds state.
  reset_load();make_packet(0,0);send_prefix(9);
  if(debug_fsm!=4)$fatal(1,"NEG_NOT_IN_RUN");reset_load();
  step_zero();rb(32'h85C,59);if(read_words[32]!==0)$fatal(1,"NEG_RUN_RESET_STALE_FRAME");pass_case();
  // Additional fixed codec gates: legacy and unsupported encodings fail closed.
  reset_load();make_packet(0,1);packet[0]=32'hF106C001;send_prefix(1,2);check_latch();
  reset_load();make_packet(0,1);packet[5]=1;send_prefix(6,2);check_latch();
  reset_load();make_packet(0,1);packet[5]=32'h00020001;send_prefix(6,2);check_latch();
  reset_load();make_packet(0,1);packet[8]|=32'h80000000;send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,1);semantic_events[0]=983;repack();send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,4);packet[9]=32'hF107C0DE;send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,1);packet[7]^=1;send_prefix(packet_size,2);check_latch();
  reset_load();make_packet(0,942);send_prefix(9);if(core_events!=expected_core_events)$fatal(1,"NEG_PARTIAL_DECODE_LEAK");
  reset_load();step_zero();rb(32'h85C,59);pass_case();
  // Same node in the two classes stays two distinct, correctly ordered events.
  reset_load();make_packet(0,4);semantic_events[0]=0;semantic_events[1]=470;semantic_events[2]=512;semantic_events[3]=982;
  repack();send_prefix(packet_size);guard=0;
  while(debug_fsm!=6)begin @(negedge aclk);guard++;if(guard>500000)$fatal(1,"NEG_BOUNDARY_RUN_TIMEOUT");end
  rb(32'h85C,59);if(read_words[43]!==4 || core_events-expected_core_events!=4)$fatal(1,"NEG_BOUNDARY_COUNT");pass_case();
  if(checks!=46)$fatal(1,"NEG_CHECK_COUNT actual=%0d",checks);
  $display("O7_NEGATIVE_PASS checks=46 reset_recovery=PASS capacity=942 idempotence=PASS CRC_collision_rejected=PASS no_implicit_unread_ack=PASS packed10=PASS");$finish;
 end
 initial begin #400000000;$fatal(1,"O7_WATCHDOG");end
endmodule
