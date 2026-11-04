// Static seed tops avoid Windows vendor batch argument splitting at '='.
module tb_o5_seed0;tb_o5_full #(.DEFAULT_SEED(0)) u_tb();endmodule
module tb_o5_seed1;tb_o5_full #(.DEFAULT_SEED(1)) u_tb();endmodule
module tb_o5_seed2;tb_o5_full #(.DEFAULT_SEED(2)) u_tb();endmodule
module tb_o5_seed3;tb_o5_full #(.DEFAULT_SEED(3)) u_tb();endmodule
module tb_o5_seed4;tb_o5_full #(.DEFAULT_SEED(4)) u_tb();endmodule
module tb_o5_seed5;tb_o5_full #(.DEFAULT_SEED(5)) u_tb();endmodule
