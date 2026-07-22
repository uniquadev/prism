create_clock -name axis_aclk -period 4.000 [get_ports axis_aclk]
set_false_path -from [get_ports axis_aresetn]
