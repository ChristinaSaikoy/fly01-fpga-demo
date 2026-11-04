`timescale 1ns/1ps
module fly01_validation_top(
 input logic sys_clk,input logic sys_rst_n,output logic [3:0] led
);
 (* ASYNC_REG="TRUE" *) logic [1:0] rst_pipe;
 always_ff @(posedge sys_clk) begin
  if(!sys_rst_n) rst_pipe<=2'b00;
  else rst_pipe<={rst_pipe[0],1'b1};
 end
 logic axi_aresetn; assign axi_aresetn=rst_pipe[1];

 logic [31:0] awaddr,wdata,araddr,rdata;
 logic [2:0] awprot,arprot; logic [3:0] wstrb;
 logic awvalid,awready,wvalid,wready,bvalid,bready,arvalid,arready,rvalid,rready;
 logic [1:0] bresp,rresp; logic [3:0] debug_fsm; logic debug_error;

 jtag_axi_0 u_jtag_axi(
  .aclk(sys_clk),.aresetn(axi_aresetn),
  .m_axi_awaddr(awaddr),.m_axi_awprot(awprot),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
  .m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
  .m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready),
  .m_axi_araddr(araddr),.m_axi_arprot(arprot),.m_axi_arvalid(arvalid),.m_axi_arready(arready),
  .m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rvalid(rvalid),.m_axi_rready(rready)
 );

 fly01_validation_axi u_validation(
  .aclk(sys_clk),.aresetn(axi_aresetn),
  .s_axi_awaddr(awaddr[11:0]),.s_axi_awprot(awprot),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
  .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
  .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
  .s_axi_araddr(araddr[11:0]),.s_axi_arprot(arprot),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
  .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
  .debug_fsm(debug_fsm),.debug_error(debug_error)
 );

 always_comb begin
  led[0]=debug_fsm[0];
  led[1]=debug_fsm[1];
  led[2]=debug_error;
  led[3]=axi_aresetn;
 end
endmodule
