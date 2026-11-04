# Windows variant: same exact volatile programming and read-only debug contract.
set bit [file normalize [lindex $argv 0]]
set sha [lindex $argv 1]
set serial [lindex $argv 2]
set receipt [lindex $argv 3]
set suite [lindex $argv 4]
if {![file exists $bit] || ![regexp {^[0-9a-f]{64}$} $sha] || $serial ne "210512180081"} {error O8_BAD_PROGRAM_ARGUMENT}
if {![info exists ::env(FLY01_SHA_PYTHON)] || ![file exists $::env(FLY01_SHA_PYTHON)]} {error O8_WINDOWS_HASH_INTERPRETER_MISSING}
proc windows_sha {path} {
    return [string trim [exec $::env(FLY01_SHA_PYTHON) -I -c {import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())} $path]]
}
set before_sha [windows_sha $bit]
if {$before_sha ne $sha} {error O8_NATIVE_BEFORE_HASH_MISMATCH}
open_hw_manager
connect_hw_server -url 127.0.0.1:3121
set targets [get_hw_targets -quiet -filter "NAME =~ *$serial*"]
if {[llength $targets]!=1} {error O8_EXACT_JTAG_TARGET_NOT_UNIQUE}
current_hw_target [lindex $targets 0]
open_hw_target
set devices [get_hw_devices -quiet -filter {PART == xc7a35t}]
if {[llength $devices]!=1} {error O8_EXACT_FPGA_NOT_UNIQUE}
set dev [lindex $devices 0]
set_property PROGRAM.FILE $bit $dev
program_hw_devices $dev
set after_sha [windows_sha $bit]
if {$after_sha ne $sha || [file normalize [get_property PROGRAM.FILE $dev]] ne $bit} {error O8_NATIVE_AFTER_HASH_OR_FILE_MISMATCH}
refresh_hw_device $dev
set ports [get_hw_axis -quiet -of_objects $dev]
if {[llength $ports]!=1} {error O8_DEBUG_AXI_NOT_UNIQUE}
set axi [lindex $ports 0]
proc read_debug {axi name address expected} {
    create_hw_axi_txn $name $axi -type read -address $address -len 1
    run_hw_axi [get_hw_axi_txns $name]
    set got [string tolower [get_property DATA [get_hw_axi_txns $name]]]
    if {$got ne $expected} {error "O8_DEBUG_IDENTITY_MISMATCH $address $got"}
    delete_hw_axi_txn [get_hw_axi_txns $name]
    return $got
}
read_debug $axi o8_id 00000000 f1081c01
read_debug $axi o8_version 00000054 f1080001
read_debug $axi o8_owner 00000068 00000001
read_debug $axi o8_baud 00000064 001e8480
read_debug $axi o8_full 00000060 00000212
set f [open $receipt {WRONLY CREAT EXCL}]
puts $f "{\"programming_status\":\"PASS\",\"bitstream_sha256\":\"$sha\",\"before_sha256\":\"$before_sha\",\"after_sha256\":\"$after_sha\",\"target_serial\":\"$serial\",\"part\":\"xc7a35t\",\"suite_id\":\"$suite\",\"volatile_only\":true,\"transport\":\"UART_ONLY_NEURAL_DATA\",\"debug_capability\":\"F1081C01\"}"
close $f
close_hw_target
disconnect_hw_server
close_hw_manager
puts O8_EXACT_VOLATILE_PROGRAM_AND_READONLY_IDENTITY_PASS
exit
