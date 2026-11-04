`timescale 1ns/1ps
// Engineering actuator transfer only. Does not feed back into the neural model.
// Zero/small samples expire after HOLD_CYCLES; permit loss clears on next clock.
module fly01_motor_envelope #(
 parameter integer HOLD_CYCLES=10000000,
 parameter integer DEADBAND=1,NEGATIVE_DEADBAND=1,START_PWM=1200,MAX_PWM=1600
)(input wire clk,reset_n,permit,valid,
 input wire signed [15:0] raw_pwm,
 output reg valid_out,output reg signed [15:0] pwm);
 reg [31:0] hold_left;
 wire signed [16:0] extended={raw_pwm[15],raw_pwm};
 wire [16:0] magnitude=raw_pwm[15]?-extended:extended;
 wire [17:0] boosted={1'b0,magnitude}+START_PWM;
 wire [15:0] bounded=(boosted>MAX_PWM)?MAX_PWM:boosted[15:0];
 initial if(HOLD_CYCLES<1||DEADBAND<1||NEGATIVE_DEADBAND<1||START_PWM<1||
            MAX_PWM<START_PWM||MAX_PWM>2000)$error("Invalid motor envelope bounds");
 always @(posedge clk)begin
  if(!reset_n||!permit)begin hold_left<=0;pwm<=0;valid_out<=0;end
  else begin
   valid_out<=valid;
   if(hold_left!=0)hold_left<=hold_left-1;
   if(hold_left==1)begin pwm<=0;valid_out<=1;end
   if(valid&&magnitude>=(raw_pwm[15]?NEGATIVE_DEADBAND:DEADBAND))begin
    pwm<=raw_pwm[15]?-$signed(bounded):$signed(bounded);
    hold_left<=HOLD_CYCLES;
   end
  end
 end
endmodule
