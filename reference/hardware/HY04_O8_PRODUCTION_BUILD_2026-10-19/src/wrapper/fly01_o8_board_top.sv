`timescale 1ns/1ps
module fly01_o8_board_top # (parameter integer UART_CLKS_PER_BIT=25)(
 input logic sys_clk,sys_rst_n,uart_rxd,output logic uart_txd,output logic [3:0] led
);
 (* ASYNC_REG="TRUE" *) logic [1:0] reset_sync;
 always_ff @(posedge sys_clk or negedge sys_rst_n)
   if(!sys_rst_n)reset_sync<=0;else reset_sync<={reset_sync[0],1'b1};
 wire reset_n=reset_sync[1];
 wire [7:0] rx_byte,tx_byte;
 wire rx_valid,rx_error,rx_break,tx_valid,tx_ready;
 wire [31:0] generation,next_frame,session,errors;
 wire pending,core_error;
 wire [3:0] fsm;
 fly01_uart_rx #(.CLKS_PER_BIT(UART_CLKS_PER_BIT)) u_rx(
   .clk(sys_clk),.reset_n(reset_n),.rx(uart_rxd),.data(rx_byte),.valid(rx_valid),
   .framing_error(rx_error),.break_detect(rx_break));
 fly01_uart_tx #(.CLKS_PER_BIT(UART_CLKS_PER_BIT)) u_tx(
   .clk(sys_clk),.reset_n(reset_n),.data(tx_byte),.valid(tx_valid),.ready(tx_ready),.tx(uart_txd));
 fly01_o8_byte_endpoint #(.UART_BAUD(50000000/UART_CLKS_PER_BIT)) u_uart_endpoint(
   .clk(sys_clk),.reset_n(reset_n),.rx_byte(rx_byte),.rx_valid(rx_valid),.rx_error(rx_error),.rx_break(rx_break),
   .tx_byte(tx_byte),.tx_valid(tx_valid),.tx_ready(tx_ready),.debug_generation(generation),
   .debug_next_frame(next_frame),.debug_session(session),.debug_errors(errors),.debug_pending(pending),
   .debug_fsm(fsm),.debug_error(core_error));
 wire awid,arid,bid,rid;
 wire [31:0] awaddr,wdata,araddr,rdata;
 wire [7:0] awlen,arlen;
 wire [2:0] awsize,arsize;
 wire [1:0] awburst,arburst,bresp,rresp;
 wire [3:0] wstrb;
 wire awvalid,awready,wvalid,wready,wlast,bvalid,bready,arvalid,arready,rvalid,rready,rlast;
 jtag_axi_o5 u_jtag_axi(
   .aclk(sys_clk),.aresetn(reset_n),
   .m_axi_awid(awid),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),
   .m_axi_awvalid(awvalid),.m_axi_awready(awready),
   .m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
   .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready),
   .m_axi_arid(arid),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
   .m_axi_arvalid(arvalid),.m_axi_arready(arready),
   .m_axi_rid(rid),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));
 fly01_o8_debug_axi #(.UART_BAUD(50000000/UART_CLKS_PER_BIT)) u_debug_readonly(
   .aclk(sys_clk),.aresetn(reset_n),
   .s_axi_awid(awid),.s_axi_awaddr(awaddr),.s_axi_awlen(awlen),.s_axi_awsize(awsize),.s_axi_awburst(awburst),
   .s_axi_awvalid(awvalid),.s_axi_awready(awready),
   .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wlast(wlast),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
   .s_axi_bid(bid),.s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
   .s_axi_arid(arid),.s_axi_araddr(araddr),.s_axi_arlen(arlen),.s_axi_arsize(arsize),.s_axi_arburst(arburst),
   .s_axi_arvalid(arvalid),.s_axi_arready(arready),
   .s_axi_rid(rid),.s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rlast(rlast),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
   .generation(generation),.next_frame(next_frame),.session(session),.errors(errors),.pending(pending),.core_fsm(fsm),.core_error(core_error));
 assign led={core_error,pending,fsm[1:0]};
endmodule
