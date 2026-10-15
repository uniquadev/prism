#!/usr/bin/env bash
# Takes the U280 off the PCIe bus before it is loaded with the PRISM design,
# which has no PCIe endpoint, and gets the host interface ready for raw frames.
#
# Usage: sudo prepare_host.sh <interface cabled to the card's port 0>
#
# Without this the host sees the card's link drop when it is programmed; with
# the card's drivers loaded that can be reported as a fatal PCIe error. A
# power cycle of the node brings the card back with the design in its flash.
set -euo pipefail
interface=${1:?usage: prepare_host.sh <interface>}

for driver in xocl xclmgmt; do
    if lsmod | grep -q "^$driver "; then
        echo "unloading $driver"
        modprobe -r "$driver"
    fi
done

found=0
for device in /sys/bus/pci/devices/*; do
    if [ "$(cat "$device/vendor")" = "0x10ee" ]; then
        echo "removing $(basename "$device") ($(cat "$device/device")) from the PCIe bus"
        echo 1 > "$device/remove"
        found=1
    fi
done
[ "$found" = 1 ] || echo "no Xilinx PCIe function present (already removed?)"

# PRISM frames are at most 1514 bytes; the node answers the manager's and the
# ranks' addresses, which are not the interface's own.
ip link set dev "$interface" up
ip link set dev "$interface" promisc on
echo "interface $interface: $(cat "/sys/class/net/$interface/operstate"), speed $(cat "/sys/class/net/$interface/speed" 2>/dev/null || echo unknown) Mb/s"
