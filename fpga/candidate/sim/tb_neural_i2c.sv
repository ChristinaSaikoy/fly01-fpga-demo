`timescale 1ns/1ps
// Inject only actuator-side raw PWM/safety status. Frozen core is not replaced in production.
module tb_neural_i2c;
 reg sys_clk=0,sys_rst_n=0,vision_rx=1,uart_rxd=1;
 always #5 sys_clk=~sys_clk;
 wire vision_tx,uart_txd;wire [3:0] led;
 tri1 motor_scl,motor_sda;
 reg hold_scl=0;assign motor_scl=hold_scl?1'b0:1'bz;
 reg ack_drive=0;assign motor_sda=ack_drive?1'b0:1'bz;
 fly01_integration_top #(.CLOCK_HZ(1000000),.UART_DIV(8),.I2C_MOTION_ENABLE(1)) dut(.*);
 integer expected_right=1620,expected_negative=-1800,expected_negative_left=1600;
 wire recovery_test_done;tb_i2c_recovery recovery_test(recovery_test_done);
 wire sensitivity_test_done;tb_sensitive_scaling sensitivity_test(sensitivity_test_done);
 reg active=0;integer pulse=0,word_idx=0,positive=0,negative=0,zeros=0;
 reg [7:0] byte_now=0;reg [7:0] rx[0:9];
 reg inject_valid=0;reg signed [15:0] inject_pwm=0;
 always @(negedge motor_sda)if(motor_scl===1'b1)begin active=1;pulse=0;word_idx=0;byte_now=0;end
 always @(posedge motor_sda)if(motor_scl===1'b1)begin
  active=0;ack_drive=0;
  if(word_idx==10)begin
   if(rx[0]!==8'h4c||rx[1]!==8'h07||{rx[6],rx[7],rx[8],rx[9]}!==32'b0)
    $fatal(1,"BAD_MOTOR_FRAME");
   if($signed({rx[2],rx[3]})==-1220&&$signed({rx[4],rx[5]})==expected_right)positive=positive+1;
   else if($signed({rx[2],rx[3]})==expected_negative_left&&$signed({rx[4],rx[5]})==expected_negative)negative=negative+1;
   else if({rx[2],rx[3],rx[4],rx[5]}==32'b0)zeros=zeros+1;
   else $fatal(1,"UNEXPECTED_CALIBRATED_FRAME");
  end
 end
 always @(posedge motor_scl)if(active)begin
  if(pulse%9<8)begin
   byte_now={byte_now[6:0],motor_sda};
   if(pulse%9==7)begin if(word_idx<10)rx[word_idx]=byte_now;word_idx=word_idx+1;end
  end
  pulse=pulse+1;
 end
 always @(negedge motor_scl)begin
  if(active&&pulse%9==8)ack_drive=1;else ack_drive=0;
 end
 task pc(input [7:0] data);integer b;begin
  @(negedge sys_clk);uart_rxd=0;repeat(8)@(negedge sys_clk);
  for(b=0;b<8;b=b+1)begin uart_rxd=data[b];repeat(8)@(negedge sys_clk);end
  uart_rxd=1;repeat(10)@(negedge sys_clk);
 end endtask
 task sample(input signed [15:0] x);begin
  @(negedge sys_clk);inject_valid=1;inject_pwm=x;
  @(negedge sys_clk);inject_valid=0;
 end endtask
 task tune(input [87:0] frame);integer j;begin
  for(j=10;j>=0;j=j-1)pc(frame[j*8+:8]);
 end endtask
 integer old_zeros,old_positive,old_negative;
 initial begin
  force dut.pwm=inject_pwm;force dut.pwm_valid=inject_valid;
  repeat(8)@(negedge sys_clk);sys_rst_n=1;wait(dut.i2c_zero_ack);
  sample(354);repeat(25000)@(negedge sys_clk);
  if(positive||negative||dut.armed)$fatal(1,"BOOT_AUTOMATIC_MOTION");
  force dut.seen=1;force dut.usable=1;force dut.age=0;
  force dut.result_age=0;force dut.result_eligible=1;
  force dut.motion_activity=1;force dut.output_step=32'd100;
  pc("E");wait(dut.armed);sample(20);wait(positive>=1);repeat(50)@(negedge sys_clk);
  if(dut.i2c_acked_right!=1620)$fatal(1,"ACKED_NEURAL_DUTY");
  sample(0);repeat(250000)@(negedge sys_clk);
  if(dut.motor_pwm!=1220||dut.i2c_acked_right!=1620)$fatal(1,"R7_HOLD_SHORTER_THAN_250MS");
  repeat(380000)@(negedge sys_clk);
  if(dut.motor_pwm!=0||dut.i2c_acked_right!=0)$fatal(1,"ENVELOPE_NO_EXPIRY");
  $display("NEURAL_START_AND_SPARSE_EXPIRY_PASS");
  sample(-400);wait(negative>=1);old_zeros=zeros;
  pc("S");wait(!dut.armed);wait(zeros>old_zeros);repeat(50)@(negedge sys_clk);
  if(dut.motor_pwm!=0||dut.i2c_acked_right!=0)$fatal(1,"STOP_NOT_ZERO");
  $display("NEURAL_NEGATIVE_AND_STOP_PASS");
  pc("E");wait(dut.armed);sample(20);wait(dut.i2c_acked_right==1620);
  force dut.motion_activity=0;repeat(25000)@(negedge sys_clk);
  if(!dut.armed||dut.motor_pwm!=0||dut.i2c_acked_right!=0)$fatal(1,"ACTIVITY_LOSS_NOT_ZERO");
  $display("NEURAL_ACTIVITY_LOSS_STOP_PASS");
  force dut.motion_activity=1;sample(20);repeat(25000)@(negedge sys_clk);
  if(!dut.armed||dut.i2c_acked_right!=1620)$fatal(1,"OPERATOR_INTENT_NOT_RETAINED");
  pc("S");wait(!dut.armed);wait(dut.i2c_acked_right==0);
  if(dut.i2c_fault)$fatal(1,"UNEXPECTED_I2C_FAULT");
  // A manual retry with a still-stuck bus must fault again, never enable.
  wait(!dut.i2c_busy);hold_scl=1;wait(dut.i2c_fault);
  pc("S");pc("R");wait(dut.i2c_retry_reset);wait(!dut.i2c_fault);
  wait(dut.i2c_fault);
  if(dut.armed||dut.i2c_acked_right!=0)$fatal(1,"RETRY_STUCK_BUS_ENABLED_MOTION");
  $display("MANUAL_RETRY_STUCK_BUS_FAILS_CLOSED_PASS");
  // Release the external fault and retry. A fresh zero transaction must ACK.
  hold_scl=0;pc("R");wait(dut.i2c_retry_reset);wait(!dut.i2c_fault);
  wait(dut.i2c_zero_ack);repeat(25000)@(negedge sys_clk);
  if(dut.i2c_fault||dut.armed||dut.i2c_acked_left!=0||dut.i2c_acked_right!=0)
    $fatal(1,"MANUAL_RETRY_NOT_RECOVERED_ZERO");
  sample(20);repeat(25000)@(negedge sys_clk);
  if(dut.armed||dut.i2c_acked_right!=0)$fatal(1,"RETRY_AUTOMATIC_REARM");
  $display("MANUAL_RETRY_ZERO_ACK_NO_AUTOREARM_PASS");
  tune({"T0700,2000",8'd10});repeat(5)@(negedge sys_clk);
  if(dut.right_trim!=700||dut.right_limit!=2000||dut.armed)$fatal(1,"TRIM_APPLY_NOT_ATOMIC_DISARMED");
  if(dut.motor_last_frame[159:158]!=1||dut.motor_last_frame[156:146]!=2000||dut.motor_last_frame[145:136]!=700)
    $fatal(1,"TRIM_READBACK_WRONG");
  tune({"T0801,2000",8'd10});tune({"T0700,2001",8'd10});
  if(dut.right_trim!=700||dut.right_limit!=2000)$fatal(1,"INVALID_TRIM_ACCEPTED");
  pc("T");pc("0");pc("E");
  if(dut.armed)$fatal(1,"PARTIAL_TRIM_ENABLED_MOTION");
  pc("T");pc("0");pc("S");repeat(25000)@(negedge sys_clk);
  if(dut.trim_receiving||dut.right_trim!=700)$fatal(1,"TRIM_STOP_NOT_CANCELLED");
  pc("T");pc("0");repeat(25000)@(negedge sys_clk);
  if(dut.trim_receiving||dut.right_trim!=700)$fatal(1,"TRIM_TIMEOUT_NOT_CANCELLED");
  expected_right=1920;expected_negative=-2000;
  pc("E");wait(dut.armed);old_positive=positive;sample(20);wait(positive>old_positive);
  tune({"T0000,1200",8'd10});
  if(dut.right_trim!=700||dut.right_limit!=2000)$fatal(1,"ARMED_TRIM_CHANGE_ACCEPTED");
  old_negative=negative;sample(-400);wait(negative>old_negative);
  pc("S");wait(!dut.armed);wait(dut.i2c_acked_right==0);
  $display("PWM_TRIM_RUNTIME_READBACK_AND_SIGNED_CAP_PASS");
  $display("PWM_TRIM_INVALID_PARTIAL_TIMEOUT_AND_ARMED_REJECTION_PASS");
  expected_negative_left=1216;expected_negative=-1916;
  pc("E");wait(dut.armed);old_negative=negative;sample(-16);wait(negative>old_negative);
  pc("S");wait(!dut.armed);wait(dut.i2c_acked_right==0);
  $display("SMALL_NEGATIVE_NEURAL_COMMAND_REACHES_MOTORS_PASS");
  expected_negative_left=1201;expected_negative=-1901;
  pc("E");wait(dut.armed);old_negative=negative;sample(-1);wait(negative>old_negative);
  pc("S");wait(!dut.armed);wait(dut.i2c_acked_right==0);
  $display("MINIMUM_NEGATIVE_COMMAND_AND_STOP_PASS");
  wait(recovery_test_done && sensitivity_test_done);
  $display("WORK28_R13_SENSITIVE_PASS");$display("WORK18_NEURAL_I2C_PASS");$finish;
 end
 always @(dut.retry_epoch)if(sys_rst_n && dut.reset_n===1'b1)begin
  #1;
  if(dut.i2c_fault || dut.i2c_frames!=0)$fatal(1,"RETRY_EPOCH_OLD_FAULT_RACE");
 end
 initial begin #25000000;$fatal(1,"NEURAL_I2C_WATCHDOG");end
endmodule
