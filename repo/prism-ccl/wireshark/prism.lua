local prism = Proto("prism_collective", "PRISM Collective Protocol 1.0")

local opcodes = {
  [0x00]="INVALID", [0x01]="CONTROL", [0x02]="COL_DATA",
  [0x03]="COL_RES", [0x04]="COL_PROGRESS"
}

local commands = {
  [0x0000]="INVALID",
  [0x0001]="CAPS_QUERY", [0x0002]="CAPS_RESPONSE",
  [0x0003]="RESOURCE_QUERY", [0x0004]="RESOURCE_RESPONSE",
  [0x0010]="SESSION_OPEN", [0x0011]="SESSION_OPEN_RESPONSE",
  [0x0012]="SESSION_RENEW", [0x0013]="SESSION_RENEW_RESPONSE",
  [0x0014]="SESSION_CLOSE", [0x0015]="SESSION_CLOSE_RESPONSE",
  [0x0100]="GROUP_STAGE", [0x0101]="GROUP_STAGE_RESPONSE",
  [0x0102]="GROUP_COMMIT", [0x0103]="GROUP_COMMIT_RESPONSE",
  [0x0104]="GROUP_ABORT", [0x0105]="GROUP_ABORT_RESPONSE",
  [0x0106]="GROUP_STATUS", [0x0107]="GROUP_STATUS_RESPONSE",
  [0x0108]="GROUP_DESTROY", [0x0109]="GROUP_DESTROY_RESPONSE",
  [0x0200]="OP_PREPARE", [0x0201]="OP_PREPARE_RESPONSE",
  [0x0202]="OP_COMMIT", [0x0203]="OP_COMMIT_RESPONSE",
  [0x0204]="OP_ABORT", [0x0205]="OP_ABORT_RESPONSE",
  [0x0206]="OP_STATUS", [0x0207]="OP_STATUS_RESPONSE",
  [0x0208]="OP_RELEASE", [0x0209]="OP_RELEASE_RESPONSE",
  [0x0300]="OP_COMPLETE_EVENT", [0x0301]="OP_ERROR_EVENT",
  [0x0302]="RESOURCE_PRESSURE_EVENT", [0x0303]="EVENT_ACK"
}

local statuses = {
  [0x00]="OK", [0x01]="UNSUPPORTED_VERSION", [0x02]="UNSUPPORTED_COMMAND",
  [0x03]="UNSUPPORTED_FEATURE", [0x04]="INVALID_REQUEST",
  [0x05]="INVALID_RECORD", [0x06]="INVALID_STATE", [0x07]="AUTH_REQUIRED",
  [0x08]="AUTH_FAILED", [0x09]="STALE_SESSION", [0x0A]="STALE_DEVICE_BOOT_ID",
  [0x0B]="TXN_CONFLICT", [0x0C]="NOT_FOUND", [0x0D]="ALREADY_EXISTS",
  [0x0E]="GENERATION_MISMATCH", [0x0F]="GROUP_BUSY",
  [0x10]="OPERATION_BUSY", [0x11]="NO_GROUP_SLOT", [0x12]="NO_OPERATION_SLOT",
  [0x13]="NO_BITMAP_MEMORY", [0x14]="NO_ACCUMULATOR_RANGE",
  [0x15]="NO_REPLAY_BUFFER", [0x16]="NO_ROUTE_RESOURCE",
  [0x17]="NO_REPLICATION_RESOURCE", [0x18]="UNSUPPORTED_ARITHMETIC_CONFIGURATION",
  [0x19]="BAD_PAYLOAD_LENGTH", [0x1A]="OUT_OF_WINDOW", [0x1B]="RETRY",
  [0x1C]="TIMEOUT", [0x1D]="ABORTED", [0x1E]="INTERNAL_ERROR"
}

local tlv_types = {
  [0x0000]="INVALID", [0x0001]="JOB_ID", [0x0002]="DEVICE_BOOT_ID",
  [0x0003]="SESSION_COOKIE", [0x0004]="LEASE_MS", [0x0005]="LEASE_GRACE_MS",
  [0x0006]="SECURITY_PROFILE", [0x0007]="FEATURE_MASK",
  [0x0008]="PROTOCOL_VERSION_RANGE", [0x0009]="CAPABILITIES",
  [0x000A]="RESOURCE_SNAPSHOT_ID", [0x000B]="RESOURCE_SNAPSHOT",
  [0x000C]="RESOURCE_RESERVATION", [0x000D]="PAYLOAD_DIGEST",
  [0x000E]="ERROR_DETAIL", [0x000F]="RELEASED_RESOURCES",
  [0x0010]="AUTH_DATA", [0x0011]="SESSION_USAGE",
  [0x0100]="GROUP_HANDLE", [0x0101]="GROUP_DESCRIPTOR",
  [0x0102]="CONTRIBUTOR_BINDING", [0x0103]="UPSTREAM_ACTION",
  [0x0104]="REPLICATION_GROUP", [0x0105]="GROUP_STATUS",
  [0x0200]="OPERATION_HANDLE", [0x0201]="OPERATION_DESCRIPTOR",
  [0x0202]="RESULT_ROUTE_RANGE", [0x0203]="GRANTED_RESOURCES",
  [0x0204]="OPERATION_STATUS", [0x0205]="PHASE_BITMAP_SUMMARY",
  [0x0206]="RETRY_POLICY", [0x0300]="EVENT_DETAIL"
}

