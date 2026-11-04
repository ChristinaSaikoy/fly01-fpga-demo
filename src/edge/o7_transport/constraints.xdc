# FLY-01 S5-FPGA-1C BOARD_VALIDATION_ONLY constraints
# ALIENTEK DaVinci A7 / XC7A35T-FGG484-2, onboard clock 50 MHz.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
set_property -dict {PACKAGE_PIN R4 IOSTANDARD LVCMOS33} [get_ports sys_clk]
set_property -dict {PACKAGE_PIN U2 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]
set_property -dict {PACKAGE_PIN R2 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN R3 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN V2 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN Y2 IOSTANDARD LVCMOS33} [get_ports {led[3]}]

set_input_delay -clock [get_clocks sys_clk] -min 0.000 [get_ports sys_rst_n]
set_input_delay -clock [get_clocks sys_clk] -max 0.000 [get_ports sys_rst_n]
set_false_path -from [get_ports sys_rst_n]
set_output_delay -clock [get_clocks sys_clk] -min 0.000 [get_ports {led[*]}]
set_output_delay -clock [get_clocks sys_clk] -max 0.000 [get_ports {led[*]}]
