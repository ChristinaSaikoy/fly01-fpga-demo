`timescale 1ns/1ps
module tb_sensitive_scaling(output reg finished=0);
 reg clk=0,reset_n=0,valid=0,permit=1;
 reg signed [31:0] yaw=0;
 wire scaled_valid,output_valid;wire signed [15:0] raw,pwm;
 always #10 clk=~clk;
 fly01_spin_pwm #(.PRESERVE_NONZERO(1)) scale(clk,reset_n,valid,yaw,scaled_valid,raw);
 fly01_motor_envelope #(.HOLD_CYCLES(20)) env(clk,reset_n,permit,scaled_valid,raw,output_valid,pwm);
 task check(input signed [31:0] y,input signed [15:0] expected_raw,input signed [15:0] expected_pwm);
 begin
  @(negedge clk);yaw=y;valid=1;
  @(negedge clk);valid=0;
  wait(scaled_valid);#1;if(raw!==expected_raw)$fatal(1,"SENSITIVE_RAW %d %d",raw,expected_raw);
  wait(output_valid);#1;if(pwm!==expected_pwm)$fatal(1,"SENSITIVE_PWM %d %d",pwm,expected_pwm);
  repeat(3)@(negedge clk);
 end endtask
 initial begin
  repeat(4)@(negedge clk);reset_n=1;
  check(32'sd1,16'sd1,16'sd1201);
  check(-32'sd1,-16'sd1,-16'sd1201);
  check(32'sd20971,16'sd1,16'sd1201);
  check(-32'sd20971,-16'sd1,-16'sd1201);
  check(32'sd1048576,16'sd40,16'sd1240);
  check(-32'sd1048576,-16'sd40,-16'sd1240);
  @(negedge clk);yaw=0;valid=1;
  @(negedge clk);valid=0;wait(scaled_valid);#1;if(raw!==0)$fatal(1,"ZERO_NOT_ZERO");
  repeat(25)@(negedge clk);if(pwm!==0)$fatal(1,"ZERO_HOLD_DID_NOT_EXPIRE");
  check(-32'sd1,-16'sd1,-16'sd1201);
  @(negedge clk);permit=0;@(negedge clk);if(pwm!==0)$fatal(1,"PERMIT_OFF_NOT_ZERO");
  $display("SENSITIVE_SIGN_ZERO_STOP_PASS");finished=1;
 end
 initial begin #100000;if(!finished)$fatal(1,"SENSITIVE_WATCHDOG");end
endmodule