local capability_keys = {
  [0x0000]="INVALID", [0x0001]="MAX_SESSIONS",
  [0x0002]="MAX_INSTALLED_GROUPS", [0x0003]="MAX_OPERATION_CONTEXTS",
  [0x0004]="MAX_ACTIVE_OPERATIONS_GLOBAL", [0x0005]="MAX_ACTIVE_OPERATIONS_PER_GROUP",
  [0x0006]="MAX_CHUNKS_PER_DIRECT_STREAM", [0x0007]="MAX_BITMAP_BYTES_PER_OPERATION",
  [0x0008]="TOTAL_PHASE_BITMAP_POOL_BYTES",
  [0x0009]="MAX_ACTIVE_ACCUMULATOR_RANGES_GLOBAL",
  [0x000A]="MAX_ACTIVE_ACCUMULATOR_RANGES_PER_OPERATION",
  [0x000B]="TOTAL_REPLAY_OUTPUT_SLOTS", [0x000C]="MAX_LOCAL_CONTRIBUTORS",
  [0x000D]="MAX_REPLICATION_GROUPS", [0x000E]="MAX_RESULT_DESTINATIONS_PER_GROUP",
  [0x000F]="MAX_OPERATION_RESULT_ROUTE_RANGES",
  [0x0010]="MAX_MANAGEMENT_STAGING_BYTES", [0x0011]="MAX_SELECTIVE_ACK_WINDOW",
  [0x0012]="SUPPORTED_COLLECTIVE_SEMANTICS",
  [0x0013]="SUPPORTED_REDUCTION_OPERATORS", [0x0014]="SUPPORTED_INPUT_FORMATS",
  [0x0015]="SUPPORTED_ACCUMULATOR_PROFILES", [0x0016]="SUPPORTED_PARTIAL_FORMATS",
  [0x0017]="SUPPORTED_OUTPUT_FORMATS", [0x0018]="MTU_BYTES",
  [0x0019]="MAX_PRISM_PAYLOAD_BYTES", [0x001A]="SUPPORTED_SECURITY_PROFILES",
  [0x001B]="SUPPORTED_RELIABILITY_FEATURES", [0x001C]="REPLAY_CACHE_DEPTH",
  [0x001D]="REPLAY_CACHE_RETENTION_MS", [0x001E]="ACCUMULATOR_PROFILE_CAPABILITY"
}

local resource_keys = {
  [0x0000]="INVALID", [0x0001]="FREE_GROUP_SLOTS",
  [0x0002]="FREE_OPERATION_CONTEXTS", [0x0003]="FREE_ACTIVE_OPERATION_SLOTS",
  [0x0004]="FREE_PHASE_BITMAP_BYTES", [0x0005]="FREE_ACCUMULATOR_RANGES",
  [0x0006]="FREE_REPLAY_OUTPUT_SLOTS", [0x0007]="FREE_ROUTE_ENTRIES",
  [0x0008]="FREE_REPLICATION_GROUPS", [0x0009]="FREE_REPLICATION_ENTRIES",
  [0x000A]="SESSION_GROUP_USAGE", [0x000B]="SESSION_PREPARED_OPERATION_USAGE",
  [0x000C]="SESSION_ACTIVE_OPERATION_USAGE", [0x000D]="SESSION_BITMAP_USAGE_BYTES",
  [0x000E]="SESSION_ACCUMULATOR_RANGE_USAGE"
}

local allocation_keys = {
  [0x0000]="INVALID", [0x0001]="GROUP_SLOTS", [0x0002]="OPERATION_SLOTS",
  [0x0003]="PHASE_BITMAP_BYTES", [0x0004]="ACCUMULATOR_RANGES",
  [0x0005]="REPLAY_OUTPUT_SLOTS", [0x0006]="ROUTE_ENTRIES",
  [0x0007]="REPLICATION_GROUPS", [0x0008]="REPLICATION_ENTRIES"
}

local security_profiles = {
  [0]="LAB_UNAUTHENTICATED", [1]="EXTERNAL_AUTHENTICATED_CHANNEL",
  [2]="IN_PROTOCOL_AUTHENTICATION"
}
local node_roles = {[0]="INVALID", [1]="LEAF", [2]="INTERNAL", [3]="ROOT", [4]="SINGLE"}
local next_hop_types = {[0]="INVALID", [1]="SWITCH", [2]="RANK"}
local semantics = {[0]="INVALID", [1]="REDUCE", [2]="ALLREDUCE", [3]="REDUCE_SCATTER"}
local operators = {[0]="INVALID", [1]="SUM"}
local wire_formats = {[0]="INVALID", [1]="INT8", [2]="FP16", [3]="BF16", [4]="FP32"}
local accumulator_profiles = {[0]="INVALID", [1]="FP32_ARRIVAL", [2]="FP32_ORDERED", [3]="KULISCH_FP32"}
local reliability_features = {
  [0]="RELIABLE_HOP_BY_HOP", [1]="SELECTIVE_ACK", [2]="RESULT_ACK",
  [3]="LEASED_SESSIONS", [4]="MANAGEMENT_AUTH", [5]="MACSEC_MANAGEMENT_DOMAIN",
  [6]="EXTERNAL_BITMAP_MEMORY"
}
local group_states = {[0]="FREE", [1]="STAGED", [2]="INSTALLED", [3]="DESTROYING"}
local operation_states = {
  [0]="FREE", [1]="PREPARED", [2]="ACTIVE", [3]="COMPLETE",
  [4]="RELEASING", [5]="ABORTED"
}
local progress_peer_kinds = {[0]="INVALID", [1]="CONTRIBUTOR", [2]="RESULT_PATH", [3]="ENDPOINT"}
local progress_reasons = {
  [0]="NONE", [1]="ACCEPTED", [2]="DUPLICATE", [3]="OUT_OF_WINDOW",
  [4]="NO_SLOT", [5]="STALE_GENERATION", [6]="BAD_PAYLOAD",
  [7]="RETRY_LATER", [8]="FATAL_OPERATION"
}

