**Ethernet Parser (eth_parser)**

- **Description**: Combinational extractor for the Ethernet header. It returns destination/source MAC addresses, EtherType, and a validity flag. Used as a fast pre-filter for reduction traffic.
- **Type**: Combinational
- **Location**: repo/rtl/src/components/eth_parser.sv

- **Inputs**:
	- `frame` : packed frame bytes.
	- `frame_len` : `uint16` — reconstructed frame length in bytes.

- **Outputs**:
	- `dst_mac` : `uint48` — destination MAC from Ethernet header.
	- `src_mac` : `uint48` — source MAC.
	- `ethertype` : `uint16`.
	- `is_reduction_ethertype` : `logic` — asserted if `ethertype == ETHERTYPE_REDUCTION`.
	- `valid_eth_frame` : `logic` — true when `frame_len >= ETH_HDR_BYTES`.

- **Usage**:
	- Instantiated by `mini_sharp_switch_core` as a first-stage filter; if `is_reduction_ethertype` is false the switch typically bypasses the Mini-Sharp parser and forwards the frame.
