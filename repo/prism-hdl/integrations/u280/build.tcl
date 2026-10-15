# Implements the U280 board top: PRISM with the CMAC subsystem and the packet
# adapter of the OpenNIC shell, and no host interface.
#
# Usage (build.py runs it):
#   vivado -mode batch -source build.tcl -tclargs <hdl root> <shell root> <output dir> ?argument ...?
#
# <hdl root> holds rtl.f and integrations/u280; <shell root> is a checkout of
# open-nic-shell at the pinned commit. An argument name:value is a generic of
# the top (for example RS_FEC:0); an argument @name:value is a flow option
# (Vivado's Windows launcher splits arguments at "=", so the separator is the
# first colon; a value may hold a drive letter):
#   @stop:synth|place|route|bitstream   last stage (default bitstream)
#   @incremental:<routed checkpoint>    place and route incrementally from it
#   @incremental_directive:<directive>  of the incremental read (default RuntimeOptimized)
#   @threads:N                          synthesis processes (default 4)
#
# The implementation is the one that closed timing at 250 MHz: the core is
# split over two SLRs (floorplan.tcl), placed with the ExtraNetDelay_high
# directive and 0.3 ns of extra setup uncertainty on the core clock during
# placement only, routed with AggressiveExplore and TNS cleanup, and
# optimised again after routing. The run stops with an error when the routed
# design misses timing, so a bitstream is only written for a closed design.
set hdl_root [file normalize [lindex $argv 0]]
set shell [file normalize [lindex $argv 1]]
set out [file normalize [lindex $argv 2]]
set generics {}
array set option {stop bitstream incremental "" incremental_directive RuntimeOptimized threads 4}
foreach argument [lrange $argv 3 end] {
    set split [string first : $argument]
    if {$split < 1} {error "expected name:value or @name:value, got '$argument'"}
    set name [string range $argument 0 [expr {$split - 1}]]
    set value [string range $argument [expr {$split + 1}] end]
    if {[string index $name 0] eq "@"} {
        set name [string range $name 1 end]
        if {![info exists option($name)]} {error "unknown flow option @$name"}
        set option($name) $value
    } else {
        lappend generics "$name=$value"
    }
}
set part xcu280-fsvh2892-2L-e
set top prism_u280_top
set board_top [file join $hdl_root integrations u280]
set placement_margin 0.3
file mkdir $out
set_param general.maxThreads 6
set_param synth.maxThreads $option(threads)

proc status {out text} {
    set f [open [file join $out stage-status.txt] w]
    puts $f $text
    puts $f [clock format [clock seconds] -gmt 1]
    close $f
}

# On some machines the first synthesis of a session fails while its helper
# process reads an installed Tcl file; such a call is repeated.
proc retried {command} {
    for {set attempt 1} {$attempt <= 3} {incr attempt} {
        if {![catch {uplevel 1 $command} message]} {return}
        puts "U280_BUILD attempt $attempt of '[lindex $command 0]' failed: $message"
        if {$attempt == 3} {error $message}
    }
}

proc reports {out stage} {
    set dir [file join $out $stage]
    file mkdir $dir
    report_timing_summary -max_paths 20 -file [file join $dir timing_summary.rpt]
    report_utilization -file [file join $dir utilization.rpt]
    report_utilization -hierarchical -hierarchical_depth 6 -file [file join $dir utilization_hierarchical.rpt]
    report_clock_interaction -file [file join $dir clock_interaction.rpt]
    set setup [get_timing_paths -setup -max_paths 1 -quiet]
    set hold [get_timing_paths -hold -max_paths 1 -quiet]
    set line "stage=$stage wns=[get_property SLACK $setup] whs=[get_property SLACK $hold]"
    set f [open [file join $dir summary.txt] w]
    puts $f $line
    close $f
    puts "U280_BUILD $line"
    return [list [get_property SLACK $setup] [get_property SLACK $hold]]
}

# ---------------------------------------------------------------- IP
# The CMAC and the crossbar of the shell's CMAC subsystem, from the shell's
# own IP scripts, configured for one port of the U280.
status $out ip
set_param board.repoPaths [file join $shell board_files]
create_project -in_memory -part $part
set_property board_part xilinx.com:au280:part0:1.1 [current_project]
set ip_build_dir [file join $out ip]
file mkdir $ip_build_dir
set board au280
set min_pkt_len 64
set max_pkt_len 1518
set num_cmac_port 1
set ip_tcl [file join $shell src cmac_subsystem vivado_ip]
foreach ip {cmac_usplus_0 cmac_subsystem_axi_crossbar} {
    if {[file exists [file join $ip_tcl ${ip}_${board}.tcl]]} {
        source [file join $ip_tcl ${ip}_${board}.tcl]
    } else {
        source [file join $ip_tcl ${ip}.tcl]
    }
}
generate_target all [get_ips]
retried {synth_ip [get_ips]}

