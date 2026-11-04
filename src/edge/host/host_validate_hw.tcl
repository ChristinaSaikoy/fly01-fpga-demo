# S5-FPGA-1C deterministic JTAG AXI-Lite backend.
# Arguments: plan capture transaction_log bitstream program(0/1) serial hw_server_url
if {$argc != 7} {
    puts stderr "usage: host_validate_hw.tcl PLAN CAPTURE TXLOG BIT PROGRAM SERIAL HW_SERVER_URL"
    exit 2
}
set plan [lindex $argv 0]
set capture [lindex $argv 1]
set txlog [lindex $argv 2]
set bitfile [lindex $argv 3]
set do_program [lindex $argv 4]
set expected_serial [lindex $argv 5]
set hw_server_url [lindex $argv 6]
set ::txn_id 0
set ::ftxn [open $txlog w]
puts $::ftxn "transaction_id,type,address,data"

proc wr {axi addr data} {
    incr ::txn_id
    create_hw_axi_txn -force wr_txn $axi -address [format %08X $addr] -data [format %08X $data] -type write
    run_hw_axi [get_hw_axi_txns wr_txn]
    puts $::ftxn [format "%d,W,%08X,%08X" $::txn_id $addr $data]
}

proc rd {axi addr} {
    incr ::txn_id
    create_hw_axi_txn -force rd_txn $axi -address [format %08X $addr] -type read
    run_hw_axi [get_hw_axi_txns rd_txn]
    set raw [get_property DATA [get_hw_axi_txns rd_txn]]
    regsub -all {_} $raw {} raw
    regsub -nocase {^0x} $raw {} raw
    set value [expr 0x$raw]
    puts $::ftxn [format "%d,R,%08X,%08X" $::txn_id $addr $value]
    return $value
}

proc soft_reset_to_load {axi seed condition} {
    wr $axi 0x050 1
    set polls 0
    while {1} {
        set status [rd $axi 0x008]
        if {(($status >> 7) & 1) != 0} {
            error [format "PROTOCOL_ERROR_AFTER_RESET seed=%d condition=%d status=0x%08X" $seed $condition $status]
        }
        if {($status & 0xF) == 2} { return }
        incr polls
        if {$polls > 5000} { error "RESET_TO_LOAD_TIMEOUT seed=$seed condition=$condition" }
    }
}

open_hw_manager
connect_hw_server -url $hw_server_url
set matching_targets {}
foreach target [get_hw_targets *] {
    set target_name [get_property NAME $target]
    if {[string match "*$expected_serial*" $target_name]} { lappend matching_targets $target }
}
if {[llength $matching_targets] != 1} {
    error "EXPECTED_ONE_TARGET_FOR_SERIAL serial=$expected_serial got=[llength $matching_targets]"
}
set target [lindex $matching_targets 0]
open_hw_target $target
set matching_devices {}
foreach dev [get_hw_devices] {
    if {[string match "xc7a35t*" [get_property PART $dev]]} { lappend matching_devices $dev }
}
if {[llength $matching_devices] != 1} { error "EXPECTED_ONE_XC7A35T_DEVICE got=[llength $matching_devices]" }
set dev [lindex $matching_devices 0]
current_hw_device $dev
if {$do_program} {
    set_property PROGRAM.FILE $bitfile $dev
    program_hw_devices $dev
}
refresh_hw_device $dev

set startup_high 0
set startup_values {}
foreach property_name {REGISTER.EOS REGISTER.CONFIG_STATUS.DONE REGISTER.CONFIG_STATUS.BITSTREAM.STARTUP_STATE} {
    if {![catch {set property_value [get_property $property_name $dev]}] && $property_value ne ""} {
        lappend startup_values "$property_name=$property_value"
        if {[regexp -nocase {^(1|true|yes|high|done|startup)$} $property_value]} { set startup_high 1 }
    }
}
if {!$startup_high} { error "FPGA_STARTUP_STATUS_NOT_HIGH values=$startup_values" }