local f_version = ProtoField.uint8("prism.version", "Encoded version", base.HEX)
local f_version_major = ProtoField.uint8("prism.version.major", "Version major", base.DEC)
local f_version_minor = ProtoField.uint8("prism.version.minor", "Version minor", base.DEC)
local f_opcode = ProtoField.uint8("prism.opcode", "Opcode", base.HEX, opcodes)
local f_cookie = ProtoField.uint64("prism.control.session_cookie", "Session cookie", base.HEX)
local f_transaction = ProtoField.uint64("prism.control.transaction_id", "Transaction / Event ID", base.HEX)
local f_command = ProtoField.uint16("prism.control.command", "Command", base.HEX, commands)
local f_flags = ProtoField.uint8("prism.flags", "Flags", base.HEX)
local f_control_request = ProtoField.bool("prism.control.flags.request", "Request", 8, nil, 0x01)
local f_control_response = ProtoField.bool("prism.control.flags.response", "Response", 8, nil, 0x02)
local f_control_event = ProtoField.bool("prism.control.flags.event", "Event", 8, nil, 0x04)
local f_control_ack_required = ProtoField.bool("prism.control.flags.ack_required", "ACK required", 8, nil, 0x08)
local f_control_auth_present = ProtoField.bool("prism.control.flags.auth_present", "Authentication present", 8, nil, 0x10)
local f_accumulation_inexact = ProtoField.bool(
  "prism.flags.accumulation_inexact", "Accumulation inexact", 8, nil, 0x08)
local f_status = ProtoField.uint8("prism.status", "Status", base.HEX, statuses)
local f_fragment_index = ProtoField.uint16("prism.control.fragment_index", "Fragment index", base.DEC)
local f_fragment_count = ProtoField.uint16("prism.control.fragment_count", "Fragment count", base.DEC)

local f_job = ProtoField.uint64("prism.job_id", "Job ID", base.HEX)
local f_group = ProtoField.uint16("prism.group_id", "Group ID", base.DEC)
local f_group_generation = ProtoField.uint16("prism.group_generation", "Group generation", base.DEC)
local f_operation = ProtoField.uint16("prism.operation_id", "Operation ID", base.DEC)
local f_operation_generation = ProtoField.uint32("prism.operation_generation", "Operation generation", base.DEC)
local f_peer = ProtoField.uint16("prism.peer_id", "Contributor / result path", base.DEC)
local f_chunk = ProtoField.uint24("prism.chunk_index", "Chunk index", base.DEC)
local f_payload = ProtoField.bytes("prism.payload", "Payload / undecoded fragment")

local f_tlv_type = ProtoField.uint16("prism.tlv.type", "TLV type", base.HEX, tlv_types)
local f_tlv_flags = ProtoField.uint16("prism.tlv.flags", "TLV flags", base.HEX)
local f_tlv_mandatory = ProtoField.bool("prism.tlv.flags.mandatory", "Mandatory", 16, nil, 0x0001)
local f_tlv_length = ProtoField.uint32("prism.tlv.length", "Value length", base.DEC)
local f_tlv_value = ProtoField.bytes("prism.tlv.value", "Raw value")
local f_tlv_u64 = ProtoField.uint64("prism.tlv.unsigned_value", "Unsigned value", base.DEC)
local f_device_boot = ProtoField.uint64("prism.device_boot_id", "Device boot ID", base.HEX)
local f_lease_ms = ProtoField.uint64("prism.session.lease_ms", "Lease (ms)", base.DEC)
local f_lease_grace_ms = ProtoField.uint64("prism.session.lease_grace_ms", "Lease grace (ms)", base.DEC)
local f_security = ProtoField.uint64("prism.security_profile", "Security profile", base.DEC, security_profiles)
local f_feature_mask = ProtoField.uint64("prism.feature_mask", "Feature mask", base.HEX)
local f_snapshot_id = ProtoField.uint64("prism.resource.snapshot_id", "Resource snapshot ID", base.DEC)
local f_error_detail = ProtoField.string("prism.error_detail", "Error detail")
local f_version_min_major = ProtoField.uint8("prism.version.minimum_major", "Minimum major", base.DEC)
local f_version_min_minor = ProtoField.uint8("prism.version.minimum_minor", "Minimum minor", base.DEC)
local f_version_max_major = ProtoField.uint8("prism.version.maximum_major", "Maximum major", base.DEC)
local f_version_max_minor = ProtoField.uint8("prism.version.maximum_minor", "Maximum minor", base.DEC)

