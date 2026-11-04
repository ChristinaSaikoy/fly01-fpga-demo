`timescale 1ns/1ps
// FLY-01 WORK18: fixed-length I2C write transaction, 7-bit address 0x26.
// SDA and SCL are BOTH open drain: NEVER drive a logic 1.
// Transaction: START, {0x4c(write), ACK}, {register, 8 payload bytes, ACK each}, STOP.
// ACK means slave received a byte, NOT that an actuator moved or stopped.
// Host must enforce a safe motion gate and an out-of-band power cut.
module fly01_i2c_write10 #(
 parameter integer CLK_HZ=50000000,
 parameter integer BUS_HZ=100000,
 parameter integer STRETCH_TIMEOUT_CYCLES=50000
)(
 input wire clk,reset_n,start,
 input wire [71:0] payload, // {register,data0..data7}, MSB first
 input wire scl_in,sda_in,
 output wire scl_drive_low,sda_drive_low,
 output reg busy,done,success,
 output reg [2:0] fault_code,
 output reg [3:0] acknowledged_bytes
);
 localparam integer Q=(CLK_HZ/(BUS_HZ*2) < 2) ? 2 : CLK_HZ/(BUS_HZ*2);
 initial if(CLK_HZ<100000 || BUS_HZ<10000 || BUS_HZ>400000 ||
             CLK_HZ/(BUS_HZ*2)<2 || STRETCH_TIMEOUT_CYCLES<2)
   $error("Unsupported clock, bus speed or timeout");
 localparam [4:0] IDLE=0,BUS_WAIT=1,START_HOLD=2,BIT_SETUP=3,
  BIT_WAIT=4,BIT_HIGH=5,BIT_FALL=6,ACK_SETUP=7,ACK_WAIT=8,
  ACK_HIGH=9,ACK_FALL=10,STOP_PREP=11,STOP_WAIT=12,STOP_HIGH=13,STOP_SETUP=14,
  REC_LOW=15,REC_WAIT=16,REC_HIGH=17;
 reg [4:0] state;
 reg scl_low,sda_low;
 assign scl_drive_low=scl_low;
 assign sda_drive_low=sda_low;
 // External open-drain feedback crosses into the fabric clock domain.
 (* ASYNC_REG="TRUE" *) reg scl_meta,scl_sync,sda_meta,sda_sync;
 always @(posedge clk)begin
  if(!reset_n)begin scl_meta<=0;scl_sync<=0;sda_meta<=0;sda_sync<=0;end
  else begin scl_meta<=scl_in;scl_sync<=scl_meta;sda_meta<=sda_in;sda_sync<=sda_meta;end
 end
 // Require 100 ns stable feedback at 50 MHz; reject short input spikes.
 localparam integer FILTER_CYCLES=(CLK_HZ/10000000<2)?2:CLK_HZ/10000000;
 localparam integer FILTER_BITS=$clog2(FILTER_CYCLES+1);
 reg scl_filtered,sda_filtered;
 reg [FILTER_BITS-1:0] scl_count,sda_count;
 always @(posedge clk)begin
  if(!reset_n)begin scl_filtered<=0;sda_filtered<=0;scl_count<=0;sda_count<=0;end
  else begin
   if(scl_sync==scl_filtered)scl_count<=0;
   else if(scl_count==FILTER_CYCLES-1)begin scl_filtered<=scl_sync;scl_count<=0;end
   else scl_count<=scl_count+1;
   if(sda_sync==sda_filtered)sda_count<=0;
   else if(sda_count==FILTER_CYCLES-1)begin sda_filtered<=sda_sync;sda_count<=0;end
   else sda_count<=sda_count+1;
  end
 end
 wire both_high=(scl_filtered===1'b1 && sda_filtered===1'b1);
 wire scl_high=(scl_filtered===1'b1);
 wire sda_ack=(sda_filtered===1'b0);
 reg recovery_allowed,recovering;
 reg [3:0] recover_pulses;
 reg [31:0] tick,stuck;
 reg [3:0] byte_index,bit_index;
 reg [7:0] tx_byte;
 reg [71:0] latched;
 reg nack;
 function [7:0] getbyte(input [3:0] idx,input [71:0] word);
 begin
  case(idx)
  4'd1:getbyte=word[71:64];4'd2:getbyte=word[63:56];
  4'd3:getbyte=word[55:48];4'd4:getbyte=word[47:40];
  4'd5:getbyte=word[39:32];4'd6:getbyte=word[31:24];
  4'd7:getbyte=word[23:16];4'd8:getbyte=word[15:8];
  4'd9:getbyte=word[7:0];default:getbyte=8'h00;
  endcase
 end endfunction
 always @(posedge clk) begin
 if(!reset_n)begin
  state<=IDLE;scl_low<=0;sda_low<=0;busy<=0;done<=0;success<=0;
  fault_code<=0;acknowledged_bytes<=0;tick<=0;stuck<=0;
  byte_index<=0;bit_index<=7;tx_byte<=0;latched<=0;nack<=0;
  recovery_allowed<=1;recovering<=0;recover_pulses<=0;
 end else begin
  done<=0;
  case(state)
   IDLE:begin
    scl_low<=0;sda_low<=0;busy<=0;tick<=0;stuck<=0;
    if(start)begin
     busy<=1;success<=0;fault_code<=0;acknowledged_bytes<=0;
     latched<=payload;byte_index<=0;tx_byte<=8'h4c;bit_index<=7;nack<=0;
     if(both_high)begin sda_low<=1;state<=START_HOLD;end
     else state<=BUS_WAIT;
    end
   end
   BUS_WAIT:begin
    if(both_high)begin stuck<=0;sda_low<=1;state<=START_HOLD;tick<=0;end
    else if(recovery_allowed&&scl_high&&!sda_filtered&&stuck>=Q-1)begin
     recovery_allowed<=0;recovering<=1;recover_pulses<=0;
     scl_low<=1;sda_low<=0;tick<=0;stuck<=0;state<=REC_LOW;
    end
    else if(stuck>=STRETCH_TIMEOUT_CYCLES-1)begin
     // A stuck bus cannot be safely "stopped" by fabric alone.
     fault_code<=3'd1;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;
    end else stuck<=stuck+1;
   end
   START_HOLD:begin
    if(tick>=Q-1)begin tick<=0;scl_low<=1;sda_low<=1;state<=BIT_SETUP;end
    else tick<=tick+1;
   end
   BIT_SETUP:begin
    if(tick>=Q-1)begin tick<=0;scl_low<=0;stuck<=0;state<=BIT_WAIT;end
    else tick<=tick+1;
   end
   BIT_WAIT:begin
    if(scl_high)begin stuck<=0;tick<=0;state<=BIT_HIGH;end
    else if(stuck>=STRETCH_TIMEOUT_CYCLES-1)begin
     fault_code<=3'd2;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;
    end else stuck<=stuck+1;
   end
   BIT_HIGH:begin
    if(!scl_high)begin fault_code<=3'd6;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;end
    else if(tick>=Q-1)begin tick<=0;scl_low<=1;state<=BIT_FALL;end
    else tick<=tick+1;
   end
   BIT_FALL:begin
    if(bit_index==0)begin sda_low<=0;tick<=0;state<=ACK_SETUP;end
    else begin bit_index<=bit_index-1;sda_low<=~tx_byte[bit_index-1];tick<=0;state<=BIT_SETUP;end
   end
   ACK_SETUP:begin
    if(tick>=Q-1)begin tick<=0;scl_low<=0;stuck<=0;state<=ACK_WAIT;end
    else tick<=tick+1;
   end
   ACK_WAIT:begin
    if(scl_high)begin stuck<=0;tick<=0;state<=ACK_HIGH;end
    else if(stuck>=STRETCH_TIMEOUT_CYCLES-1)begin
     fault_code<=3'd2;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;
    end else stuck<=stuck+1;
   end
   ACK_HIGH:begin
    if(!scl_high)begin fault_code<=3'd6;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;end
    else if(tick>=Q-1)begin
     tick<=0;nack<=!sda_ack;if(sda_ack)acknowledged_bytes<=acknowledged_bytes+1;
     scl_low<=1;state<=ACK_FALL;
    end else tick<=tick+1;
   end
   ACK_FALL:begin
    if(nack)begin fault_code<=3'd3;state<=STOP_PREP;tick<=0;sda_low<=1;end
    else if(byte_index==9)begin state<=STOP_PREP;tick<=0;sda_low<=1;end
    else begin
     byte_index<=byte_index+1;
     tx_byte<=getbyte(byte_index+1,latched);
     bit_index<=7;
     sda_low<=((getbyte(byte_index+1,latched)&8'h80)==0);
     tick<=0;state<=BIT_SETUP;
    end
   end
   STOP_PREP:begin
    scl_low<=1;sda_low<=1;
    if(tick>=Q-1)begin tick<=0;scl_low<=0;stuck<=0;state<=STOP_WAIT;end
    else tick<=tick+1;
   end
   STOP_WAIT:begin
    if(scl_high)begin tick<=0;stuck<=0;state<=STOP_SETUP;end
    else if(stuck>=STRETCH_TIMEOUT_CYCLES-1)begin
     fault_code<=3'd2;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;
    end else stuck<=stuck+1;
   end
   // UM10204: hold SDA low after SCL rises, before releasing SDA for STOP.
   // At 100 kHz Q is 5 us, exceeding the Standard-mode 4 us minimum.
   STOP_SETUP:begin
    if(!scl_high)begin tick<=0;state<=STOP_WAIT;end
    else if(tick>=Q-1)begin tick<=0;sda_low<=0;state<=STOP_HIGH;end
    else tick<=tick+1;
   end
   STOP_HIGH:begin
    if(tick>=Q-1)begin
     tick<=0;
     if(recovering)begin recovering<=0;stuck<=0;state<=BUS_WAIT;end
     else begin state<=IDLE;busy<=0;done<=1;success<=!nack && fault_code==0;end
    end else tick<=tick+1;
   end
   REC_LOW:begin
    if(tick>=Q-1)begin tick<=0;scl_low<=0;stuck<=0;state<=REC_WAIT;end
    else tick<=tick+1;
   end
   REC_WAIT:begin
    if(scl_high)begin tick<=0;stuck<=0;state<=REC_HIGH;end
    else if(stuck>=STRETCH_TIMEOUT_CYCLES-1)begin
     fault_code<=3'd2;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;
    end else stuck<=stuck+1;
   end
   REC_HIGH:begin
    if(!scl_high)begin fault_code<=3'd6;success<=0;done<=1;busy<=0;
     scl_low<=0;sda_low<=0;state<=IDLE;end
    else if(tick>=Q-1)begin
     tick<=0;scl_low<=1;
     if(recover_pulses==8)begin sda_low<=1;state<=STOP_PREP;end
     else begin recover_pulses<=recover_pulses+1;state<=REC_LOW;end
    end else tick<=tick+1;
   end
   default:begin state<=IDLE;scl_low<=0;sda_low<=0;busy<=0;end
  endcase
 end
 end
endmodule
