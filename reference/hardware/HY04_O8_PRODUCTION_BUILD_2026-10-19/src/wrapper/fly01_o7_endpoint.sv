`timescale 1ns/1ps
// Versioned, checksum-validated frame transport around the unchanged neural core.
// A new valid packet acknowledges a fully consumed previous result, never blindly.
module fly01_o7_endpoint #(parameter integer PACKET_TIMEOUT_CYCLES=50000000)(
 input logic aclk,aresetn,
 input logic [12:0] s_axi_awaddr,input logic [2:0] s_axi_awprot,
 input logic s_axi_awvalid,output logic s_axi_awready,
 input logic [31:0] s_axi_wdata,input logic [3:0] s_axi_wstrb,
 input logic s_axi_wvalid,output logic s_axi_wready,
 output logic [1:0] s_axi_bresp,output logic s_axi_bvalid,input logic s_axi_bready,
 input logic [12:0] s_axi_araddr,input logic [2:0] s_axi_arprot,
 input logic s_axi_arvalid,output logic s_axi_arready,
 output logic [31:0] s_axi_rdata,output logic [1:0] s_axi_rresp,
 output logic s_axi_rvalid,input logic s_axi_rready,
 output logic [3:0] debug_fsm,output logic debug_error
);
 localparam [31:0] VERSION=32'hF1070001, MAGIC=32'hF107C001, SEAL=32'hF107C0DE;
 localparam [3:0] RESET=1,LOAD=2,ARM=3,RUN=4,READBACK=6,DRAIN=10,PREFETCH=11;
 logic [3:0] fsm;
 logic core_rst_n,step_commit,core_busy,core_done,evt_ready,dn_enable;
 logic [9:0] reset_count,accepted_count,event_count,drain_index;
 logic [31:0] generation,next_frame,completed_frame,request_id,last_crc,request_generation;
 logic [31:0] core_cycles,acc_sat,state_sat,overflow,drop,error_status;
 logic fault,have_result,valid;
 logic [31:0] commit_count,replay_count,reject_count,timeout_count,run_guard;
 logic [8:0] probe_index;
 logic probe_dn,linear_pending;
 logic signed [17:0] state_data;
 logic [31:0] dn_data,status;
 logic [58:0] consumed;
 logic response_consumes;
 logic [5:0] response_index;
 (* ram_style="block" *) logic [9:0] events[0:941];
 (* ram_style="block" *) logic [9:0] replay_events[0:941];
 logic [9:0] event_read;
 logic [9:0] replay_read;
 logic aw_hold,w_hold;
 logic [12:0] wa;
 logic [31:0] wd;
 logic [3:0] ws;
 logic packet_active,crc_busy,packet_retry;
 logic [9:0] packet_index,packet_events,last_event;
 logic [31:0] header[0:7],crc_state,crc_word,packet_timer;
 logic [5:0] crc_bit;
 // Fixed canonical 10-bit events. CRC and decoding finish before any core event.
 logic [41:0] unpack_buffer;
 logic [5:0] unpack_count;
 logic unpack_wait;
 logic [31:0] working_decode_cycles,working_protocol_cycles,last_decode_cycles,last_protocol_cycles;
 wire [9:0] packed_event=unpack_buffer[9:0];
 wire [9:0] payload_words=(header[4][9:0]*14'd10+14'd31)>>5;
 wire [13:0] useful_payload_bits=header[4][9:0]*14'd10;
 wire [13:0] remaining_payload_bits=useful_payload_bits-((packet_index-8)<<5);
 wire snapshot_address=s_axi_araddr>=13'h100 && s_axi_araddr<=13'h944;
 wire executing=fsm==ARM || fsm==RUN || fsm==PREFETCH || fsm==DRAIN;
 wire crc_feedback=crc_state[0]^crc_word[0];
 wire [31:0] crc_next=(crc_state>>1)^(crc_feedback?32'hEDB88320:32'd0);
 assign valid=have_result && fsm==READBACK && !fault;
 assign debug_fsm=fault?4'd15:fsm;
 assign debug_error=fault;
 assign status={23'd0,(core_cycles>500000),fault,valid,core_busy,evt_ready,debug_fsm};
 assign s_axi_awready=aresetn && !aw_hold && !s_axi_bvalid && !crc_busy;
 assign s_axi_wready=aresetn && !w_hold && !s_axi_bvalid && !crc_busy;
 assign s_axi_arready=aresetn && !s_axi_rvalid && !linear_pending &&
     (!snapshot_address || !executing || fault);
 fly01_formal_top u_frozen_formal_top(
  .sys_clk(aclk),.sys_rst_n(core_rst_n),
  .evt_valid(fsm==DRAIN && !fault),.evt_kind_noise(event_read[9]),.evt_neuron(event_read[8:0]),.evt_ready(evt_ready),
  .step_commit(step_commit),.dn_count_enable(dn_enable),.step_busy(core_busy),.step_done(core_done),
  .state_probe_addr(probe_index),.state_probe_data(state_data),
  .dn_counter_sel(probe_index[4:0]),.dn_counter_data(dn_data),.timestep_cycles(core_cycles),
  .acc_saturation_count(acc_sat),.state_saturation_count(state_sat),.overflow_count(overflow),.drop_count(drop)
 );
 always_ff @(posedge aclk) event_read<=events[drain_index];
 always_ff @(posedge aclk)begin
  if(packet_events<942)replay_read<=replay_events[packet_events];
  if(aresetn && fsm==DRAIN && !fault && evt_ready)replay_events[drain_index]<=event_read;
 end
 task automatic fail(input logic [31:0] code);
  begin
   if(!fault)begin error_status<=code;reject_count<=reject_count+1'b1;end
   fault<=1;packet_active<=0;crc_busy<=0;
  end
 endtask
 integer j;
 always_ff @(posedge aclk) begin
  if(!aresetn)begin
   fsm<=LOAD;core_rst_n<=0;reset_count<=0;step_commit<=0;dn_enable<=0;
   generation<=0;next_frame<=0;completed_frame<=32'hFFFFFFFF;request_id<=0;last_crc<=0;request_generation<=0;
   fault<=0;have_result<=0;error_status<=0;consumed<=0;accepted_count<=0;event_count<=0;drain_index<=0;
   commit_count<=0;replay_count<=0;reject_count<=0;timeout_count<=0;run_guard<=0;
   aw_hold<=0;w_hold<=0;wa<=0;wd<=0;ws<=0;s_axi_bvalid<=0;s_axi_bresp<=0;
   s_axi_rvalid<=0;s_axi_rresp<=0;s_axi_rdata<=0;linear_pending<=0;probe_index<=0;probe_dn<=0;
   response_consumes<=0;response_index<=0;packet_active<=0;crc_busy<=0;packet_index<=0;
   packet_events<=0;last_event<=0;crc_state<=32'hFFFFFFFF;crc_word<=0;crc_bit<=0;packet_timer<=0;packet_retry<=0;
   unpack_buffer<=0;unpack_count<=0;unpack_wait<=0;
   working_decode_cycles<=0;working_protocol_cycles<=0;last_decode_cycles<=0;last_protocol_cycles<=0;
   for(j=0;j<8;j=j+1)header[j]<=0;
  end else begin
   step_commit<=0;
   if(s_axi_bvalid && s_axi_bready)s_axi_bvalid<=0;
   if(s_axi_rvalid && s_axi_rready)begin
    s_axi_rvalid<=0;
    if(response_consumes && valid)consumed[response_index]<=1;
    response_consumes<=0;
   end
   if(linear_pending)begin
    linear_pending<=0;s_axi_rvalid<=1;
    if(!valid)begin s_axi_rresp<=2;s_axi_rdata<=0;fail(32'h101);end
    else begin s_axi_rresp<=0;s_axi_rdata<=probe_dn?dn_data:{{14{state_data[17]}},state_data};end
   end
   if(s_axi_awvalid && s_axi_awready)begin aw_hold<=1;wa<=s_axi_awaddr;end
   if(s_axi_wvalid && s_axi_wready)begin w_hold<=1;wd<=s_axi_wdata;ws<=s_axi_wstrb;end
   if(packet_active && !crc_busy)begin
    packet_timer<=packet_timer+1'b1;
    if(packet_timer>=PACKET_TIMEOUT_CYCLES-1)begin fail(32'h110);timeout_count<=timeout_count+1'b1;end
   end
   if(crc_busy)begin
    crc_state<=crc_next;crc_word<=crc_word>>1;crc_bit<=crc_bit+1'b1;
    if(crc_bit==31)begin crc_busy<=0;s_axi_bvalid<=1;s_axi_bresp<=0;end
   end
   if(!fault && (packet_active || fsm==PREFETCH || fsm==DRAIN || fsm==ARM))
    working_protocol_cycles<=working_protocol_cycles+1'b1;
   if(unpack_wait)unpack_wait<=0;
   if(crc_busy && !fault && unpack_count>=10 && packet_events<header[4])begin
    working_decode_cycles<=working_decode_cycles+1'b1;
    // One idle cycle makes synchronous replay RAM identity available at each index.
    if(!unpack_wait)begin
     if((packet_retry && packed_event!=replay_read) || packed_event[8:0]>470 || packet_events>=942 ||
        (packet_events!=0 && ((!packed_event[9] && last_event[9]) ||
        (packed_event[9]==last_event[9] && packed_event[8:0]<=last_event[8:0]))))begin
      fail(packet_retry?32'h10F:32'h102);s_axi_bvalid<=1;s_axi_bresp<=2;
     end else begin
      events[packet_events]<=packed_event;last_event<=packed_event;packet_events<=packet_events+1'b1;
      unpack_buffer<=unpack_buffer>>10;unpack_count<=unpack_count-10;unpack_wait<=1;
     end
    end
   end
   if(!fault)case(fsm)
    RESET:begin
     if(reset_count<4)begin core_rst_n<=0;reset_count<=reset_count+1'b1;end
     else if(reset_count<516)begin core_rst_n<=1;reset_count<=reset_count+1'b1;end
     else begin reset_count<=0;fsm<=LOAD;end
    end
    PREFETCH:fsm<=DRAIN;
    DRAIN:if(evt_ready)begin
     accepted_count<=accepted_count+1'b1;
     if(drain_index+1'b1==event_count)fsm<=ARM;
     else begin drain_index<=drain_index+1'b1;fsm<=PREFETCH;end
    end
    ARM:begin
     step_commit<=1;commit_count<=commit_count+1'b1;run_guard<=0;fsm<=RUN;
     last_decode_cycles<=working_decode_cycles;last_protocol_cycles<=working_protocol_cycles+1'b1;
    end
    RUN:begin
     run_guard<=run_guard+1'b1;
     if(core_done)begin
      if(core_cycles>500000 || overflow!=0 || drop!=0)fail(32'h10D);
      else begin completed_frame<=request_id;next_frame<=request_id+1'b1;have_result<=1;fsm<=READBACK;end
     end else if(run_guard>=500000)fail(32'h10E);
    end
    default:begin end
   endcase
   if(aw_hold && w_hold && !s_axi_bvalid && !crc_busy)begin
    aw_hold<=0;w_hold<=0;s_axi_bvalid<=1;s_axi_bresp<=0;
    if(ws!=15)begin fail(32'h107);s_axi_bresp<=2;end
    else if(wa==13'h050 && wd==1)begin
     // Explicit soft reset discards half packets and restores the original guard.
     fsm<=RESET;core_rst_n<=0;reset_count<=0;generation<=generation+1'b1;
     fault<=0;have_result<=0;error_status<=0;consumed<=0;next_frame<=0;completed_frame<=32'hFFFFFFFF;
     packet_active<=0;packet_index<=0;packet_timer<=0;crc_busy<=0;crc_state<=32'hFFFFFFFF;packet_retry<=0;
     accepted_count<=0;event_count<=0;drain_index<=0;dn_enable<=0;run_guard<=0;
     request_id<=0;last_crc<=0;request_generation<=0;
     commit_count<=0;replay_count<=0;reject_count<=0;timeout_count<=0;
     unpack_buffer<=0;unpack_count<=0;unpack_wait<=0;
     working_decode_cycles<=0;working_protocol_cycles<=0;last_decode_cycles<=0;last_protocol_cycles<=0;
    end else if(fault)begin s_axi_bresp<=2;end
    else if(wa<13'h1000 || wa>13'h1ED8 || wa[1:0]!=0 || executing || fsm==RESET)begin
     fail(32'h107);s_axi_bresp<=2;
    end else if((!packet_active && wa!=13'h1000) ||
                (packet_active && ((wa-13'h1000)>>2)!=packet_index))begin
     fail(32'h104);s_axi_bresp<=2;
    end else if(!packet_active)begin
     if(wd!=MAGIC || !core_rst_n)begin fail(32'h108);s_axi_bresp<=2;end
     else begin
      packet_active<=1;packet_index<=1;packet_timer<=0;packet_events<=0;last_event<=0;packet_retry<=0;
      unpack_buffer<=0;unpack_count<=0;unpack_wait<=0;working_decode_cycles<=0;working_protocol_cycles<=0;
      header[0]<=wd;crc_state<=32'hFFFFFFFF;crc_word<=wd;crc_bit<=0;crc_busy<=1;s_axi_bvalid<=0;
     end
    end else if(packet_index<7)begin
     packet_timer<=0;
     if((packet_index==1 && wd!=VERSION) || (packet_index==2 && wd!=generation) ||
        (packet_index==3 && wd!=next_frame && !(have_result && wd==completed_frame)) ||
        (packet_index==4 && (wd>942 || (packet_retry && wd!=event_count))) ||
        (packet_index==5 && ((wd!=32'h00010000 && wd!=32'h00010001) || (packet_retry && wd[0]!=dn_enable))) ||
        (packet_index==6 && wd!=header[3]))begin fail(32'h109);s_axi_bresp<=2;end
     else begin
      header[packet_index]<=wd;packet_index<=packet_index+1'b1;
      if(packet_index==3)packet_retry<=have_result && wd==completed_frame;
      crc_word<=wd;crc_bit<=0;crc_busy<=1;s_axi_bvalid<=0;
     end
    end else if(packet_index==7)begin
     header[7]<=wd;packet_index<=8;packet_timer<=0;
    end else if(packet_index<8+payload_words)begin
     packet_timer<=0;
     if(unpack_count>=10 || (remaining_payload_bits<32 && (wd>>remaining_payload_bits)!=0))begin
      fail(32'h112);s_axi_bresp<=2;
     end
     else begin
      unpack_buffer<=unpack_buffer|({10'd0,wd}<<unpack_count);unpack_count<=unpack_count+32;
      packet_index<=packet_index+1'b1;crc_word<=wd;crc_bit<=0;crc_busy<=1;s_axi_bvalid<=0;
     end
    end else if(packet_index==8+payload_words)begin
     packet_active<=0;packet_timer<=0;
     if(wd!=SEAL || packet_events!=header[4] || unpack_buffer!=0 || (crc_state^32'hFFFFFFFF)!=header[7])begin
      fail(32'h10A);s_axi_bresp<=2;
     end else if(have_result && header[3]==completed_frame)begin
      if(header[7]!=last_crc || header[6]!=request_id || header[2]!=request_generation)begin
       fail(32'h10B);s_axi_bresp<=2;
      end else replay_count<=replay_count+1'b1;
     end else if(header[3]!=next_frame || (have_result && !(&consumed)))begin
      fail(32'h10C);s_axi_bresp<=2;
     end else begin
      // All header/events/CRC/seal validated before any core event/commit.
      // Consumed 57-word view is the controlled protocol ACK of prior result.
      have_result<=0;consumed<=0;accepted_count<=0;event_count<=packet_events;drain_index<=0;
      request_id<=header[6];request_generation<=header[2];last_crc<=header[7];dn_enable<=header[5][0];
      fsm<=packet_events==0?ARM:PREFETCH;
     end
    end else begin fail(32'h104);s_axi_bresp<=2;end
   end
   if(s_axi_arvalid && s_axi_arready)begin
    s_axi_rvalid<=1;s_axi_rresp<=0;s_axi_rdata<=0;response_consumes<=0;
    if(s_axi_araddr>=13'h100 && s_axi_araddr<=13'h944 && s_axi_araddr[1:0]==0)begin
     if(!valid)begin s_axi_rresp<=2;fail(32'h101);end
     else begin
      if(s_axi_araddr>=13'h85C)begin response_consumes<=1;response_index<=(s_axi_araddr-13'h85C)>>2;end
      if(s_axi_araddr<=13'h8D8)begin
       probe_dn<=s_axi_araddr>=13'h85C;
       probe_index<=s_axi_araddr>=13'h85C ? ((s_axi_araddr-13'h85C)>>2):((s_axi_araddr-13'h100)>>2);
       linear_pending<=1;s_axi_rvalid<=0;
      end else case(s_axi_araddr)
       13'h8DC:s_axi_rdata<=completed_frame;
       13'h8E0:s_axi_rdata<=acc_sat;
       13'h8E4:s_axi_rdata<=state_sat;
       13'h8E8:s_axi_rdata<=overflow;
       13'h8EC:s_axi_rdata<=drop;
       13'h8F0:s_axi_rdata<=core_cycles;
       13'h8F4:s_axi_rdata<=status;
       13'h8F8:s_axi_rdata<=generation;
       13'h8FC:s_axi_rdata<=1;
       13'h900:s_axi_rdata<=VERSION;
       13'h904:s_axi_rdata<=error_status;
       13'h908:s_axi_rdata<=accepted_count;
       13'h90C:s_axi_rdata<=request_id;
       13'h910:s_axi_rdata<=last_crc;
       13'h914:s_axi_rdata<=request_generation;
       13'h918:s_axi_rdata<=9+((event_count*14'd10+14'd31)>>5);
       13'h91C:s_axi_rdata<=commit_count;
       13'h920:s_axi_rdata<=replay_count;
       13'h924:s_axi_rdata<=reject_count;
       13'h928:s_axi_rdata<=timeout_count;
       13'h92C:s_axi_rdata<=fsm;
       13'h930:s_axi_rdata<=942;
       13'h934:s_axi_rdata<=32'h00020002;
       13'h938:s_axi_rdata<=530;
       13'h93C:s_axi_rdata<=32'hF107A11D;
       13'h940:s_axi_rdata<=last_decode_cycles;
       13'h944:s_axi_rdata<=last_protocol_cycles;
       default:begin s_axi_rresp<=2;fail(32'h107);end
      endcase
     end
    end else case(s_axi_araddr)
     13'h000:s_axi_rdata<=32'hF1071C01;
     13'h008:s_axi_rdata<=status;
     13'h00C:s_axi_rdata<=next_frame;
     13'h01C:s_axi_rdata<=accepted_count;
     13'h020:s_axi_rdata<=completed_frame;
     13'h048:s_axi_rdata<=error_status;
     13'h054:s_axi_rdata<=VERSION;
     13'h058:s_axi_rdata<=generation;
     13'h05C:s_axi_rdata<=valid;
     13'h060:s_axi_rdata<=530;
     13'h064:s_axi_rdata<=packet_events;
     default:begin s_axi_rresp<=2;fail(32'h107);end
    endcase
   end
  end
 end
endmodule
