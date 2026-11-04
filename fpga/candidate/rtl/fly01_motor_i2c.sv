`timescale 1ns/1ps
// WORK18 actuator adapter: consumes the SAME signed PWM/stop signals as UART baseline.
// No changes to neural math. Motion disabled by default at elaboration.
// On boot probe with zero PWM and require ten ACKs (address + nine data bytes).
// A NACK/stuck bus irrevocably inhibits nonzero outputs until system reset.
// Bus ACK is not motor feedback; emergency physical power switch remains mandatory.
module fly01_motor_i2c #(
 parameter integer CLK_HZ=50000000,
 parameter integer BUS_HZ=100000,
 parameter integer UPDATE_MS=20,
 parameter integer MAX_MOTION_MS=780,
 parameter integer ENABLE_MOTION=0
)(
 input wire clk,reset_n,stop,command_valid,
 input wire signed [15:0] left_pwm,right_pwm,
 input wire scl_in,sda_in,
 output wire scl_drive_low,sda_drive_low,
 output reg fault,output reg [2:0] fault_code,
 output reg zero_acknowledged,output reg [31:0] completed_frames,
 output reg [3:0] last_acks,
 output wire i2c_busy,
 output reg signed [15:0] last_acked_left,last_acked_right,
 output reg [3:0] first_fault_acks
);
 localparam integer UPDATE_CYCLES=(CLK_HZ/1000)*UPDATE_MS;
 localparam integer MAX_CYCLES=(CLK_HZ/1000)*MAX_MOTION_MS;
 initial if(UPDATE_MS<5||UPDATE_MS>50||MAX_MOTION_MS<1||MAX_MOTION_MS>1000 ||
             ENABLE_MOTION<0||ENABLE_MOTION>1||MAX_CYCLES<1)
  $error("Invalid actuator safety bounds");
 reg signed [15:0] wanted_left,wanted_right;
 reg action_latched,urgent_zero;
 reg [31:0] motion_age,interval;
 reg [71:0] payload;
 reg issue;
 reg inflight_motion;
 wire done,good;wire [2:0] error;wire [3:0] acknowledgements;
 wire master_busy;
 fly01_i2c_write10 #(.CLK_HZ(CLK_HZ),.BUS_HZ(BUS_HZ)) master(
  .clk(clk),.reset_n(reset_n),.start(issue),.payload(payload),
  .scl_in(scl_in),.sda_in(sda_in),.scl_drive_low(scl_drive_low),.sda_drive_low(sda_drive_low),
  .busy(master_busy),.done(done),.success(good),
  .fault_code(error),.acknowledged_bytes(acknowledgements));
 assign i2c_busy=master_busy;
 wire safe_stop=stop||fault||!ENABLE_MOTION||!zero_acknowledged||
    !action_latched||motion_age>=MAX_CYCLES;
 wire [15:0] m1=safe_stop?16'h0000:wanted_left;
 wire [15:0] m2=safe_stop?16'h0000:wanted_right;
 wire values_valid=($signed(m1)<=16'sd2000 && $signed(m1)>=-16'sd2000 &&
                    $signed(m2)<=16'sd2000 && $signed(m2)>=-16'sd2000);
 wire invalid_command=command_valid &&
   ($signed(left_pwm)>16'sd2000 || $signed(left_pwm)<-16'sd2000 ||
    $signed(right_pwm)>16'sd2000 || $signed(right_pwm)<-16'sd2000);
 // signed big-endian natural packing in Verilog.
 wire [71:0] next_payload={8'h07,m1,m2,16'h0000,16'h0000};
 always @(posedge clk)begin
 if(!reset_n)begin
  wanted_left<=0;wanted_right<=0;action_latched<=0;
  urgent_zero<=1;motion_age<=0;interval<=UPDATE_CYCLES;
  issue<=0;payload<={8'h07,64'h0000};inflight_motion<=0;
  fault<=0;fault_code<=0;zero_acknowledged<=0;
  completed_frames<=0;last_acks<=0;last_acked_left<=0;last_acked_right<=0;first_fault_acks<=0;
 end else begin
  issue<=0;
  if(interval<UPDATE_CYCLES)interval<=interval+1;
  if(motion_age<MAX_CYCLES)motion_age<=motion_age+1;
  if(stop)begin
   if(action_latched)urgent_zero<=1;
   wanted_left<=0;wanted_right<=0;action_latched<=0;
   motion_age<=0;
  end else if(command_valid && !fault && ENABLE_MOTION && zero_acknowledged)begin
   if($signed(left_pwm)>16'sd2000 || $signed(left_pwm)<-16'sd2000 ||
      $signed(right_pwm)>16'sd2000 || $signed(right_pwm)<-16'sd2000)begin
    fault<=1;fault_code<=3'd4;action_latched<=0;urgent_zero<=1;
   end else begin
    wanted_left<=left_pwm;wanted_right<=right_pwm;
    action_latched<=1;motion_age<=0;
   end
  end
  if(done)begin
   completed_frames<=completed_frames+1;last_acks<=acknowledgements;
   if(good && acknowledgements==4'd10)begin
    last_acked_left<=payload[63:48];last_acked_right<=payload[47:32];
   end
   if(!good || acknowledgements!=4'd10)begin
    // Preserve the cause paired with first_fault_acks across zero retries.
    if(!fault)begin
     first_fault_acks<=acknowledgements;
     fault_code<=good?3'd5:error;
    end
    fault<=1;action_latched<=0;
    urgent_zero<=inflight_motion;
   end else if(!inflight_motion)begin
    zero_acknowledged<=1;
   end
  end
  // Never enqueue a stale command in the same cycle as processing the prior result.
  if(!master_busy && !issue && !done && (urgent_zero||interval>=UPDATE_CYCLES))begin
   // If STOP was asserted in this cycle, nonzero selection is still masked.
   if(urgent_zero||safe_stop||!values_valid||invalid_command)begin
    payload<={8'h07,64'h0000};inflight_motion<=0;
   end else begin
    payload<=next_payload;inflight_motion<=1;
   end
   issue<=1;interval<=0;urgent_zero<=0;
  end
 end
 end
endmodule