set axis [get_hw_axis]
if {[llength $axis] != 1} { error "EXPECTED_ONE_HW_AXI got=[llength $axis]" }
set axi [lindex $axis 0]
set protocol_id [rd $axi 0x000]
if {$protocol_id != 0xF1011C01} { error [format "PROTOCOL_ID_MISMATCH got=0x%08X" $protocol_id] }

set fin [open $plan r]
set fout [open $capture w]
puts $fout "META,PROTOCOL_ID,[format %08X $protocol_id]"
puts $fout "META,TARGET,[get_property NAME $target]"
puts $fout "META,DEVICE,[get_property PART $dev]"
puts $fout "META,STARTUP,[join $startup_values {;}]"
set current_seed -1
set current_condition -1

while {[gets $fin line] >= 0} {
    set line [string trim $line]
    if {$line eq ""} { continue }
    set fields [split $line ","]
    set kind [lindex $fields 0]
    if {$kind eq "CASE"} {
        set current_seed [expr {[lindex $fields 1] + 0}]
        set current_condition [expr {[lindex $fields 2] + 0}]
        soft_reset_to_load $axi $current_seed $current_condition
        puts $fout "CASE,$current_seed,$current_condition"
        continue
    }
    if {$kind ne "STEP" || $current_seed < 0} { error "BAD_PLAN_LINE $line" }
    set timestep [expr {[lindex $fields 1] + 0}]
    set dn_enable [expr {[lindex $fields 2] + 0}]
    set event_count [expr {[lindex $fields 3] + 0}]
    wr $axi 0x00C $timestep
    wr $axi 0x010 $event_count
    wr $axi 0x04C $dn_enable
    for {set i 0} {$i < $event_count} {incr i} {
        wr $axi 0x014 [expr 0x[lindex $fields [expr {$i + 4}]]]
    }
    set accepted [rd $axi 0x01C]
    if {$accepted != $event_count} { error "EVENT_COUNT_MISMATCH seed=$current_seed condition=$current_condition t=$timestep got=$accepted expected=$event_count" }
    wr $axi 0x018 1
    set polls 0
    while {1} {
        set status [rd $axi 0x008]
        if {(($status >> 7) & 1) != 0} { error [format "PROTOCOL_ERROR seed=%d condition=%d t=%d status=0x%08X" $current_seed $current_condition $timestep $status] }
        if {($status & 0xF) == 6} { break }
        incr polls
        if {$polls > 200000} { error "RUN_TO_READBACK_TIMEOUT seed=$current_seed condition=$current_condition t=$timestep" }
    }

    set completed [rd $axi 0x020]
    set acc_sat [rd $axi 0x034]
    set state_sat [rd $axi 0x038]
    set overflow [rd $axi 0x03C]
    set event_drop [rd $axi 0x040]
    set cycles [rd $axi 0x044]
    set states {}
    for {set neuron 0} {$neuron < 471} {incr neuron} {
        wr $axi 0x024 $neuron
        lappend states [format %08X [rd $axi 0x028]]
    }
    set dn_counts {}
    for {set counter 0} {$counter < 32} {incr counter} {
        wr $axi 0x02C $counter
        lappend dn_counts [format %08X [rd $axi 0x030]]
    }
    puts $fout "STEP,$current_seed,$current_condition,$timestep,$completed,$acc_sat,$state_sat,$overflow,$event_drop,$cycles,[join $states ,],[join $dn_counts ,]"
    flush $fout
    flush $::ftxn
    if {$timestep < 99} {
        wr $axi 0x004 2
        set status [rd $axi 0x008]
        if {($status & 0xF) != 2} { error "ACK_TO_LOAD_FAIL seed=$current_seed condition=$current_condition t=$timestep" }
    }
}

close $fin
close $fout
close $::ftxn
puts "S5_FPGA1C_HW_CAPTURE_COMPLETE capture=$capture transactions=$::txn_id"
close_hw_target $target
disconnect_hw_server
close_hw_manager
exit
