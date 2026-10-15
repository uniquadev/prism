# Pins of the U280 design. Read as unmanaged Tcl (it has an if).
#
# The lane pins of the QSFP cages follow from the transceiver locations of the
# CMAC IP and are not listed here.

# 100 MHz system clock (SYSCLK3).
set_property -dict {PACKAGE_PIN G31 IOSTANDARD LVDS} [get_ports sysclk_p]
set_property -dict {PACKAGE_PIN F31 IOSTANDARD LVDS} [get_ports sysclk_n]

# 156.25 MHz reference clocks of the QSFP cages.
set_property PACKAGE_PIN T42 [get_ports {qsfp_refclk_p[0]}]
set_property PACKAGE_PIN T43 [get_ports {qsfp_refclk_n[0]}]
if {[llength [get_ports -quiet {qsfp_refclk_p[1]}]] > 0} {
    set_property PACKAGE_PIN P42 [get_ports {qsfp_refclk_p[1]}]
    set_property PACKAGE_PIN P43 [get_ports {qsfp_refclk_n[1]}]
}

# Must be low: with the pin floating the board can shut down for good.
set_property -dict {PACKAGE_PIN D32 IOSTANDARD LVCMOS18 PULLDOWN TRUE} [get_ports hbm_cattrip]
