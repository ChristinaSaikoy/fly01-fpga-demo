set here [file normalize [file dirname [info script]]]
cd $here
set_param general.maxThreads 4
puts "MIGRATION_VERSION [version -short]"
if {[version -short] ne "2025.2"} {error WRONG_VIVADO_VERSION}
set_part xc7a35tfgg484-2
read_verilog -sv [file join $here {src/core/fly01_accum_add.sv}]
read_verilog -sv [file join $here {src/core/fly01_engine_core.sv}]
read_verilog -sv [file join $here {src/core/fly01_event_fifo.sv}]
read_verilog -sv [file join $here {src/core/fly01_formal_top.sv}]
read_verilog -sv [file join $here {src/core/fly01_neuron_update.sv}]
read_verilog -sv [file join $here {src/core/fly01_round_shift.sv}]
read_verilog -sv [file join $here {src/core/fly01_source_drive.sv}]
read_verilog -sv [file join $here {src/core/fly01_synapse_banks.sv}]
read_verilog -sv [file join $here {src/uart/fly01_uart_rx.sv}]
read_verilog -sv [file join $here {src/uart/fly01_uart_tx.sv}]
read_verilog -sv [file join $here {src/wrapper/fly01_o7_endpoint.sv}]
read_verilog -sv [file join $here {src/wrapper/fly01_o7_transport.sv}]
read_verilog -sv [file join $here {src/wrapper/fly01_o8_board_top.sv}]
read_verilog -sv [file join $here {src/wrapper/fly01_o8_byte_endpoint.sv}]
read_verilog -sv [file join $here {src/wrapper/fly01_o8_debug_axi.sv}]
read_ip [file join $here {ip/ip_project/o5_ip.srcs/sources_1/ip/jtag_axi_o5/jtag_axi_o5.xci}]
report_ip_status -file ip_status_before.rpt
set ip [get_ips jtag_axi_o5]
if {[get_property IS_LOCKED $ip]} {error HY04_LOCKED_IP_NO_IMPLICIT_UPGRADE}
set ip [get_ips jtag_axi_o5]
report_ip_status -file ip_status_upgraded.rpt
if {[get_property IS_LOCKED $ip]} {error MIGRATION_IP_LOCKED_REQUIRES_REVIEW}
set f [open ip_parameter_readback.txt w]
foreach {key want} {RD_TXN_QUEUE_LENGTH 2 WR_TXN_QUEUE_LENGTH 2 M_HAS_BURST 0 PROTOCOL 0 M_AXI_DATA_WIDTH 32 M_AXI_ADDR_WIDTH 32 M_AXI_ID_WIDTH 1} {set got [get_property CONFIG.$key $ip]; puts $f "$key=$got"; if {$got ne $want} {error MIGRATION_IP_CONFIG_CHANGED}}
close $f
set_property GENERATE_SYNTH_CHECKPOINT false [get_files *jtag_axi_o5.xci]
generate_target all $ip
read_xdc constraints.xdc
synth_design -top fly01_o8_board_top -part xc7a35tfgg484-2
write_checkpoint post_synth.dcp
report_utilization -file utilization_synth.rpt
set cells [get_cells -hier -filter {NAME =~ u_rx/rx_meta_reg || NAME =~ u_rx/rx_sync_reg}]
if {[llength $cells]!=2} {error MIGRATION_RX_SYNC_COUNT}
foreach c $cells {if {![get_property ASYNC_REG $c]} {error MIGRATION_RX_ASYNC_REG}}
opt_design
place_design
phys_opt_design
route_design
report_utilization -file utilization_route.rpt
report_utilization -hierarchical -file utilization_route_hier.rpt
report_timing_summary -delay_type min_max -max_paths 30 -file timing_summary.rpt
report_drc -file drc.rpt
report_methodology -file methodology.rpt
check_timing -verbose -file check_timing.rpt
report_cdc -details -file cdc_route.rpt
report_bus_skew -file bus_skew.rpt
report_clock_networks -file clock_networks.rpt
report_ip_status -file ip_status_after.rpt
write_xdc -exclude_physical resolved_constraints.xdc
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set blockers 0
foreach v [get_drc_violations] {if {[get_property SEVERITY $v] in {Error {Critical Warning}}} {incr blockers}}
set f [open metrics.txt w]
puts $f "WNS=$wns
WHS=$whs
DRC_BLOCKERS=$blockers
CLOCK_MHZ=50
PART=xc7a35tfgg484-2"
close $f
if {$wns<0 || $whs<0 || $blockers>0} {error MIGRATION_TIMING_DRC_GATE}
write_checkpoint post_route.dcp
write_bitstream HY04_O8_CANDIDATE_NOT_PROGRAMMED.bit
puts HY04_PRODUCTION_BUILD_DONE
exit
