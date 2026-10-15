local prism = Proto("prism_collective", "PRISM NumberGroup Protocol 2.0")

local opcodes = {[1]="CONTROL", [2]="DATA", [3]="RESULT", [4]="PROGRESS"}
local commands = {
  [1]="STAGE", [2]="COMMIT", [3]="COMPLETE", [4]="RELEASE",
  [5]="ACK", [6]="ABORT", [7]="CAPS_QUERY", [8]="CAPS_RESPONSE"
}
local formats = {[1]="INT8", [2]="FP16", [3]="BF16", [4]="FP32", [128]="KULISCH"}
local roles = {[1]="SINGLE", [2]="LEAF", [3]="INTERNAL", [4]="ROOT"}
local control_statuses = {
  [0]="OK", [1]="INVALID", [2]="UNSUPPORTED", [3]="NO_RESOURCE",
  [4]="BAD_STATE", [5]="STALE_GENERATION", [6]="TRANSACTION_CONFLICT",
  [7]="BINDING_INVALID"
}
local statuses = {
  [0]="ACCEPTED", [1]="DUPLICATE", [2]="RETRY",
  [3]="OUT_OF_WINDOW", [4]="REJECTED"
}

local f = {
  version = ProtoField.uint8("prism.version", "Version", base.HEX),
  opcode = ProtoField.uint8("prism.opcode", "Packet class", base.HEX, opcodes),
  job = ProtoField.uint64("prism.job_id", "Job ID", base.DEC),
  group = ProtoField.uint16("prism.group_id", "Group ID", base.DEC),
  group_generation = ProtoField.uint16("prism.group_generation", "Group generation", base.DEC),
  operation = ProtoField.uint16("prism.operation_id", "Operation ID", base.DEC),
  operation_generation = ProtoField.uint32("prism.operation_generation", "Operation generation", base.DEC),
  source_endpoint = ProtoField.uint16("prism.source_endpoint", "Source endpoint", base.DEC),
  destination_endpoint = ProtoField.uint16("prism.destination_endpoint", "Destination endpoint", base.DEC),
  packet_id = ProtoField.uint32("prism.packet_id", "Packet ID", base.DEC),
  first_element = ProtoField.uint32("prism.first_element", "First global element", base.DEC),
  element_count = ProtoField.uint16("prism.element_count", "Element count", base.DEC),
  group_count = ProtoField.uint8("prism.group_count", "NumberGroup count", base.DEC),
  flags = ProtoField.uint8("prism.flags", "Flags", base.HEX),
  last = ProtoField.bool("prism.flags.last", "LAST", 8, nil, 0x01),
  accumulation_inexact = ProtoField.bool("prism.flags.accumulation_inexact",
    "ACCUMULATION_INEXACT", 8, nil, 0x02),
  body_bytes = ProtoField.uint16("prism.body_bytes", "Body bytes", base.DEC),
  stream_id = ProtoField.uint16("prism.stream_id", "Contributor/result path ID", base.DEC),
  group_format = ProtoField.uint8("prism.group.format", "Concrete format", base.HEX, formats),
  group_flags = ProtoField.uint8("prism.group.flags", "Group flags", base.HEX),
  group_elements = ProtoField.uint16("prism.group.elements", "Group elements", base.DEC),
  group_values = ProtoField.bytes("prism.group.values", "NumberGroup value bytes"),
  group_padding = ProtoField.bytes("prism.group.padding", "Zero alignment padding"),
  transaction = ProtoField.uint32("prism.transaction_id", "Transaction ID", base.DEC),
  command = ProtoField.uint8("prism.command", "Control command", base.HEX, commands),
  control_status = ProtoField.uint8("prism.control_status", "Control status", base.DEC, control_statuses),
  fragment_index = ProtoField.uint8("prism.fragment_index", "Fragment index", base.DEC),
  fragment_count = ProtoField.uint8("prism.fragment_count", "Fragment count", base.DEC),
  context_role = ProtoField.uint8("prism.context.role", "Context role", base.HEX, roles),
  context_parent = ProtoField.uint16("prism.context.parent", "Parent endpoint", base.DEC),
  manager_mac = ProtoField.ether("prism.context.manager_mac", "Manager MAC"),
  manager_port = ProtoField.uint16("prism.context.manager_port", "Manager ingress port", base.DEC),
  maximum_terms = ProtoField.uint32("prism.context.maximum_terms", "Maximum original terms", base.DEC),
  rank_formats = ProtoField.uint8("prism.context.rank_formats", "Rank format mask", base.HEX),
  binding_local = ProtoField.uint16("prism.binding.local_endpoint", "Local endpoint", base.DEC),
  binding_peer = ProtoField.uint16("prism.binding.peer_endpoint", "Peer endpoint", base.DEC),
  binding_port = ProtoField.uint16("prism.binding.local_port", "Local physical port", base.DEC),
  binding_kind = ProtoField.uint8("prism.binding.peer_kind", "Peer kind", base.DEC),
  binding_flags = ProtoField.uint8("prism.binding.flags", "Result enabled", base.HEX),
  binding_mac = ProtoField.ether("prism.binding.peer_mac", "Peer MAC"),
  binding_rank = ProtoField.uint16("prism.binding.rank_id", "Rank ID", base.DEC),
  binding_terms = ProtoField.uint32("prism.binding.original_terms", "Subtree original terms", base.DEC),
  binding_formats = ProtoField.uint8("prism.binding.formats", "Allowed format mask", base.HEX),
  kulisch_bits = ProtoField.uint16("prism.context.kulisch_bits", "Kulisch signed width", base.DEC),
  progress_status = ProtoField.uint8("prism.progress.status", "Progress status", base.HEX, statuses),
  cumulative = ProtoField.uint32("prism.progress.cumulative_element", "Committed element watermark", base.DEC),
  credit_intervals = ProtoField.uint16("prism.progress.credit_intervals", "Free interval credits", base.DEC),
  credit_bytes = ProtoField.uint32("prism.progress.credit_bytes", "Free byte credits", base.DEC),
  hole_count = ProtoField.uint16("prism.progress.hole_count", "Selective hole count", base.DEC),
  hole_first = ProtoField.uint32("prism.progress.hole_first", "Hole first element", base.DEC),
  hole_end = ProtoField.uint32("prism.progress.hole_end", "Hole exclusive end", base.DEC),
  unknown = ProtoField.bytes("prism.unknown", "Unparsed bytes")
}
prism.fields = f
prism.prefs.kulisch_bits = Pref.uint("Fallback Kulisch width", 279,
  "Used only when a matching STAGE was not observed in this capture")

