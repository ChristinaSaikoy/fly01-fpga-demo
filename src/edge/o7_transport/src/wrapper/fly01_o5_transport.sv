`timescale 1ns/1ps
// One outstanding AXI4 request, ordered beat-to-Lite endpoint adapter.
// No clock-domain crossing, neural model copy, or reference outputs.
module fly01_o5_transport # (parameter ID_W=1)(
 input logic aclk, aresetn,
 input logic [ID_W-1:0] s_axi_awid, input logic [31:0] s_axi_awaddr,
 input logic [7:0] s_axi_awlen, input logic [2:0] s_axi_awsize,
 input logic [1:0] s_axi_awburst, input logic s_axi_awvalid,
 output logic s_axi_awready,
 input logic [31:0] s_axi_wdata, input logic [3:0] s_axi_wstrb,
 input logic s_axi_wlast, s_axi_wvalid, output logic s_axi_wready,
 output logic [ID_W-1:0] s_axi_bid, output logic [1:0] s_axi_bresp,
 output logic s_axi_bvalid, input logic s_axi_bready,
 input logic [ID_W-1:0] s_axi_arid, input logic [31:0] s_axi_araddr,
 input logic [7:0] s_axi_arlen, input logic [2:0] s_axi_arsize,
 input logic [1:0] s_axi_arburst, input logic s_axi_arvalid,
 output logic s_axi_arready,
 output logic [ID_W-1:0] s_axi_rid, output logic [31:0] s_axi_rdata,
 output logic [1:0] s_axi_rresp, output logic s_axi_rlast,s_axi_rvalid,
 input logic s_axi_rready, output logic [3:0] debug_fsm, output logic debug_error
);
 typedef enum logic [3:0] {IDLE,R_ADDR,R_WAIT,R_SEND,W_DATA,W_SEND,W_WAIT,W_RESP} phase_t;
 phase_t phase;
 logic [31:0] address;
 logic [7:0] remaining;
 logic invalid, write_failed, aw_sent, w_sent;
 logic [ID_W-1:0] transaction_id;
 logic [31:0] beat_data;
 logic [3:0] beat_strb;
 logic [12:0] la;
 logic lav,lar,lwv,lwr,lbv,lbr,lrv,lrr,endpoint_arready;
 logic [31:0] lrd;
 logic [1:0] lbresp,lrresp;
 logic [32:0] read_end,write_end;
 assign read_end={1'b0,s_axi_araddr}+({25'd0,s_axi_arlen}<<2);
 assign write_end={1'b0,s_axi_awaddr}+({25'd0,s_axi_awlen}<<2);
 assign s_axi_arready=aresetn && phase==IDLE;
 assign s_axi_awready=aresetn && phase==IDLE && !s_axi_arvalid;
 assign s_axi_wready=aresetn && phase==W_DATA;
 assign s_axi_bvalid=phase==W_RESP;
 assign s_axi_bid=transaction_id;
 assign s_axi_bresp=write_failed ? 2'b10 : 2'b00;
 assign s_axi_rvalid=phase==R_SEND;
 assign s_axi_rid=transaction_id;
 assign s_axi_rlast=remaining==0;
 assign la=invalid ? 13'hFFC : address[12:0];
 assign lav=phase==W_SEND && !aw_sent;
 assign lwv=phase==W_SEND && !w_sent;
 assign lbr=phase==W_WAIT;
 assign lrr=phase==R_WAIT;
 fly01_validation_axi u_endpoint(
  .aclk(aclk),.aresetn(aresetn),
  .s_axi_awaddr(la),.s_axi_awprot(3'd0),.s_axi_awvalid(lav),.s_axi_awready(lar),
  .s_axi_wdata(beat_data),.s_axi_wstrb(beat_strb),.s_axi_wvalid(lwv),.s_axi_wready(lwr),
  .s_axi_bresp(lbresp),.s_axi_bvalid(lbv),.s_axi_bready(lbr),
  .s_axi_araddr(la),.s_axi_arprot(3'd0),.s_axi_arvalid(phase==R_ADDR),.s_axi_arready(endpoint_arready),
  .s_axi_rdata(lrd),.s_axi_rresp(lrresp),.s_axi_rvalid(lrv),.s_axi_rready(lrr),
  .debug_fsm(debug_fsm),.debug_error(debug_error)
 );
 always_ff @(posedge aclk) begin
  if (!aresetn) begin
   phase<=IDLE;address<=0;remaining<=0;invalid<=0;write_failed<=0;
   aw_sent<=0;w_sent<=0;transaction_id<=0;beat_data<=0;beat_strb<=0;
   s_axi_rdata<=0;s_axi_rresp<=0;
  end else case (phase)
   IDLE: begin
    if (s_axi_arvalid && s_axi_arready) begin
     address<=s_axi_araddr;remaining<=s_axi_arlen;transaction_id<=s_axi_arid;
     invalid<=s_axi_arsize!=2 || s_axi_arburst!=1 || s_axi_araddr[1:0]!=0 ||
      read_end[32] || s_axi_araddr[31:12]!=read_end[31:12] ||
      (s_axi_arlen!=0 && !(s_axi_araddr>=32'h100 && read_end<=32'h8FC)) || s_axi_araddr>32'h1FFF;
     phase<=R_ADDR;
    end else if (s_axi_awvalid && s_axi_awready) begin
     address<=s_axi_awaddr;remaining<=s_axi_awlen;transaction_id<=s_axi_awid;
     invalid<=s_axi_awsize!=2 || s_axi_awburst!=1 || s_axi_awaddr[1:0]!=0 ||
      write_end[32] || s_axi_awaddr[31:12]!=write_end[31:12] ||
      (s_axi_awlen!=0 && !(s_axi_awaddr>=32'h1000 && write_end<=32'h1EB4)) || s_axi_awaddr>32'h1FFF;
     write_failed<=0;phase<=W_DATA;
    end
   end
   R_ADDR: if (endpoint_arready) phase<=R_WAIT;
   R_WAIT: if (lrv) begin s_axi_rdata<=lrd;s_axi_rresp<=lrresp;phase<=R_SEND;end
   R_SEND: if (s_axi_rready) begin
    if (remaining==0) phase<=IDLE;
    else begin address<=address+4;remaining<=remaining-1'b1;phase<=R_ADDR;end
   end
   W_DATA: if (s_axi_wvalid) begin
    beat_data<=s_axi_wdata;beat_strb<=s_axi_wstrb;aw_sent<=0;w_sent<=0;
    if (s_axi_wlast!=(remaining==0)) begin invalid<=1;write_failed<=1;end
    phase<=W_SEND;
   end
   W_SEND: begin
    if (lav && lar) aw_sent<=1;
    if (lwv && lwr) w_sent<=1;
    if ((aw_sent || lar) && (w_sent || lwr)) phase<=W_WAIT;
   end
   W_WAIT: if (lbv) begin
    if (lbresp!=0) begin write_failed<=1;invalid<=1;end
    if (remaining==0) phase<=W_RESP;
    else begin address<=address+4;remaining<=remaining-1'b1;phase<=W_DATA;end
   end
   W_RESP: if (s_axi_bready) phase<=IDLE;
   default: phase<=IDLE;
  endcase
 end
endmodule
