set rtl_root [file normalize [file join [file dirname [info script]] .. ..]]
set output_root [file normalize [file join $rtl_root .. .. .. build vivado]]
file mkdir $output_root
create_project prism_collective $output_root -part xcvu9p-flga2104-2L-e -force
set manifest [open [file join $rtl_root rtl.f] r]
while {[gets $manifest source_file] >= 0} {
  set source_file [string trim $source_file]
  if {$source_file ne ""} {
    read_verilog -sv [file join $rtl_root $source_file]
  }
}
close $manifest
read_xdc [file join $rtl_root integrations vivado prism_250mhz.xdc]
set_property top prism_vivado_top [current_fileset]
update_compile_order -fileset sources_1
synth_design -top prism_vivado_top -part xcvu9p-flga2104-2L-e
report_timing_summary -file [file join $output_root timing_summary.rpt]
report_utilization -file [file join $output_root utilization.rpt]