local f_entry_flags = ProtoField.uint16("prism.entry.flags", "Entry flags", base.HEX)
local f_entry_value = ProtoField.uint64("prism.entry.value", "Entry value", base.DEC)
local f_entry_reserved = ProtoField.uint32("prism.entry.reserved", "Reserved", base.HEX)
local f_capability_key = ProtoField.uint16("prism.capability.key", "Capability key", base.HEX, capability_keys)
local f_resource_key = ProtoField.uint16("prism.resource.key", "Resource key", base.HEX, resource_keys)
local f_allocation_key = ProtoField.uint16("prism.allocation.key", "Allocation key", base.HEX, allocation_keys)
local f_profile_state_bits = ProtoField.uint16("prism.capability.accumulator_state_bits", "Accumulator state bits", base.DEC)
local f_profile_max_terms = ProtoField.uint32("prism.capability.maximum_reduction_terms", "Maximum reduction terms", base.DEC)
local f_profile_partial_capable = ProtoField.bool("prism.capability.partial_wire_capable", "Partial-wire capable", 8, nil, 0x01)
local f_supported_semantics = ProtoField.uint64("prism.capability.supported_collective_semantics", "Supported collective semantics", base.HEX)
local f_supported_operators = ProtoField.uint64("prism.capability.supported_reduction_operators", "Supported reduction operators", base.HEX)
local f_supported_input_formats = ProtoField.uint64("prism.capability.supported_input_formats", "Supported input formats", base.HEX)
local f_supported_accumulator_profiles = ProtoField.uint64("prism.capability.supported_accumulator_profiles", "Supported accumulator profiles", base.HEX)
local f_supported_partial_formats = ProtoField.uint64("prism.capability.supported_partial_formats", "Supported partial formats", base.HEX)
local f_supported_output_formats = ProtoField.uint64("prism.capability.supported_output_formats", "Supported output formats", base.HEX)
local f_supported_security_profiles = ProtoField.uint64("prism.capability.supported_security_profiles", "Supported security profiles", base.HEX)
local f_supported_reliability_features = ProtoField.uint64("prism.capability.supported_reliability_features", "Supported reliability features", base.HEX)

local f_node_role = ProtoField.uint8("prism.group.node_role", "Node role", base.DEC, node_roles)
local f_expected_contributors = ProtoField.uint16("prism.group.expected_local_contributors", "Expected local contributors", base.DEC)
local f_contributor_id = ProtoField.uint16("prism.group.contributor_id", "Contributor ID", base.DEC)
local f_ingress_port = ProtoField.uint16("prism.group.ingress_port", "Ingress port", base.DEC)
local f_source_mac = ProtoField.ether("prism.group.source_mac", "Source MAC")
local f_has_parent = ProtoField.bool("prism.group.has_parent", "Has parent", 8, nil, 0x01)
local f_parent_contributor = ProtoField.uint16("prism.group.parent_contributor_id", "Parent contributor ID", base.DEC)
local f_egress_port = ProtoField.uint16("prism.group.egress_port", "Egress port", base.DEC)
local f_parent_mac = ProtoField.ether("prism.group.parent_mac", "Parent MAC")
local f_replication_group = ProtoField.uint16("prism.group.replication_group_id", "Replication group ID", base.DEC)
local f_replication_count = ProtoField.uint16("prism.group.replication_entry_count", "Replication entry count", base.DEC)
local f_result_path = ProtoField.uint16("prism.group.result_path_id", "Result path ID", base.DEC)
local f_next_hop_type = ProtoField.uint8("prism.group.next_hop_type", "Next-hop type", base.DEC, next_hop_types)
local f_destination_mac = ProtoField.ether("prism.group.destination_mac", "Destination MAC")
local f_group_state = ProtoField.uint64("prism.group.state", "Group state", base.DEC, group_states)

local f_semantic = ProtoField.uint8("prism.operation.semantic", "Collective semantic", base.DEC, semantics)
local f_operator = ProtoField.uint8("prism.operation.reduction_operator", "Reduction operator", base.DEC, operators)
local f_input_format = ProtoField.uint8("prism.operation.input_format", "Input format", base.DEC, wire_formats)
local f_accumulator_profile = ProtoField.uint8("prism.operation.accumulator_profile", "Accumulator profile", base.DEC, accumulator_profiles)
local f_partial_format = ProtoField.uint8("prism.operation.partial_format", "Partial format", base.DEC, wire_formats)
local f_output_format = ProtoField.uint8("prism.operation.output_format", "Output format", base.DEC, wire_formats)
local f_result_delivery = ProtoField.bool("prism.operation.result_delivery_role", "Result delivery role", 8, nil, 0x01)
local f_element_count = ProtoField.uint32("prism.operation.element_count", "Element count", base.DEC)
local f_max_terms = ProtoField.uint32("prism.operation.maximum_reduction_terms", "Maximum reduction terms", base.DEC)
local f_timeout_ms = ProtoField.uint32("prism.operation.timeout_ms", "Timeout (ms)", base.DEC)
local f_window_chunks = ProtoField.uint16("prism.operation.requested_window_chunks", "Requested window chunks", base.DEC)
local f_replay_slots = ProtoField.uint16("prism.operation.requested_replay_slots", "Requested replay slots", base.DEC)
local f_route_count = ProtoField.uint16("prism.operation.result_route_count", "Result-route count", base.DEC)
local f_retry_limit = ProtoField.uint16("prism.operation.retry_limit", "Retry limit", base.DEC)
local f_route_first = ProtoField.uint24("prism.operation.route.first_chunk", "First result chunk", base.DEC)
local f_route_last = ProtoField.uint24("prism.operation.route.last_chunk", "Last result chunk", base.DEC)
local f_operation_state = ProtoField.uint64("prism.operation.state", "Operation state", base.DEC, operation_states)

