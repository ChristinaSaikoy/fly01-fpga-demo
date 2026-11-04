`timescale 1ns/1ps
module fly01_motor_ascii #(parameter integer CLOCK_HZ=50000000)(input wire clk,reset_n,stop,command_valid,
 input wire signed [15:0] left_pwm,right_pwm,
 output reg byte_valid,input wire byte_ready,output reg [7:0] byte_data);
 localparam IDLE=0,PREP_LEFT=1,PREP_RIGHT=2,PREFIX=3,LEFT_SIGN=4,LEFT_DIGIT=5,
   COMMA=6,RIGHT_SIGN=7,RIGHT_DIGIT=8,TAIL=9,RIGHT_COMMA=10;
 reg [3:0] state;reg pending,stop_pending,left_negative,right_negative;
 reg signed [15:0] next_left,next_right;
 reg [15:0] remainder;reg [3:0] digits[0:7];reg [2:0] index;integer i;
 wire selected_zero=stop||stop_pending;
 wire signed [15:0] selected_left=selected_zero?16'sd0:next_left;
 wire signed [15:0] selected_right=selected_zero?16'sd0:next_right;
 reg [15:0] right_abs;
 reg stop_seen;
 localparam integer REPEAT_CYCLES=(CLOCK_HZ/1000)*20;
 // Measured from acceptance of '#'; UART sends it in ~87us, leaving >2.9ms idle.
 localparam integer GAP_CYCLES=(CLOCK_HZ/1000)*3;
 reg [31:0] stop_timer,gap_timer;
 always @*begin
  byte_valid=1;byte_data=0;
  case(state)
   PREFIX:case(index)0:byte_data="$";1:byte_data="p";2:byte_data="w";3:byte_data="m";default:byte_data=":";endcase
   LEFT_SIGN:begin byte_data="-";byte_valid=left_negative;end
   RIGHT_SIGN:begin byte_data="-";byte_valid=right_negative;end
   LEFT_DIGIT:byte_data=8'd48+digits[index];
   RIGHT_DIGIT:byte_data=8'd48+digits[index+4];
   COMMA,RIGHT_COMMA:byte_data=",";
   TAIL:case(index)0:byte_data="0";1:byte_data=",";2:byte_data="0";default:byte_data="#";endcase
   default:byte_valid=0;
  endcase
 end
 always @(posedge clk)begin
  if(!reset_n)begin
   state<=IDLE;pending<=0;stop_pending<=1;next_left<=0;next_right<=0;index<=0;
   remainder<=0;right_abs<=0;left_negative<=0;right_negative<=0;
   for(i=0;i<8;i=i+1)digits[i]<=0;
   stop_seen<=0;
   stop_timer<=0;gap_timer<=0;
  end else begin
   stop_seen<=stop;
   if(gap_timer!=0)gap_timer<=gap_timer-1;
   if(!stop)stop_timer<=0;
   else if(!stop_seen||stop_timer>=REPEAT_CYCLES-1)stop_timer<=0;
   else stop_timer<=stop_timer+1;
   if(stop)begin
    pending<=0;next_left<=0;next_right<=0;
    if(!stop_seen||stop_timer>=REPEAT_CYCLES-1)stop_pending<=1;
   end
   else if(command_valid)begin pending<=1;next_left<=left_pwm;next_right<=right_pwm;end
   case(state)
   IDLE:if(gap_timer==0&&(stop_pending||(!stop&&pending)))begin
    left_negative<=selected_left<0;right_negative<=selected_right<0;
    remainder<=selected_left<0?-selected_left:selected_left;
    right_abs<=selected_right<0?-selected_right:selected_right;
    for(i=0;i<8;i=i+1)digits[i]<=0;
    // Sending a queued STOP must not consume a newer, post-STOP command.
    if(!selected_zero)pending<=command_valid&&!stop;
    stop_pending<=0;state<=PREP_LEFT;
   end
   PREP_LEFT,PREP_RIGHT:begin
    if(remainder>=1000)begin remainder<=remainder-1000;digits[state==PREP_LEFT?0:4]<=digits[state==PREP_LEFT?0:4]+1'b1;end
    else if(remainder>=100)begin remainder<=remainder-100;digits[state==PREP_LEFT?1:5]<=digits[state==PREP_LEFT?1:5]+1'b1;end
    else if(remainder>=10)begin remainder<=remainder-10;digits[state==PREP_LEFT?2:6]<=digits[state==PREP_LEFT?2:6]+1'b1;end
    else begin
     digits[state==PREP_LEFT?3:7]<=remainder[3:0];
     if(state==PREP_LEFT)begin remainder<=right_abs;state<=PREP_RIGHT;end
     else begin state<=PREFIX;index<=0;end
    end
   end
   LEFT_SIGN:if(!left_negative||byte_ready)begin state<=LEFT_DIGIT;index<=0;end
   RIGHT_SIGN:if(!right_negative||byte_ready)begin state<=RIGHT_DIGIT;index<=0;end
   default:if(byte_valid&&byte_ready)case(state)
    PREFIX:if(index==4)state<=LEFT_SIGN;else index<=index+1'b1;
    LEFT_DIGIT:if(index==3)state<=COMMA;else index<=index+1'b1;
    COMMA:state<=RIGHT_SIGN;
    RIGHT_DIGIT:if(index==3)state<=RIGHT_COMMA;else index<=index+1'b1;
    RIGHT_COMMA:begin state<=TAIL;index<=0;end
    TAIL:if(index==3)begin state<=IDLE;gap_timer<=GAP_CYCLES;end else index<=index+1'b1;
    default:state<=IDLE;
   endcase
   endcase
   if(stop&&!stop_seen&&(state==PREP_LEFT||state==PREP_RIGHT||(state==PREFIX&&index==0)))begin
     state<=PREP_LEFT;remainder<=0;right_abs<=0;left_negative<=0;right_negative<=0;
     for(i=0;i<8;i=i+1)digits[i]<=0;
   end
  end
 end
endmodule
