`timescale 1ns/1ps
module tb_i2c_recovery(output reg finished=0);
 reg clk=0,reset_n=0,start=0;
 always #10 clk=~clk; // Actual 50 MHz
 tri1 scl,sda;
 pullup(scl);pullup(sda);
 reg force_scl=0,force_sda=0;
 assign scl=force_scl?1'b0:1'bz;
 assign sda=force_sda?1'b0:1'bz;
 reg slave_ack=1,slave_low=0;
 assign sda=slave_low?1'b0:1'bz;
 reg [71:0] payload={8'h07,16'hfb50,16'h04b0,16'h0000,16'h0000};
 wire scl_drive_low,sda_drive_low;
 assign scl=scl_drive_low?1'b0:1'bz;
 assign sda=sda_drive_low?1'b0:1'bz;
 wire busy,done,success;wire [2:0] fault_code;wire [3:0] acknowledged_bytes;
 fly01_i2c_write10 #(.CLK_HZ(50000000),.BUS_HZ(50000),.STRETCH_TIMEOUT_CYCLES(1000))
 dut(.clk(clk),.reset_n(reset_n),.start(start),.payload(payload),
 .scl_in(scl),.sda_in(sda),.scl_drive_low(scl_drive_low),.sda_drive_low(sda_drive_low),
 .busy(busy),.done(done),.success(success),
 .fault_code(fault_code),.acknowledged_bytes(acknowledged_bytes));
 integer recovery_edges=0;
 reg release_after_nine=0;
 always @(posedge scl)if(release_after_nine && dut.recovering)begin
  recovery_edges=recovery_edges+1;
  if(recovery_edges==9)begin force_sda=0;release_after_nine=0;end
 end
 reg active=0;integer poscount=0,recorded=0,nack_index=-1;
 reg [7:0] word=0;
 reg [7:0] seen[0:9];
 integer clk_cycles=0,last_scl_rise=-1,checked_periods=0;
 time scl_rose_at=0;
 always @(posedge scl) scl_rose_at=$time;
 always @(posedge sda) if(scl===1'b1 && recorded==10) begin
  $display("MEASURED_STOP_SETUP_NS=%0d",$time-scl_rose_at);
  if($time-scl_rose_at<4000) $fatal(1,"STOP_SETUP_BELOW_STANDARD_MODE_4000NS");
 end
 always @(posedge clk)clk_cycles=clk_cycles+1;
 always @(posedge scl)if(active)begin
  if(poscount>2&&poscount<8&&last_scl_rise>=0)begin
   if(clk_cycles-last_scl_rise<1000||clk_cycles-last_scl_rise>1040)
    $fatal(1,"I2C_NOT_50KHZ_PERIOD measured_clocks=%d",clk_cycles-last_scl_rise);
   checked_periods=checked_periods+1;
  end
  last_scl_rise=clk_cycles;
 end
 always @(negedge sda)if(scl===1'b1)begin active=1;poscount=0;recorded=0;word=0;end
 always @(posedge sda)if(scl===1'b1)begin active=0;slave_low=0;end
 always @(posedge scl)if(active)begin
  if(poscount%9<8)begin
   word={word[6:0],sda};
   if(poscount%9==7)begin
    if(recorded<10)seen[recorded]=word;
    recorded=recorded+1;
   end
  end
  poscount=poscount+1;
 end
 always @(negedge scl)begin
  if(active && slave_ack && poscount%9==8 &&
   ((poscount/9)!=nack_index))slave_low=1;
  else slave_low=0;
 end
 task launch;begin @(negedge clk);start=1;@(negedge clk);start=0;end endtask
 task finish_wait;integer n;begin
  n=0;
  while(!done&&n<200000)begin @(negedge clk);n=n+1;end
  if(!done)$fatal(1,"MASTER_TIMEOUT");
  @(negedge clk);
 end endtask
 initial begin
  repeat(5)@(negedge clk);reset_n=1;
  launch();finish_wait();
  if(!success||acknowledged_bytes!=10||fault_code!=0)
   $fatal(1,"MASTER_NORMAL_FAIL success=%b ack=%d fault=%d rec=%d",success,acknowledged_bytes,fault_code,recorded);
  if(seen[0]!==8'h4c||seen[1]!==8'h07||seen[2]!==8'hfb||
     seen[3]!==8'h50||seen[4]!==8'h04||seen[5]!==8'hb0||
     seen[6]!==0||seen[7]!==0||seen[8]!==0||seen[9]!==0)
   $fatal(1,"MASTER_PAYLOAD_INCORRECT");
  if(checked_periods<2)$fatal(1,"I2C_PERIOD_CHECK_NOT_EXERCISED");
  $display("I2C_50KHZ_PERIOD_PASS checks=%d",checked_periods);
  $display("I2C_NORMAL_PASS address_and_payload=PASS 10_ACK=PASS");
  repeat(25)@(negedge clk);
  fork
   begin launch();finish_wait();end
   begin
    wait(dut.state==5 && dut.tick==20);
    @(negedge clk);force dut.scl_sync=1'b0;
    @(negedge clk);release dut.scl_sync;
   end
  join
  if(!success||acknowledged_bytes!=10||fault_code!=0)$fatal(1,"SHORT_GLITCH_ABORTED_FRAME");
  $display("I2C_20NS_SPIKE_FILTER_PASS");
  repeat(25)@(negedge clk);
  force_sda=1;release_after_nine=1;recovery_edges=0;
  repeat(20)@(negedge clk);launch();finish_wait();
  if(!success||fault_code!=0||acknowledged_bytes!=10||recovery_edges!=9)
    $fatal(1,"BUS_CLEAR_DID_NOT_RECOVER_ZERO_FRAME");
  $display("I2C_NINE_CLOCK_BUS_CLEAR_PASS");
  repeat(25)@(negedge clk);
  nack_index=4;
  launch();finish_wait();
  if(success||fault_code!=3||acknowledged_bytes!=4)
   $fatal(1,"MASTER_NACK_FAIL success=%b fault=%d ack=%d",success,fault_code,acknowledged_bytes);
  $display("I2C_NACK_PASS no_false_success=PASS");
  repeat(25)@(negedge clk);
  nack_index=-1;force_scl=1;
  // This case is a bus stuck BEFORE launch; let the input synchronizer settle.
  repeat(20)@(negedge clk);
  launch();finish_wait();
  if(success||fault_code!=1)$fatal(1,"STUCK_SCL_FAIL %d",fault_code);
  $display("I2C_STUCK_BUS_PASS timeout_and_release=PASS");
  force_scl=0;
  repeat(25)@(negedge clk);
  force_sda=1;
  repeat(20)@(negedge clk);
  launch();finish_wait();
  if(success||fault_code!=1)$fatal(1,"STUCK_SDA_FAIL %d",fault_code);
  $display("I2C_STUCK_SDA_PASS timeout_and_release=PASS");
  $display("R12_I2C_RECOVERY_UNIT_PASS");finished=1;
 end
 initial begin #100000000;if(!finished)$fatal(1,"TB_GLOBAL_WATCHDOG");end
endmodule