local f_peer_kind = ProtoField.uint8("prism.progress.peer_kind", "Peer kind", base.DEC, progress_peer_kinds)
local f_progress_window_base = ProtoField.uint24("prism.progress.window_base", "Window base", base.DEC)
local f_progress_window_chunks = ProtoField.uint16("prism.progress.window_chunks", "Admitted window chunks", base.DEC)
local f_ack_base = ProtoField.uint24("prism.progress.ack_base", "Selective ACK base", base.DEC)
local f_ack_bits = ProtoField.uint16("prism.progress.ack_bits", "Selective ACK bits", base.DEC)
local f_reason = ProtoField.uint8("prism.progress.reason", "Reason", base.HEX, progress_reasons)
local f_retry = ProtoField.uint32("prism.progress.retry_delay_us", "Retry delay (us)", base.DEC)

prism.fields = {
  f_version, f_version_major, f_version_minor, f_opcode, f_cookie, f_transaction,
  f_command, f_flags, f_control_request, f_control_response, f_control_event,
  f_control_ack_required, f_control_auth_present, f_accumulation_inexact, f_status,
  f_fragment_index, f_fragment_count, f_job, f_group, f_group_generation,
  f_operation, f_operation_generation, f_peer, f_chunk, f_payload, f_tlv_type,
  f_tlv_flags, f_tlv_mandatory, f_tlv_length, f_tlv_value, f_tlv_u64,
  f_device_boot, f_lease_ms, f_lease_grace_ms, f_security, f_feature_mask,
  f_snapshot_id, f_error_detail, f_version_min_major, f_version_min_minor,
  f_version_max_major, f_version_max_minor, f_entry_flags, f_entry_value,
  f_entry_reserved, f_capability_key, f_resource_key, f_allocation_key,
  f_profile_state_bits, f_profile_max_terms, f_profile_partial_capable,
  f_supported_semantics, f_supported_operators,
  f_supported_input_formats, f_supported_accumulator_profiles,
  f_supported_partial_formats, f_supported_output_formats,
  f_supported_security_profiles, f_supported_reliability_features,
  f_node_role, f_expected_contributors, f_contributor_id, f_ingress_port,
  f_source_mac, f_has_parent, f_parent_contributor, f_egress_port, f_parent_mac,
  f_replication_group, f_replication_count, f_result_path, f_next_hop_type,
  f_destination_mac, f_group_state, f_semantic, f_operator, f_input_format,
  f_accumulator_profile, f_partial_format, f_output_format, f_result_delivery,
  f_element_count, f_max_terms, f_timeout_ms, f_window_chunks, f_replay_slots,
  f_route_count, f_retry_limit, f_route_first, f_route_last, f_operation_state,
  f_peer_kind, f_progress_window_base, f_progress_window_chunks, f_ack_base,
  f_ack_bits, f_reason, f_retry
}

local function add_identity(tree, buffer, offset)
  tree:add(f_job, buffer(offset, 8)); offset = offset + 8
  tree:add(f_group, buffer(offset, 2)); offset = offset + 2
  tree:add(f_group_generation, buffer(offset, 2)); offset = offset + 2
  tree:add(f_operation, buffer(offset, 2)); offset = offset + 2
  tree:add(f_operation_generation, buffer(offset, 4)); offset = offset + 4
  return offset
end

local function add_reserved_warning(tree, range, label)
  if range:uint() ~= 0 then
    tree:add_expert_info(PI_MALFORMED, PI_ERROR, "Non-zero reserved " .. label)
  end
end

local function mask_names(range, names, include_zero)
  local supported = {}
  for value, name in pairs(names) do
    if (include_zero or value > 0) and value < 64 then
      local byte_index = 7 - math.floor(value / 8)
      local bit_value = 2 ^ (value % 8)
      if math.floor(range(byte_index, 1):uint() / bit_value) % 2 == 1 then
        table.insert(supported, name)
      end
    end
  end
  table.sort(supported)
  if #supported == 0 then return "none" end
  return table.concat(supported, ", ")
end

local function add_named_mask(entry, range, field, names, include_zero)
  entry:add(field, range):append_text(
    " (" .. mask_names(range, names, include_zero or false) .. ")")
end

