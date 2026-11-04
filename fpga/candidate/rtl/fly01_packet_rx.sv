`timescale 1ns/1ps
// Byte-level packet receiver, 20 ms inter-byte timeout, no implicit flow control.
module fly01_packet_rx #(parameter integer TIMEOUT_CYCLES=1000000)(
 input wire clk,reset_n, input wire byte_valid,input wire [7:0] byte_data,
 output reg valid, output reg [7:0] kind, output reg [31:0] session,seq,
 output reg [6:0] length,output reg [511:0] payload,output reg [31:0] bad_count
);
 reg [2:0] state;reg [6:0] index;reg [15:0] crc,received_crc;
 reg [31:0] timer;reg [7:0] header[0:10];reg [511:0] buf_payload;
 function automatic [15:0] crc_byte(input [15:0] c,input [7:0] b);
   reg [15:0] v;integer n;begin v=c^{b,8'b0};for(n=0;n<8;n=n+1)v=v[15]?(v<<1)^16'h1021:v<<1;crc_byte=v;end
 endfunction
 always @(posedge clk)begin
   if(!reset_n)begin state<=0;index<=0;crc<=16'hffff;valid<=0;kind<=0;session<=0;seq<=0;
     length<=0;payload<=0;buf_payload<=0;bad_count<=0;timer<=0;received_crc<=0;end
   else begin
     valid<=0;
     if(state!=0 && timer>=TIMEOUT_CYCLES)begin state<=0;timer<=0;bad_count<=bad_count+1;end
     else if(byte_valid)begin
       timer<=0;
       case(state)
       0:if(byte_data==8'ha5)state<=1;
       1:if(byte_data==8'h5a)begin state<=2;index<=0;crc<=16'hffff;buf_payload<=0;end
         else if(byte_data!=8'ha5)state<=0;
       2:begin
         header[index]<=byte_data;crc<=crc_byte(crc,byte_data);
         if(index==10)begin
           if(header[0]!=1 || byte_data>64)begin state<=0;bad_count<=bad_count+1;end
           else begin index<=0;state<=byte_data==0?4:3;end
         end else index<=index+1;
       end
       3:begin
         buf_payload[index*8+:8]<=byte_data;crc<=crc_byte(crc,byte_data);
         if(index+1==header[10])state<=4;else index<=index+1;
       end
       4:begin received_crc[7:0]<=byte_data;state<=5;end
       5:begin
         state<=0;
         if({byte_data,received_crc[7:0]}==crc)begin
           valid<=1;kind<=header[1];session<={header[5],header[4],header[3],header[2]};
           seq<={header[9],header[8],header[7],header[6]};length<=header[10];payload<=buf_payload;
         end else bad_count<=bad_count+1;
       end
       default:state<=0;
       endcase
     end else if(state!=0)timer<=timer+1;
   end
 end
endmodule
