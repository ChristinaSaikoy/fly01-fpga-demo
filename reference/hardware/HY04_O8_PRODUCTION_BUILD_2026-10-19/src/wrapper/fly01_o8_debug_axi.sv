`timescale 1ns/1ps
// JTAG AXI is a distinct read-only diagnostic bank, never a second neural owner.
module fly01_o8_debug_axi # (parameter ID_W=1,parameter integer UART_BAUD=2000000)(
 input logic aclk,aresetn,
 input logic [ID_W-1:0] s_axi_awid,input logic [31:0] s_axi_awaddr,
 input logic [7:0] s_axi_awlen,input logic [2:0] s_axi_awsize,input logic [1:0] s_axi_awburst,
 input logic s_axi_awvalid,output logic s_axi_awready,
 input logic [31:0] s_axi_wdata,input logic [3:0] s_axi_wstrb,input logic s_axi_wlast,s_axi_wvalid,
 output logic s_axi_wready,output logic [ID_W-1:0] s_axi_bid,
 output logic [1:0] s_axi_bresp,output logic s_axi_bvalid,input logic s_axi_bready,
 input logic [ID_W-1:0] s_axi_arid,input logic [31:0] s_axi_araddr,
 input logic [7:0] s_axi_arlen,input logic [2:0] s_axi_arsize,input logic [1:0] s_axi_arburst,
 input logic s_axi_arvalid,output logic s_axi_arready,
 output logic [ID_W-1:0] s_axi_rid,output logic [31:0] s_axi_rdata,
 output logic [1:0] s_axi_rresp,output logic s_axi_rlast,s_axi_rvalid,input logic s_axi_rready,
 input logic [31:0] generation,next_frame,session,errors,input logic pending,
 input logic [3:0] core_fsm,input logic core_error
);
 logic reading,writing,read_invalid;
 logic [31:0] read_address;
 logic [7:0] read_remaining,write_remaining;
 logic [31:0] saved_generation,saved_next,saved_session,saved_errors;
 logic saved_pending,saved_error;
 logic [3:0] saved_fsm;
 assign s_axi_awready=aresetn && !writing && !s_axi_bvalid;
 assign s_axi_wready=aresetn && writing;
 assign s_axi_bresp=2'b10;
 assign s_axi_arready=aresetn && !reading && !s_axi_rvalid;
 assign s_axi_rlast=read_remaining==0;
 always_ff @(posedge aclk)begin
   if(!aresetn)begin
     reading<=0;writing<=0;read_invalid<=0;read_address<=0;read_remaining<=0;write_remaining<=0;
     s_axi_bid<=0;s_axi_bvalid<=0;s_axi_rid<=0;s_axi_rdata<=0;s_axi_rresp<=0;s_axi_rvalid<=0;
     saved_generation<=0;saved_next<=0;saved_session<=0;saved_errors<=0;saved_pending<=0;saved_error<=0;saved_fsm<=0;
   end else begin
     if(s_axi_bvalid && s_axi_bready)s_axi_bvalid<=0;
     if(s_axi_awvalid && s_axi_awready)begin writing<=1;write_remaining<=s_axi_awlen;s_axi_bid<=s_axi_awid;end
     if(s_axi_wvalid && s_axi_wready)begin
       if(write_remaining==0)begin writing<=0;s_axi_bvalid<=1;end
       else write_remaining<=write_remaining-1;
     end
     if(s_axi_arvalid && s_axi_arready)begin
       reading<=1;read_address<=s_axi_araddr;read_remaining<=s_axi_arlen;s_axi_rid<=s_axi_arid;
       read_invalid<=s_axi_arsize!=2 || s_axi_arburst!=1 || s_axi_araddr[1:0]!=0 ||
                     ({1'b0,s_axi_araddr}+({25'd0,s_axi_arlen}<<2))>33'hFFFFFFFF;
       saved_generation<=generation;saved_next<=next_frame;saved_session<=session;saved_errors<=errors;
       saved_pending<=pending;saved_error<=core_error;saved_fsm<=core_fsm;
     end
     if(reading && !s_axi_rvalid)begin
       s_axi_rvalid<=1;s_axi_rresp<=read_invalid?2'b10:2'b00;s_axi_rdata<=0;
       if(!read_invalid)case(read_address)
         32'h000:s_axi_rdata<=32'hF1081C01;
         32'h008:s_axi_rdata<={24'd0,saved_pending,saved_error,2'd0,saved_fsm};
         32'h00C:s_axi_rdata<=saved_next;
         32'h054:s_axi_rdata<=32'hF1080001;
         32'h058:s_axi_rdata<=saved_generation;
         32'h060:s_axi_rdata<=530;
         32'h064:s_axi_rdata<=UART_BAUD;
         32'h068:s_axi_rdata<=1; // UART is the sole scientific state owner.
         32'h070:s_axi_rdata<=saved_session;
         32'h074:s_axi_rdata<={31'd0,saved_pending};
         32'h078:s_axi_rdata<=saved_errors;
         default:s_axi_rresp<=2'b10;
       endcase
     end
     if(s_axi_rvalid && s_axi_rready)begin
       s_axi_rvalid<=0;
       if(read_remaining==0)reading<=0;
       else begin read_remaining<=read_remaining-1;read_address<=read_address+4;end
     end
   end
 end
endmodule