local function dissect_entry_vector(tree, buffer, offset, length, key_field, vector_name)
  if length % 16 ~= 0 then
    tree:add_expert_info(PI_MALFORMED, PI_ERROR, vector_name .. " length is not a multiple of 16")
    tree:add(f_tlv_value, buffer(offset, length))
    return
  end
  local finish = offset + length
  while offset < finish do
    local key = buffer(offset, 2):uint()
    local key_name = "UNKNOWN"
    if key_field == f_capability_key then key_name = capability_keys[key] or key_name end
    if key_field == f_resource_key then key_name = resource_keys[key] or key_name end
    if key_field == f_allocation_key then key_name = allocation_keys[key] or key_name end
    local entry = tree:add(prism, buffer(offset, 16), vector_name .. ": " .. key_name)
    entry:add(key_field, buffer(offset, 2))
    entry:add(f_entry_flags, buffer(offset + 2, 2))
    entry:add(f_entry_value, buffer(offset + 4, 8))
    entry:add(f_entry_reserved, buffer(offset + 12, 4))
    add_reserved_warning(entry, buffer(offset + 2, 2), "entry flags")
    add_reserved_warning(entry, buffer(offset + 12, 4), "entry field")
    if key_field == f_capability_key and key == 0x0012 then
      add_named_mask(entry, buffer(offset + 4, 8), f_supported_semantics, semantics)
    elseif key_field == f_capability_key and key == 0x0013 then
      add_named_mask(entry, buffer(offset + 4, 8), f_supported_operators, operators)
    elseif key_field == f_capability_key and key == 0x0014 then
      add_named_mask(entry, buffer(offset + 4, 8), f_supported_input_formats, wire_formats)
    elseif key_field == f_capability_key and key == 0x0015 then
      add_named_mask(entry, buffer(offset + 4, 8), f_supported_accumulator_profiles, accumulator_profiles)
    elseif key_field == f_capability_key and key == 0x0016 then
      add_named_mask(entry, buffer(offset + 4, 8), f_supported_partial_formats, wire_formats)
    elseif key_field == f_capability_key and key == 0x0017 then
      add_named_mask(entry, buffer(offset + 4, 8), f_supported_output_formats, wire_formats)
    elseif key_field == f_capability_key and key == 0x001A then
      add_named_mask(
        entry, buffer(offset + 4, 8), f_supported_security_profiles, security_profiles, true)
    elseif key_field == f_capability_key and key == 0x001B then
      add_named_mask(
        entry, buffer(offset + 4, 8), f_supported_reliability_features, reliability_features, true)
    elseif key_field == f_capability_key and key == 0x001E then
      entry:add(f_accumulator_profile, buffer(offset + 4, 1))
      entry:add(f_profile_state_bits, buffer(offset + 5, 2))
      entry:add(f_profile_max_terms, buffer(offset + 7, 4))
      entry:add(f_profile_partial_capable, buffer(offset + 11, 1))
    end
    offset = offset + 16
  end
end


