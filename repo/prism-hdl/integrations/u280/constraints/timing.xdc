# Clocks and clock crossings of the U280 design. Read as unmanaged Tcl (it has
# loops).

create_clock -period 10.000 -name sysclk [get_ports sysclk_p]

# The packet adapters cross between the 250 MHz clock of the core and the
# clock of each CMAC through asynchronous FIFOs. The crossing paths are bounded
# by one period of the receiving clock, as in the OpenNIC shell.
foreach axis_clock [get_clocks -quiet -of_objects [get_nets -quiet axis_aclk]] {
    foreach cmac_clock [get_clocks -quiet -of_objects [get_nets -quiet cmac_clk*]] {
        set_max_delay -datapath_only -from $axis_clock -to $cmac_clock 4.000
        set_max_delay -datapath_only -from $cmac_clock -to $axis_clock 3.103
    }
}

# The power-on reset leaves the MMCM lock asynchronously and is synchronised.
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *u_clocks/locked_sync_reg[*]/CLR}]
