# PRISM OpenNIC 250 MHz plugin source loader.
set plugin_root [file normalize [file dirname [info script]]]
set rtl_root [file normalize [file join $plugin_root .. ..]]
set manifest [open [file join $rtl_root rtl.f] r]
while {[gets $manifest source_file] >= 0} {
  set source_file [string trim $source_file]
  if {$source_file ne ""} {
    read_verilog -quiet -sv [file join $rtl_root $source_file]
  }
}
close $manifest
