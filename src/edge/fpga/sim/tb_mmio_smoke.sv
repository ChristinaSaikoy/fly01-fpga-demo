`timescale 1ns/1ps
module tb_mmio_smoke;
 logic clk=0; always #5 clk=~clk;
 logic rstn;
 logic [11:0] awaddr; logic [2:0] awprot=0; logic awvalid; logic awready;
 logic [31:0] wdata; logic [3:0] wstrb; logic wvalid; logic wready;
 logic [1:0] bresp; logic bvalid; logic bready;
 logic [11:0] araddr; logic [2:0] arprot=0; logic arvalid; logic arready;
 logic [31:0] rdata; logic [1:0] rresp; logic rvalid; logic rready;
 logic [3:0] debug_fsm; logic debug_error;

 fly01_validation_axi dut(.aclk(clk),.aresetn(rstn),
  .s_axi_awaddr(awaddr),.s_axi_awprot(awprot),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
  .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
  .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
  .s_axi_araddr(araddr),.s_axi_arprot(arprot),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
  .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
  .debug_fsm(debug_fsm),.debug_error(debug_error));
 task automatic axi_write(input [11:0] a,input [31:0] d);
  begin
   @(negedge clk); awaddr=a;awvalid=1;wdata=d;wstrb=4'hF;wvalid=1;bready=1;
   do @(posedge clk); while(!(awready&&wready));
   @(negedge clk); awvalid=0;wvalid=0;
   while(!bvalid) @(negedge clk);
   if(bresp!==2'b00) $fatal(1,"MMIO_WRITE_SLVERR addr=%h resp=%b",a,bresp);
   @(posedge clk); @(negedge clk); bready=0;
  end
 endtask
 task automatic axi_read(input [11:0] a,output [31:0] d);
  begin
   @(negedge clk);araddr=a;arvalid=1;rready=1;
   do @(posedge clk); while(!arready);
   @(negedge clk);arvalid=0;
   while(!rvalid) @(negedge clk);
   d=rdata;
   if(rresp!==2'b00) $fatal(1,"MMIO_READ_SLVERR addr=%h resp=%b",a,rresp);
   @(posedge clk);@(negedge clk);rready=0;
  end
 endtask
 integer polls; logic [31:0] rd;
 initial begin
  awaddr=0;awvalid=0;wdata=0;wstrb=0;wvalid=0;bready=0;
  araddr=0;arvalid=0;rready=0;rstn=0;
  repeat(10) @(posedge clk); @(negedge clk);rstn=1;
  axi_read(12'h000,rd); if(rd!==32'hF1011C01) $fatal(1,"PROTOCOL_ID_FAIL %h",rd);
  axi_write(12'h004,32'h1);
  polls=0; rd=0;
  while(rd[3:0]!=4'd2) begin axi_read(12'h008,rd); polls=polls+1; if(polls>1000)$fatal(1,"RESET_TO_LOAD_TIMEOUT"); end
  if(debug_error)$fatal(1,"UNEXPECTED_ERROR_AFTER_RESET");
  axi_write(12'h00C,0);
  axi_write(12'h010,0);
  axi_write(12'h04C,0);
  axi_write(12'h018,1);
  polls=0; rd=0;
  while(rd[3:0]!=4'd6) begin axi_read(12'h008,rd);polls=polls+1;if(polls>20000)$fatal(1,"RUN_TO_READBACK_TIMEOUT status=%h",rd);end
  axi_read(12'h01C,rd);if(rd!==0)$fatal(1,"ACCEPTED_COUNT_FAIL %0d",rd);
  axi_read(12'h020,rd);if(rd!==0)$fatal(1,"COMPLETED_ID_FAIL %0d",rd);
  axi_write(12'h024,0);axi_read(12'h028,rd);
  if($signed(rd)!==32'sd1147)$fatal(1,"STATE0_FAIL got=%0d",$signed(rd));
  axi_write(12'h02C,0);axi_read(12'h030,rd);if(rd!==0)$fatal(1,"DN0_FAIL %0d",rd);
  axi_read(12'h034,rd);if(rd!==0)$fatal(1,"ACC_SAT_FAIL %0d",rd);
  axi_read(12'h038,rd);if(rd!==0)$fatal(1,"STATE_SAT_FAIL %0d",rd);
  axi_read(12'h03C,rd);if(rd!==0)$fatal(1,"OVERFLOW_FAIL %0d",rd);
  axi_read(12'h040,rd);if(rd!==0)$fatal(1,"DROP_FAIL %0d",rd);
  axi_read(12'h044,rd);if(rd>500000)$fatal(1,"CYCLE_GATE_FAIL %0d",rd);
  axi_write(12'h004,32'h2);
  axi_read(12'h008,rd);if(rd[3:0]!==4'd2)$fatal(1,"ACK_TO_LOAD_FAIL %h",rd);
  if(debug_error)$fatal(1,"FINAL_ERROR");
  $display("S5_FPGA1C_MMIO_SMOKE_PASS cycles=%0d",rd);
  $finish;
 end
endmodule
