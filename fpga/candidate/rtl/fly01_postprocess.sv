`timescale 1ns/1ps
module fly01_postprocess(input wire clk,reset_n,valid,input wire [1023:0] dn,
 output reg valid_out,output reg signed [31:0] yaw_q20);
 `include "postprocess_constants.vh"
 reg signed [31:0] y0,y1,y2;reg pending;
 reg signed [63:0] a0,a1,a2,raw_yaw;
 function automatic signed [31:0] round_alpha(input signed [63:0] v);
   begin round_alpha=v>=0?(v+64'sd8388608)>>>24:-(((-v)+64'sd8388608)>>>24);end
 endfunction
 always @*begin
   a0=y0>THETA_0?$signed(y0)-$signed(THETA_0):0;
   a1=y1>THETA_1?$signed(y1)-$signed(THETA_1):0;
   a2=y2>THETA_2?$signed(y2)-$signed(THETA_2):0;
   raw_yaw=((a2-a0)*64'sd1811+a1*64'sd14835)>>>5;
 end
 always @(posedge clk)begin
   if(!reset_n)begin y0<=0;y1<=0;y2<=0;pending<=0;valid_out<=0;yaw_q20<=0;end
   else begin
     pending<=valid;valid_out<=pending;
     if(valid)begin
       y0<=y0+round_alpha((($signed(dn[12*32+:32])!=0?Z1_0:Z0_0)-$signed(y0))*$signed(ALPHA));
       y1<=y1+round_alpha((($signed(dn[22*32+:32])!=0?Z1_1:Z0_1)-$signed(y1))*$signed(ALPHA));
       y2<=y2+round_alpha((($signed(dn[23*32+:32])!=0?Z1_2:Z0_2)-$signed(y2))*$signed(ALPHA));
     end
     if(pending)begin
       if(raw_yaw>64'sd20971520)yaw_q20<=32'sd20971520;
       else if(raw_yaw< -64'sd20971520)yaw_q20<=-32'sd20971520;
       else yaw_q20<=raw_yaw[31:0];
     end
   end
 end
endmodule
