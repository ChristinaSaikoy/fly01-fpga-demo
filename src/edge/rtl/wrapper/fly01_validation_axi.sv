`timescale 1ns/1ps
module fly01_validation_axi(
 input logic aclk, input logic aresetn,
 input logic [11:0] s_axi_awaddr, input logic [2:0] s_axi_awprot,
 input logic s_axi_awvalid, output logic s_axi_awready,
 input logic [31:0] s_axi_wdata, input logic [3:0] s_axi_wstrb,
 input logic s_axi_wvalid, output logic s_axi_wready,
 output logic [1:0] s_axi_bresp, output logic s_axi_bvalid, input logic s_axi_bready,
 input logic [11:0] s_axi_araddr, input logic [2:0] s_axi_arprot,
 input logic s_axi_arvalid, output logic s_axi_arready,
 output logic [31:0] s_axi_rdata, output logic [1:0] s_axi_rresp,
 output logic s_axi_rvalid, input logic s_axi_rready,
 output logic [3:0] debug_fsm, output logic debug_error
);
 localparam logic [31:0] PROTOCOL_ID = 32'hF1011C01;
 localparam logic [11:0] A_PROTOCOL=12'h000, A_CONTROL=12'h004, A_STATUS=12'h008;
 localparam logic [11:0] A_TIMESTEP=12'h00C, A_EVENT_COUNT=12'h010, A_EVENT_DATA=12'h014;
 localparam logic [11:0] A_EVENT_COMMIT=12'h018, A_ACCEPTED=12'h01C, A_COMPLETED=12'h020;
 localparam logic [11:0] A_STATE_INDEX=12'h024, A_STATE_DATA=12'h028, A_DN_INDEX=12'h02C;
 localparam logic [11:0] A_DN_DATA=12'h030, A_ACC_SAT=12'h034, A_STATE_SAT=12'h038;
 localparam logic [11:0] A_OVERFLOW=12'h03C, A_DROP=12'h040, A_CYCLES=12'h044;
 localparam logic [11:0] A_ERROR=12'h048, A_STEP_CONFIG=12'h04C, A_SOFT_RESET=12'h050;
 typedef enum logic [3:0] {ST_IDLE=4'd0,ST_RESET=4'd1,ST_LOAD=4'd2,ST_ARM=4'd3,
   ST_RUN=4'd4,ST_DONE=4'd5,ST_READBACK=4'd6,ST_ERROR=4'd15} vstate_t;
 vstate_t fsm;
 logic core_rst_n, evt_valid, evt_ready, step_commit, core_busy, core_done;
 logic evt_kind_noise; logic [8:0] evt_neuron;
 logic [8:0] state_probe_addr; logic signed [17:0] state_probe_data;
 logic [4:0] dn_counter_sel; logic [31:0] dn_counter_data;
 logic [31:0] timestep_cycles, acc_sat, state_sat, overflow, drop;
 logic dn_count_enable;

 fly01_formal_top u_frozen_formal_top(
  .sys_clk(aclk),.sys_rst_n(core_rst_n),
  .evt_valid(evt_valid),.evt_kind_noise(evt_kind_noise),.evt_neuron(evt_neuron),.evt_ready(evt_ready),
  .step_commit(step_commit),.dn_count_enable(dn_count_enable),
  .step_busy(core_busy),.step_done(core_done),
  .state_probe_addr(state_probe_addr),.state_probe_data(state_probe_data),
  .dn_counter_sel(dn_counter_sel),.dn_counter_data(dn_counter_data),
  .timestep_cycles(timestep_cycles),.acc_saturation_count(acc_sat),
  .state_saturation_count(state_sat),.overflow_count(overflow),.drop_count(drop)
 );
 logic aw_hold,w_hold,event_pending,done_latched,error_latched,deadline_violation;
 logic [11:0] awaddr_hold; logic [31:0] wdata_hold; logic [3:0] wstrb_hold;
 logic [9:0] event_pending_word;
 logic [31:0] timestep_id,next_timestep_id,completed_timestep_id,error_status;
 logic [9:0] expected_event_count,accepted_event_count;
 logic [8:0] state_index,last_stim,last_noise;
 logic [4:0] dn_index;
 logic have_stim,have_noise,seen_noise,step_config_dn;
 logic [9:0] reset_count;

 assign evt_valid=event_pending;
 assign evt_kind_noise=event_pending_word[9];
 assign evt_neuron=event_pending_word[8:0];
 assign state_probe_addr=state_index;
 assign dn_counter_sel=dn_index;
 assign dn_count_enable=step_config_dn;
 assign debug_fsm=fsm;
 assign debug_error=error_latched;
 assign s_axi_awready=aresetn && !aw_hold && !s_axi_bvalid && !event_pending;
 assign s_axi_wready =aresetn && !w_hold  && !s_axi_bvalid && !event_pending;
 assign s_axi_arready=aresetn && !s_axi_rvalid;
 task automatic set_error(input logic [31:0] code);
  begin
   if (!error_latched) error_status <= code;
   error_latched <= 1'b1;
   fsm <= ST_ERROR;
  end
 endtask

 function automatic logic canonical_ok(input logic [9:0] ev);
  logic [8:0] idx; logic kind;
  begin
   idx=ev[8:0]; kind=ev[9];
   if (idx>9'd470) canonical_ok=1'b0;
   else if (!kind) begin
    if (seen_noise) canonical_ok=1'b0;
    else if (have_stim && idx<=last_stim) canonical_ok=1'b0;
    else canonical_ok=1'b1;
   end else begin
    if (have_noise && idx<=last_noise) canonical_ok=1'b0;
    else canonical_ok=1'b1;
   end
  end
 endfunction
 always_ff @(posedge aclk) begin
  if (!aresetn) begin
   fsm<=ST_IDLE; core_rst_n<=1'b0; reset_count<='0; step_commit<=1'b0;
   aw_hold<=1'b0; w_hold<=1'b0; event_pending<=1'b0;
   s_axi_bvalid<=1'b0; s_axi_bresp<=2'b00; s_axi_rvalid<=1'b0;
   s_axi_rdata<='0; s_axi_rresp<=2'b00;
   timestep_id<=0; next_timestep_id<=0; completed_timestep_id<=32'hFFFFFFFF;
   expected_event_count<=0; accepted_event_count<=0; state_index<=0; dn_index<=0;
   error_status<=0; error_latched<=0; done_latched<=0; deadline_violation<=0;
   have_stim<=0;have_noise<=0;seen_noise<=0;last_stim<=0;last_noise<=0;step_config_dn<=0;
   awaddr_hold<=0;wdata_hold<=0;wstrb_hold<=0;event_pending_word<=0;
  end else begin
   step_commit<=1'b0;
   if (s_axi_bvalid && s_axi_bready) s_axi_bvalid<=1'b0;
   if (s_axi_rvalid && s_axi_rready) s_axi_rvalid<=1'b0;
   if (s_axi_awvalid && s_axi_awready) begin aw_hold<=1'b1; awaddr_hold<=s_axi_awaddr; end
   if (s_axi_wvalid && s_axi_wready) begin w_hold<=1'b1; wdata_hold<=s_axi_wdata; wstrb_hold<=s_axi_wstrb; end
   case (fsm)
    ST_RESET: begin
     if (reset_count < 10'd4) begin core_rst_n<=1'b0; reset_count<=reset_count+1'b1; end
     else if (reset_count < 10'd516) begin core_rst_n<=1'b1; reset_count<=reset_count+1'b1; end
     else begin core_rst_n<=1'b1; reset_count<=0; fsm<=ST_LOAD; end
    end
    ST_ARM: begin step_commit<=1'b1; fsm<=ST_RUN; end
    ST_RUN: if (core_done) begin
     completed_timestep_id<=timestep_id; done_latched<=1'b1;
     if (timestep_cycles>32'd500000) deadline_violation<=1'b1;
     fsm<=ST_DONE;
    end
    ST_DONE: fsm<=ST_READBACK;
    default: begin end
   endcase

   if (event_pending && evt_ready && !s_axi_bvalid) begin
    event_pending<=1'b0; accepted_event_count<=accepted_event_count+1'b1;
    if (event_pending_word[9]) begin seen_noise<=1'b1;have_noise<=1'b1;last_noise<=event_pending_word[8:0]; end
    else begin have_stim<=1'b1;last_stim<=event_pending_word[8:0]; end
    s_axi_bvalid<=1'b1; s_axi_bresp<=2'b00;
   end
   if (aw_hold && w_hold && !s_axi_bvalid && !event_pending) begin
    aw_hold<=1'b0; w_hold<=1'b0; s_axi_bresp<=2'b00;
    if (wstrb_hold!=4'hF) begin set_error(32'h00000007); s_axi_bvalid<=1'b1; s_axi_bresp<=2'b10; end
    else case (awaddr_hold)
     A_CONTROL: begin
      s_axi_bvalid<=1'b1;
      if (wdata_hold[0] && wdata_hold[31:2]==0) begin
       fsm<=ST_RESET; core_rst_n<=1'b0; reset_count<=0;
       timestep_id<=0;next_timestep_id<=0;completed_timestep_id<=32'hFFFFFFFF;
       expected_event_count<=0;accepted_event_count<=0;state_index<=0;dn_index<=0;
       error_status<=0;error_latched<=0;done_latched<=0;deadline_violation<=0;
       have_stim<=0;have_noise<=0;seen_noise<=0;last_stim<=0;last_noise<=0;step_config_dn<=0;
      end else if (wdata_hold[1] && fsm==ST_READBACK) begin
       next_timestep_id<=completed_timestep_id+1'b1; timestep_id<=completed_timestep_id+1'b1;
       expected_event_count<=0;accepted_event_count<=0;done_latched<=0;deadline_violation<=0;
       have_stim<=0;have_noise<=0;seen_noise<=0;last_stim<=0;last_noise<=0;step_config_dn<=0;
       fsm<=ST_LOAD;
      end else begin set_error(32'h00000001); s_axi_bresp<=2'b10; end
     end
     A_TIMESTEP: begin
      s_axi_bvalid<=1'b1;
      if (fsm==ST_LOAD && accepted_event_count==0) timestep_id<=wdata_hold;
      else begin set_error(32'h00000001); s_axi_bresp<=2'b10; end
     end
     A_EVENT_COUNT: begin
      s_axi_bvalid<=1'b1;
      if (fsm==ST_LOAD && accepted_event_count==0 && wdata_hold<=32'd942) expected_event_count<=wdata_hold[9:0];
      else begin set_error(32'h00000004); s_axi_bresp<=2'b10; end
     end
     A_EVENT_DATA: begin
      if (fsm!=ST_LOAD || accepted_event_count>=expected_event_count) begin set_error(32'h00000004); s_axi_bvalid<=1'b1;s_axi_bresp<=2'b10; end
      else if (wdata_hold[31:10]!=0 || wdata_hold[8:0]>9'd470) begin set_error(32'h00000002);s_axi_bvalid<=1'b1;s_axi_bresp<=2'b10;end
      else if (!canonical_ok(wdata_hold[9:0])) begin set_error(32'h00000003);s_axi_bvalid<=1'b1;s_axi_bresp<=2'b10;end
      else begin event_pending_word<=wdata_hold[9:0];event_pending<=1'b1;end
     end
     A_EVENT_COMMIT: begin
      s_axi_bvalid<=1'b1;
      if (fsm!=ST_LOAD || wdata_hold!=32'd1) begin set_error(32'h00000001);s_axi_bresp<=2'b10;end
      else if (accepted_event_count!=expected_event_count) begin set_error(32'h00000004);s_axi_bresp<=2'b10;end
      else if (timestep_id!=next_timestep_id) begin set_error(32'h00000005);s_axi_bresp<=2'b10;end
      else if (core_busy) begin set_error(32'h00000006);s_axi_bresp<=2'b10;end
      else fsm<=ST_ARM;
     end
     A_STATE_INDEX: begin
      s_axi_bvalid<=1'b1;
      if (fsm==ST_READBACK && wdata_hold<=32'd470) state_index<=wdata_hold[8:0];
      else begin set_error(32'h00000001);s_axi_bresp<=2'b10;end
     end
     A_DN_INDEX: begin
      s_axi_bvalid<=1'b1;
      if (fsm==ST_READBACK && wdata_hold<=32'd31) dn_index<=wdata_hold[4:0];
      else begin set_error(32'h00000001);s_axi_bresp<=2'b10;end
     end
     A_STEP_CONFIG: begin
      s_axi_bvalid<=1'b1;
      if (fsm==ST_LOAD && accepted_event_count==0 && wdata_hold[31:1]==0) step_config_dn<=wdata_hold[0];
      else begin set_error(32'h00000001);s_axi_bresp<=2'b10;end
     end
     A_SOFT_RESET: begin
      s_axi_bvalid<=1'b1;
      if (wdata_hold==32'd1) begin
       fsm<=ST_RESET; core_rst_n<=1'b0; reset_count<=0;
       timestep_id<=0;next_timestep_id<=0;completed_timestep_id<=32'hFFFFFFFF;
       expected_event_count<=0;accepted_event_count<=0;state_index<=0;dn_index<=0;
       error_status<=0;error_latched<=0;done_latched<=0;deadline_violation<=0;
       have_stim<=0;have_noise<=0;seen_noise<=0;last_stim<=0;last_noise<=0;step_config_dn<=0;
      end else begin set_error(32'h00000001);s_axi_bresp<=2'b10;end
     end
     default: begin set_error(32'h00000007);s_axi_bvalid<=1'b1;s_axi_bresp<=2'b10;end
    endcase
   end
   if (s_axi_arvalid && s_axi_arready) begin
    s_axi_rvalid<=1'b1; s_axi_rresp<=2'b00; s_axi_rdata<=32'd0;
    case (s_axi_araddr)
     A_PROTOCOL: s_axi_rdata<=PROTOCOL_ID;
     A_STATUS: begin
      s_axi_rdata[3:0]<=fsm; s_axi_rdata[4]<=evt_ready; s_axi_rdata[5]<=core_busy;
      s_axi_rdata[6]<=done_latched; s_axi_rdata[7]<=error_latched; s_axi_rdata[8]<=deadline_violation;
     end
     A_TIMESTEP: s_axi_rdata<=timestep_id;
     A_EVENT_COUNT: s_axi_rdata<=expected_event_count;
     A_ACCEPTED: s_axi_rdata<=accepted_event_count;
     A_COMPLETED: s_axi_rdata<=completed_timestep_id;
     A_ERROR: s_axi_rdata<=error_status;
     A_STEP_CONFIG: s_axi_rdata<=step_config_dn;
     A_STATE_INDEX: s_axi_rdata<=state_index;
     A_DN_INDEX: s_axi_rdata<=dn_index;
     A_STATE_DATA: if (fsm==ST_READBACK) s_axi_rdata<={{14{state_probe_data[17]}},state_probe_data}; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     A_DN_DATA: if (fsm==ST_READBACK) s_axi_rdata<=dn_counter_data; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     A_ACC_SAT: if (fsm==ST_READBACK) s_axi_rdata<=acc_sat; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     A_STATE_SAT: if (fsm==ST_READBACK) s_axi_rdata<=state_sat; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     A_OVERFLOW: if (fsm==ST_READBACK) s_axi_rdata<=overflow; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     A_DROP: if (fsm==ST_READBACK) s_axi_rdata<=drop; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     A_CYCLES: if (fsm==ST_READBACK) s_axi_rdata<=timestep_cycles; else begin set_error(32'h00000001);s_axi_rresp<=2'b10;end
     default: begin set_error(32'h00000007);s_axi_rresp<=2'b10;s_axi_rdata<=0;end
    endcase
   end
  end
 end
endmodule
