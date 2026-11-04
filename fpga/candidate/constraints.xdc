create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
set_property -dict {PACKAGE_PIN R4 IOSTANDARD LVCMOS33} [get_ports sys_clk]
set_property -dict {PACKAGE_PIN U2 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]
# ATK-DF7A35 V2.1 schematic PDF p9: J2 pins 1(M13),2(K14),3(R17), GND53/55.
set_property -dict {PACKAGE_PIN M13 IOSTANDARD LVCMOS33} [get_ports vision_rx]
set_property -dict {PACKAGE_PIN K14 IOSTANDARD LVCMOS33} [get_ports vision_tx]
# WORK18 I2C pins pending independent pinout/voltage clearance:
# J2-3 R17 (legacy UART TX) proposed SCL.
set_property -dict {PACKAGE_PIN R17 IOSTANDARD LVCMOS33} [get_ports motor_scl]
# V2.1 PDF page 9 verified: J2-5 N15. J2-4 is J16, not SDA.
set_property -dict {PACKAGE_PIN N15 IOSTANDARD LVCMOS33} [get_ports motor_sda]
# External 3.3V pull-ups are required; internal weak pulls are not adequate.
set_property PULLUP FALSE [get_ports {motor_scl motor_sda}]
# Board CH340 remains a distinct electrical net.
set_property -dict {PACKAGE_PIN U5 IOSTANDARD LVCMOS33} [get_ports uart_rxd]
set_property -dict {PACKAGE_PIN T6 IOSTANDARD LVCMOS33} [get_ports uart_txd]
set_property -dict {PACKAGE_PIN R2 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN R3 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN V2 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN Y2 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
set_false_path -from [get_ports vision_rx] -to [get_pins camera_rx/rx_meta_reg/D]
set_false_path -from [get_ports uart_rxd] -to [get_pins pc_rx/rx_meta_reg/D]
# Existing modules use a synchronous active-low reset. Physical reset is synchronized below.
set_false_path -from [get_ports sys_rst_n] -to [get_pins reset_meta_reg/D]
# Candidate external output budget; does not prove receiver electrical or baud tolerance.
set_output_delay -clock sys_clk -max 5 [get_ports {vision_tx uart_txd led[*]}]
set_output_delay -clock sys_clk -min 0 [get_ports {vision_tx uart_txd led[*]}]
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

# Asynchronous external I2C feedback is sampled only by these first-stage FFs.
set_false_path -from [get_ports motor_scl] -to [get_pins motor_i2c/master/scl_meta_reg/D]
set_false_path -from [get_ports motor_sda] -to [get_pins motor_i2c/master/sda_meta_reg/D]