# ----------------------------------------------------------- sources
status $out read
set list_file [open [file join $hdl_root rtl.f] r]
foreach line [split [read $list_file] "\n"] {
    set line [string trim $line]
    if {$line eq "" || [string match "#*" $line] || [string match "//*" $line]} {continue}
    read_verilog -sv [file join $hdl_root $line]
}
close $list_file
read_verilog -sv [glob [file join $board_top rtl *.sv]]
read_verilog [file join $shell src open_nic_shell_macros.vh]
foreach name {cmac_subsystem/cmac_subsystem.sv cmac_subsystem/cmac_subsystem_cmac_wrapper.sv
        packet_adapter/packet_adapter.sv packet_adapter/packet_adapter_tx.sv
        packet_adapter/packet_adapter_rx.sv utility/generic_reset.sv
        utility/axi_lite_register.sv utility/axi_lite_slave.sv
        utility/axi_stream_register_slice.sv utility/axi_stream_packet_fifo.sv
        utility/axi_stream_packet_buffer.sv utility/axi_stream_size_counter.sv
        utility/level_trigger_cdc.sv} {
    read_verilog -sv [file join $shell src $name]
}
foreach name {cmac_subsystem/cmac_subsystem_address_map.v
        packet_adapter/packet_adapter_register.v} {
    read_verilog [file join $shell src $name]
}
set_property verilog_define {__synthesis__ __au280__} [current_fileset]
set_property include_dirs [file join $shell src] [current_fileset]
read_xdc -unmanaged [file join $board_top constraints pins.xdc]
read_xdc -unmanaged [file join $board_top constraints timing.xdc]
read_xdc [file join $board_top constraints bitstream.xdc]

# ------------------------------------------------------- synthesis
status $out synth
set arguments [list -top $top -part $part -flatten_hierarchy rebuilt -generic NUM_PORTS=1]
foreach generic $generics {lappend arguments -generic $generic}
retried [list synth_design {*}$arguments]
# The clock crossings of the adapter are bounded in timing.xdc by clock; stop
# if those clocks were not found.
if {[llength [get_clocks -quiet -of_objects [get_nets -quiet cmac_clk*]]] != 1
        || [llength [get_clocks -quiet -of_objects [get_nets -quiet axis_aclk]]] != 1} {
    error "the clocks of the adapter crossing were not found"
}
reports $out post_synth
write_checkpoint -force [file join $out post_synth.dcp]
if {$option(stop) eq "synth"} {status $out terminal; puts U280_BUILD_COMPLETE; exit}

# --------------------------------------------------------- placement
status $out place
opt_design
source [file join $board_top floorplan.tcl]
if {$option(incremental) ne ""} {
    read_checkpoint -incremental [file normalize $option(incremental)] \
        -directive $option(incremental_directive)
}
set core_clock [get_clocks -of_objects [get_nets axis_aclk]]
set_clock_uncertainty -setup $placement_margin $core_clock
place_design -directive ExtraNetDelay_high
phys_opt_design
set_clock_uncertainty -setup 0 $core_clock
reports $out post_place
write_checkpoint -force [file join $out post_place.dcp]
if {$option(stop) eq "place"} {status $out terminal; puts U280_BUILD_COMPLETE; exit}

# ----------------------------------------------------------- routing
status $out route
route_design -directive AggressiveExplore -tns_cleanup
reports $out post_route
phys_opt_design -directive AggressiveExplore
lassign [reports $out post_route_physopt] wns whs
set final [file join $out final]
file mkdir $final
report_route_status -file [file join $final route_status.rpt]
report_methodology -file [file join $final methodology.rpt]
report_cdc -file [file join $final cdc.rpt]
report_drc -file [file join $final drc.rpt]
report_power -file [file join $final power.rpt]
if {$option(incremental) ne ""} {
    report_incremental_reuse -file [file join $final incremental_reuse.rpt]
}
write_checkpoint -force [file join $out routed.dcp]
if {$wns < 0 || $whs < 0} {
    status $out failed
    error "the routed design misses timing: WNS $wns ns, WHS $whs ns"
}
if {$option(stop) eq "route"} {status $out terminal; puts U280_BUILD_COMPLETE; exit}

# --------------------------------------------------------- bitstream
status $out bitstream
report_drc -ruledeck bitstream_checks -file [file join $final bitstream_drc.rpt]
write_bitstream -force [file join $out prism_u280.bit]
status $out terminal
puts U280_BUILD_COMPLETE
exit
