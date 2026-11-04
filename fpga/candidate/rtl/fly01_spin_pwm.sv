`timescale 1ns/1ps
// Exact yaw/20 * LIMIT, truncation toward zero; engineering actuator scaling only.
module fly01_spin_pwm #(parameter integer LIMIT=800,parameter integer PRESERVE_NONZERO=0)(input wire clk,reset_n,valid,
 input wire signed [31:0] yaw_q20,output reg valid_out,output reg signed [15:0] pwm);
 reg pending;reg signed [31:0] product;
 initial if(LIMIT<=0 || LIMIT>2000 || LIMIT%20!=0)$error("PWM limit must be positive multiple of 20, <=2000");
 always @(posedge clk)begin
  if(!reset_n)begin pending<=0;valid_out<=0;product<=0;pwm<=0;end
  else begin
   pending<=valid;valid_out<=pending;
   if(valid)product<=$signed(yaw_q20)*(LIMIT/20);
   if(pending)begin
    if(PRESERVE_NONZERO && product!=0 && product<32'sd1048576 && product> -32'sd1048576)
      pwm<=product<0?-16'sd1:16'sd1;
    else pwm<=product<0?-((-$signed(product))>>>20):$signed(product)>>>20;
   end
  end
 end
endmodule