local function dissect_tlv_value(item, buffer, offset, length, type_value)
  if type_value == 0x0001 and length == 8 then
    item:add(f_job, buffer(offset, 8))
  elseif type_value == 0x0002 and length == 8 then
    item:add(f_device_boot, buffer(offset, 8))
  elseif type_value == 0x0003 and length == 8 then
    item:add(f_cookie, buffer(offset, 8))
  elseif type_value == 0x0004 and length == 8 then
    item:add(f_lease_ms, buffer(offset, 8))
  elseif type_value == 0x0005 and length == 8 then
    item:add(f_lease_grace_ms, buffer(offset, 8))
  elseif type_value == 0x0006 and length == 8 then
    item:add(f_security, buffer(offset, 8))
  elseif type_value == 0x0007 and length == 8 then
    item:add(f_feature_mask, buffer(offset, 8))
  elseif type_value == 0x0008 and length == 8 then
    item:add(f_version_min_major, buffer(offset, 1))
    item:add(f_version_min_minor, buffer(offset + 1, 1))
    item:add(f_version_max_major, buffer(offset + 2, 1))
    item:add(f_version_max_minor, buffer(offset + 3, 1))
    add_reserved_warning(item, buffer(offset + 4, 4), "version-range field")
  elseif type_value == 0x0009 then
    dissect_entry_vector(item, buffer, offset, length, f_capability_key, "Capability")
  elseif type_value == 0x000A and length == 8 then
    item:add(f_snapshot_id, buffer(offset, 8))
  elseif type_value == 0x000B or type_value == 0x0011 then
    dissect_entry_vector(item, buffer, offset, length, f_resource_key, "Resource")
  elseif type_value == 0x000C or type_value == 0x000F or type_value == 0x0203 then
    dissect_entry_vector(item, buffer, offset, length, f_allocation_key, "Allocation")
  elseif type_value == 0x000E then
    item:add(f_error_detail, buffer(offset, length))
  elseif type_value == 0x0100 and length == 4 then
    item:add(f_group, buffer(offset, 2))
    item:add(f_group_generation, buffer(offset + 2, 2))
  elseif type_value == 0x0101 and length == 8 then
    item:add(f_node_role, buffer(offset, 1))
    add_reserved_warning(item, buffer(offset + 1, 1), "group-descriptor flags")
    item:add(f_expected_contributors, buffer(offset + 2, 2))
    add_reserved_warning(item, buffer(offset + 4, 4), "group-descriptor field")
  elseif type_value == 0x0102 and length == 12 then
    item:add(f_contributor_id, buffer(offset, 2))
    item:add(f_ingress_port, buffer(offset + 2, 2))
    item:add(f_source_mac, buffer(offset + 4, 6))
    add_reserved_warning(item, buffer(offset + 10, 2), "contributor-binding field")
  elseif type_value == 0x0103 and length == 16 then
    item:add(f_has_parent, buffer(offset, 1))
    add_reserved_warning(item, buffer(offset + 1, 1), "upstream-action field")
    item:add(f_parent_contributor, buffer(offset + 2, 2))
    item:add(f_egress_port, buffer(offset + 4, 2))
    item:add(f_parent_mac, buffer(offset + 6, 6))
    add_reserved_warning(item, buffer(offset + 12, 4), "upstream-action field")
  elseif type_value == 0x0104 and length >= 8 then
    local count = buffer(offset + 2, 2):uint()
    item:add(f_replication_group, buffer(offset, 2))
    item:add(f_replication_count, buffer(offset + 2, 2))
    add_reserved_warning(item, buffer(offset + 4, 4), "replication-group field")
    if count == 0 or length ~= 8 + count * 12 then
      item:add_expert_info(PI_MALFORMED, PI_ERROR, "Invalid replication-group entry count")
    else
      local cursor = offset + 8
      for index = 1, count do
        local entry = item:add(prism, buffer(cursor, 12), "Result destination " .. index)
        entry:add(f_result_path, buffer(cursor, 2))
        entry:add(f_egress_port, buffer(cursor + 2, 2))
        entry:add(f_next_hop_type, buffer(cursor + 4, 1))
        add_reserved_warning(entry, buffer(cursor + 5, 1), "next-hop flags")
        entry:add(f_destination_mac, buffer(cursor + 6, 6))
        cursor = cursor + 12
      end
    end
  elseif type_value == 0x0105 and length == 8 then
    item:add(f_group_state, buffer(offset, 8))
  elseif type_value == 0x0200 and length == 6 then
    item:add(f_operation, buffer(offset, 2))
    item:add(f_operation_generation, buffer(offset + 2, 4))
  elseif type_value == 0x0201 and length == 32 then
    item:add(f_semantic, buffer(offset, 1))
    item:add(f_operator, buffer(offset + 1, 1))
    item:add(f_input_format, buffer(offset + 2, 1))
    item:add(f_accumulator_profile, buffer(offset + 3, 1))
    item:add(f_partial_format, buffer(offset + 4, 1))
    item:add(f_output_format, buffer(offset + 5, 1))
    item:add(f_result_delivery, buffer(offset + 6, 1))
    add_reserved_warning(item, buffer(offset + 7, 1), "operation-descriptor field")
    item:add(f_element_count, buffer(offset + 8, 4))
    item:add(f_max_terms, buffer(offset + 12, 4))
    item:add(f_timeout_ms, buffer(offset + 16, 4))
    item:add(f_window_chunks, buffer(offset + 20, 2))
    item:add(f_replay_slots, buffer(offset + 22, 2))
    item:add(f_route_count, buffer(offset + 24, 2))
    item:add(f_retry_limit, buffer(offset + 26, 2))
    add_reserved_warning(item, buffer(offset + 28, 4), "operation-descriptor field")
  elseif type_value == 0x0202 and length == 8 then
    item:add(f_route_first, buffer(offset, 3))
    item:add(f_route_last, buffer(offset + 3, 3))
    item:add(f_replication_group, buffer(offset + 6, 2))
  elseif type_value == 0x0204 and length == 8 then
    item:add(f_operation_state, buffer(offset, 8))
  else
    item:add(f_tlv_value, buffer(offset, length))
    if length == 8 then item:add(f_tlv_u64, buffer(offset, 8)) end
  end
end

local function dissect_tlvs(tree, buffer, offset)
  while offset < buffer:len() do
    if offset + 8 > buffer:len() then
      tree:add_expert_info(PI_MALFORMED, PI_ERROR, "Truncated TLV header")
      tree:add(f_payload, buffer(offset))
      return
    end
    local type_value = buffer(offset, 2):uint()
    local flags = buffer(offset + 2, 2):uint()
    local length = buffer(offset + 4, 4):uint()
    local padded = math.floor((length + 7) / 8) * 8
    if offset + 8 + padded > buffer:len() then
      tree:add_expert_info(PI_MALFORMED, PI_ERROR, "Truncated TLV value")
      tree:add(f_payload, buffer(offset))
      return
    end
    local name = tlv_types[type_value]
    if name == nil and flags % 2 == 1 then
      name = string.format("UNKNOWN_MANDATORY_0x%04X", type_value)
    elseif name == nil then
      name = string.format("UNKNOWN_OPTIONAL_0x%04X (ignored)", type_value)
    end
    local item = tree:add(prism, buffer(offset, 8 + padded),
      string.format("TLV: %s (%d value bytes)", name, length))
    item:add(f_tlv_type, buffer(offset, 2))
    item:add(f_tlv_flags, buffer(offset + 2, 2))
    item:add(f_tlv_mandatory, buffer(offset + 2, 2))
    item:add(f_tlv_length, buffer(offset + 4, 4))
    if flags > 1 then item:add_expert_info(PI_MALFORMED, PI_ERROR, "Unknown TLV flag bits") end
    if tlv_types[type_value] == nil and flags % 2 == 1 then
      item:add_expert_info(PI_MALFORMED, PI_ERROR, "Unknown mandatory TLV")
    end
    if length > 0 then dissect_tlv_value(item, buffer, offset + 8, length, type_value) end
    if padded > length then
      local padding = buffer(offset + 8 + length, padded - length)
      local nonzero = false
      for index = 0, padding:len() - 1 do
        if padding(index, 1):uint() ~= 0 then nonzero = true end
      end
      if nonzero then item:add_expert_info(PI_MALFORMED, PI_ERROR, "Non-zero TLV padding") end
    end
    offset = offset + 8 + padded
  end
