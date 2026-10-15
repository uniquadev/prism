# Floorplan of the U280 board top: the core over two SLRs, its front in SLR1
# and its back in SLR2, where the CMAC sits, so both ends of the core are
# next to the MAC.
#
# Front (SLR1): the ingress without the rounding lanes, the lane classifiers
# and the reader up to its alignment step.
# Back (SLR2): the rounding lanes with their queue, the reader's last register
# and output queue, the streamer, the native egress and the output buffers.
# The entry of the rounding (first tile register, count of the queue places)
# stays in the front, next to the bank memories and to the handshake that reads
# them.
set single u_core/u_single
set egress $single/u_exact_result_egress
set rounding $single/u_ingress/u_fast_round

create_pblock pb_front
resize_pblock pb_front -add {SLR1}
create_pblock pb_back
resize_pblock pb_back -add {SLR2}

add_cells_to_pblock pb_front [get_cells [list $single/u_ingress $egress/u_auto_classify $egress/u_splitter]]
set back_cells [get_cells [list $egress/u_streamer $egress/u_splitter/u_queue \
    $single/u_result_egress $single/u_result_tile_buffer $single/u_native_output \
    $single/u_exact_output $rounding]]
set crossing [get_cells -hierarchical -filter "NAME =~ $egress/u_splitter/crossing_*"]
# The copy of the egress state that chooses the output, the reset register of
# the streamer, its copy of the operation context (stream_*) and the release
# register of the output lie with the streamer.
set output_state [get_cells -quiet -hierarchical -filter "NAME =~ $egress/output_state_reg* || NAME =~ $egress/stream_*_reg* || NAME =~ $single/output_releasing_reg*"]
add_cells_to_pblock pb_back $back_cells
add_cells_to_pblock pb_back $crossing
if {[llength $output_state] > 0} {add_cells_to_pblock pb_back $output_state}
add_cells_to_pblock pb_front [get_cells $rounding/u_entry]
puts "U280_FLOORPLAN front=[llength [get_cells -of_objects [get_pblocks pb_front]]] back=[llength $back_cells] crossing_registers=[llength $crossing] output_state=[llength $output_state]"
