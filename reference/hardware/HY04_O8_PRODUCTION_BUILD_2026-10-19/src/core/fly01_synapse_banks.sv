`timescale 1ns/1ps
module fly01_weight_bank_2k #(parameter MEMFILE="")(
 input logic clk, input logic en, input logic [10:0] addr, output logic signed [15:0] q);
 (* rom_style="block" *) logic signed [15:0] mem [0:2047];
 initial $readmemh(MEMFILE, mem);
 always_ff @(posedge clk) if(en) q <= mem[addr];
endmodule

module fly01_dst_bank_4k #(parameter MEMFILE="")(
 input logic clk, input logic en, input logic [11:0] addr, output logic [8:0] q);
 (* rom_style="block" *) logic [8:0] mem [0:4095];
 initial $readmemh(MEMFILE, mem);
 always_ff @(posedge clk) if(en) q <= mem[addr];
endmodule

module fly01_synapse_banks(input logic clk,input logic [15:0] addr,
 output logic signed [15:0] weight_q, output logic [8:0] dst_q);
 logic [4:0] wbank; logic [3:0] dbank; assign wbank=addr[15:11]; assign dbank=addr[15:12];
 logic signed [15:0] wq_0;
 logic signed [15:0] wq_1;
 logic signed [15:0] wq_2;
 logic signed [15:0] wq_3;
 logic signed [15:0] wq_4;
 logic signed [15:0] wq_5;
 logic signed [15:0] wq_6;
 logic signed [15:0] wq_7;
 logic signed [15:0] wq_8;
 logic signed [15:0] wq_9;
 logic signed [15:0] wq_10;
 logic signed [15:0] wq_11;
 logic signed [15:0] wq_12;
 logic signed [15:0] wq_13;
 logic signed [15:0] wq_14;
 logic signed [15:0] wq_15;
 logic signed [15:0] wq_16;
 logic signed [15:0] wq_17;
 logic signed [15:0] wq_18;
 logic signed [15:0] wq_19;
 logic signed [15:0] wq_20;
 logic signed [15:0] wq_21;
 logic [8:0] dq_0;
 logic [8:0] dq_1;
 logic [8:0] dq_2;
 logic [8:0] dq_3;
 logic [8:0] dq_4;
 logic [8:0] dq_5;
 logic [8:0] dq_6;
 logic [8:0] dq_7;
 logic [8:0] dq_8;
 logic [8:0] dq_9;
 logic [8:0] dq_10;
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b00.mem")) u_w0(.clk(clk),.en(wbank==5'd0),.addr(addr[10:0]),.q(wq_0));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b01.mem")) u_w1(.clk(clk),.en(wbank==5'd1),.addr(addr[10:0]),.q(wq_1));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b02.mem")) u_w2(.clk(clk),.en(wbank==5'd2),.addr(addr[10:0]),.q(wq_2));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b03.mem")) u_w3(.clk(clk),.en(wbank==5'd3),.addr(addr[10:0]),.q(wq_3));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b04.mem")) u_w4(.clk(clk),.en(wbank==5'd4),.addr(addr[10:0]),.q(wq_4));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b05.mem")) u_w5(.clk(clk),.en(wbank==5'd5),.addr(addr[10:0]),.q(wq_5));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b06.mem")) u_w6(.clk(clk),.en(wbank==5'd6),.addr(addr[10:0]),.q(wq_6));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b07.mem")) u_w7(.clk(clk),.en(wbank==5'd7),.addr(addr[10:0]),.q(wq_7));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b08.mem")) u_w8(.clk(clk),.en(wbank==5'd8),.addr(addr[10:0]),.q(wq_8));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b09.mem")) u_w9(.clk(clk),.en(wbank==5'd9),.addr(addr[10:0]),.q(wq_9));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b10.mem")) u_w10(.clk(clk),.en(wbank==5'd10),.addr(addr[10:0]),.q(wq_10));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b11.mem")) u_w11(.clk(clk),.en(wbank==5'd11),.addr(addr[10:0]),.q(wq_11));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b12.mem")) u_w12(.clk(clk),.en(wbank==5'd12),.addr(addr[10:0]),.q(wq_12));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b13.mem")) u_w13(.clk(clk),.en(wbank==5'd13),.addr(addr[10:0]),.q(wq_13));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b14.mem")) u_w14(.clk(clk),.en(wbank==5'd14),.addr(addr[10:0]),.q(wq_14));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b15.mem")) u_w15(.clk(clk),.en(wbank==5'd15),.addr(addr[10:0]),.q(wq_15));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b16.mem")) u_w16(.clk(clk),.en(wbank==5'd16),.addr(addr[10:0]),.q(wq_16));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b17.mem")) u_w17(.clk(clk),.en(wbank==5'd17),.addr(addr[10:0]),.q(wq_17));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b18.mem")) u_w18(.clk(clk),.en(wbank==5'd18),.addr(addr[10:0]),.q(wq_18));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b19.mem")) u_w19(.clk(clk),.en(wbank==5'd19),.addr(addr[10:0]),.q(wq_19));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b20.mem")) u_w20(.clk(clk),.en(wbank==5'd20),.addr(addr[10:0]),.q(wq_20));
 fly01_weight_bank_2k #(.MEMFILE("generated/banked/weight_b21.mem")) u_w21(.clk(clk),.en(wbank==5'd21),.addr(addr[10:0]),.q(wq_21));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b00.mem")) u_d0(.clk(clk),.en(dbank==4'd0),.addr(addr[11:0]),.q(dq_0));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b01.mem")) u_d1(.clk(clk),.en(dbank==4'd1),.addr(addr[11:0]),.q(dq_1));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b02.mem")) u_d2(.clk(clk),.en(dbank==4'd2),.addr(addr[11:0]),.q(dq_2));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b03.mem")) u_d3(.clk(clk),.en(dbank==4'd3),.addr(addr[11:0]),.q(dq_3));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b04.mem")) u_d4(.clk(clk),.en(dbank==4'd4),.addr(addr[11:0]),.q(dq_4));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b05.mem")) u_d5(.clk(clk),.en(dbank==4'd5),.addr(addr[11:0]),.q(dq_5));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b06.mem")) u_d6(.clk(clk),.en(dbank==4'd6),.addr(addr[11:0]),.q(dq_6));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b07.mem")) u_d7(.clk(clk),.en(dbank==4'd7),.addr(addr[11:0]),.q(dq_7));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b08.mem")) u_d8(.clk(clk),.en(dbank==4'd8),.addr(addr[11:0]),.q(dq_8));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b09.mem")) u_d9(.clk(clk),.en(dbank==4'd9),.addr(addr[11:0]),.q(dq_9));
 fly01_dst_bank_4k #(.MEMFILE("generated/banked/dst_b10.mem")) u_d10(.clk(clk),.en(dbank==4'd10),.addr(addr[11:0]),.q(dq_10));
 always_comb begin weight_q=16'sd0; case(wbank)
 5'd0: weight_q=wq_0;
 5'd1: weight_q=wq_1;
 5'd2: weight_q=wq_2;
 5'd3: weight_q=wq_3;
 5'd4: weight_q=wq_4;
 5'd5: weight_q=wq_5;
 5'd6: weight_q=wq_6;
 5'd7: weight_q=wq_7;
 5'd8: weight_q=wq_8;
 5'd9: weight_q=wq_9;
 5'd10: weight_q=wq_10;
 5'd11: weight_q=wq_11;
 5'd12: weight_q=wq_12;
 5'd13: weight_q=wq_13;
 5'd14: weight_q=wq_14;
 5'd15: weight_q=wq_15;
 5'd16: weight_q=wq_16;
 5'd17: weight_q=wq_17;
 5'd18: weight_q=wq_18;
 5'd19: weight_q=wq_19;
 5'd20: weight_q=wq_20;
 5'd21: weight_q=wq_21;
 default: weight_q=16'sd0; endcase end
 always_comb begin dst_q=9'd0; case(dbank)
 4'd0: dst_q=dq_0;
 4'd1: dst_q=dq_1;
 4'd2: dst_q=dq_2;
 4'd3: dst_q=dq_3;
 4'd4: dst_q=dq_4;
 4'd5: dst_q=dq_5;
 4'd6: dst_q=dq_6;
 4'd7: dst_q=dq_7;
 4'd8: dst_q=dq_8;
 4'd9: dst_q=dq_9;
 4'd10: dst_q=dq_10;
 default: dst_q=9'd0; endcase end
endmodule