end

function prism.dissector(buffer, pinfo, tree)
  if buffer:len() < 2 then return 0 end
  pinfo.cols.protocol = "PRISM"
  local root = tree:add(prism, buffer())
  local encoded_version = buffer(0, 1):uint()
  root:add(f_version, buffer(0, 1))
  root:add(f_version_major, buffer(0, 1), math.floor(encoded_version / 16))
  root:add(f_version_minor, buffer(0, 1), encoded_version % 16)
  root:add(f_opcode, buffer(1, 1))
  local opcode = buffer(1, 1):uint()
  local offset = 2

  if opcode == 0x01 and buffer:len() >= 26 then
    root:add(f_cookie, buffer(offset, 8)); offset = offset + 8
    local transaction = buffer(offset, 8):uint64()
    root:add(f_transaction, buffer(offset, 8)); offset = offset + 8
    local command = buffer(offset, 2):uint()
    root:add(f_command, buffer(offset, 2)); offset = offset + 2
    root:add(f_flags, buffer(offset, 1))
    root:add(f_control_request, buffer(offset, 1))
    root:add(f_control_response, buffer(offset, 1))
    root:add(f_control_event, buffer(offset, 1))
    root:add(f_control_ack_required, buffer(offset, 1))
    root:add(f_control_auth_present, buffer(offset, 1)); offset = offset + 1
    root:add(f_status, buffer(offset, 1)); offset = offset + 1
    local fragment_index = buffer(offset, 2):uint()
    root:add(f_fragment_index, buffer(offset, 2)); offset = offset + 2
    local fragment_count = buffer(offset, 2):uint()
    root:add(f_fragment_count, buffer(offset, 2)); offset = offset + 2
    local command_name = commands[command] or string.format("UNKNOWN_CONTROL_0x%04X", command)
    pinfo.cols.info:set(string.format("%s  txn=%s", command_name, tostring(transaction)))
    if fragment_count == 1 and fragment_index == 0 then
      dissect_tlvs(root, buffer, offset)
    else
      if offset < buffer:len() then root:add(f_payload, buffer(offset)) end
      pinfo.cols.info:append(string.format("  fragment=%d/%d (TLVs require reassembly)",
        fragment_index + 1, fragment_count))
    end
  elseif (opcode == 0x02 or opcode == 0x03) and buffer:len() >= 26 then
    local identity_offset = offset
    offset = add_identity(root, buffer, offset)
    root:add(f_peer, buffer(offset, 2)); offset = offset + 2
    local chunk = buffer(offset, 3):uint()
    root:add(f_chunk, buffer(offset, 3)); offset = offset + 3
    root:add(f_flags, buffer(offset, 1))
    root:add(f_accumulation_inexact, buffer(offset, 1)); offset = offset + 1
    if offset < buffer:len() then root:add(f_payload, buffer(offset)) end
    pinfo.cols.info:set(string.format("%s  group=%d/%d op=%d/%d peer=%d chunk=%d",
      opcodes[opcode], buffer(identity_offset + 8, 2):uint(),
      buffer(identity_offset + 10, 2):uint(), buffer(identity_offset + 12, 2):uint(),
      buffer(identity_offset + 14, 4):uint(), buffer(identity_offset + 18, 2):uint(), chunk))
  elseif opcode == 0x04 and buffer:len() >= 42 then
    local identity_offset = offset
    offset = add_identity(root, buffer, offset)
    root:add(f_peer, buffer(offset, 2)); offset = offset + 2
    root:add(f_peer_kind, buffer(offset, 1)); offset = offset + 1
    root:add(f_flags, buffer(offset, 1)); offset = offset + 1
    root:add(f_progress_window_base, buffer(offset, 3)); offset = offset + 3
    root:add(f_progress_window_chunks, buffer(offset, 2)); offset = offset + 2
    root:add(f_ack_base, buffer(offset, 3)); offset = offset + 3
    root:add(f_ack_bits, buffer(offset, 2)); offset = offset + 2
    root:add(f_status, buffer(offset, 1)); offset = offset + 1
    local reason = buffer(offset, 1):uint()
    root:add(f_reason, buffer(offset, 1)); offset = offset + 1
    root:add(f_retry, buffer(offset, 4)); offset = offset + 6
    if offset < buffer:len() then root:add(f_payload, buffer(offset)) end
    pinfo.cols.info:set(string.format("COL_PROGRESS  group=%d/%d op=%d/%d reason=%s",
      buffer(identity_offset + 8, 2):uint(), buffer(identity_offset + 10, 2):uint(),
      buffer(identity_offset + 12, 2):uint(), buffer(identity_offset + 14, 4):uint(),
      progress_reasons[reason] or string.format("0x%02X", reason)))
  else
    root:add_expert_info(PI_MALFORMED, PI_ERROR, "Truncated or unknown PRISM opcode")
    pinfo.cols.info:set("Malformed or unknown PRISM packet")
  end
  return buffer:len()
end

DissectorTable.get("ethertype"):add(0x88B5, prism)
