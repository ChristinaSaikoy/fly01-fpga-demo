`timescale 1ns/1ps
module fly01_packet_tx(
 input wire clk,reset_n,valid,output wire ready,input wire [7:0] kind,
 input wire [31:0] session,seq,input wire [6:0] length,input wire [511:0] payload,
 output wire byte_valid,input wire byte_ready,output reg [7:0] byte_data
);
 reg active;reg [6:0] index,size;reg [7:0] k;
 reg [31:0] sess,number;reg [511:0] data;reg [15:0] crc;
 function automatic [15:0] crc_byte(input [15:0] c,input [7:0] b);
   reg [15:0] v;integer n;begin v=c^{b,8'b0};for(n=0;n<8;n=n+1)v=v[15]?(v<<1)^16'h1021:v<<1;crc_byte=v;end
 endfunction
 assign ready=!active;assign byte_valid=active;
 always @*begin
   case(index)
   0:byte_data=8'ha5;1:byte_data=8'h5a;2:byte_data=1;3:byte_data=k;
   4,5,6,7:byte_data=sess[(index-4)*8+:8];
   8,9,10,11:byte_data=number[(index-8)*8+:8];
   12:byte_data={1'b0,size};
   default:if(index<13+size)byte_data=data[(index-13)*8+:8];
     else if(index==13+size)byte_data=crc[7:0];else byte_data=crc[15:8];
   endcase
 end
 always @(posedge clk)begin
   if(!reset_n)begin active<=0;index<=0;size<=0;k<=0;sess<=0;number<=0;data<=0;crc<=16'hffff;end
   else if(valid&&ready&&length<=64)begin active<=1;index<=0;size<=length;k<=kind;sess<=session;number<=seq;data<=payload;crc<=16'hffff;end
   else if(byte_valid&&byte_ready)begin
     if(index>=2&&index<13+size)crc<=crc_byte(crc,byte_data);
     if(index==14+size)active<=0;else index<=index+1;
   end
 end
endmodule
