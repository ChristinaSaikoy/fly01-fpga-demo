`timescale 1ns/1ps
module fly01_o7_board_top(input logic sys_clk,sys_rst_n,output logic [3:0] led);
 (* ASYNC_REG="TRUE" *) logic [1:0] reset_sync;
 always_ff @(posedge sys_clk or negedge sys_rst_n)
  if(!sys_rst_n)reset_sync<=0;else reset_sync<={reset_sync[0],1'b1};
 wire reset_n=reset_sync[1];
 wire awid,arid,bid,rid;
 wire [31:0] awaddr,wdata,araddr,rdata;
 wire [7:0] awlen,arlen;
 wire [2:0] awsize,arsize;
 wire [1:0] awburst,arburst,bresp,rresp;
 wire [3:0] wstrb,fsm;
 wire awvalid,awready,wvalid,wready,wlast,bvalid,bready,arvalid,arready,rvalid,rready,rlast,error;
 jtag_axi_o5 u_jtag_axi(
  .aclk(sys_clk),.aresetn(reset_n),
  .m_axi_awid(awid),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),
  .m_axi_awvalid(awvalid),.m_axi_awready(awready),
  .m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
  .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready),
  .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
  .m_axi_arvalid(arvalid),.m_axi_arready(arready),
  .m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready)
 );
 fly01_o7_transport u_transport(
  .aclk(sys_clk),.aresetn(reset_n),
  .s_axi_awid(awid),.s_axi_awaddr(awaddr),.s_axi_awlen(awlen),.s_axi_awsize(awsize),.s_axi_awburst(awburst),
  .s_axi_awvalid(awvalid),.s_axi_awready(awready),
  .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wlast(wlast),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
  .s_axi_bid(bid),.s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
  .s_axi_arid(arid),.s_axi_araddr(araddr),.s_axi_arlen(arlen),.s_axi_arsize(arsize),.s_axi_arburst(arburst),
  .s_axi_arvalid(arvalid),.s_axi_arready(arready),
  .s_axi_rid(rid),.s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rlast(rlast),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
  .debug_fsm(fsm),.debug_error(error)
 );
 assign led={error,fsm[2:0]};
endmodule
