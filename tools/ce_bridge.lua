--[[  Cheat Engine agentic bridge  ---------------------------------------------------------
  Turns Cheat Engine into a file-driven memory server so an agent can do reverse-engineering
  research WITHOUT touching the GUI. The agent writes a command file; this script (running in
  CE's Lua engine on a timer) executes it and writes a JSON result file. Robust: every op is
  pcall-wrapped, so a bad command returns an error string instead of breaking the bridge.

  READ-ONLY BY DEFAULT. The 'write' op exists but is refused unless ALLOW_WRITES=true below —
  the stats-mapping research never needs it.

  LOAD:  in Cheat Engine -> Table menu -> "Show Cheat Table Lua Script" -> paste this -> Execute
         (or Memory View -> Tools -> Auto Assemble is NOT needed; this is the Lua console).
  It auto-attaches to eFootball.exe and starts polling every POLL_MS.

  PROTOCOL:
    command file  : <DIR>/cmd.txt     (agent writes; bridge renames to cmd.done after running)
    result file   : <DIR>/result.json (bridge writes; agent reads)
  Command format = one 'key=value' per line, first line must be 'op=<name>'. Examples:
    op=open
    ---
    op=firstscan\ntype=float\nvalue=7.5
    op=nextscan\nvalue=6.5
    op=list\nmax=40
    op=read\naddr=0x1A2B3C4D\ntype=float
    op=readstruct\naddr=0x1A2B3C40\nsize=256
    op=aob\npattern=48 8B 05 ?? ?? ?? ??
    op=modules
    op=snapshot\naddrs=0x1000,0x1040,0x1080\ntype=float
--------------------------------------------------------------------------------------------]]

local DIR       = [[C:\Users\tjgg2\Downloads\eFootball Master League\build\ce]]
local CMD       = DIR .. [[\cmd.txt]]
local DONE      = DIR .. [[\cmd.done]]
local RESULT    = DIR .. [[\result.json]]
local TARGET    = "eFootball.exe"
local POLL_MS   = 400
local ALLOW_WRITES = false

-- ---- tiny JSON emitter (only the shapes we produce) -------------------------------------
local function jstr(s) return '"' .. tostring(s):gsub('\\','\\\\'):gsub('"','\\"') .. '"' end
local function jval(v)
  local t = type(v)
  if t == "number" then return tostring(v)
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "table" then
    local parts = {}
    local isarr = (#v > 0) or next(v) == nil
    if isarr then
      for _, e in ipairs(v) do parts[#parts+1] = jval(e) end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      for k, e in pairs(v) do parts[#parts+1] = jstr(k) .. ":" .. jval(e) end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  else return jstr(v) end
end

local function writeResult(tbl)
  local f = io.open(RESULT, "w"); if f then f:write(jval(tbl)); f:close() end
end

local function parseCmd(text)
  local c = {}
  for line in text:gmatch("[^\r\n]+") do
    local k, v = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
    if k then c[k] = v end
  end
  return c
end

-- ---- scan state -------------------------------------------------------------------------
local scan, foundlist

local VT = { byte=vtByte, word=vtWord, dword=vtDword, qword=vtQword,
             i32=vtDword, u32=vtDword, f32=vtSingle, float=vtSingle,
             f64=vtDouble, double=vtDouble }

local function ensureAttached()
  if getOpenedProcessID() == 0 then
    openProcess(TARGET)
  end
  return getOpenedProcessID() ~= 0
end

-- ---- op handlers ------------------------------------------------------------------------
local ops = {}

ops.ping = function() return { ok=true, op="ping", attached = getOpenedProcessID() ~= 0,
                               pid = getOpenedProcessID() } end

ops.open = function()
  openProcess(TARGET)
  local pid = getOpenedProcessID()
  return { ok = pid ~= 0, op="open", pid = pid,
           msg = pid ~= 0 and ("attached to "..TARGET) or (TARGET.." not found") }
end

ops.modules = function()
  local mods = enumModules()
  local out = {}
  for _, m in ipairs(mods or {}) do
    out[#out+1] = { name = m.Name, base = string.format("0x%X", m.Address), size = m.Size }
  end
  return { ok=true, op="modules", count=#out, modules=out }
end

ops.firstscan = function(c)
  if not ensureAttached() then return { ok=false, error="not attached" } end
  local vt = VT[(c.type or "float"):lower()]; if not vt then return {ok=false,error="bad type"} end
  scan = createMemScan()
  scan.firstScan(soExactValue, vt, rtRounded, tostring(c.value), nil,
                 0, 0x7fffffffffff, "*X-C+W", fsmNotAligned, "4", false, false, false, false)
  scan.waitTillDone()
  foundlist = createFoundList(scan); foundlist.initialize()
  return { ok=true, op="firstscan", type=c.type, value=c.value, count=foundlist.Count }
end

ops.nextscan = function(c)
  if not scan then return { ok=false, error="run firstscan first" } end
  if foundlist then foundlist.deinitialize() end
  scan.nextScan(soExactValue, rtRounded, tostring(c.value), nil, false, false, false, false)
  scan.waitTillDone()
  foundlist = createFoundList(scan); foundlist.initialize()
  return { ok=true, op="nextscan", value=c.value, count=foundlist.Count }
end

ops.list = function(c)
  if not foundlist then return { ok=false, error="no scan results" } end
  local max = tonumber(c.max) or 40
  local n = math.min(foundlist.Count, max)
  local out = {}
  for i = 0, n-1 do out[#out+1] = foundlist.Address[i] end
  return { ok=true, op="list", count=foundlist.Count, shown=n, addresses=out }
end

ops.read = function(c)
  if not ensureAttached() then return { ok=false, error="not attached" } end
  local a = tonumber(c.addr) or tonumber(c.addr, 16)
  local t = (c.type or "float"):lower()
  local v
  if t=="float" or t=="f32" then v = readFloat(a)
  elseif t=="double" or t=="f64" then v = readDouble(a)
  elseif t=="qword" then v = readQword(a)
  else v = readInteger(a) end
  return { ok = v ~= nil, op="read", addr=string.format("0x%X",a), type=t, value=v }
end

ops.readstruct = function(c)
  if not ensureAttached() then return { ok=false, error="not attached" } end
  local a = tonumber(c.addr) or tonumber(c.addr, 16)
  local size = tonumber(c.size) or 128
  local rows = {}
  for off = 0, size-4, 4 do
    local i = readInteger(a+off, false)
    local f = readFloat(a+off)
    rows[#rows+1] = { off=off, addr=string.format("0x%X", a+off),
                      i32=i, f32 = (f and string.format("%.3f", f)) or "nan" }
  end
  return { ok=true, op="readstruct", addr=string.format("0x%X",a), size=size, rows=rows }
end

ops.aob = function(c)
  if not ensureAttached() then return { ok=false, error="not attached" } end
  local res = AOBScan(c.pattern, "*X-C+W")
  local out = {}
  if res then
    for i = 0, math.min(res.Count-1, 100) do out[#out+1] = res[i] end
    res.destroy()
  end
  return { ok=true, op="aob", pattern=c.pattern, count=#out, addresses=out }
end

ops.snapshot = function(c)
  if not ensureAttached() then return { ok=false, error="not attached" } end
  local t = (c.type or "float"):lower()
  local out = {}
  for a in (c.addrs or ""):gmatch("[^,]+") do
    local addr = tonumber(a) or tonumber(a, 16)
    local v = (t=="float" or t=="f32") and readFloat(addr) or readInteger(addr)
    out[#out+1] = { addr=string.format("0x%X", addr), value=v }
  end
  return { ok=true, op="snapshot", values=out }
end

ops.write = function(c)
  if not ALLOW_WRITES then return { ok=false, error="writes disabled (ALLOW_WRITES=false)" } end
  local a = tonumber(c.addr) or tonumber(c.addr, 16)
  local t = (c.type or "float"):lower()
  if t=="float" or t=="f32" then writeFloat(a, tonumber(c.value)) else writeInteger(a, tonumber(c.value)) end
  return { ok=true, op="write", addr=string.format("0x%X",a), value=c.value }
end

-- ---- poll loop --------------------------------------------------------------------------
local function tick()
  local f = io.open(CMD, "r"); if not f then return end
  local text = f:read("*a"); f:close()
  os.remove(CMD)
  local c = parseCmd(text)
  local handler = ops[(c.op or ""):lower()]
  local res
  if not handler then
    res = { ok=false, error="unknown op: "..tostring(c.op),
            ops = { "ping","open","modules","firstscan","nextscan","list","read",
                    "readstruct","aob","snapshot","write" } }
  else
    local okp, r = pcall(handler, c)
    res = okp and r or { ok=false, error="lua error: "..tostring(r), op=c.op }
  end
  writeResult(res)
  local d = io.open(DONE, "w"); if d then d:write(text); d:close() end
end

ensureAttached()
if bridgeTimer then bridgeTimer.destroy() end
bridgeTimer = createTimer(nil)
bridgeTimer.Interval = POLL_MS
bridgeTimer.OnTimer = function() local ok, e = pcall(tick); if not ok then print("bridge tick error: "..tostring(e)) end end
print("CE bridge running. Polling "..CMD.." every "..POLL_MS.."ms. Attached pid="..getOpenedProcessID())
writeResult({ ok=true, op="startup", attached = getOpenedProcessID() ~= 0, pid = getOpenedProcessID(),
              msg = "bridge ready" })
