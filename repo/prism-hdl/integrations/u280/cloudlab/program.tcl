# Loads a bitstream into the U280 over JTAG (volatile: a power cycle restores
# the design in the card's flash).
#
# Usage:
#   vivado_lab -mode batch -source program.tcl -tclargs <bitstream> ?<hw_server url>?
#
# The PRISM design has no PCIe endpoint, so the card leaves the PCIe bus when
# it is programmed: remove its functions from the bus first (see
# prepare_host.sh), or the host may treat the lost link as a fatal error.
set bitstream [file normalize [lindex $argv 0]]
set server [expr {[llength $argv] > 1 ? [lindex $argv 1] : "localhost:3121"}]
if {![file exists $bitstream]} {error "no bitstream at $bitstream"}

open_hw_manager
connect_hw_server -url $server
set devices {}
foreach target [get_hw_targets] {
    open_hw_target $target
    set found [get_hw_devices -quiet xcu280*]
    if {[llength $found] > 0} {
        set devices $found
        break
    }
    close_hw_target $target
}
if {[llength $devices] != 1} {error "expected one U280 on the JTAG chain, found '$devices'"}
set device [lindex $devices 0]
current_hw_device $device
set_property PROGRAM.FILE $bitstream $device
program_hw_devices $device
refresh_hw_device $device
puts "PRISM_PROGRAM done=[get_property -quiet REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $device] device=$device"
close_hw_manager