local widths = {}

local function key(buffer)
  return tostring(buffer(2,8):uint64()) .. ":" .. buffer(10,2):uint() .. ":" ..
    buffer(12,2):uint() .. ":" .. buffer(14,2):uint() .. ":" .. buffer(16,4):uint()
end

local function add_common(tree, buffer)
  tree:add(f.job, buffer(2,8))
  tree:add(f.group, buffer(10,2))
  tree:add(f.group_generation, buffer(12,2))
  tree:add(f.operation, buffer(14,2))
  tree:add(f.operation_generation, buffer(16,4))
end

function prism.dissector(buffer, pinfo, tree)
  if buffer:len() < 2 then return end
  local root = tree:add(prism, buffer())
  root:add(f.version, buffer(0,1))
  root:add(f.opcode, buffer(1,1))
  if buffer(0,1):uint() ~= 0x20 then
    pinfo.cols.info = "Unsupported PRISM version"
    return
  end
  local opcode = buffer(1,1):uint()
  pinfo.cols.protocol = "PRISM"
  if opcode == 2 or opcode == 3 then
    if buffer:len() < 42 then return end
    add_common(root, buffer)
    root:add(f.source_endpoint, buffer(20,2))
    root:add(f.destination_endpoint, buffer(22,2))
    root:add(f.packet_id, buffer(24,4))
    root:add(f.first_element, buffer(28,4))
    root:add(f.element_count, buffer(32,2))
    root:add(f.group_count, buffer(34,1))
    root:add(f.flags, buffer(35,1))
    root:add(f.last, buffer(35,1))
    root:add(f.accumulation_inexact, buffer(35,1))
    root:add(f.body_bytes, buffer(36,2))
    root:add(f.stream_id, buffer(38,2))
    local groups = buffer(34,1):uint()
    local body_end = 42 + buffer(36,2):uint()
    if body_end > buffer:len() then return end
    local offset = 42
    local bits = widths[key(buffer)] or prism.prefs.kulisch_bits
    for _ = 1, groups do
      if offset + 4 > body_end then return end
      local format = buffer(offset,1):uint()
      local count = buffer(offset+2,2):uint()
      local width = ({[1]=1, [2]=2, [3]=2, [4]=4})[format]
      if format == 128 then width = 1 + math.floor((bits+7)/8) end
      if width == nil then return end
      local value_bytes = count * width
      local padding = (4 - value_bytes % 4) % 4
      if offset + 4 + value_bytes + padding > body_end then return end
      local group_tree = root:add(buffer(offset,4+value_bytes+padding),
        "NumberGroup " .. (formats[format] or "UNKNOWN") .. " × " .. count)
      group_tree:add(f.group_format, buffer(offset,1))
      group_tree:add(f.group_flags, buffer(offset+1,1))
      group_tree:add(f.group_elements, buffer(offset+2,2))
      if value_bytes > 0 then group_tree:add(f.group_values, buffer(offset+4,value_bytes)) end
      if padding > 0 then group_tree:add(f.group_padding, buffer(offset+4+value_bytes,padding)) end
      offset = offset + 4 + value_bytes + padding
    end
    if offset < body_end then root:add(f.unknown, buffer(offset,body_end-offset)) end
    local info = (opcodes[opcode] or "UNKNOWN") .. " packet=" ..
      buffer(24,4):uint() .. " first=" .. buffer(28,4):uint() ..
      " count=" .. buffer(32,2):uint() .. " groups=" .. groups
    if buffer(35,1):uint() % 4 >= 2 then
      info = info .. " ACCUMULATION_INEXACT"
    end
    pinfo.cols.info = info
  elseif opcode == 1 then
    if buffer:len() < 34 then return end
    add_common(root, buffer)
    root:add(f.transaction, buffer(20,4))
    root:add(f.source_endpoint, buffer(24,2))
    root:add(f.destination_endpoint, buffer(26,2))
    root:add(f.command, buffer(28,1))
    root:add(f.control_status, buffer(29,1))
    root:add(f.body_bytes, buffer(30,2))
    root:add(f.fragment_index, buffer(32,1))
    root:add(f.fragment_count, buffer(33,1))
    local command = buffer(28,1):uint()
    local body_end = 34 + buffer(30,2):uint()
    if body_end > buffer:len() then return end
    if command == 1 and body_end >= 82 then
      root:add(f.context_role, buffer(34,1))
      root:add(f.context_parent, buffer(38,2))
      root:add(f.kulisch_bits, buffer(54,2))
      root:add(f.manager_mac, buffer(66,6))
      root:add(f.manager_port, buffer(72,2))
      root:add(f.maximum_terms, buffer(74,4))
      root:add(f.rank_formats, buffer(78,1))
      widths[key(buffer)] = buffer(54,2):uint()
      local children = buffer(35,1):uint()
      local results = buffer(36,1):uint()
      local bindings = children + (buffer(38,2):uint() == 65535 and 0 or 1)
      local binding_start = 82 + 2*(children + results)
      if binding_start + 24*bindings ~= body_end then return end
      for i = 0, bindings-1 do
        local offset = binding_start + 24*i
        local item = root:add(buffer(offset,24), "Endpoint binding " .. (i+1))
        item:add(f.binding_local, buffer(offset,2))
        item:add(f.binding_peer, buffer(offset+2,2))
        item:add(f.binding_port, buffer(offset+4,2))
        item:add(f.binding_kind, buffer(offset+6,1))
        item:add(f.binding_flags, buffer(offset+7,1))
        item:add(f.binding_mac, buffer(offset+8,6))
        item:add(f.binding_rank, buffer(offset+14,2))
        item:add(f.binding_terms, buffer(offset+16,4))
        item:add(f.binding_formats, buffer(offset+20,1))
      end
    end
    pinfo.cols.info = "CONTROL " .. (commands[command] or "UNKNOWN")
  elseif opcode == 4 then
    if buffer:len() < 46 then return end
    add_common(root, buffer)
    root:add(f.source_endpoint, buffer(20,2))
    root:add(f.destination_endpoint, buffer(22,2))
    root:add(f.stream_id, buffer(24,2))
    root:add(f.packet_id, buffer(26,4))
    root:add(f.cumulative, buffer(30,4))
    root:add(f.credit_intervals, buffer(34,2))
    root:add(f.credit_bytes, buffer(36,4))
    root:add(f.progress_status, buffer(40,1))
    root:add(f.flags, buffer(41,1))
    root:add(f.hole_count, buffer(42,2))
    local holes = buffer(42,2):uint()
    if 46 + 8*holes > buffer:len() then return end
    for i = 0, holes-1 do
      root:add(f.hole_first, buffer(46+8*i,4))
      root:add(f.hole_end, buffer(50+8*i,4))
    end
    pinfo.cols.info = "PROGRESS packet=" .. buffer(26,4):uint() ..
      " cumulative=" .. buffer(30,4):uint()
  else
    pinfo.cols.info = "Unknown PRISM packet class"
  end
end

DissectorTable.get("ethertype"):add(0x88B5, prism)
