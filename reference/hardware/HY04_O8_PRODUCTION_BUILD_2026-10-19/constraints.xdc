# Same accepted 50MHz board source and physical pins; user confirms V2.1 matches.
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
set_property -dict {PACKAGE_PIN R4 IOSTANDARD LVCMOS33} [get_ports sys_clk]
set_property -dict {PACKAGE_PIN U2 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]
set_property -dict {PACKAGE_PIN R2 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN R3 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN V2 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN Y2 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
set_property -dict {PACKAGE_PIN U5 IOSTANDARD LVCMOS33} [get_ports uart_rxd]
set_property -dict {PACKAGE_PIN T6 IOSTANDARD LVCMOS33} [get_ports uart_txd]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CFGBVS VCCO [current_design]
# RX is truly asynchronous. Only the port -> first synchronizer D is excepted.
# Internal second stage/control paths remain fully timed at 50MHz.
set_input_delay -clock sys_clk -max 0.000 [get_ports uart_rxd]
set_input_delay -clock sys_clk -min 0.000 [get_ports uart_rxd]
set_false_path -from [get_ports uart_rxd] -to [get_pins -hier -filter {NAME =~ u_rx/rx_meta_reg/D}]
# Asynchronous UART TX / human LED have no receiver-synchronous launch clock.
# These explicit 0ns budgets cover package launch timing, not a physical CH340 setup guarantee.
set_output_delay -clock sys_clk -max 0.000 [get_ports uart_txd]
set_output_delay -clock sys_clk -min 0.000 [get_ports uart_txd]
set_output_delay -clock sys_clk -max 0.000 [get_ports {led[*]}]
set_output_delay -clock sys_clk -min 0.000 [get_ports {led[*]}]
set_input_delay -clock sys_clk -max 0.000 [get_ports sys_rst_n]
set_input_delay -clock sys_clk -min 0.000 [get_ports sys_rst_n]
# Preserve accepted external asynchronous reset synchronizer exception, first stage only.
set_false_path -from [get_ports sys_rst_n] -to [get_pins -hier -filter {NAME =~ reset_sync_reg*/CLR}]
